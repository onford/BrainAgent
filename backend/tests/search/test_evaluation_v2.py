"""Real numerical checks for subject OOF, adaptation, and label isolation."""

import csv
from copy import deepcopy
import json
from pathlib import Path

import mne
import numpy as np
import pytest
from pydantic import ValidationError
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from app.preprocessing.storage import digest, file_hash, write_json
from app.search import evaluation
from app.search.evaluation_contracts import (
    EvaluationReceipt,
    CoreLearnerMetadata,
)
from app.search.evaluation_numeric import (
    covariance,
    paired_ci,
    regularized,
    fit_csp,
)
from app.search.panel import freeze_panel
from tests.search.test_evaluation import make_case, rehash


def cv_case(tmp_path, *, tmax=0.1):
    result, plan, root, _ = make_case(tmp_path, tmax=tmax)
    panel = freeze_panel(
        plan.input_snapshot,
        {r.id: r.id for r in plan.input_snapshot.collection.records},
        seed=42,
        tmin=-0.1,
        tmax=tmax,
        sfreq=160,
    )
    rng = np.random.default_rng(872)
    for rid in panel["records"]:
        path = root / rid / "signal_V.npy"
        values = np.load(path)
        trials = [t for t in panel["trials"] if t["record_id"] == rid and t["eligible"]]
        for i, trial in enumerate(trials):
            scales = [1, 5] if trial["label"] == "left_hand" else [5, 1]
            values[i] = (
                rng.normal(size=values[i].shape) * np.asarray(scales)[:, None] * 1e-6
            )
        np.save(path, values)
        rehash(result, root, rid, "signal_V.npy")
    return result, plan, root, panel


def test_real_csp_lda_oof_has_complete_coverage_without_secondary_fit(
    tmp_path, monkeypatch
):
    result, plan, root, panel = cv_case(tmp_path)
    fits, lda_fits = [], []

    def forbidden(*args, **kwargs):
        pytest.fail("core must never fit a secondary learner or standardizer")

    monkeypatch.setattr(LogisticRegression, "fit", forbidden)
    monkeypatch.setattr(StandardScaler, "fit", forbidden)
    original_csp = evaluation.fit_csp

    def csp(covs, indices, train_labels):
        assert isinstance(covs, np.memmap)
        fits.append((indices.copy(), train_labels.copy()))
        return original_csp(covs, indices, train_labels)

    monkeypatch.setattr(evaluation, "fit_csp", csp)
    for cls, records in [
        (evaluation.LinearDiscriminantAnalysis, lda_fits),
    ]:
        original = cls.fit

        def fit(self, X, y=None, *args, _original=original, _records=records, **kwargs):
            _records.append((X.copy(), None if y is None else y.copy()))
            return _original(self, X, y, *args, **kwargs)

        monkeypatch.setattr(cls, "fit", fit)
    receipt = evaluation.evaluate(result, plan, root, panel, tmp_path / "evaluation")
    assert receipt["status"] == "evaluated", receipt
    assert receipt["macro_ba"] >= 0.95
    assert panel["evaluator_version"] == 2
    assert receipt["evaluator_version"] == 4
    assert receipt["secondary_learner"] is receipt["secondary_macro_ba"] is None
    assert receipt["secondary_subjects"] == {}
    assert len(fits) == len(lda_fits) == len(panel["folds"])
    assert receipt["coverage"]["eligible"] == receipt["coverage"]["predicted"] == 24
    assert receipt["coverage"]["train"]["original"] == 0
    trials = [t for t in panel["trials"] if t["eligible"]]
    for k, (fold, (indices, labels)) in enumerate(zip(panel["folds"], fits)):
        assert {trials[i]["subject"] for i in indices} == set(fold["train_subjects"])
        assert labels.tolist() == [trials[i]["label"] for i in indices]
        assert lda_fits[k][0].shape == (len(indices), 2)  # CSP4 capped to two channels.
        assert lda_fits[k][1].tolist() == labels.tolist()
    with Path(receipt["predictions_path"]).open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    predicted = [r for r in rows if r["prediction"]]
    assert len(predicted) == len({r["event_id"] for r in predicted}) == 24
    for row in predicted:
        fold = next(f for f in panel["folds"] if f["id"] == row["fold_id"])
        assert row["subject"] in fold["development_subjects"]
        assert row["primary_prediction"] == row["prediction"]
        assert row["secondary_prediction"] == ""
    assert not (tmp_path / "evaluation" / "epoch-covariances.npy").exists()






