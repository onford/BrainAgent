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
from app.search import eegnet
from app.search.utility_contracts import UtilityReceipt
from app.search.panel import freeze_panel
from tests.search import test_evaluation as fixtures
from tests.search.test_evaluation_v2 import cv_case
from tests.search.test_panel import make_input


TRAINING = {"max_epochs": 2, "patience": 1, "batch_size": 8}
EXECUTION = {"eegnet_training": TRAINING}


@pytest.fixture
def case(tmp_path, monkeypatch):
    # These semantic/label-leakage tests spy on Python fit calls in this process.
    # Real spawn, supervision and serial/parallel equivalence are tested separately.
    def local_tasks(payload, execution, cancel_check):
        outcomes = {name: utility._run_learner(name, payload["trials"],
            {k: Path(v) for k, v in payload["paths"].items()}, payload["panel"], payload["core"],
            payload["core_rows"], payload["band"], Path(payload["output"]), training_config=execution["eegnet_training"]) for name in utility.LEARNER_SUITE}
        return outcomes, {"test_dispatch": "in-process spies", "configuration": execution}
    monkeypatch.setattr(utility, "run_utility_tasks", local_tasks)
    monkeypatch.setattr(fixtures, "make_input", lambda root: make_input(root, counts=(6, 8, 14)))
    result, plan, root, panel = cv_case(tmp_path, tmax=.4)
    core = evaluation.evaluate(result, plan, root, panel, tmp_path / "core")
    assert core["status"] == "evaluated", core
    entry = {"id": "utility-fixture", "parameters": {}}
    return plan, result, root, panel, entry, core


def run(case, output):
    return utility.evaluate_dataset_utility(*case, output, execution=EXECUTION)


def read(ref):
    path = Path(ref["path"])
    assert file_hash(path) == ref["sha256"]
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["eegnet", "csp_lda"])
def test_input_mapping_failure_preserves_original_error(tmp_path, name):
    outcome = utility._run_learner(
        name, [], {"representation": tmp_path / "missing.npy",
                   "core_covariances": tmp_path / "missing.npy"},
        {"class_labels": {"right": "right_hand"}}, {}, {}, None, tmp_path,
    )
    assert outcome["status"] == "failed"
    assert "FileNotFoundError" in outcome["error"]
    assert outcome["seeds"] == {} and outcome["summary"] == {}
    assert outcome["predictions"] is None
    assert read(outcome["metadata"])["error"] == outcome["error"]


