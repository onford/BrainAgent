"""Compose independent assessments; parent persists this dict in receipt.assessment.

Fresh output_dir contains utility/, quality/, reconstruction/, failure receipts,
artifact-manifest.json and assessment.json. Full evaluator results remain in their
native files. assessment.json is an exact copy of the trusted returned summary,
excluded from the manifest; its non-manifest content is also saved as an inventoried
snapshot. The manifest's own checksum lives in the summary, avoiding cyclic hashes.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from app.preprocessing.schemas import ExecutionPlan, RunResult
from app.preprocessing.storage import digest, file_hash, within, write_json
from .assessment_contracts import (
    ArtifactEntry, ArtifactRef, AssessmentCoverage, AssessmentManifest,
    AssessmentSnapshot, AssessmentSummary, AuxiliarySummary, Bindings, METRIC_NAMES, UtilitySummary,
)
from .panel import validate_panel
from .utility_contracts import LEARNER_SUITE, PRIMARY_SUITE, UtilityReceipt
from .utility_parallel import UtilityExecutionError


# Lazy adapters isolate optional learner dependencies.
def evaluate_dataset_utility(*args, **kwargs):
    from .utility_evaluation import evaluate_dataset_utility as run
    return run(*args, **kwargs)


def evaluate_dataset_quality(*args):
    from .quality_evaluation import evaluate_dataset_quality as run
    return run(*args)


def evaluate_dataset_reconstruction(*args):
    from .reconstruction_evaluation import evaluate_dataset_reconstruction as run
    return run(*args)


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _dump(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else deepcopy(value)


def _json_file(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _ref(path, output):
    path = Path(path)
    _require(path.resolve().is_relative_to(output), "artifact escapes assessment output")
    return ArtifactRef(path=path.relative_to(output).as_posix(), sha256=file_hash(path), bytes=path.stat().st_size)


def _tree_files(output):
    for path in sorted(output.rglob("*")):
        _require(not path.is_symlink() and not getattr(path, "is_junction", lambda: False)(),
                 "linked assessment artifacts are unsupported")
        if path.is_file():
            _require(path.resolve().is_relative_to(output), "artifact escaped output tree")
            yield path


def _inventory(output):
    files = []
    for path in _tree_files(output):
        # The complete summary contains the manifest hash. Keep its persisted
        # copy outside that manifest to avoid a circular checksum dependency.
        if path == output / "assessment.json":
            continue
        component = path.relative_to(output).parts[0]
        if component not in {"utility", "quality", "reconstruction"}:
            component = "assessment"
        files.append(ArtifactEntry(**_ref(path, output).model_dump(), component=component))
    return files


def _verify_refs(value, directory):
    """Verify native absolute/relative artifact declarations before using scores."""
    if isinstance(value, dict):
        if "path" in value and "sha256" in value:
            path = Path(value["path"])
            path = path if path.is_absolute() else within(directory, value["path"])
            _require(path.resolve().is_relative_to(directory.resolve()), "component artifact outside its output directory")
            _require(path.is_file() and file_hash(path) == value["sha256"], "component artifact checksum mismatch")
            if "bytes" in value:
                _require(path.stat().st_size == value["bytes"], "component artifact byte count mismatch")
        for child in value.values():
            _verify_refs(child, directory)
    elif isinstance(value, list):
        for child in value:
            _verify_refs(child, directory)


def _native_file(payload, directory, name, output):
    # Also rejects nonfinite values deeply nested in otherwise dynamic payloads.
    digest(payload)
    list(_tree_files(output))
    _verify_refs(payload, directory)
    path = directory / name
    _require(path.is_file() and _json_file(path) == payload, "native receipt file differs from returned payload")
    return _ref(path, output)


def _failure(output, component, exc, bindings, *, status="failed"):
    reason = str(exc) or type(exc).__name__
    path = output / "_assessment" / (component + ".json")
    write_json(path, {"schema_version": "assessment-component-failure-v1", "component": component,
                      "status": status, "reason": reason, "exception_type": type(exc).__name__,
                      "bindings": bindings.model_dump(mode="json")})
    return reason, _ref(path, output)


def _utility_denominator(panel):
    subjects = set(panel["development_subjects"])
    return Counter(t["subject"] for t in panel["trials"]
                   if t["eligible"] and t["role"] == "development" and t["subject"] in subjects)


def _learner_coverage(panel, receipt=None):
    subjects = set(panel["development_subjects"])
    expected = sum(_utility_denominator(panel).values())
    return {name: {"subjects_expected": len(subjects),
                   "subjects_available": len(receipt.learners[name].subjects) if receipt else 0,
                   "eligible_trials_expected": expected,
                   "trials_available": sum(s.n_trials for s in receipt.learners[name].subjects.values()) if receipt else 0}
            for name in LEARNER_SUITE}


def _utility_failed(panel, reason, artifact):
    coverage = _learner_coverage(panel)
    return UtilitySummary(status="failed", evaluation_mode=panel["evaluation_mode"], reason=reason, primary_suite=list(PRIMARY_SUITE),
                          learner_scores=dict.fromkeys(LEARNER_SUITE), learner_statuses=dict.fromkeys(LEARNER_SUITE, "failed"),
                          learner_statistics={name: dict.fromkeys(sorted(METRIC_NAMES)) for name in LEARNER_SUITE},
                          learner_coverage=coverage, summary=None, primary_models_available=0,
                          primary_trial_predictions_expected=3*sum(_utility_denominator(panel).values()),
                          primary_trial_predictions_available=0, receipt_artifact=None, failure_artifact=artifact,
                          failure_reasons=[reason], warnings=[])


def _utility_summary(payload, panel, candidate, core, directory, output):
    receipt = UtilityReceipt.model_validate(payload)
    _require(receipt.candidate_id == candidate["id"] and receipt.candidate_hash == digest(candidate), "utility candidate binding mismatch")
    _require(receipt.panel_hash == panel["panel_hash"] and receipt.core_receipt_hash == digest(core), "utility panel/core binding mismatch")
    expected = _utility_denominator(panel)
    _require(receipt.evaluation_mode == panel["evaluation_mode"], "utility evaluation mode mismatch")
    # UtilityReceipt enforces INTERNAL common denominators. This additionally
    # binds those denominators to ALL subjects/trials in this frozen panel.
    if receipt.subjects:
        _require(set(receipt.subjects) == set(expected), "utility omitted frozen subjects")
        _require(all(row.eligible_trials == expected[s] for s, row in receipt.subjects.items()), "utility frozen eligible trial count differs")
    if receipt.status == "evaluated":
        _require(set(receipt.subjects) == set(expected), "complete utility needs all panel subjects")
    artifact = _native_file(payload, directory, "utility.json", output)
    coverage = _learner_coverage(panel, receipt)
    return UtilitySummary(status=receipt.status, evaluation_mode=receipt.evaluation_mode,
                          reason=None if receipt.status == "evaluated" else "; ".join(receipt.failure_reasons),
                          primary_suite=receipt.primary_suite, learner_scores=receipt.learner_scores,
                          learner_statuses={n: receipt.learners[n].status for n in LEARNER_SUITE},
                          learner_statistics={n: {k: receipt.learners[n].summary.get(k) for k in sorted(METRIC_NAMES)} for n in LEARNER_SUITE},
                          learner_coverage=coverage, summary=receipt.summary,
                          primary_models_available=sum(receipt.learners[n].status == "evaluated" for n in PRIMARY_SUITE),
                          primary_trial_predictions_expected=3*sum(expected.values()),
                          primary_trial_predictions_available=sum(coverage[n]["trials_available"] for n in PRIMARY_SUITE),
                          receipt_artifact=artifact, failure_artifact=None,
                          failure_reasons=receipt.failure_reasons, warnings=receipt.warnings), receipt.selection_score


def _compact_quality(native):
    """Retain group statistics/counts, not duplicated subject tables or curves."""
    compact = {k: deepcopy(native[k]) for k in (
        "schema_version", "status", "metric_count", "coverage", "aggregation", "limitations", "precue_seconds"
    )}
    compact["metrics"] = {}
    for mid, metric in native["metrics"].items():
        row = {k: deepcopy(metric[k]) for k in (
            "metricID", "value", "unit", "direction", "status", "reason", "formula", "axes", "aggregation", "applicability", "selection_role"
        )}
        denominator = metric["denominator"]
        row["denominator"] = {k: deepcopy(v) for k, v in denominator.items() if k not in {"expected_ids", "available_ids", "missing_reasons"}}
        row["denominator"]["missing_reason_counts"] = dict(Counter(denominator.get("missing_reasons", {}).values()))
        compact["metrics"][mid] = row
    compact["stage_status_counts"] = {stage: dict(Counter(m["status"] for m in metrics.values()))
                                       for stage, metrics in native["stages"].items()}
    compact["detail_policy"] = "all_subject_record_metrics_and_full_curves_in_quality_receipt_and_detail_artifacts"
    return compact


def _quality_summary(payload, panel, candidate, bindings, directory, output):
    native = payload["summary"]
    _require(native["candidate_id"] == candidate["id"] and native["candidate_recipe_hash"] == digest(candidate["recipe"]), "quality candidate binding mismatch")
    _require(native["panel_hash"] == bindings.panel_hash and native["input_hash"] == bindings.input_hash
             and native["plan_hash"] == bindings.plan_hash, "quality input/panel/plan binding mismatch")
    coverage = native["coverage"]
    _require(coverage["subjects_expected"] == len({r["subject"] for r in panel["records"].values()})
             and coverage["records_expected"] == len(panel["records"])
             and coverage["eligible_trials"] == sum(t["eligible"] for t in panel["trials"]), "quality frozen denominator mismatch")
    _require(native["metric_count"] == len(native["metrics"]) == 25, "quality metric inventory mismatch")
    _require(native["status"] in {"evaluated", "partial"}, "unknown quality status")
    _verify_refs(payload, directory)
    artifact = _native_file(native, directory, "data-quality.json", output)
    return AuxiliarySummary(status=native["status"], reason=None if native["status"] == "evaluated" else "quality_has_incomplete_record_or_metric_coverage",
                            summary=_compact_quality(native), receipt_artifact=artifact, failure_artifact=None)


def _reconstruction_summary(payload, panel, candidate, probe, bindings, directory, output):
    native = payload["summary"]
    _require(native["candidate_id"] == candidate["id"] and native["candidate_entry_hash"] == bindings.candidate_hash
             and native["plan_hash"] == bindings.plan_hash and native["probe_hash"] == probe["probe_hash"], "reconstruction candidate/plan/probe binding mismatch")
    _require(native["subjects_expected"] == len({r["subject"] for r in panel["records"].values()})
             and native["cases_expected"] == sum(len(s["cases"]) for s in probe["subjects"].values())
             and native["trial_cases_expected"] == sum(len(s["cases"])*len(s["trial_ids"]) for s in probe["subjects"].values()),
             "reconstruction frozen denominator mismatch")
    _require(native["status"] in {"evaluated", "incomplete"}, "unknown reconstruction status")
    # Kuhn returns an additional inventory including the saved receipt itself;
    # that inventory cannot be embedded in the file whose hash it declares.
    _verify_refs(payload, directory)
    persisted = {key: payload[key] for key in ("summary", "details")}
    artifact = _native_file(persisted, directory, "reconstruction_evaluation.json", output)
    compact = deepcopy(native)
    for case in compact["by_case"].values():
        case.pop("subjects_assigned", None)  # Assignment remains in probe_panel.json.
    return AuxiliarySummary(status="evaluated" if native["status"] == "evaluated" else "partial",
                            reason=None if native["status"] == "evaluated" else "reconstruction_has_failed_or_undefined_assigned_cases",
                            summary=compact, receipt_artifact=artifact, failure_artifact=None)


def _core_paths(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if (key == "path" or key.endswith("_path")) and isinstance(child, str) and Path(child).is_absolute():
                yield Path(child).resolve()
            else:
                yield from _core_paths(child)
    elif isinstance(value, list):
        for child in value:
            yield from _core_paths(child)


def assess_candidate(plan, result, store_root, panel, candidate_entry, core_receipt, output_dir, probe_panel, *, utility_execution=None) -> dict:
    """Return AssessmentSummary JSON directly for receipt.assessment.

    Selection path is assessment.selection_score ONLY; core_csp_macro_ba is an
    anchor. All three primary models and all frozen development subjects/trials
    are required (all subjects in group CV; held-out subjects in holdout mode).
    Full UtilityReceipt is utility/utility.json; no subject-by-learner table is
    duplicated here. Quality/reconstruction missingness never changes utility.

    Requires a fresh output_dir disjoint from source/engine artifact directories.
    Core files may be siblings of output_dir, but must not be inside output_dir.
    Calls utility -> quality -> reconstruction serially. probe_panel=None records
    reconstruction N/A; no probe is silently generated or reselected. Global
    binding/path errors raise before execution. Component errors are isolated.
    KeyboardInterrupt/SystemExit/MemoryError propagate rather than launching
    more heavy work. artifact-manifest.json inventories ALL component files;
    its own hash/size is added to this returned artifacts list. Parent writes the
    outer receipt; assessment.json stores this exact returned summary outside
    the manifest, and _assessment/summary.json stores its non-manifest fields.
    """
    plan = ExecutionPlan.model_validate(_dump(plan))
    result = RunResult.model_validate(_dump(result))
    panel, candidate, core, probe = map(_dump, (panel, candidate_entry, core_receipt, probe_panel))
    validate_panel(panel)
    _require(isinstance(candidate.get("id"), str) and candidate["id"], "candidate id required")
    _require(result.plan_ref.id == result.plan_ref.sha256 == digest(plan.model_dump(mode="json")), "result/plan hash mismatch")
    _require(plan.request.input_ref.id == plan.request.input_ref.sha256 == panel["input_hash"]
             == digest(plan.input_snapshot.model_dump(mode="json")), "plan/panel input hash mismatch")
    _require(isinstance(core, dict), "core_receipt must be a JSON object")
    bindings = Bindings(candidate_hash=digest(candidate), plan_hash=result.plan_ref.sha256,
                        result_hash=digest(result.model_dump(mode="json")), input_hash=panel["input_hash"],
                        panel_hash=panel["panel_hash"], core_receipt_hash=digest(core),
                        probe_panel_hash=digest(probe) if probe is not None else None)
    coverage = AssessmentCoverage(subjects_expected=len({r["subject"] for r in panel["records"].values()}),
                                    records_expected=len(panel["records"]), original_trials=len(panel["trials"]),
                                    eligible_trials=sum(t["eligible"] for t in panel["trials"]),
                                    common_invalid_trials=sum(not t["eligible"] for t in panel["trials"]))
    anchor = core.get("macro_ba")
    _require(anchor is None or (type(anchor) in (int, float) and 0 <= anchor <= 1), "invalid core CSP anchor")
    output, store = Path(output_dir).resolve(), Path(store_root).resolve()
    protected = [Path(plan.input_snapshot.collection.root).resolve()]
    protected.extend(within(store, a["path"]).parent for item in result.records
                     for a in (item.get("result") or {}).get("artifacts", []))
    _require(not any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected), "assessment output overlaps protected input")
    _require(not any(p.is_relative_to(output) for p in _core_paths(core)),
             "assessment output contains a protected core file")
    _require(not output.exists(), "assessment requires a fresh output directory")
    output.mkdir(parents=True)

    def common():
        return (plan.model_copy(deep=True), result.model_copy(deep=True), store,
                deepcopy(panel), deepcopy(candidate))

    selection_score = None
    try:
        options = {"execution": utility_execution} if utility_execution is not None else {}
        payload = evaluate_dataset_utility(*common(), deepcopy(core), output / "utility", **options)
        utility, selection_score = _utility_summary(payload, panel, candidate, core, output / "utility", output)
    except (MemoryError, UtilityExecutionError):
        raise
    except Exception as exc:
        reason, failure = _failure(output, "utility", exc, bindings)
        utility = _utility_failed(panel, reason, failure)
    try:
        payload = evaluate_dataset_quality(*common(), output / "quality")
        quality = _quality_summary(payload, panel, candidate, bindings, output / "quality", output)
    except MemoryError:
        raise
    except Exception as exc:
        reason, failure = _failure(output, "quality", exc, bindings)
        quality = AuxiliarySummary(status="failed", reason=reason, summary=None, receipt_artifact=None, failure_artifact=failure)
    try:
        if probe is None:
            reason, failure = _failure(output, "reconstruction", ValueError("frozen_probe_panel_unavailable"), bindings, status="not_applicable")
            reconstruction = AuxiliarySummary(status="not_applicable", reason=reason, summary=None,
                                                receipt_artifact=None, failure_artifact=failure)
        else:
            _require(probe["panel_hash"] == panel["panel_hash"] and probe["input_hash"] == panel["input_hash"]
                     and probe["probe_hash"] == digest({k: v for k, v in probe.items() if k != "probe_hash"}), "frozen probe binding/hash mismatch")
            # Kuhn's order is candidate_entry, PROBE_PANEL, OUTPUT_DIR.
            payload = evaluate_dataset_reconstruction(*common(), deepcopy(probe), output / "reconstruction")
            reconstruction = _reconstruction_summary(payload, panel, candidate, probe, bindings, output / "reconstruction", output)
    except MemoryError:
        raise
    except Exception as exc:
        reason, failure = _failure(output, "reconstruction", exc, bindings)
        reconstruction = AuxiliarySummary(status="failed", reason=reason, summary=None, receipt_artifact=None, failure_artifact=failure)

    states = (utility.status, quality.status, reconstruction.status)
    state = "complete" if all(s == "evaluated" for s in states) else "failed" if all(s in {"failed", "not_applicable"} for s in states) else "partial"
    content = dict(schema_version="assessment-v1", candidate_id=candidate["id"], bindings=bindings.model_dump(mode="json"),
                   coverage=coverage.model_dump(mode="json"), status=state, selection_score=selection_score,
                   selection_ready=utility.status == "evaluated",
                   selection_policy="utility_only_all_three_primary_models_all_frozen_subjects",
                   core_csp_macro_ba=anchor, core_status=str(core.get("status", "unknown")),
                   utility=utility.model_dump(mode="json"), quality=quality.model_dump(mode="json"),
                   reconstruction=reconstruction.model_dump(mode="json"))
    snapshot = AssessmentSnapshot(content=content)
    write_json(output / "_assessment" / "summary.json", snapshot.model_dump(mode="json"))
    artifacts = _inventory(output)
    manifest = AssessmentManifest(bindings=bindings, artifacts=artifacts)
    path = output / "artifact-manifest.json"
    write_json(path, manifest.model_dump(mode="json"))
    manifest_ref = _ref(path, output)
    artifacts.append(ArtifactEntry(**manifest_ref.model_dump(), component="assessment"))
    summary = AssessmentSummary(**content, artifact_manifest=manifest_ref, artifacts=artifacts).model_dump(mode="json")
    write_json(output / "assessment.json", summary)
    return summary


def verify_assessment(output_dir, summary, *, panel_hash=None, candidate_id=None) -> dict:
    """Read-only verification for worker reuse/export; no evaluator/model calls.

    Return a normalized AssessmentSummary dict, or raise ValueError/OSError for
    invalid schema, identity, persisted summary, file inventory or content.
    Checksum trust is anchored in the caller's summary/outer receipt; this is not
    a digital signature against an attacker replacing that trusted receipt too.
    """
    model = AssessmentSummary.model_validate(_dump(summary))
    result = model.model_dump(mode="json")
    _require(panel_hash is None or model.bindings.panel_hash == panel_hash, "assessment panel_hash mismatch")
    _require(candidate_id is None or model.candidate_id == candidate_id, "assessment candidate_id mismatch")
    output = Path(output_dir).resolve(strict=True)
    _require(output.is_dir(), "assessment output is not a directory")
    _require(_json_file(output / "assessment.json") == result, "assessment.json differs from trusted summary")
    _require(model.artifact_manifest.path == "artifact-manifest.json", "unexpected assessment manifest path")
    actual = _inventory(output)
    actual_by_path = {a.path: a.model_dump(mode="json") for a in actual}
    declared_by_path = {a.path: a.model_dump(mode="json") for a in model.artifacts}
    _require(actual_by_path == declared_by_path, "assessment artifact inventory/checksum/size mismatch")
    manifest = AssessmentManifest.model_validate(_json_file(output / model.artifact_manifest.path))
    _require(manifest.bindings == model.bindings, "artifact manifest input bindings mismatch")
    expected = {k: v for k, v in declared_by_path.items() if k != model.artifact_manifest.path}
    declared = {a.path: a.model_dump(mode="json") for a in manifest.artifacts}
    _require(len(declared) == len(manifest.artifacts) and declared == expected, "manifest and assessment artifact inventories differ")
    snapshot = AssessmentSnapshot.model_validate(_json_file(output / "_assessment" / "summary.json"))
    content = {k: v for k, v in result.items() if k not in {"artifacts", "artifact_manifest"}}
    _require(snapshot.content == content, "assessment differs from persisted summary")
    # The native receipts are separately hashed; their declared file references
    # must also resolve and match. Failed components can retain forensic files,
    # but never a usable score or a falsely validated native receipt reference.
    if model.utility.receipt_artifact is not None:
        raw = _json_file(output / model.utility.receipt_artifact.path)
        receipt = UtilityReceipt.model_validate(raw)
        _require(receipt.candidate_id == model.candidate_id and receipt.candidate_hash == model.bindings.candidate_hash
                 and receipt.panel_hash == model.bindings.panel_hash and receipt.core_receipt_hash == model.bindings.core_receipt_hash,
                 "utility receipt bindings differ from assessment")
        _require(receipt.selection_score == model.selection_score and receipt.status == model.utility.status,
                 "selection_score differs from native full utility receipt")
        _verify_refs(raw, output / "utility")
    if model.quality.receipt_artifact is not None:
        raw = _json_file(output / model.quality.receipt_artifact.path)
        _require(raw["candidate_id"] == model.candidate_id and raw["panel_hash"] == model.bindings.panel_hash
                 and raw["plan_hash"] == model.bindings.plan_hash and raw["input_hash"] == model.bindings.input_hash,
                 "quality receipt bindings differ from assessment")
        _require(_compact_quality(raw) == model.quality.summary, "quality aggregate differs from native receipt")
        _verify_refs(raw, output / "quality")
    if model.reconstruction.receipt_artifact is not None:
        raw = _json_file(output / model.reconstruction.receipt_artifact.path)
        native = raw["summary"]
        _require(native["candidate_id"] == model.candidate_id and native["candidate_entry_hash"] == model.bindings.candidate_hash
                 and native["plan_hash"] == model.bindings.plan_hash, "reconstruction receipt bindings differ from assessment")
        compact = deepcopy(native)
        for case in compact["by_case"].values():
            case.pop("subjects_assigned", None)
        _require(compact == model.reconstruction.summary, "reconstruction aggregate differs from native receipt")
        probe = _json_file(output / "reconstruction" / "probe_panel.json")
        _require(digest(probe) == model.bindings.probe_panel_hash and probe["probe_hash"] == native["probe_hash"],
                 "reconstruction frozen probe binding mismatch")
        _verify_refs(raw, output / "reconstruction")
    return result
