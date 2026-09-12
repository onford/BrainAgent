"""Budgeted secondary numerical analysis of verified quality receipts, without labels."""

from copy import deepcopy
import math
from pathlib import Path

from app.preprocessing.storage import digest, within
from .neural_priors import evaluate_priors
from .diagnostic_registry import DiagnosticInputBudget, validate_request, branch_result, METRICS


def quality_input(root, state, candidate_id, budget=None):
    candidate = next((c for c in state["candidates"] if c["id"] == candidate_id and c["status"] == "evaluated"), None)
    if candidate is None:
        raise ValueError("诊断只能读取已完成候选")
    receipt = candidate.get("receipt") or {}
    ref = ((receipt.get("assessment") or {}).get("quality") or {}).get("receipt_artifact")
    if not ref or not receipt.get("assessment_path"):
        raise ValueError("候选没有可核验的质量回执，不能合成观测")
    directory = within(Path(root), f"candidates/{candidate_id}/{receipt['assessment_path']}")
    path = within(directory, ref["path"])
    budget = budget or DiagnosticInputBudget(64 * 1024**2)
    q = budget.read(path, ref['sha256'])
    entry = next(r for r in state["registry"] if r["id"] == candidate_id)
    if (q.get("candidate_id") != candidate_id or q.get("panel_hash") != state["panel"]["panel_hash"]
            or q.get("input_hash") != state["protocol"]["input_hash"]
            or q.get("candidate_recipe_hash") != digest(entry["recipe"])):
        raise ValueError("质量回执与冻结候选或面板不一致")
    if candidate.get("plan_ref") and q.get("plan_hash") != candidate["plan_ref"]["sha256"]:
        raise ValueError("质量回执与执行计划不一致")
    return q, {"path": path.relative_to(Path(root)).as_posix(), "sha256": ref["sha256"]}


def observations(quality, reference, stage):
    metrics = quality.get("stages", {}).get(stage, {})
    return {mid: {"value": metrics.get(mid, {}).get("value"),
                  "status": metrics.get(mid, {}).get("status", "not_applicable"),
                  "reason": metrics.get(mid, {}).get("reason", "metric_not_saved"),
                  "unit": metrics.get(mid, {}).get("unit"),
                  "denominator": metrics.get(mid, {}).get("denominator", {}),
                  "reference": {**reference, "json_pointer": f"/stages/{stage}/{mid}"}}
            for mid in METRICS}


def _number(row):
    value = row.get("value")
    return value if row.get("status") == "ok" and type(value) in (int, float) and math.isfinite(value) else None


def explain_missing(root, quality, reference, stage_observations, budget=None):
    """Resolve aggregate 'no_available_members' to hashed per-record causes."""
    budget = budget or DiagnosticInputBudget(64 * 1024**2)
    wanted = {stage: {mid for mid, row in rows.items() if row["status"] != "ok"}
              for stage, rows in stage_observations.items()}
    counts = {stage: {mid: {} for mid in mids} for stage, mids in wanted.items()}
    examples = {stage: {mid: [] for mid in mids} for stage, mids in wanted.items()}
    refs = []
    indexed = {record['record_id']: record for subject in quality.get('bysubject', {}).values()
               for record in subject.get('records', []) if 'diagnostic_missing_index' in record}
    inspected = 0
    index_count = 0
    for artifact in quality.get("detail_artifacts", []):
        path = within(within(Path(root), reference["path"]).parent, artifact["path"])
        budget.check()
        row = indexed.get(artifact['record_id'])
        if row is not None:
            if row.get('detail_artifact') != artifact:
                raise ValueError('质量缺测索引与源明细引用不一致')
            stage_metrics = row['diagnostic_missing_index']
            index_count += 1
        else:
            detail = budget.read(path, artifact['sha256'])
            if detail.get("record_id") != artifact["record_id"]:
                raise ValueError("逐记录质量明细身份不一致")
            stage_metrics = {stage: [{**metric, 'metric_index': i} for i, metric in enumerate(data.get('metrics', []))]
                             for stage, data in detail.get('stages', {}).items()}
        inspected += 1
        ref = {"path": path.relative_to(Path(root)).as_posix(), "sha256": artifact["sha256"]}
        if row is None:
            refs.append(ref)
        for stage, mids in wanted.items():
            for metric in stage_metrics.get(stage, []):
                i = metric['metric_index']
                mid = metric["metricID"]
                if mid not in mids or metric.get("status") == "ok":
                    continue
                reason = metric.get("reason") or "unspecified_missing_reason"
                counts[stage][mid][reason] = counts[stage][mid].get(reason, 0) + 1
                if len(examples[stage][mid]) < 4:
                    examples[stage][mid].append({"record_id": artifact["record_id"], "reason": reason,
                        "reference": {**ref, "json_pointer": f"/stages/{stage}/metrics/{i}"}})
    for stage, mids in wanted.items():
        for mid in mids:
            stage_observations[stage][mid]["missing_detail"] = {
                "record_reason_counts": counts[stage][mid], "examples": examples[stage][mid],
                "records_inspected": inspected, 'records_from_frozen_missing_index': index_count,
                "examples_truncated": sum(counts[stage][mid].values()) > len(examples[stage][mid])}
    return refs


