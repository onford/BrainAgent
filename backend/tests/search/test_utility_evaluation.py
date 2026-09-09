"""End-to-end utility tests with real artifact checking and numerical learners."""

from copy import deepcopy
import csv
import json
from pathlib import Path

import joblib
import numpy as np
import pytest
from pydantic import ValidationError

from app.preprocessing.storage import digest, file_hash
from app.search import evaluation, utility_evaluation as utility
from app.search.evaluation_numeric import covariance, csp_features
from app.search.learners import LearnerUnavailable
from app.search.utility_contracts import PRIMARY_SUITE, UtilityReceipt
from app.search.panel import freeze_panel
from tests.search import test_evaluation as fixtures
from tests.search.test_evaluation_v2 import cv_case
from tests.search.test_panel import make_input


@pytest.fixture
def case(tmp_path, monkeypatch):
    # These semantic/label-leakage tests spy on Python fit calls in this process.
    # Real spawn, supervision and serial/parallel equivalence are tested separately.
    def local_tasks(payload, execution, cancel_check):
        outcomes = {name: utility._run_learner(name, payload["trials"],
            {k: Path(v) for k, v in payload["paths"].items()}, payload["panel"], payload["core"],
            payload["core_rows"], payload["band"], Path(payload["output"])) for name in utility.LEARNER_SUITE}
        return outcomes, {"test_dispatch": "in-process spies", "configuration": execution}
    monkeypatch.setattr(utility, "run_utility_tasks", local_tasks)
    # Enough examples in even the smallest inner training subject for MI/CSP.
    monkeypatch.setattr(fixtures, "make_input", lambda root: make_input(root, counts=(6, 8, 14)))
    result, plan, root, panel = cv_case(tmp_path)
    core = evaluation.evaluate(result, plan, root, panel, tmp_path / "core", policy={"adaptation": "euclidean_alignment"})
    assert core["status"] == "evaluated", core
    entry = {"id": "utility-fixture", "parameters": {"adaptation": "euclidean_alignment"}}
    return plan, result, root, panel, entry, core


def run(case, output):
    return utility.evaluate_dataset_utility(*case, output)


def test_complete_suite_equal_subject_denominator_and_saved_models(case, tmp_path):
    result = run(case, tmp_path / "utility")
    assert result["status"] == "evaluated", result["failure_reasons"]
    UtilityReceipt.model_validate(json.loads((tmp_path / "utility/utility.json").read_text(encoding="utf-8")))
    assert result["selection_score"] == pytest.approx(np.mean([result["learner_scores"][k] for k in PRIMARY_SUITE]))
    assert result["selection_score"] == pytest.approx(np.mean([s["mean_ba"] for s in result["subjects"].values()]))
    assert [s["eligible_trials"] for s in result["subjects"].values()] == [6, 8, 14]
    manifest = json.loads(Path(result["inputs"]["path"]).read_text(encoding="utf-8"))
    eligible_ids = {t["event_id"] for t in case[3]["trials"] if t["eligible"]}
    for name, learner in result["learners"].items():
        assert learner["status"] == "evaluated", (name, learner["error"])
        assert learner["summary"]["ba"]["n_subjects"] == 3
        rows = json.loads(Path(learner["predictions"]["path"]).read_text(encoding="utf-8"))
        assert len(rows) == len({r["event_id"] for r in rows}) == 28
        assert {r["event_id"] for r in rows} == eligible_ids
        assert all(r["epoch_index"] >= 0 for r in rows)
        assert learner["predictions"]["sha256"] == file_hash(Path(learner["predictions"]["path"]))
        if name in {"csp_lda", "logvar_lr"}:
            assert all(r["proba_right"] is None for r in rows)
            assert learner["summary"]["auc"] is None
        else:
            assert all(0 <= r["proba_right"] <= 1 for r in rows)
            assert learner["summary"]["auc"] is not None
        fold = learner["folds"][0]
        metadata = json.loads(Path(fold["metadata"]["path"]).read_text(encoding="utf-8"))
        assert set(metadata["train_subjects"]).isdisjoint(metadata["development_subjects"])
        assert fold["model"]["sha256"] == file_hash(Path(fold["model"]["path"]))
        # Only load our own freshly generated, checksum-verified local models.
        model = joblib.load(fold["model"]["path"])
        predictions = json.loads(Path(fold["predictions"]["path"]).read_text(encoding="utf-8"))
        indices = [p["array_index"] for p in predictions]
        with evaluation._mapped(manifest["arrays"]["phys_V" if name == "ea_fbcsp" else "representation"]["path"]) as X:
            if name in {"csp_lda", "logvar_lr"}:
                covs = np.array([covariance(X[i]) for i in indices])
                features = csp_features(covs, model["filters"]) if name == "csp_lda" else model["scaler"].transform(
                    np.log(np.maximum(np.diagonal(covs, axis1=1, axis2=2), 1e-20)))
                replay = model["classifier"].predict(features)
            else:
                replay = model.predict(X[indices], np.array([p["subject"] for p in predictions]) if name == "ea_fbcsp" else None)
                reference_probabilities = model.predict_proba(X[indices], np.array([p["subject"] for p in predictions]) if name == "ea_fbcsp" else None)
                np.testing.assert_allclose(reference_probabilities[:, 1], [p["proba_right"] for p in predictions], atol=1e-12)
            assert list(replay) == [p["prediction"] for p in predictions]
    assert any("pre_adaptation" in s for s in result["learners"]["ea_fbcsp"]["warnings"])


