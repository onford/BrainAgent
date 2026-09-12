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
from app.search.utility_contracts import (
    EEGNET_SEEDS, LEARNER_SUITE, PRIMARY_SUITE,
    LEGACY_LEARNER_SUITE, LEGACY_PRIMARY_SUITE, UtilityReceipt,
)
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


def utility(plan, result, root, panel, entry, core, out, missing=None, *, legacy=False):
    if not legacy:
        return seeded_utility(plan, result, root, panel, entry, core, out, missing)
    ref = artifact(out / "protocol.json", {"fixture": True})
    counts = a._utility_denominator(panel)
    learners, scores = {}, {}
    suite = LEGACY_LEARNER_SUITE if legacy else LEARNER_SUITE
    primary = LEGACY_PRIMARY_SUITE if legacy else PRIMARY_SUITE

    def distribution(v):
        return dict(mean=v, lower_quartile=v, subject_sd=0.0, n_subjects=len(counts))

    def prediction(score):
        values = dict(ba=score, accuracy=score, f1=score, kappa=0.2, auc=None, brier=None, logloss=None)
        return dict(status="evaluated", predictions=ref, metadata=ref,
            folds=[dict(fold_id=f["id"], train_subjects=f["train_subjects"], development_subjects=f["development_subjects"],
                        model=ref, metadata=ref, predictions=ref) for f in panel["folds"]],
            subjects={s: dict(n_trials=n, **values, probability_status="not_available_in_core_predictions") for s, n in counts.items()},
            summary={m: distribution(v) if v is not None else None for m, v in values.items()})

    for i, name in enumerate(suite):
        role = "primary" if name in primary else "diagnostic" if legacy else "benchmark"
        if name == missing or (legacy and name not in primary):
            learners[name] = dict(role=role, status="failed", input_representation="candidate_representation", error="fixture unavailable")
            scores[name] = None
            continue
        score = 0.6 + 0.1*i if legacy else 0.7 if name == "eegnet" else 0.95
        learner = dict(role=role, input_representation="candidate_representation", **prediction(score))
        if name == "eegnet":
            learner["folds"] = []
            learner["seeds"] = {str(seed): dict(seed=seed, **prediction(value))
                                for seed, value in zip(EEGNET_SEEDS, [0.6, 0.7, 0.8])}
            learner["seed_summary"] = dict(seeds=list(EEGNET_SEEDS), mean_ba=0.7,
                                           seed_sd=(0.02/3)**0.5, minimum_ba=0.6, maximum_ba=0.8)
        learners[name] = learner
        scores[name] = score
    complete = all(scores[n] is not None for n in primary)
    score = sum(scores[n] for n in primary)/len(primary) if complete else None
    receipt = UtilityReceipt(utility_version=1 if legacy else 2,
        candidate_id=entry["id"], candidate_hash=digest(entry), panel_hash=panel["panel_hash"],
        core_receipt_hash=digest(core), evaluation_mode=panel["evaluation_mode"], protocol=ref, inputs=ref,
        status="evaluated" if complete else "incomplete", selection_score=score,
        primary_suite=list(primary), learner_scores=scores, learners=learners,
        seed_summary=learners.get("eegnet", {}).get("seed_summary"),
        subjects={s: dict(eligible_trials=n, mean_ba=score, learner_ba=scores) for s, n in counts.items()},
        summary=distribution(score) if score is not None else None,
        failure_reasons=[] if complete else ["fixture missing primary"])
    payload = receipt.model_dump(mode="json")
    write_json(out / "utility.json", payload)
    return payload