def test_complete_three_seed_subject_denominators_and_checkpoint_replay(case, tmp_path):
    result = run(case, tmp_path / "utility")
    assert result["status"] == "evaluated", result["failure_reasons"]
    UtilityReceipt.model_validate(result)
    assert result["utility_version"] == 2 and result["primary_suite"] == ["eegnet"]
    assert set(result["learners"]) == {"eegnet", "csp_lda"}
    assert [s["eligible_trials"] for s in result["subjects"].values()] == [6, 8, 14]
    manifest = read(result["inputs"])
    learner = result["learners"]["eegnet"]
    assert learner["folds"] == [] and set(learner["seeds"]) == {"17", "42", "2026"}
    combined = read(learner["predictions"])
    assert len(combined) == 84
    seed_scores = []
    for seed in [17, 42, 2026]:
        output = learner["seeds"][str(seed)]
        rows = read(output["predictions"])
        assert len(rows) == len({r["event_id"] for r in rows}) == 28
        assert rows == [r for r in combined if r["seed"] == seed]
        subject_scores = []
        for subject, metric in output["subjects"].items():
            selected = [r for r in rows if r["subject"] == subject]
            recalls = [np.mean([r["prediction"] == label for r in selected if r["label"] == label])
                       for label in case[3]["class_labels"].values()]
            subject_scores.append(float(np.mean(recalls)))
            assert metric["ba"] == pytest.approx(subject_scores[-1])
        seed_scores.append(float(np.mean(subject_scores)))
        for fold in output["folds"]:
            meta, predictions = read(fold["metadata"]), read(fold["predictions"])
            assert meta["seed"] == seed
            fit, val = set(meta["fit_subjects"]), set(meta["validation_subjects"])
            assert fit and val and not fit & val
            assert fit | val == set(fold["train_subjects"])
            assert not (fit | val) & set(fold["development_subjects"])
            assert set(meta["normalization_fit_subjects"]) == fit
            assert not set(meta["fit_event_ids"]) & set(meta["validation_event_ids"])
            assert set(meta["fit_event_ids"]) | set(meta["validation_event_ids"]) == set(meta["train_event_ids"])
            assert file_hash(Path(fold["model"]["path"])) == fold["model"]["sha256"]
            with evaluation._mapped(manifest["arrays"]["representation"]["path"]) as X:
                probability = eegnet.predict_checkpoint(fold["model"]["path"], X[[r["array_index"] for r in predictions]])
            np.testing.assert_allclose(probability, [[r["proba_left"], r["proba_right"]] for r in predictions], atol=1e-7)
            predicted = np.asarray([case[3]["class_labels"]["left"], case[3]["class_labels"]["right"]])[probability.argmax(axis=1)]
            assert list(predicted) == [r["prediction"] for r in predictions]
    assert result["selection_score"] == pytest.approx(np.mean(seed_scores))
    assert result["seed_summary"]["seed_sd"] == pytest.approx(np.std(seed_scores))
    assert result["seed_summary"] == learner["seed_summary"]
    for subject, metric in learner["subjects"].items():
        for key in utility.METRICS:
            assert metric[key] == pytest.approx(np.mean([v["subjects"][subject][key] for v in learner["seeds"].values()]))
        assert metric["n_trials"] == result["subjects"][subject]["eligible_trials"]
    csp = result["learners"]["csp_lda"]
    assert csp["seeds"] == {} and csp["seed_summary"] is None
    assert csp["summary"]["auc"] is None
    for fold in csp["folds"]:
        assert file_hash(Path(fold["model"]["path"])) == fold["model"]["sha256"]
        model, rows = joblib.load(fold["model"]["path"]), read(fold["predictions"])
        with evaluation._mapped(manifest["arrays"]["representation"]["path"]) as X:
            replay = model["classifier"].predict(csp_features(np.array([covariance(X[r["array_index"]]) for r in rows]), model["filters"]))
        assert list(replay) == [r["prediction"] for r in rows]


