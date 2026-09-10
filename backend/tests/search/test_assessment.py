"""Orchestration fixtures only: no learner training, source signal IO or search."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.preprocessing.schemas import ExecutionPlan, PlanRequest, RecordPlan, Ref, RunResult
from app.preprocessing.storage import digest, file_hash, write_json
from app.search import assessment as a
from app.search.assessment_contracts import AssessmentSummary, METRIC_NAMES
from app.search.panel import freeze_panel
from app.search.utility_contracts import LEARNER_SUITE, PRIMARY_SUITE, UtilityReceipt
from tests.search.test_panel import make_input


def case(tmp_path, holdout=False):
    data = make_input(tmp_path / "source", counts=(4, 4))
    split = dict(train_subjects=["sub-01"], development_subjects=["sub-02"]) if holdout else {}
    panel = freeze_panel(data, {r.id: r.id for r in data.collection.records}, seed=42,
                         tmin=0.0, tmax=2.0, sfreq=160, **split)
    method = Ref(id="a"*64, sha256="a"*64)
    plan = ExecutionPlan(request=PlanRequest(input_ref=Ref(id=panel["input_hash"], sha256=panel["input_hash"]),
                                             methods=[method], mode="validation"),
                         input_snapshot=data, screening=[], environment={}, engine_sha256="b"*64, records=[])
    h = digest(plan.model_dump(mode="json"))
    result = RunResult(job_id="fixture", plan_ref=Ref(id=h, sha256=h), status="completed", records=[],
                       completed=0, total=0, cancel_requested=False)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    predictions = candidate / "originalpredictions.tsv"
    predictions.write_text("fixture predictions", encoding="utf-8")
    core = dict(status="evaluated", macro_ba=0.91, predictions_path=str(predictions), predictions_sha256=file_hash(predictions))
    write_json(candidate / "core-receipt.json", core)
    entry = dict(id="candidate", recipe=dict(nodes=[]))
    probe = dict(panel_hash=panel["panel_hash"], input_hash=panel["input_hash"], subjects={
        s: dict(cases=["case"], trial_ids=[t["event_id"] for t in panel["trials"] if t["eligible"] and t["subject"] == s])
        for s in {r["subject"] for r in panel["records"].values()}})
    probe["probe_hash"] = digest(probe)
    return (plan, result, tmp_path / "store", panel, entry, core), probe


def artifact(path, payload):
    write_json(path, payload)
    return dict(path=str(path), sha256=file_hash(path))


def utility(plan, result, root, panel, entry, core, out, missing=None):
    ref = artifact(out / "protocol.json", {"fixture": True})
    counts = a._utility_denominator(panel)
    learners, scores = {}, {}
    def distribution(v):
        return dict(mean=v, lower_quartile=v, subject_sd=0.0, n_subjects=len(counts))
    for i, name in enumerate(LEARNER_SUITE):
        role = "primary" if name in PRIMARY_SUITE else "diagnostic"
        if name not in PRIMARY_SUITE or name == missing:
            learners[name] = dict(role=role, status="failed", input_representation="candidate_representation", error="fixture unavailable")
            scores[name] = None
            continue
        score = 0.6 + 0.1*i
        values = dict(ba=score, accuracy=score, f1=score, kappa=0.2, auc=None, brier=None, logloss=None)
        learners[name] = dict(role=role, status="evaluated", input_representation="candidate_representation",
            predictions=ref, metadata=ref,
            folds=[dict(fold_id=f["id"], train_subjects=f["train_subjects"], development_subjects=f["development_subjects"],
                        model=ref, metadata=ref, predictions=ref) for f in panel["folds"]],
            subjects={s: dict(n_trials=n, **values, probability_status="not_available_in_core_predictions") for s, n in counts.items()},
            summary={m: distribution(v) if v is not None else None for m, v in values.items()})
        scores[name] = score
    score = sum(scores[n] for n in PRIMARY_SUITE)/3 if missing is None else None
    receipt = UtilityReceipt(candidate_id=entry["id"], candidate_hash=digest(entry), panel_hash=panel["panel_hash"],
        core_receipt_hash=digest(core), evaluation_mode=panel["evaluation_mode"], protocol=ref, inputs=ref,
        status="evaluated" if missing is None else "incomplete", selection_score=score,
        primary_suite=list(PRIMARY_SUITE), learner_scores=scores, learners=learners,
        subjects={s: dict(eligible_trials=n, mean_ba=score, learner_ba=scores) for s, n in counts.items()},
        summary=distribution(score) if score is not None else None,
        failure_reasons=["fixture missing primary"] if missing else [])
    payload = receipt.model_dump(mode="json")
    write_json(out / "utility.json", payload)
    return payload


def quality(plan, result, root, panel, entry, out):
    from app.search.quality_evaluation import METRIC_IDS
    metric = dict(value=None, unit="ratio", direction="non_monotonic", status="not_applicable", reason="fixture",
                  formula="fixture", axes={}, aggregation="subject_equal", applicability="unavailable", selection_role="proxy_observation",
                  denominator=dict(subjects_expected=2, subjects_available=0, expected_ids=["sub-01", "sub-02"],
                                   missing_reasons={"sub-01": "fixture", "sub-02": "fixture"}))
    native = dict(schema_version="fixture", status="evaluated", metric_count=25, candidate_id=entry["id"],
        candidate_recipe_hash=digest(entry["recipe"]), panel_hash=panel["panel_hash"], input_hash=panel["input_hash"], plan_hash=result.plan_ref.sha256,
        coverage=dict(subjects_expected=2, records_expected=2, eligible_trials=sum(t["eligible"] for t in panel["trials"])),
        aggregation="subject_equal", limitations=["fixture"], precue_seconds=[-2.5, -0.5],
        metrics={m: dict(metricID=m, **deepcopy(metric)) for m in METRIC_IDS}, stages={}, bysubject={"large": "omitted"})
    ref = artifact(out / "record.json", {"full_curves": [1, 2, 3]})
    write_json(out / "data-quality.json", native)
    return dict(summary=native, detail_artifacts=[ref])


def reconstruction(plan, result, root, panel, entry, probe, out):
    write_json(out / "probe_panel.json", probe)
    ref = artifact(out / "case.json", {"detail": True})
    summary = dict(candidate_id=entry["id"], candidate_entry_hash=digest(entry), plan_hash=result.plan_ref.sha256,
        probe_hash=probe["probe_hash"], status="evaluated", subjects_expected=2, cases_expected=2,
        trial_cases_expected=sum(len(s["trial_ids"]) for s in probe["subjects"].values()),
        by_case={"case": dict(subjects_assigned=list(probe["subjects"]), subjects_expected=2)})
    payload = dict(summary=summary, details=[ref])
    write_json(out / "reconstruction_evaluation.json", payload)
    payload["artifacts"] = [dict(name=p.relative_to(out).as_posix(), path=p.relative_to(out).as_posix(),
                                 sha256=file_hash(p), bytes=p.stat().st_size) for p in sorted(out.rglob("*.json"))]
    return payload


@pytest.fixture
def adapters(monkeypatch):
    monkeypatch.setattr(a, "evaluate_dataset_utility", utility)
    monkeypatch.setattr(a, "evaluate_dataset_quality", quality)
    monkeypatch.setattr(a, "evaluate_dataset_reconstruction", reconstruction)


@pytest.mark.parametrize("holdout", [False, True])
def test_real_candidate_sibling_attempt_and_development_denominator(tmp_path, adapters, holdout):
    args, probe = case(tmp_path, holdout)
    before = digest([a._dump(x) if not isinstance(x, Path) else str(x) for x in args])
    for attempt in ("a1", "a2"):
        out = tmp_path / "candidate" / "assessment" / attempt
        summary = a.assess_candidate(*args, out, probe)
        assert summary["status"] == "complete", summary
        assert summary["selection_score"] == pytest.approx(0.7)
        assert summary["core_csp_macro_ba"] == 0.91
        assert summary["bindings"]["core_receipt_hash"] == digest(json.loads((tmp_path / "candidate/core-receipt.json").read_text()))
        assert summary["coverage"]["subjects_expected"] == 2
        coverage = summary["utility"]["learner_coverage"]["csp_lda"]
        assert coverage["subjects_expected"] == (1 if holdout else 2)
        assert coverage["eligible_trials_expected"] == sum(a._utility_denominator(args[3]).values())
        assert summary["quality"]["summary"]["coverage"]["subjects_expected"] == 2
        assert "bysubject" not in summary["quality"]["summary"]
        assert "subjects" not in summary["utility"]
        assert set(summary["utility"]["learner_statistics"]["csp_lda"]) == METRIC_NAMES
        assert a.verify_assessment(out, summary, panel_hash=args[3]["panel_hash"], candidate_id="candidate") == summary
        assert json.loads((out / "assessment.json").read_text()) == summary
        assert "assessment.json" not in {r["path"] for r in summary["artifacts"]}
        with pytest.raises(ValueError, match="fresh"):
            a.assess_candidate(*args, out, probe)
    assert digest([a._dump(x) if not isinstance(x, Path) else str(x) for x in args]) == before


def test_missing_primary_no_partial_averaging(tmp_path, adapters, monkeypatch):
    monkeypatch.setattr(a, "evaluate_dataset_utility", lambda *args: utility(*args, missing="fbcsp"))
    args, probe = case(tmp_path)
    out = tmp_path / "assessment"
    s = a.assess_candidate(*args, out, probe)
    assert s["utility"]["status"] == "incomplete", s
    assert s["utility"]["primary_models_available"] == 2
    assert s["selection_score"] is None and not s["selection_ready"]
    assert a.verify_assessment(out, s) == s


@pytest.mark.parametrize("component", ["quality", "utility", "reconstruction"])
def test_component_exception_is_isolated(tmp_path, adapters, monkeypatch, component):
    def fail(*args):
        artifact(args[-1] / "interrupted.json", {"partial": True})
        raise RuntimeError("fixture interruption")
    monkeypatch.setattr(a, "evaluate_dataset_" + component, fail)
    args, probe = case(tmp_path)
    out = tmp_path / "assessment"
    s = a.assess_candidate(*args, out, probe)
    assert s[component]["status"] == "failed"
    assert (s["selection_score"] is None) == (component == "utility")
    assert a.verify_assessment(out, s) == s


def test_no_probe_explicit_na(tmp_path, adapters):
    args, _ = case(tmp_path)
    out = tmp_path / "assessment"
    s = a.assess_candidate(*args, out, None)
    assert s["reconstruction"]["status"] == "not_applicable"
    assert s["selection_ready"]
    assert a.verify_assessment(out, s) == s


def test_interrupted_attempt_is_retained_and_next_attempt_runs(tmp_path, adapters, monkeypatch):
    args, probe = case(tmp_path)
    first = tmp_path / "candidate/assessment/a1"
    def interrupt(*values):
        artifact(values[-1] / "partial.json", {"uncommitted": True})
        raise KeyboardInterrupt()
    monkeypatch.setattr(a, "evaluate_dataset_utility", interrupt)
    with pytest.raises(KeyboardInterrupt):
        a.assess_candidate(*args, first, probe)
    partial_hash = file_hash(first / "utility/partial.json")
    assert not (first / "assessment.json").exists()
    monkeypatch.setattr(a, "evaluate_dataset_utility", utility)
    second = tmp_path / "candidate/assessment/a2"
    s = a.assess_candidate(*args, second, probe)
    assert a.verify_assessment(second, s) == s
    assert file_hash(first / "utility/partial.json") == partial_hash
    with pytest.raises(ValueError, match="fresh"):
        a.assess_candidate(*args, first, probe)


def test_native_utility_cannot_change_frozen_denominator(tmp_path, adapters, monkeypatch):
    def wrong(*values):
        altered = list(values)
        altered[3] = deepcopy(values[3])
        trial = next(t for t in altered[3]["trials"] if t["eligible"])
        trial["eligible"] = False
        return utility(*altered)
    monkeypatch.setattr(a, "evaluate_dataset_utility", wrong)
    args, probe = case(tmp_path)
    out = tmp_path / "assessment"
    s = a.assess_candidate(*args, out, probe)
    assert s["utility"]["status"] == "failed"
    assert "trial count" in s["utility"]["reason"]
    assert s["selection_score"] is None
    assert a.verify_assessment(out, s) == s


def test_reconstruction_returned_inventory_is_verified(tmp_path, adapters, monkeypatch):
    def corrupted(*values):
        payload = reconstruction(*values)
        payload["artifacts"][0]["sha256"] = "0"*64
        return payload
    monkeypatch.setattr(a, "evaluate_dataset_reconstruction", corrupted)
    args, probe = case(tmp_path)
    out = tmp_path / "assessment"
    s = a.assess_candidate(*args, out, probe)
    assert s["reconstruction"]["status"] == "failed"
    assert "checksum mismatch" in s["reconstruction"]["reason"]
    assert s["selection_ready"]
    assert a.verify_assessment(out, s) == s


@pytest.mark.parametrize("kind", ["file", "extra", "missing", "manifest", "persisted", "snapshot", "path", "score", "binding"])
def test_tampering_rejected(tmp_path, adapters, kind):
    args, probe = case(tmp_path)
    out = tmp_path / "assessment"
    s = a.assess_candidate(*args, out, probe)
    if kind in {"file", "extra", "manifest", "persisted", "snapshot"}:
        target = {"file": "utility/protocol.json", "extra": "extra.txt", "manifest": "artifact-manifest.json",
                  "persisted": "assessment.json", "snapshot": "_assessment/summary.json"}[kind]
        (out / target).write_text("{}", encoding="utf-8")
    elif kind == "missing":
        (out / "utility/protocol.json").unlink()
    elif kind == "path":
        s["artifacts"][0]["path"] = "../escape"
    elif kind == "score":
        s["core_csp_macro_ba"] = 0.12  # Valid schema but not the persisted summary.
    else:
        s["bindings"]["core_receipt_hash"] = "0"*64
    with pytest.raises((ValueError, OSError)):
        a.verify_assessment(out, s)


@pytest.mark.parametrize("kind", ["source_child", "source_parent", "engine_child", "core_file"])
def test_output_protection(tmp_path, adapters, kind):
    args, probe = case(tmp_path)
    out = tmp_path / "new"
    if kind == "source_child":
        out = tmp_path / "source/new"
    elif kind == "source_parent":
        out = tmp_path
    elif kind == "engine_child":
        args[1].records.append(dict(result=dict(artifacts=[dict(path="engine/signal_V.npy")])))
        args[1].completed = args[1].total = 1
        out = tmp_path / "store/engine/assessment"
    else:
        args[5]["future_path"] = str(out / "core.json")
    with pytest.raises(ValueError, match="protect"):
        a.assess_candidate(*args, out, probe)


def test_strict_summary_and_identity(tmp_path, adapters):
    args, probe = case(tmp_path)
    out = tmp_path / "assessment"
    s = a.assess_candidate(*args, out, probe)
    with pytest.raises(ValueError):
        AssessmentSummary.model_validate(dict(s, unknown=True))
    with pytest.raises(ValueError):
        a.verify_assessment(out, s, candidate_id="different")
    with pytest.raises(ValueError):
        a.verify_assessment(out, s, panel_hash="0"*64)
    s["quality"]["summary"]["nonfinite"] = float("nan")
    with pytest.raises(ValueError):
        AssessmentSummary.model_validate(s)


def test_real_compiler_cleaning_expansion_and_filter_history():
    from app.search.method_space import seed_entries
    from app.search.recipe_compiler import compile_recipe
    from app.search.scientific_space import build_space
    from app.search.quality_evaluation import _data_chain, _history, _recipe

    context = dict(at_least_four_eeg=True, electrode_positions=True, asr_dependency=True)
    space = build_space(context)
    panel = {"output_contract": dict(sfreq=160.0, tmin=0.0, tmax=2.0)}
    entries = [e for e in seed_entries(space, context) if "repair" in e["id"]]
    assert {e["id"] for e in entries} == {
        "literature-channel-repair", "literature-asr-repair",
        "literature-conditional-asr-repair",
    }
    for entry in entries:
        method = compile_recipe(entry, space, panel, context)
        config = RecordPlan(method_ref=Ref(id="a"*64, sha256="a"*64), record_id="fixture",
                            steps=method.recipe, output=method.output, code_hashes={})
        boundary = _recipe(config, entry)
        assert config.steps[boundary].op == "epoch"
        chain = _data_chain(config)
        assert "detect_bad_channels" not in {s.op for s in chain}
        assert "mark_channels" in {s.op for s in chain}
        asr = [s for s in chain if s.op == "asr_clean"]
        if "asr" in entry["id"]:
            assert len(asr) == 1
            assert asr[0].params["on_insufficient_calibration"] == (
                "identity" if "conditional" in entry["id"] else "error"
            )
        else:
            assert not asr
        history = _history(SimpleNamespace(info=dict(highpass=0.0, lowpass=80.0)),
                           dict(SoftwareFilters={}, HardwareFilters={}), config, entry)
        assert len(history["operations"]) == len(config.steps)
        assert history["nominal_band_hz"][0] > 0
        assert history["nominal_band_hz"][1] < 80
        for field, value in (("input", "incorrect"), ("decision_from", "incorrect"), ("params", {"max_fraction": 0.9})):
            bad = config.model_copy(deep=True)
            mark = next(s for s in bad.steps if s.op == "mark_channels")
            setattr(mark, field, value)
            with pytest.raises(ValueError):
                _recipe(bad, entry)
