"""Budgeted secondary numerical analysis of verified quality receipts, without labels."""

from copy import deepcopy
import math
from pathlib import Path

from app.preprocessing.storage import digest, file_hash, within
from .io import read
from .neural_priors import evaluate_priors


METRICS = ("line_ratio_50hz", "line_ratio_60hz", "low_correlation_fraction", "flat_fraction",
           "numerical_rank", "mu_mean_psd", "beta_mean_psd", "erds_mu", "erds_beta",
           "emg_hf_proxy", "covariance_trace")


def quality_input(root, state, candidate_id):
    candidate = next((c for c in state["candidates"] if c["id"] == candidate_id and c["status"] == "evaluated"), None)
    if candidate is None:
        raise ValueError("诊断只能读取已完成候选")
    receipt = candidate.get("receipt") or {}
    ref = ((receipt.get("assessment") or {}).get("quality") or {}).get("receipt_artifact")
    if not ref or not receipt.get("assessment_path"):
        raise ValueError("候选没有可核验的质量回执，不能合成观测")
    directory = within(Path(root), f"candidates/{candidate_id}/{receipt['assessment_path']}")
    path = within(directory, ref["path"])
    if file_hash(path) != ref["sha256"]:
        raise ValueError("质量回执哈希不一致")
    q = read(path)
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


def explain_missing(root, quality, reference, stage_observations):
    """Resolve aggregate 'no_available_members' to hashed per-record causes."""
    wanted = {stage: {mid for mid, row in rows.items() if row["status"] != "ok"}
              for stage, rows in stage_observations.items()}
    counts = {stage: {mid: {} for mid in mids} for stage, mids in wanted.items()}
    examples = {stage: {mid: [] for mid in mids} for stage, mids in wanted.items()}
    refs = []
    for artifact in quality.get("detail_artifacts", []):
        path = within(within(Path(root), reference["path"]).parent, artifact["path"])
        if file_hash(path) != artifact["sha256"]:
            raise ValueError("逐记录质量明细哈希不一致")
        detail = read(path)
        if detail.get("record_id") != artifact["record_id"]:
            raise ValueError("逐记录质量明细身份不一致")
        ref = {"path": path.relative_to(Path(root)).as_posix(), "sha256": artifact["sha256"]}
        refs.append(ref)
        for stage, mids in wanted.items():
            for i, metric in enumerate(detail.get("stages", {}).get(stage, {}).get("metrics", [])):
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
                "records_inspected": len(refs), "examples_truncated": sum(counts[stage][mid].values()) > len(examples[stage][mid])}
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
            elif av is None or bv is None or a.get("unit") != b.get("unit") or a.get("axes") != b.get("axes"):
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


def run_diagnostic(root, state, request):
    identity = request["candidate_id"]
    stage = request["stage"]
    quality, ref = quality_input(root, state, identity)
    measured = {s: observations(quality, ref, s) for s in {stage, "source_raw", "source_task"}}
    detail_refs = explain_missing(root, quality, ref, measured)
    observed = measured[stage]
    bundle = state["protocol"]["neural_priors"]
    # Source-wide spectra and metadata are used for pollution hypotheses, not already narrow-band outputs.
    raw_observed = deepcopy(measured["source_raw"])
    raw_observed["erds_mu"] = measured["source_task"]["erds_mu"]
    result = {"schema_version": "neural-diagnostic-1", "kind": request["kind"],
              "candidate_id": identity, "stage": stage, "question": request["question"],
              "status": "evaluated" if any(_number(v) is not None for v in observed.values()) else "unavailable",
              "observations": observed, "input_artifacts": [ref, *detail_refs],
              "prior_evaluation": evaluate_priors(bundle, raw_observed, candidate_id=identity),
              "limitations": ["Secondary analysis of saved numerical measurements, not a new EEG preprocessing run.",
                              "No class labels, no automatic channel/trial deletion, no new selection score.",
                              "Rule screens are engineering suggestions; false/unknown do not certify absence of artifacts."]}
    if request["kind"] == "paired_comparison":
        other = request.get("reference_candidate_id")
        if not other or other == identity:
            raise ValueError("配对诊断需要不同的已完成参考候选")
        baseline, base_ref = quality_input(root, state, other)
        entries = {e["id"]: e for e in state["registry"]}
        result.update(comparison(baseline, quality, entries[other], entries[identity], stage))
        result["reference_candidate_id"] = other
        result["input_artifacts"].append(base_ref)
    result["request_sha256"] = digest({"request": {k: v for k, v in request.items() if k not in {"question", "reason"}},
                                       "inputs": result["input_artifacts"], "bundle": digest(bundle)})
    result["id"] = "diagnostic-" + result["request_sha256"][:20]
    return deepcopy(result)