def test_failed_seed_never_averages_remaining_seeds(case, tmp_path, monkeypatch):
    original = eegnet.train_fold
    def train(*args, **kwargs):
        if kwargs["seed"] == 42:
            raise RuntimeError("intentional seed failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(eegnet, "train_fold", train)
    receipt = run(case, tmp_path / "failed-seed")
    assert receipt["status"] == "incomplete" and receipt["selection_score"] is None
    learner = receipt["learners"]["eegnet"]
    assert learner["seeds"]["17"]["status"] == "evaluated"
    assert learner["seeds"]["42"]["status"] == "failed"
    assert learner["predictions"] is None and learner["summary"] == {}
    assert receipt["seed_summary"] is None and receipt["learner_scores"]["eegnet"] is None
    assert receipt["learner_scores"]["csp_lda"] is not None
    assert "intentional seed failure" in " ".join(receipt["failure_reasons"])
    assert all(s["mean_ba"] is None for s in receipt["subjects"].values())


def test_benchmark_failure_does_not_change_primary_utility(case, tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("intentional benchmark failure")
    monkeypatch.setattr(utility, "_fit_core", fail)
    receipt = run(case, tmp_path / "failed-benchmark")
    assert receipt["status"] == "evaluated" and receipt["failure_reasons"] == []
    assert receipt["learner_scores"]["csp_lda"] is None
    assert receipt["selection_score"] == receipt["learner_scores"]["eegnet"]


def test_fit_receives_only_outer_training_signal_and_labels(case, tmp_path, monkeypatch):
    calls = []
    original = eegnet.train_fold
    def train(X, y, subjects, **kwargs):
        calls.append((X.copy(), y.copy(), subjects.copy(), kwargs["seed"]))
        return original(X, y, subjects, **kwargs)
    monkeypatch.setattr(eegnet, "train_fold", train)
    receipt = run(case, tmp_path / "routing")
    assert receipt["status"] == "evaluated", receipt["failure_reasons"]
    manifest = read(receipt["inputs"])
    for row in manifest["trials"]:
        record = case[5]["representation"]["records"][row["record_id"]]
        with evaluation._mapped(record["array_path"]) as source, evaluation._mapped(manifest["arrays"]["representation"]["path"]) as assembled:
            np.testing.assert_array_equal(assembled[row["array_index"]], source[row["epoch_index"]])
    assert len(calls) == 9
    for X, y, groups, seed in calls:
        fold = next(f for f in case[3]["folds"] if set(f["train_subjects"]) == set(groups))
        assert not set(groups) & set(fold["development_subjects"])
        selected = [r for r in manifest["trials"] if r["subject"] in set(groups)]
        assert y.tolist() == [int(r["label"] == case[3]["class_labels"]["right"]) for r in selected]
        with evaluation._mapped(manifest["arrays"]["representation"]["path"]) as array:
            np.testing.assert_array_equal(X, array[[r["array_index"] for r in selected]])
        assert seed in [17, 42, 2026]


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
    assert any("zero" in s or "nonfinite" in s or "checksum" in s for s in receipt["failure_reasons"])


def test_invalid_probability_has_no_uniform_fallback(case, tmp_path, monkeypatch):
    monkeypatch.setattr(eegnet, "predict_checkpoint", lambda path, X: np.zeros((len(X), 2)))
    receipt = run(case, tmp_path / "invalid-probability")
    assert receipt["selection_score"] is None
    assert receipt["learners"]["eegnet"]["status"] == "failed"


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
    for change in ("seed_fold_id", "seed_fold_order", "missing_seed", "physical_input", "csp_seeds"):
        bad = deepcopy(good)
        eegnet = bad["learners"]["eegnet"]
        if change == "seed_fold_id":
            eegnet["seeds"]["42"]["folds"][0]["fold_id"] = "different-fold"
        elif change == "seed_fold_order":
            eegnet["seeds"]["42"]["folds"].reverse()
        elif change == "missing_seed":
            del eegnet["seeds"]["2026"]
        elif change == "physical_input":
            eegnet["input_representation"] = "pre_adaptation_phys_V"
        else:
            bad["learners"]["csp_lda"]["seeds"] = deepcopy(eegnet["seeds"])
        with pytest.raises(ValidationError):
            UtilityReceipt.model_validate(bad)


def test_public_protocol_freezes_training_and_seeds(case, tmp_path):
    frozen = utility.utility_protocol(execution=EXECUTION)
    assert frozen["utility_version"] == 2 and frozen["seeds"] == [17, 42, 2026]
    assert frozen["primary_suite"] == ["eegnet"] and frozen["learner_suite"] == ["eegnet", "csp_lda"]
    assert frozen["eegnet"]["training"]["max_epochs"] == 2
    assert "eegnet.py" in frozen["implementation_sha256"]
    receipt = run(case, tmp_path / "protocol")
    assert receipt["protocol"]["sha256"] == digest(frozen)
    frozen["eegnet"]["training"]["max_epochs"] = 999
    assert utility.utility_protocol(execution=EXECUTION)["eegnet"]["training"]["max_epochs"] == 2


def test_explicit_holdout_scores_only_development(case, tmp_path):
    plan, result, root, _, entry, _ = case
    panel = freeze_panel(plan.input_snapshot, {r.record_id: r.record_id for r in plan.records}, seed=42,
                         tmin=-.1, tmax=.4, sfreq=160, train_subjects=["sub-01", "sub-02"], development_subjects=["sub-03"])
    core = evaluation.evaluate(result, plan, root, panel, tmp_path / "holdout-core")
    receipt = run((plan, result, root, panel, entry, core), tmp_path / "holdout-utility")
    assert receipt["status"] == "evaluated", receipt["failure_reasons"]
    assert receipt["evaluation_mode"] == "subject_holdout" and set(receipt["subjects"]) == {"sub-03"}
    eegnet = receipt["learners"]["eegnet"]
    for output in eegnet["seeds"].values():
        rows = read(output["predictions"])
        assert len(rows) == 14 and {r["subject"] for r in rows} == {"sub-03"}
        assert output["folds"][0]["train_subjects"] == ["sub-01", "sub-02"]


def test_full109_pipeline_fit_budget_is_fixed():
    subjects = [f"sub-{s:03}" for s in range(109)]
    panel = {"trials": [{"subject": s, "eligible": True} for s in subjects for _ in range(45)],
             "folds": [{"train_subjects": [s for j, s in enumerate(subjects) if j % 5 != k],
                        "development_subjects": subjects[k::5]} for k in range(5)]}
    budget = utility.utility_fit_budget(panel)
    assert budget["pipeline_fits"] == {"eegnet": 15, "csp_lda": 5}
    assert budget["total_utility_pipeline_fits"] == 20 and budget["prior_core_evaluation_fits"] == 5