def test_primary_failure_never_averages_remaining_winners(case, tmp_path, monkeypatch):
    original = utility.make_learner

    def factory(name, **kwargs):
        if name == "fbcsp":
            raise LearnerUnavailable("intentional absent primary")
        return original(name, **kwargs)

    monkeypatch.setattr(utility, "make_learner", factory)
    receipt = run(case, tmp_path / "failed-primary")
    assert receipt["status"] == "incomplete" and receipt["selection_score"] is None
    assert receipt["learner_scores"]["csp_lda"] is not None and receipt["learner_scores"]["ts_lr"] is not None
    assert receipt["learner_scores"]["fbcsp"] is None
    assert "intentional absent primary" in " ".join(receipt["failure_reasons"])
    assert all(s["mean_ba"] is None for s in receipt["subjects"].values())


def test_benchmark_failures_do_not_change_complete_primary_utility(case, tmp_path, monkeypatch):
    original = utility.make_learner

    def factory(name, **kwargs):
        if name in {"fgmdm", "ea_fbcsp"}:
            raise RuntimeError("intentional optional benchmark failure")
        return original(name, **kwargs)

    monkeypatch.setattr(utility, "make_learner", factory)
    receipt = run(case, tmp_path / "failed-extra")
    assert receipt["status"] == "evaluated" and receipt["failure_reasons"] == []
    assert receipt["learner_scores"]["fgmdm"] is None and receipt["learner_scores"]["ea_fbcsp"] is None
    assert receipt["selection_score"] == pytest.approx(np.mean([receipt["learner_scores"][k] for k in PRIMARY_SUITE]))


