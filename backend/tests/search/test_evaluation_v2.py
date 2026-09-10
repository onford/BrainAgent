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
    GateMetricMetadata,
    CoreLearnerMetadata,
)
from app.search.evaluation_numeric import (
    alignment,
    covariance,
    paired_ci,
    prepare_representation,
    regularized,
    spectral_diagnostics,
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
    assert receipt["evaluator_version"] == 3
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


@pytest.mark.parametrize(
    "adaptation",
    ["none", "subject_scale", "euclidean_alignment", "conditional_alignment"],
)
def test_adaptation_numeric_delivery_hashes_units_and_raw_immutability(
    tmp_path, adaptation
):
    result, plan, root, panel = cv_case(tmp_path)
    raw_hashes = {
        rid: file_hash(root / rid / "signal_V.npy") for rid in panel["records"]
    }
    receipt = evaluation.evaluate(
        result,
        plan,
        root,
        panel,
        tmp_path / "evaluation",
        policy={
            "adaptation": adaptation,
            "alignment_threshold": 10.0,
            "l_freq": 8,
            "reference": "original",
        },
    )
    assert receipt["status"] == "evaluated", receipt
    rep = receipt["representation"]
    unit = "V" if adaptation == "none" else "dimensionless"
    assert rep["unit"] == unit
    assert rep["transductive"] == (adaptation != "none")
    for rid, metadata in rep["records"].items():
        assert metadata["unit"] == unit
        assert file_hash(Path(metadata["array_path"])) == metadata["array_sha256"]
        assert file_hash(root / rid / "signal_V.npy") == raw_hashes[rid]
        original = np.load(root / rid / "signal_V.npy")
        delivered = np.load(metadata["array_path"])
        info = rep["subjects"][metadata["subject"]]
        if adaptation == "none":
            assert info["transform_path"] is None
            assert np.array_equal(original, delivered)
        else:
            transform_path = Path(info["transform_path"])
            assert transform_path.parent == tmp_path / "evaluation" / "adaptation"
            assert file_hash(transform_path) == info["transform_sha256"]
            transform = np.load(transform_path)
            np.testing.assert_allclose(
                delivered, np.einsum("ij,njt->nit", transform, original)
            )
        before = np.mean([covariance(v) for v in original], axis=0)
        after = np.mean([covariance(v) for v in delivered], axis=0)
        diagnostics = receipt["diagnostics"]["subjects"][metadata["subject"]]
        assert diagnostics["mean_channel_variance_before"] == pytest.approx(
            np.trace(before) / 2
        )
        assert diagnostics["mean_channel_variance_after"] == pytest.approx(
            np.trace(after) / 2
        )
        if info["applied_adaptation"] == "scale_only":
            assert np.trace(after) / 2 == pytest.approx(1)
            np.testing.assert_allclose(
                before / np.trace(before), after / np.trace(after)
            )
        elif info["applied_adaptation"] == "euclidean_alignment":
            transform = np.load(info["transform_path"])
            np.testing.assert_allclose(
                transform @ regularized(before) @ transform.T, np.eye(2), atol=1e-12
            )


def test_conditional_mixed_gate_decisions_share_dimensionless_scale(tmp_path):
    # Balanced deterministic waves make one subject isotropic and one anisotropic.
    result, plan, root, panel = cv_case(tmp_path)
    time = np.arange(33) * 2 * np.pi / 33
    for rid in panel["records"]:
        path = root / rid / "signal_V.npy"
        values = np.load(path)
        gain = 8 if rid == "sub-03" else 1
        values[:] = np.array([np.sin(time), gain * np.cos(time)]) * 1e-6
        np.save(path, values)
        rehash(result, root, rid, "signal_V.npy")
    receipt = evaluation.evaluate(
        result,
        plan,
        root,
        panel,
        tmp_path / "evaluation",
        policy={"adaptation": "conditional_alignment", "alignment_threshold": 3.0},
    )
    assert receipt["status"] == "evaluated", receipt
    rep = receipt["representation"]
    assert {s["unit"] for s in rep["subjects"].values()} == {"dimensionless"}
    assert rep["subjects"]["sub-03"]["applied_adaptation"] == "euclidean_alignment"
    assert rep["subjects"]["sub-01"]["applied_adaptation"] == "scale_only"
    assert (
        rep["subjects"]["sub-01"]["fallback_reason"] == "保持空间结构，仅统一无量纲尺度"
    )
    diag = receipt["diagnostics"]["subjects"]
    assert (
        diag["sub-03"]["covariance_condition_after"]
        < diag["sub-03"]["covariance_condition_before"]
    )
    assert diag["sub-01"]["mean_channel_variance_after"] == pytest.approx(1)
    assert rep["gate_fraction"] == pytest.approx(1 / 3)
    assert rep["gate_subject_count"] == 3
    assert rep["gate_passed_subject_count"] == 1
    assert receipt["diagnostics"]["summary"]["gate_fraction"] == pytest.approx(1 / 3)


def test_development_label_permutation_cannot_change_gate_transform_or_learner_fit(
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
    policy = {"adaptation": "conditional_alignment", "alignment_threshold": 2.0}
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
    for subject, before in first["representation"]["subjects"].items():
        after = second["representation"]["subjects"][subject]
        assert before["gate_passed"] == after["gate_passed"]
        assert before["transform_sha256"] == after["transform_sha256"]
    for rid, before in first["representation"]["records"].items():
        assert (
            before["array_sha256"]
            == second["representation"]["records"][rid]["array_sha256"]
        )


def test_subject_batch_alignment_pools_records_and_uses_common_coordinate(tmp_path):
    sources = []
    rng = np.random.default_rng(52)
    pooled = []
    for rid, gain in [("r1", 1), ("r2", 4)]:
        values = rng.normal(size=(3, 2, 50)) * np.array([gain, 2])[:, None] * 1e-6
        path = tmp_path / f"{rid}.npy"
        np.save(path, values)
        sources.append(
            (path, [{"epoch_index": i} for i in range(3)], list(values.shape), rid)
        )
        pooled.extend(covariance(x) for x in values)
    panel = {
        "records": {rid: {"subject": "s1"} for rid in ["r1", "r2"]},
        "output_contract": {"channels": ["C4", "C3"]},
    }
    policy = {"adaptation": "euclidean_alignment", "alignment_threshold": 10.0}
    _, _, rep = prepare_representation(
        sources, panel, tmp_path / "out", policy, evaluation._mapped
    )
    transform = np.load(rep["subjects"]["s1"]["transform_path"])
    expected, _, _ = alignment(np.mean(pooled, axis=0), policy)
    np.testing.assert_allclose(transform, expected)
    assert rep["subjects"]["s1"]["fit_trials"] == 6
    assert rep["channels"] == ["C4", "C3"]


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


@pytest.mark.parametrize("scale", [1e-24, 1e-12, 1.0, 1e12])
@pytest.mark.parametrize("threshold", [3.0, 10.0])
def test_reference_nullspace_and_single_flat_channel_do_not_trigger_gate(
    scale, threshold
):
    n = 64
    reference_projection = np.eye(n) - np.ones((n, n)) / n
    for matrix in (reference_projection, np.diag([0.0] + [1.0] * 63)):
        condition, rank, metric = spectral_diagnostics(matrix * scale)
        assert condition == pytest.approx(1e12)
        assert rank == 63
        assert metric == pytest.approx(1.0)
        transform, passed, value = alignment(
            matrix * scale,
            {"adaptation": "conditional_alignment", "alignment_threshold": threshold},
        )
        assert not passed
        assert value == pytest.approx(metric)
        # Scalar normalization must not change the diagnostic condition or rank,
        # including voltage covariances below the old absolute condition floor.
        after = spectral_diagnostics(transform @ (matrix * scale) @ transform.T)
        assert after == pytest.approx((condition, rank, metric))


@pytest.mark.parametrize("scale", [1e-24, 1e-12, 1.0, 1e12])
@pytest.mark.parametrize("threshold", [3.0, 10.0])
def test_broad_spectral_anisotropy_triggers_predeclared_gate_across_units(
    scale, threshold
):
    eigenvalues = np.array([1.0] * 32 + [100.0] * 32)
    matrix = np.diag(eigenvalues) * scale
    condition, rank, metric = spectral_diagnostics(matrix)
    # Analytic quantiles: both lie inside a constant half-spectrum.
    expected = (0.9 * 100 / 50.5 + 0.1) / (0.9 / 50.5 + 0.1)
    assert metric == pytest.approx(expected)
    assert condition == pytest.approx(100)
    assert rank == 64
    _, passed, value = alignment(
        matrix,
        {"adaptation": "conditional_alignment", "alignment_threshold": threshold},
    )
    assert passed
    assert value == pytest.approx(expected)


def test_zero_covariance_and_relative_rank_have_explicit_finite_semantics():
    assert spectral_diagnostics(np.zeros((64, 64))) == (1.0, 0, 1.0)
    _, passed, value = alignment(
        np.zeros((64, 64)),
        {"adaptation": "conditional_alignment", "alignment_threshold": 3.0},
    )
    assert not passed and value == 1
    assert spectral_diagnostics(np.diag([1.0, 1e-9, 1e-14]))[1] == 1


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


def test_numeric_summary_and_learner_metadata_are_persisted_subject_means(tmp_path):
    result, plan, root, panel = cv_case(tmp_path)
    out = tmp_path / "evaluation"
    receipt = evaluation.evaluate(
        result,
        plan,
        root,
        panel,
        out,
        policy={"adaptation": "conditional_alignment", "alignment_threshold": 3.0},
    )
    assert receipt["status"] == "evaluated", receipt
    assert json.loads((out / "receipt.json").read_text(encoding="utf-8")) == receipt
    diagnostics = receipt["diagnostics"]
    summary = diagnostics["summary"]
    for key, field in {
        "mean_condition_before": "covariance_condition_before",
        "mean_condition_after": "covariance_condition_after",
        "mean_variance_before": "mean_channel_variance_before",
        "mean_variance_after": "mean_channel_variance_after",
        "mean_effective_rank": "effective_rank_before",
    }.items():
        assert summary[key] == pytest.approx(
            np.mean([s[field] for s in diagnostics["subjects"].values()])
        )
    subjects = receipt["representation"]["subjects"]
    assert summary["mean_anisotropy"] == pytest.approx(
        np.mean([s["gate_metric_value"] for s in subjects.values()])
    )
    assert summary["gate_fraction"] == sum(
        s["gate_passed"] for s in subjects.values()
    ) / len(subjects)
    assert receipt["representation"]["gate_metric"] == GateMetricMetadata().model_dump()
    learner = receipt["learner_metadata"]
    assert (
        learner
        == CoreLearnerMetadata(csp_components=2).model_dump()
    )
    assert learner["lda_covariance_estimator"] == "LedoitWolf_within_training_class"
    assert learner["lda_ridge"] == 1e-12
    assert learner["variance_floor"] == 1e-20
    assert learner["csp_regularization"] == 0.1


@pytest.mark.parametrize(
    "mutation",
    [
        "summary",
        "gate_fraction",
        "gate_value",
        "gate_metadata",
        "ridge",
        "rank",
        "components",
    ],
)
def test_numeric_receipt_rejects_inconsistent_or_changed_algorithm_metadata(
    tmp_path, mutation
):
    result, plan, root, panel = cv_case(tmp_path)
    receipt = evaluation.evaluate(
        result,
        plan,
        root,
        panel,
        tmp_path / "out",
        policy={"adaptation": "conditional_alignment", "alignment_threshold": 10.0},
    )
    assert receipt["status"] == "evaluated", receipt
    changed = deepcopy(receipt)
    if mutation == "summary":
        changed["diagnostics"]["summary"]["mean_variance_before"] *= 2
    elif mutation == "gate_fraction":
        changed["representation"]["gate_fraction"] = 0.5
    elif mutation == "gate_value":
        changed["representation"]["subjects"]["sub-01"]["gate_metric_value"] = 100.0
    elif mutation == "gate_metadata":
        changed["representation"]["gate_metric"]["shrinkage"] = 0.2
    elif mutation == "ridge":
        changed["learner_metadata"]["lda_ridge"] = 1e-6
    elif mutation == "components":
        changed["learner_metadata"]["csp_components"] = 4
    else:
        changed["diagnostics"]["subjects"]["sub-01"]["effective_rank_before"] = 3
    with pytest.raises(ValidationError):
        EvaluationReceipt.model_validate(changed)