def test_development_label_permutation_cannot_change_signal_or_learner_fit(
    tmp_path, monkeypatch
):
    result, plan, root, panel = make_case(tmp_path)
    fits = []
    original = evaluation.LinearDiscriminantAnalysis.fit

    def fit(self, X, y, **kwargs):
        value = original(self, X, y, **kwargs)
        fits.append((X.copy(), y.copy(), self.coef_.copy(), self.intercept_.copy()))
        return value

    monkeypatch.setattr(evaluation.LinearDiscriminantAnalysis, "fit", fit)
    policy = {}
    first = evaluation.evaluate(
        result, plan, root, panel, tmp_path / "first", policy=policy
    )
    assert first["status"] == "evaluated", first
    swap = {"left_hand": "right_hand", "right_hand": "left_hand"}
    for subject in panel["development_subjects"]:
        for trial in panel["trials"]:
            if trial["subject"] == subject:
                trial["label"] = swap[trial["label"]]
        events_path = root / subject / "events.json"
        rows = json.loads(events_path.read_text())
        for row in rows:
            row["label"] = swap[row["label"]]
            row["code"] = 3 - row["code"]
        write_json(events_path, rows)
        rehash(result, root, subject, "events.json")
        fif = root / subject / "data-epo.fif"
        epochs = mne.read_epochs(fif, preload=True, verbose="ERROR")
        epochs.events[:, 2] = 3 - epochs.events[:, 2]
        epochs.save(fif, overwrite=True, fmt="double", verbose="ERROR")
        rehash(result, root, subject, "data-epo.fif")
    panel["panel_hash"] = digest({k: v for k, v in panel.items() if k != "panel_hash"})
    second = evaluation.evaluate(
        result, plan, root, panel, tmp_path / "second", policy=policy
    )
    assert second["status"] == "evaluated", second
    for before, after in zip(fits[0], fits[1]):
        np.testing.assert_array_equal(before, after)
    assert first["diagnostics"]["subjects"] == second["diagnostics"]["subjects"]
    for rid, before in first["representation"]["records"].items():
        assert (
            before["array_sha256"]
            == second["representation"]["records"][rid]["array_sha256"]
        )




def test_paired_bootstrap_is_subject_level_deterministic_and_descriptive(tmp_path):
    result, plan, root, panel = cv_case(tmp_path)
    baseline = evaluation.evaluate(result, plan, root, panel, tmp_path / "baseline")
    receipt = evaluation.evaluate(
        result, plan, root, panel, tmp_path / "paired", baseline
    )
    assert receipt["status"] == "evaluated", receipt
    ci = receipt["paired_subject_ci"]
    assert ci["low"] == ci["high"] == 0
    assert ci["n_subjects"] == 3
    assert ci["interpretation"] == "descriptive_development_only_not_independent_test"
    assert paired_ci([-0.1, 0.2, 0.4], 5) == paired_ci([-0.1, 0.2, 0.4], 5)


@pytest.mark.parametrize(
    "policy",
    [
        {"adaptation": "bad"},
        {"alignment_threshold": 0},
        {"alignment_threshold": float("nan")},
        [],
    ],
)
def test_invalid_policy_stops_before_signal_read(tmp_path, monkeypatch, policy):
    result, plan, root, panel = cv_case(tmp_path)
    monkeypatch.setattr(
        evaluation, "_mapped", lambda *a: pytest.fail("invalid policy read signal")
    )
    receipt = evaluation.evaluate(
        result, plan, root, panel, tmp_path / "out", policy=policy
    )
    assert receipt["status"] == "candidate_invalid"


def test_v1_baseline_cannot_execute_or_fall_back(tmp_path, monkeypatch):
    result, plan, root, panel = cv_case(tmp_path)
    baseline = evaluation.evaluate(result, plan, root, panel, tmp_path / "baseline")
    baseline["evaluator_version"] = 1
    monkeypatch.setattr(
        evaluation, "_mapped", lambda *a: pytest.fail("v1 baseline read signal")
    )
    receipt = evaluation.evaluate(result, plan, root, panel, tmp_path / "out", baseline)
    assert receipt["status"] == "data_unevaluable"
    assert receipt["error_code"] == "baseline_invalid"








def test_signed_rank_deficient_csp_is_finite_and_held_out_covariance_is_not_fitted():
    rng = np.random.default_rng(98)
    projection = np.eye(64) - np.ones((64, 64)) / 64
    epochs = np.array([projection @ rng.normal(size=(64, 90)) * 1e-6 for _ in range(5)])
    covariances = np.array([covariance(e) for e in epochs])
    assert np.any(covariances < 0)  # Preserve signed cross-channel covariance.
    labels = np.array(["left", "right", "left", "right"])
    first = fit_csp(covariances, np.arange(4), labels)
    covariances[4] = np.eye(64) * 1e6
    second = fit_csp(covariances, np.arange(4), labels)
    assert first.shape == (4, 64) and np.isfinite(first).all()
    np.testing.assert_array_equal(first, second)