def test_actual_representation_epoch_indices_and_physical_ea_input(case, tmp_path, monkeypatch):
    fit_calls = []
    original = utility.make_learner

    def factory(name, **kwargs):
        model = original(name, **kwargs)
        actual_fit = model.fit

        def fit(X, y, subjects):
            fit_calls.append((name, np.asarray(X).copy(), np.asarray(y).copy(), np.asarray(subjects).copy(), deepcopy(kwargs)))
            return actual_fit(X, y, subjects)

        # A local spy is not pickleable; restore method before model serialization.
        def fitted(X, y, subjects):
            result = fit(X, y, subjects)
            del model.fit
            return result

        model.fit = fitted
        return model

    monkeypatch.setattr(utility, "make_learner", factory)
    receipt = run(case, tmp_path / "routing")
    assert receipt["status"] == "evaluated", receipt["failure_reasons"]
    manifest = json.loads(Path(receipt["inputs"]["path"]).read_text())
    for row in manifest["trials"]:
        record = case[5]["representation"]["records"][row["record_id"]]
        with evaluation._mapped(record["array_path"]) as source, evaluation._mapped(manifest["arrays"]["representation"]["path"]) as assembled:
            np.testing.assert_array_equal(assembled[row["array_index"]], source[row["epoch_index"]])
    for name, X, y, groups, options in fit_calls:
        fold = next(f for f in case[3]["folds"] if set(f["train_subjects"]) == set(groups))
        assert set(groups).isdisjoint(fold["development_subjects"])
        selected = [r for r in manifest["trials"] if r["subject"] in set(groups)]
        assert y.tolist() == [r["label"] for r in selected]
        key = "phys_V" if name == "ea_fbcsp" else "representation"
        with evaluation._mapped(manifest["arrays"][key]["path"]) as array:
            np.testing.assert_array_equal(X, array[[r["array_index"] for r in selected]])
        if name != "fgmdm":
            assert options["param_grid"]["C"] == [0.1, 1.0, 10.0]
            assert options["inner_splits"] == 2
        if name in {"fbcsp", "ea_fbcsp"}:
            assert options["param_grid"]["k_best"] == [10]
    assert len(fit_calls) == 12  # Four independently fitted advanced learners × three folds.


@pytest.mark.parametrize("kind", ["missing", "wrong_fold", "wrong_label", "duplicate"])
def test_corrupted_core_trial_provenance_is_rejected(case, tmp_path, kind):
    plan, result, root, panel, entry, core = case
    core = deepcopy(core)
    path = Path(core["predictions_path"])
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    row = next(r for r in rows if r["eligible"] == "True")
    if kind == "missing":
        rows.remove(row)
    elif kind == "duplicate":
        rows.append(row.copy())
    else:
        row["fold_id" if kind == "wrong_fold" else "label"] = "wrong"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    core["predictions_sha256"] = file_hash(path)  # Matching checksum is insufficient provenance.
    receipt = run((plan, result, root, panel, entry, core), tmp_path / "corrupt")
    assert receipt["status"] == "incomplete" and receipt["selection_score"] is None
    assert all(s is None for s in receipt["learner_scores"].values())


@pytest.mark.parametrize("bad_value", [0.0, float("nan")])
def test_degenerate_representation_cannot_receive_a_perfect_fake_score(case, tmp_path, bad_value):
    core = deepcopy(case[5])
    rep = next(iter(core["representation"]["records"].values()))
    path = Path(rep["array_path"])
    shape = np.load(path, mmap_mode="r").shape
    np.save(path, np.full(shape, bad_value))
    rep["array_sha256"] = file_hash(path)
    receipt = run((*case[:5], core), tmp_path / "invalid-signal")
    assert receipt["selection_score"] is None
    assert any("zero" in s or "nonfinite" in s for s in receipt["failure_reasons"])


def test_invalid_probability_has_no_uniform_fallback(case, tmp_path, monkeypatch):
    original = utility._predict_all

    def predict(model, X, subjects):
        predicted, p, score, audit = original(model, X, subjects)
        return predicted, np.zeros_like(p) if model.learner == "ts_lr" else p, score, audit

    monkeypatch.setattr(utility, "_predict_all", predict)
    receipt = run(case, tmp_path / "invalid-probability")
    assert receipt["selection_score"] is None
    assert "sum to one" in receipt["learners"]["ts_lr"]["error"]


def test_metrics_are_subject_macro_and_probability_na_is_explicit():
    rows = [{"label": label, "prediction": predicted, "proba_right": p, "decision_score": p}
            for label, predicted, p in zip(["left", "left", "left", "right"], ["left", "left", "right", "right"], [.1, .2, .8, .9])]
    metric = utility._metrics(rows, "right")
    assert metric["ba"] == pytest.approx(5 / 6)
    assert metric["accuracy"] == .75 and metric["f1"] == pytest.approx(2 / 3)
    assert metric["kappa"] == .5 and metric["auc"] == 1
    assert metric["brier"] == pytest.approx(.175)
    for row in rows:
        row.update(proba_right=None, decision_score=None)
    discrete = utility._metrics(rows, "right")
    assert discrete["auc"] is None and discrete["brier"] is None and discrete["logloss"] is None
    assert utility._distribution([.25, .5, 1])["mean"] == pytest.approx(7 / 12)