def seeded_utility(plan, result, root, panel, entry, core, out, missing=None):
    """Real prediction JSON and derived metrics, without training a model."""
    import numpy as np
    from app.search.utility_evaluation import _metrics, _distribution

    ref = artifact(out / "protocol.json", {"fixture": True})
    trials = [t for t in panel["trials"] if t["eligible"]]
    indices = {t["event_id"]: i for i, t in enumerate(trials)}
    counts = a._utility_denominator(panel)
    left, right = panel["class_labels"]["left"], panel["class_labels"]["right"]

    def run(name, seed, mistakes, destination):
        rows, outputs = [], []
        for fold in panel["folds"]:
            fold_rows = []
            for subject in fold["development_subjects"]:
                for i, t in enumerate(t for t in trials if t["subject"] == subject):
                    prediction = ({left: right, right: left}[t["label"]] if i < mistakes else t["label"])
                    p = 0.8 if prediction == right else 0.2
                    row = dict(event_id=t["event_id"], record_id=t["record_id"], subject=subject,
                               label=t["label"], epoch_index=i, array_index=indices[t["event_id"]],
                               fold_id=fold["id"], prediction=prediction,
                               proba_left=1-p if seed is not None else None,
                               proba_right=p if seed is not None else None,
                               decision_score=p if seed is not None else None)
                    if seed is not None:
                        row["seed"] = seed
                    fold_rows.append(row)
            folder = destination / fold["id"]
            metadata = dict(learner=name, seed=seed, fold_id=fold["id"],
                            train_subjects=fold["train_subjects"], development_subjects=fold["development_subjects"],
                            train_event_ids=[t["event_id"] for t in trials if t["subject"] in fold["train_subjects"]],
                            development_event_ids=[r["event_id"] for r in fold_rows])
            outputs.append(dict(fold_id=fold["id"], train_subjects=fold["train_subjects"],
                                development_subjects=fold["development_subjects"],
                                model=ref, metadata=artifact(folder / "metadata.json", metadata),
                                predictions=artifact(folder / "predictions.json", fold_rows)))
            rows.extend(fold_rows)
        subjects = {s: _metrics([r for r in rows if r["subject"] == s], right) for s in counts}
        return dict(status="evaluated", predictions=artifact(destination / "predictions.json", rows),
                    metadata=artifact(destination / "metadata.json", dict(learner=name, seed=seed, folds=outputs)),
                    folds=outputs, subjects=subjects,
                    summary={m: _distribution([s[m] for s in subjects.values()]) for m in METRIC_NAMES})

    learners = {}
    for name in LEARNER_SUITE:
        common = dict(role="primary" if name == "eegnet" else "benchmark", input_representation="candidate_representation")
        if name == missing:
            learners[name] = dict(**common, status="failed", error="fixture unavailable")
        elif name == "csp_lda":
            learners[name] = dict(**common, **run(name, None, 0, out / name))
        else:
            runs = {str(k): dict(seed=k, **run(name, k, mistakes, out / name / f"s{k}"))
                    for k, mistakes in zip(EEGNET_SEEDS, [2, 1, 0])}
            subjects = {s: dict(n_trials=counts[s], probability_status="available",
                                **{m: float(np.mean([r["subjects"][s][m] for r in runs.values()])) for m in METRIC_NAMES})
                        for s in counts}
            scores = [r["summary"]["ba"]["mean"] for r in runs.values()]
            seed_summary = dict(seeds=list(EEGNET_SEEDS), mean_ba=float(np.mean(scores)),
                                seed_sd=float(np.std(scores)), minimum_ba=min(scores), maximum_ba=max(scores))
            combined = [row for r in runs.values() for row in json.loads(Path(r["predictions"]["path"]).read_text())]
            learners[name] = dict(**common, status="evaluated", seeds=runs, seed_summary=seed_summary,
                                 subjects=subjects, summary={m: _distribution([s[m] for s in subjects.values()]) for m in METRIC_NAMES},
                                 predictions=artifact(out / name / "predictions.json", combined),
                                 metadata=artifact(out / name / "metadata.json", {"learner": name, "seed_summary": seed_summary}))
    scores = {n: r["summary"]["ba"]["mean"] if r["status"] == "evaluated" else None for n, r in learners.items()}
    score = scores["eegnet"]
    receipt = UtilityReceipt(utility_version=2, candidate_id=entry["id"], candidate_hash=digest(entry),
        panel_hash=panel["panel_hash"], core_receipt_hash=digest(core), evaluation_mode=panel["evaluation_mode"],
        protocol=ref, inputs=ref, status="evaluated" if score is not None else "incomplete", selection_score=score,
        primary_suite=list(PRIMARY_SUITE), learner_scores=scores, learners=learners,
        seed_summary=learners["eegnet"].get("seed_summary"),
        subjects={s: dict(eligible_trials=n, mean_ba=learners["eegnet"].get("subjects", {}).get(s, {}).get("ba"),
                         learner_ba={name: r.get("subjects", {}).get(s, {}).get("ba") for name, r in learners.items()})
                  for s, n in counts.items()},
        summary=learners["eegnet"].get("summary", {}).get("ba"),
        failure_reasons=[] if score is not None else ["fixture missing primary"])
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
        assert summary["schema_version"] == "assessment-v2"
        assert summary["utility"]["primary_models_expected"] == 1
        assert summary["utility"]["primary_models_available"] == 1
        assert summary["utility"]["primary_suite"] == ["eegnet"]
        assert summary["utility"]["seed_summary"]["seeds"] == list(EEGNET_SEEDS)
        expected = 3 * sum(a._utility_denominator(args[3]).values())
        assert summary["utility"]["primary_trial_predictions_expected"] == expected
        assert summary["utility"]["primary_trial_predictions_available"] == expected
        assert summary["selection_score"] == pytest.approx(5 / 6)
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
    monkeypatch.setattr(a, "evaluate_dataset_utility", lambda *args: utility(*args, missing="eegnet"))
    args, probe = case(tmp_path)
    out = tmp_path / "assessment"
    s = a.assess_candidate(*args, out, probe)
    assert s["utility"]["status"] == "incomplete", s
    assert s["utility"]["primary_models_available"] == 0
    assert s["utility"]["primary_models_expected"] == 1
    assert s["utility"]["primary_trial_predictions_available"] == 0
    assert s["utility"]["seed_summary"] is None
    assert s["selection_score"] is None and not s["selection_ready"]
    assert a.verify_assessment(out, s) == s