def comparison(left, right, left_entry, right_entry, stage):
    from .physical_frames import paired_frames
    # Registry names and matching array shapes do not establish physical frames.
    common_panel=bool(left.get('panel_hash') and left.get('input_hash')
        and left['panel_hash']==right.get('panel_hash') and left['input_hash']==right.get('input_hash'))
    frame_checks={subject:paired_frames(left.get('bysubject',{}).get(subject,{}).get('records',[]),
        right.get('bysubject',{}).get(subject,{}).get('records',[]),stage)
        for subject in set(left.get('bysubject',{}))|set(right.get('bysubject',{}))}
    comparable=common_panel and bool(frame_checks) and all(v[0] for v in frame_checks.values())
    expected = sorted(set(left.get("bysubject", {})) | set(right.get("bysubject", {})))
    rows = {}
    for mid in METRICS:
        diffs, missing = {}, {}
        for subject in expected:
            a = left.get("bysubject", {}).get(subject, {}).get("stages", {}).get(stage, {}).get(mid, {})
            b = right.get("bysubject", {}).get(subject, {}).get("stages", {}).get(stage, {}).get(mid, {})
            av, bv = _number(a), _number(b)
            sa, sb = left.get("bysubject", {}).get(subject, {}), right.get("bysubject", {}).get(subject, {})
            records_a = sorted(r["record_id"] for r in sa.get("records", []))
            records_b = sorted(r["record_id"] for r in sb.get("records", []))
            if (not records_a or records_a != records_b or sa.get("coverage") != sb.get("coverage")
                    or a.get("denominator") != b.get("denominator")):
                missing[subject] = "record_or_trial_denominator_unverified_or_differs"
            elif (av is None or bv is None or a.get("unit") != b.get("unit") or a.get("axes") != b.get("axes")
                  or a.get('within_record_reduction') != b.get('within_record_reduction')):
                missing[subject] = "unavailable_or_incompatible_measurement"
            elif not common_panel or not frame_checks[subject][0]:
                missing[subject] = "physical_frame_or_panel_unverified_or_differs"
            else:
                diffs[subject] = bv - av
        rows[mid] = {"mean_subject_difference": sum(diffs.values()) / len(diffs) if diffs else None,
                     "subject_differences": diffs, "expected_subjects": len(expected),
                     "paired_subjects": len(diffs), "missing": missing,
                     "status": "ok" if diffs and not missing else "partial" if diffs else "not_comparable"}
    return {"metrics": rows, "comparison_contract": {
        "same_panel_required": True, "stage": stage, "passband_reference_sampling_match": comparable,
        "record_frame_checks":{s:{'comparable':v[0],'reasons':v[1]} for s,v in frame_checks.items()},
        "difference": "candidate_minus_reference", "causal_claim": False,
        "interpretation": "Verified native-frame descriptive differences; complete executed-operation matching is conservative and does not establish neural preservation."}}


def run_diagnostic(root, state, request, budget=None):
    definition = validate_request(state['protocol'], request)
    budget = budget or DiagnosticInputBudget(64 * 1024**2)
    identity = request["candidate_id"]
    stage = request["stage"]
    quality, ref = quality_input(root, state, identity, budget)
    measured = {s: observations(quality, ref, s) for s in {stage, "source_raw", "source_task"}}
    # Spectrum and native-frame comparisons do not consume unrelated waveform/TFR details.
    detail_refs = explain_missing(root, quality, ref, measured, budget) if definition.kind == 'signal_profile' else []
    observed = measured[stage]
    bundle = state["protocol"]["neural_priors"]
    # Source-wide spectra and metadata are used for pollution hypotheses, not already narrow-band outputs.
    raw_observed = deepcopy(measured["source_raw"])
    raw_observed["erds_mu"] = measured["source_task"]["erds_mu"]
    result = {"schema_version": "neural-diagnostic-2", "kind": request["kind"],
              "candidate_id": identity, "stage": stage, "question": request["question"],
              "status": "evaluated" if any(_number(v) is not None for v in observed.values()) else "unavailable",
              "observations": observed, "input_artifacts": [ref, *detail_refs],
              "prior_evaluation": evaluate_priors(bundle, raw_observed, candidate_id=identity),
              "limitations": ["Secondary analysis of saved numerical measurements, not a new EEG preprocessing run.",
                              "No class labels, no automatic channel/trial deletion, no new selection score.",
                              "Rule screens are engineering suggestions; false/unknown do not certify absence of artifacts."]}
    baseline = None
    if definition.reference_required:
        other = request.get("reference_candidate_id")
        if not other or other == identity:
            raise ValueError("配对诊断需要不同的已完成参考候选")
        baseline, base_ref = quality_input(root, state, other, budget)
        result["reference_candidate_id"] = other
        result["input_artifacts"].append(base_ref)
    result.update(definition.handler(quality, ref, baseline, stage))
    budget.check()
    result['diagnostic_contract'] = {'kind': definition.kind, 'version': definition.version,
        'registry_sha256': state['protocol'].get('diagnostic_registry_hash'),
        'input_domain': definition.input_domain, 'label_permission': 'none',
        'numeric_contract': definition.numeric_contract}
    if request.get('experiment'):
        result['decision_effect'] = branch_result(result, request['experiment'])
    result["request_sha256"] = digest({"request": {k: v for k, v in request.items() if k not in {"question", "reason", "experiment"}},
                                       "inputs": result["input_artifacts"], "bundle": digest(bundle),
                                       "contract": result['diagnostic_contract']})
    result["id"] = "diagnostic-" + result["request_sha256"][:20]
    return deepcopy(result)