def test_strict_contract_rejects_partial_average_nan_and_unknown_fields(case, tmp_path):
    good = run(case, tmp_path / "contract")
    assert good["status"] == "evaluated"
    for key, value in [("selection_score", float("nan")), ("selection_score", .123), ("made_up", 1)]:
        bad = deepcopy(good)
        bad[key] = value
        with pytest.raises(ValidationError):
            UtilityReceipt.model_validate(bad)


def test_public_protocol_can_be_frozen_before_candidate_runs(case, tmp_path):
    frozen = utility.utility_protocol()
    assert frozen["inner_cv"]["fbcsp"] == {"C": [.1, 1., 10.], "n_components": [4, 6], "k_best": [10]}
    assert frozen["library_versions"]["numpy"] == "1.26.4"
    assert "learners.py" in frozen["implementation_sha256"]
    receipt = run(case, tmp_path / "protocol")
    assert receipt["protocol"]["sha256"] == digest(frozen)
    assert utility.utility_protocol() == frozen
    frozen["inner_cv"]["fbcsp"]["C"].append(99)
    assert utility.utility_protocol()["inner_cv"]["fbcsp"]["C"] == [.1, 1., 10.]


def test_explicit_holdout_scores_only_development_and_preserves_train_roles(case, tmp_path):
    plan, result, root, _, entry, _ = case
    panel = freeze_panel(plan.input_snapshot, {r.record_id: r.record_id for r in plan.records}, seed=42,
                         tmin=-.1, tmax=.1, sfreq=160, train_subjects=["sub-01"], development_subjects=["sub-02", "sub-03"])
    core = evaluation.evaluate(result, plan, root, panel, tmp_path / "holdout-core", policy={"adaptation": "euclidean_alignment"})
    receipt = run((plan, result, root, panel, entry, core), tmp_path / "holdout-utility")
    assert receipt["status"] == "evaluated", receipt["failure_reasons"]
    assert receipt["evaluation_mode"] == "subject_holdout"
    assert set(receipt["subjects"]) == {"sub-02", "sub-03"}
    for name, learner in receipt["learners"].items():
        assert learner["status"] == "evaluated", (name, learner["error"])
        rows = json.loads(Path(learner["predictions"]["path"]).read_text())
        assert len(rows) == 22 and {row["subject"] for row in rows} == {"sub-02", "sub-03"}
        assert learner["folds"][0]["train_subjects"] == ["sub-01"]
        if name in {"fbcsp", "ts_lr", "ea_fbcsp"}:
            metadata = json.loads(Path(learner["folds"][0]["metadata"]["path"]).read_text())
            assert not metadata["inner_cv"]["enabled"]
            assert "one training subject" in metadata["inner_cv"]["reason"]


def test_full109_pipeline_fit_budget_is_fixed():
    subjects = [f"sub-{s:03}" for s in range(109)]
    panel = {"output_contract": {"channels": list(range(64))},
             "trials": [{"subject": s, "eligible": True} for s in subjects for _ in range(45)],
             "folds": [{"train_subjects": [s for j, s in enumerate(subjects) if j % 5 != k],
                        "development_subjects": subjects[k::5]} for k in range(5)]}
    budget = utility.utility_fit_budget(panel)
    assert budget["pipeline_fits"] == {"csp_lda": 5, "fbcsp": 95, "ts_lr": 50, "fgmdm": 5, "ea_fbcsp": 95, "logvar_lr": 5}
    assert budget["total_utility_pipeline_fits"] == 255 and budget["prior_core_evaluation_fits"] == 10