def test_benchmark_failure_does_not_change_eegnet_selection(tmp_path, adapters, monkeypatch):
    monkeypatch.setattr(a, "evaluate_dataset_utility", lambda *args: utility(*args, missing="csp_lda"))
    args, probe = case(tmp_path)
    out = tmp_path / "assessment"
    summary = a.assess_candidate(*args, out, probe)
    assert summary["selection_ready"]
    assert summary["selection_score"] == pytest.approx(5 / 6)
    assert summary["utility"]["learner_scores"]["csp_lda"] is None
    assert summary["utility"]["primary_models_available"] == 1
    assert a.verify_assessment(out, summary) == summary


@pytest.mark.parametrize("mutation", ["missing_seed", "seed_trial_count", "seed_mean", "legacy"])
def test_native_utility_requires_all_three_complete_seeds(tmp_path, adapters, monkeypatch, mutation):
    def invalid(*args):
        payload = utility(*args, legacy=mutation == "legacy")
        if mutation == "missing_seed":
            payload["learners"]["eegnet"]["seeds"].pop(str(EEGNET_SEEDS[0]))
        elif mutation == "seed_trial_count":
            run = payload["learners"]["eegnet"]["seeds"][str(EEGNET_SEEDS[0])]
            next(iter(run["subjects"].values()))["n_trials"] += 1
        elif mutation == "seed_mean":
            payload["seed_summary"]["mean_ba"] = 0.65
        write_json(args[-1] / "utility.json", payload)
        return payload

    monkeypatch.setattr(a, "evaluate_dataset_utility", invalid)
    args, probe = case(tmp_path)
    out = tmp_path / "assessment"
    summary = a.assess_candidate(*args, out, probe)
    assert summary["utility"]["status"] == "failed"
    assert summary["selection_score"] is None
    assert summary["utility"]["seed_summary"] is None
    assert a.verify_assessment(out, summary) == summary


@pytest.mark.parametrize("mutation", ["models", "predictions", "expected", "seed_summary", "policy", "version", "score"])
def test_v2_summary_rejects_old_denominators_and_inconsistent_seeds(tmp_path, adapters, mutation):
    args, probe = case(tmp_path)
    summary = a.assess_candidate(*args, tmp_path / "assessment", probe)
    if mutation == "models":
        summary["utility"]["primary_models_expected"] = 3
    elif mutation == "predictions":
        summary["utility"]["primary_trial_predictions_available"] //= 3
    elif mutation == "expected":
        summary["utility"]["primary_trial_predictions_expected"] //= 3
    elif mutation == "seed_summary":
        summary["utility"]["seed_summary"] = None
    elif mutation == "policy":
        summary["selection_policy"] = "utility_only_all_three_primary_models_all_frozen_subjects"
    elif mutation == "version":
        summary["schema_version"] = "assessment-v1"
    else:
        summary["selection_score"] = 0.95  # CSP benchmark cannot become selection utility.
    with pytest.raises(ValueError):
        AssessmentSummary.model_validate(summary)


def test_historical_v1_assessment_verifies_without_rewriting_or_rescoring(tmp_path, adapters):
    from app.search.assessment_contracts import LegacyUtilitySummary

    args, probe = case(tmp_path)
    out = tmp_path / "assessment"
    summary = a.assess_candidate(*args, out, probe)
    # Build a synthetic v1 artifact tree in test temp space, never inspect history.
    native = utility(*args, out / "utility", legacy=True)
    native.pop("seed_summary")
    for learner in native["learners"].values():
        learner.pop("seeds")
        learner.pop("seed_summary")
    write_json(out / "utility/utility.json", native)
    expected = a._utility_denominator(args[3])
    coverage = {name: dict(subjects_expected=len(expected),
                          subjects_available=len(learner["subjects"]),
                          eligible_trials_expected=sum(expected.values()),
                          trials_available=sum(s["n_trials"] for s in learner["subjects"].values()))
                for name, learner in native["learners"].items()}
    legacy = LegacyUtilitySummary(
        status="evaluated", evaluation_mode=native["evaluation_mode"], reason=None,
        primary_suite=list(LEGACY_PRIMARY_SUITE), learner_scores=native["learner_scores"],
        learner_statuses={n: r["status"] for n, r in native["learners"].items()},
        learner_statistics={n: {m: r["summary"].get(m) for m in METRIC_NAMES}
                            for n, r in native["learners"].items()},
        learner_coverage=coverage, summary=native["summary"], primary_models_available=3,
        primary_trial_predictions_expected=3*sum(expected.values()),
        primary_trial_predictions_available=3*sum(expected.values()),
        receipt_artifact=a._ref(out / "utility/utility.json", out), failure_artifact=None,
        failure_reasons=[], warnings=native["warnings"],
    )
    summary.update(schema_version="assessment-v1", utility=legacy.model_dump(mode="json"),
                   selection_score=native["selection_score"],
                   selection_policy="utility_only_all_three_primary_models_all_frozen_subjects")
    content = {k: v for k, v in summary.items() if k not in {"artifacts", "artifact_manifest"}}
    write_json(out / "_assessment/summary.json", a.AssessmentSnapshot(content=content).model_dump(mode="json"))
    (out / "artifact-manifest.json").unlink()
    artifacts = a._inventory(out)
    manifest = a.AssessmentManifest(bindings=summary["bindings"], artifacts=artifacts)
    write_json(out / "artifact-manifest.json", manifest.model_dump(mode="json"))
    ref = a._ref(out / "artifact-manifest.json", out)
    artifacts.append(a.ArtifactEntry(**ref.model_dump(), component="assessment"))
    summary.update(artifact_manifest=ref.model_dump(mode="json"),
                   artifacts=[r.model_dump(mode="json") for r in artifacts])
    write_json(out / "assessment.json", summary)
    before = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
    assert a.verify_assessment(out, summary) == summary
    assert summary["selection_score"] == pytest.approx(0.7)
    assert summary["utility"]["learner_scores"]["csp_lda"] == 0.6
    assert "seed_summary" not in summary["utility"]
    assert {p: p.read_bytes() for p in out.rglob("*") if p.is_file()} == before


def test_real_three_seed_utility_integrates_with_core_v3_and_assessment_v2(tmp_path, monkeypatch):
    from app.search import evaluation
    from tests.search.test_evaluation_v2 import cv_case

    result, plan, root, panel = cv_case(tmp_path, tmax=0.4)
    core = evaluation.evaluate(result, plan, root, panel, tmp_path / "core")
    assert core["status"] == "evaluated", core

    def auxiliary_unavailable(*args):
        raise ValueError("auxiliary fixture unavailable")

    monkeypatch.setattr(a, "evaluate_dataset_quality", auxiliary_unavailable)
    out = tmp_path / "assessment"
    summary = a.assess_candidate(
        plan, result, root, panel, {"id": "synthetic-eegnet"}, core, out, None,
        utility_execution={"max_workers": 1, "eegnet_training": {"max_epochs": 1, "patience": 1}},
    )
    assert summary["selection_ready"], summary["utility"]["reason"]
    assert summary["schema_version"] == "assessment-v2"
    assert summary["utility"]["primary_models_available"] == 1
    native = json.loads((out / "utility/utility.json").read_text(encoding="utf-8"))
    assert summary["utility"]["seed_summary"] == native["seed_summary"]
    assert summary["selection_score"] == native["learner_scores"]["eegnet"]
    assert native["learners"]["csp_lda"]["status"] == "evaluated"
    expected = {t["event_id"] for t in panel["trials"] if t["eligible"] and t["role"] == "development"}
    predicted = []
    for seed in EEGNET_SEEDS:
        run = native["learners"]["eegnet"]["seeds"][str(seed)]
        rows = json.loads(Path(run["predictions"]["path"]).read_text(encoding="utf-8"))
        assert len(rows) == len(expected)
        assert {r["event_id"] for r in rows} == expected
        predicted.extend(rows)
    assert len(predicted) == summary["utility"]["primary_trial_predictions_available"] == 3*len(expected)
    assert summary["utility"]["primary_trial_predictions_expected"] == 3*len(expected)
    assert a.verify_assessment(out, summary) == summary


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
        assert len(history["operations"]) == len(chain)
        assert history["nominal_band_hz"][0] > 0
        assert history["nominal_band_hz"][1] < 80
        for field, value in (("input", "incorrect"), ("decision_from", "incorrect"), ("params", {"max_fraction": 0.9})):
            bad = config.model_copy(deep=True)
            mark = next(s for s in bad.steps if s.op == "mark_channels")
            setattr(mark, field, value)
            with pytest.raises(ValueError):
                _recipe(bad, entry)
