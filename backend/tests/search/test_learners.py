"""Reference parity, subject isolation and numerical checks for MI learners."""

import json
import pickle
import warnings

import numpy as np
import pytest
from scipy.signal import butter, sosfiltfilt
from sklearn.covariance import oas
from sklearn.exceptions import ConvergenceWarning, NotFittedError
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from app.search import learners
from app.search.learners import LearnerNotApplicable, LearnerUnavailable, TraditionalLearner


@pytest.fixture
def reference():
    package = pytest.importorskip("pyriemann", reason="Advanced learners require optional pyriemann==0.7")
    if package.__version__ != "0.7":
        pytest.skip("This reference recipe is pinned to pyriemann==0.7")
    return learners._reference_classes()


@pytest.fixture
def trials():
    rng = np.random.default_rng(407)
    subjects = np.repeat(np.arange(6), 12)
    y = np.tile(np.repeat([0, 1], 6), 6)
    X = rng.normal(size=(len(y), 4, 320)) * 0.3
    t = np.arange(320) / 160
    for i, label in enumerate(y):
        phase = rng.uniform(0, 2 * np.pi)
        X[i, label] += (1.4 + rng.uniform(0, 0.2)) * np.sin(2 * np.pi * 10 * t + phase)
        X[i, 2 + label] += 0.7 * np.sin(2 * np.pi * 18 * t + phase)
    return X, y, subjects


def learner(method="ts_lr", **kwargs):
    return TraditionalLearner(method, sfreq=160, available_band=(8, 24), **kwargs)


def test_band_support_and_ea_declaration():
    model = TraditionalLearner("ea_fbcsp", sfreq=160, available_band=(8, 30),
                               upstream_adaptation="none")
    info = model.applicability()
    assert info["applicable"]
    assert info["derived_bands_hz"] == [[8, 12], [12, 16], [16, 20], [20, 24], [24, 28]]
    assert info["per_band_ea_refit"]
    broad = learner("broadband_ea_fbcsp", upstream_adaptation="euclidean_alignment").applicability()
    assert broad["applicable"] and not broad["per_band_ea_refit"]
    assert not learner("ea_fbcsp", upstream_adaptation="euclidean_alignment").applicability()["applicable"]
    assert not learner("ea_fbcsp").applicability()["applicable"]
    assert not TraditionalLearner("fbcsp", sfreq=160, available_band=(9, 13)).applicability()["applicable"]
    with pytest.raises(ValueError, match="inside available_band"):
        learner("fbcsp", bands=[(4, 8), (8, 12)])
    with pytest.raises(ValueError, match="distinct"):
        learner("fbcsp", bands=[(8, 12), (8, 12)])


def test_missing_or_wrong_reference_never_substitutes(monkeypatch, trials):
    real_import = learners.import_module

    def missing(name):
        if name == "pyriemann":
            raise ModuleNotFoundError("deliberately absent")
        return real_import(name)

    monkeypatch.setattr(learners, "import_module", missing)
    model = learner()
    with pytest.raises(LearnerUnavailable, match="no fallback"):
        model.fit(*trials)
    with pytest.raises(NotFittedError):
        model.predict(trials[0])
    monkeypatch.setattr(learners, "import_module", lambda name: type("Package", (), {"__version__": "99"})())
    with pytest.raises(LearnerUnavailable, match="audited"):
        learners._reference_classes()


@pytest.mark.parametrize("method", ["fbcsp", "ea_fbcsp", "broadband_ea_fbcsp", "ts_lr", "fgmdm"])
def test_probability_auc_determinism_and_input_integrity(reference, trials, method):
    X, y, subjects = trials
    original = X.copy()
    fit = subjects < 4
    options = {"upstream_adaptation": "euclidean_alignment"} if method == "broadband_ea_fbcsp" else {}
    if method == "ea_fbcsp":
        options = {"upstream_adaptation": "none"}
    prediction_options = {"subjects": subjects[~fit]} if method == "ea_fbcsp" else {}
    first = learner(method, **options).fit(X[fit], y[fit], subjects[fit])
    second = learner(method, **options).fit(X[fit], y[fit], subjects[fit])
    p = first.predict_proba(X[~fit], **prediction_options)
    scores = first.decision_score(X[~fit], **prediction_options)
    assert np.isfinite(p).all() and np.isfinite(scores).all()
    assert (p >= 0).all() and (p <= 1).all()
    np.testing.assert_allclose(p.sum(axis=1), 1, atol=1e-12)
    np.testing.assert_allclose(p, second.predict_proba(X[~fit], **prediction_options), atol=1e-12)
    np.testing.assert_array_equal(first.predict(X[~fit], **prediction_options), first.classes_[p.argmax(axis=1)])
    assert roc_auc_score(y[~fit], scores) > 0.9  # Recover a planted, held-out spatial signal.
    np.testing.assert_array_equal(X, original)
    audit = first.describe()
    assert json.loads(json.dumps(audit))["fit_subject_roles"]["outer_training"] == [0, 1, 2, 3]
    assert audit["fit_subject_roles"]["target_labels_received"] is False
    assert not audit["inner_cv"]["enabled"]
    audit["params"]["not_real"] = 7
    assert "not_real" not in first.describe()["params"]


@pytest.mark.parametrize("method", ["fbcsp", "ts_lr", "fgmdm"])
def test_prediction_is_batch_invariant_and_freezes_fitted_state(reference, trials, method):
    X, y, subjects = trials
    fit = subjects < 4
    model = learner(method).fit(X[fit], y[fit], subjects[fit])
    before = pickle.dumps(model.model_)
    one = model.predict_proba(X[~fit][:1])
    batch = np.concatenate([X[~fit][:1], X[~fit][1:] * 100], axis=0)
    np.testing.assert_allclose(one, model.predict_proba(batch)[:1], atol=1e-10)
    assert pickle.dumps(model.model_) == before
    assert model.describe()["fit_subject_roles"]["target_statistics_fitted_by_learner"] is False


@pytest.mark.parametrize("method", ["fbcsp", "ea_fbcsp", "ts_lr"])
def test_all_inner_learned_stages_are_refit_on_exact_training_subjects(reference, trials, monkeypatch, method):
    X, y, subjects = trials
    # Targets 4/5 never enter fit, not even covariance preprocessing.
    X, y, subjects = X[subjects < 4], y[subjects < 4], subjects[subjects < 4]
    model = learner(method, tune=True, inner_splits=2, param_grid={"C": [0.1, 1]},
                    upstream_adaptation="none")
    covs = model._covariances(X, subjects)
    splits = list(GroupKFold(n_splits=2).split(X, y, subjects))
    expected = [train for _ in range(2) for train, _ in splits] + [np.arange(len(X))]
    feature_calls, scale_calls, selection_calls, classifier_calls = [], [], [], []
    if method in learners.FBCSP_METHODS:
        cls, operation = learners._FilterBankCSP, "fit"
    else:
        cls, operation = reference[1], "fit_transform"
    original = getattr(cls, operation)

    def feature_spy(self, values, labels=None, **kwargs):
        indices = expected[len(feature_calls)]
        np.testing.assert_array_equal(values, covs[indices])
        np.testing.assert_array_equal(labels, y[indices])
        feature_calls.append(indices)
        return original(self, values, labels, **kwargs)

    monkeypatch.setattr(cls, operation, feature_spy)
    original_scale = learners.StandardScaler.fit
    original_selection = learners.SelectKBest.fit
    original_classifier = learners.LogisticRegression.fit

    def scale_spy(self, values, labels=None, **kwargs):
        indices = expected[len(scale_calls)]
        assert len(values) == len(indices)
        np.testing.assert_array_equal(labels, y[indices])
        scale_calls.append(indices)
        result = original_scale(self, values, labels, **kwargs)
        np.testing.assert_allclose(self.mean_, np.mean(values, axis=0))
        return result

    def selection_spy(self, values, labels):
        indices = expected[len(selection_calls)]
        assert len(values) == len(indices)
        np.testing.assert_array_equal(labels, y[indices])
        selection_calls.append(indices)
        return original_selection(self, values, labels)

    def classifier_spy(self, values, labels, **kwargs):
        indices = expected[len(classifier_calls)]
        assert len(values) == len(indices)
        np.testing.assert_array_equal(labels, y[indices])
        classifier_calls.append(indices)
        return original_classifier(self, values, labels, **kwargs)

    monkeypatch.setattr(learners.StandardScaler, "fit", scale_spy)
    monkeypatch.setattr(learners.SelectKBest, "fit", selection_spy)
    monkeypatch.setattr(learners.LogisticRegression, "fit", classifier_spy)
    model.fit(X, y, subjects)
    assert len(feature_calls) == len(scale_calls) == len(classifier_calls) == 5
    assert len(selection_calls) == (5 if method in learners.FBCSP_METHODS else 0)
    audit = model.describe()["inner_cv"]
    assert len(audit["candidates"]) == 2
    for role in audit["roles"]:
        assert set(role["fit_subjects"]).isdisjoint(role["validation_subjects"])
        assert set(role["fit_subjects"] + role["validation_subjects"]) == {0, 1, 2, 3}


def test_oas_and_filtering_match_reference_without_cross_trial_statistics(trials):
    X, _, _ = trials
    model = learner("fbcsp")
    covs = model._covariances(X[:2])
    for band, limits in enumerate(model._derived_bands()):
        filtered = sosfiltfilt(butter(4, limits, btype="bandpass", fs=160, output="sos"), X[0], axis=-1)
        expected, _ = oas(filtered.T, assume_centered=False)
        expected += np.eye(4) * (learners.SPD_RIDGE * np.trace(expected) / 4)
        np.testing.assert_allclose(covs[0, band], expected, atol=1e-13)
    np.testing.assert_allclose(model._covariances(X[:1])[0], covs[0], atol=1e-13)


def test_tangent_reference_and_fgmdm_match_official_library(reference, trials):
    X, y, subjects = trials
    _, TangentSpace, FgMDM = reference
    ts = learner().fit(X, y, subjects)
    covs = ts._covariances(X)
    official_ts = TangentSpace(metric="riemann", tsupdate=False).fit(covs)
    np.testing.assert_allclose(ts.model_.named_steps["features"].reference_, official_ts.reference_)
    fg = learner("fgmdm").fit(X, y, subjects)
    official_fg = FgMDM(metric="riemann", tsupdate=False, n_jobs=1).fit(covs, y)
    np.testing.assert_allclose(fg.predict_proba(X[:4]), official_fg.predict_proba(covs[:4]))
    distances = official_fg.transform(covs[:4])
    np.testing.assert_allclose(fg.decision_score(X[:4]), distances[:, 0] ** 2 - distances[:, 1] ** 2)


@pytest.mark.parametrize("method", ["fbcsp", "ts_lr", "fgmdm"])
def test_rank_deficient_covariance_is_spd_and_voltage_scale_does_not_change_predictions(reference, trials, method):
    X, y, subjects = trials
    X = X.copy()
    X[:, 3] = X[:, 2]  # Deliberate exact channel rank deficiency.
    model = learner(method)
    covs = model._covariances(X)
    assert np.linalg.eigvalsh(covs).min() > 0
    first = model.fit(X, y, subjects).predict_proba(X[:3])
    second = learner(method).fit(X * 1e-6, y, subjects).predict_proba(X[:3] * 1e-6)
    np.testing.assert_allclose(first, second, atol=1e-6)


def test_invalid_refit_erases_previous_success(reference, trials):
    X, y, subjects = trials
    model = learner().fit(X, y, subjects)
    with pytest.raises(ValueError, match="zero covariance"):
        model.fit(np.zeros_like(X), y, subjects)
    with pytest.raises(NotFittedError):
        model.predict(X)
    with pytest.raises(NotFittedError):
        model.describe()


def test_invalid_geometry_data_and_subject_cv_are_explicit(reference, trials):
    X, y, subjects = trials
    bad = X.copy()
    bad[0, 0, 0] = np.nan
    with pytest.raises(ValueError, match="Nonfinite"):
        learner().fit(bad, y, subjects)
    with pytest.raises(MemoryError, match="budget"):
        learner(max_working_bytes=1).fit(X, y, subjects)
    with pytest.raises(LearnerNotApplicable, match="Insufficient subjects"):
        learner(tune=True).fit(X, y, np.zeros(len(y)))
    with pytest.raises(LearnerNotApplicable, match="both (labels|classes)"):
        learner(tune=True, inner_splits=2).fit(X, y, subjects * 2 + y)
    model = learner().fit(X, y, subjects)
    with pytest.raises(ValueError, match="geometry"):
        model.predict(X[:, :, :-1])
    with pytest.raises(ValueError, match="padlen"):
        learner("fbcsp").fit(X[:, :, :8], y, subjects)


def test_bounded_grid_and_no_unrequested_tuning(reference, trials):
    with pytest.raises(ValueError, match="requires tune"):
        learner(param_grid={"C": [1, 2]})
    with pytest.raises(ValueError, match="blas_threads"):
        learner(blas_threads=21)
    with pytest.raises(LearnerNotApplicable, match="24"):
        learner(tune=True, param_grid={"C": list(range(1, 26))}).fit(*trials)
    with pytest.raises(LearnerNotApplicable, match="fixed recipe"):
        learner("fgmdm", tune=True).fit(*trials)


def test_string_labels_have_explicit_positive_auc_class(reference, trials):
    X, y, subjects = trials
    labels = np.where(y, "right_hand", "left_hand")
    model = learner().fit(X, labels, subjects)
    assert model.describe()["positive_class"] == "right_hand"
    assert roc_auc_score(y, model.decision_function(X)) > 0.9


def test_nonconvergence_fails_without_retaining_a_model(reference, trials, monkeypatch):
    def fail(self, *args, **kwargs):
        warnings.warn("Deliberate optimizer failure", ConvergenceWarning)

    monkeypatch.setattr(learners.LogisticRegression, "fit", fail)
    model = learner()
    with pytest.raises(ConvergenceWarning, match="optimizer"):
        model.fit(*trials)
    with pytest.raises(NotFittedError):
        model.describe()


def test_inference_rejects_changed_signal_contract(reference, trials):
    model = learner().fit(*trials)
    model.sfreq = 128
    with pytest.raises(ValueError, match="settings changed"):
        model.predict(trials[0])


def test_byte_subject_ids_are_json_serializable(reference, trials):
    X, y, subjects = trials
    model = learner().fit(X, y, subjects.astype("S"))
    assert json.loads(json.dumps(model.describe()))["fit_subject_roles"]["outer_training"] == list("012345")


def test_numpy_parameter_scalars_are_auditable(reference, trials):
    model = learner("fbcsp", params={"C": np.float64(1), "n_components": np.int64(4)}).fit(*trials)
    assert json.loads(json.dumps(model.describe()))["requested_params"]["n_components"] == 4


def test_per_band_ea_is_actual_signal_whitening_before_oas(reference, trials):
    X, _, subjects = trials
    model = learner("ea_fbcsp", upstream_adaptation="none", ea_ridge=0)
    actual, audit = model._covariances(X, subjects, return_audit=True)
    inverse_root = learners.import_module("pyriemann.utils.base").invsqrtm
    pre_oas_congruence_differences = []
    for band, limits in enumerate(model._derived_bands()):
        filtered = sosfiltfilt(butter(4, limits, btype="bandpass", fs=160, output="sos"), X, axis=-1)
        centered = filtered - filtered.mean(axis=-1, keepdims=True)
        for subject in np.unique(subjects):
            indices = np.flatnonzero(subjects == subject)
            scm = centered[indices] @ centered[indices].transpose(0, 2, 1) / X.shape[-1]
            mean = scm.mean(axis=0)
            whitener = inverse_root(mean)
            aligned = whitener @ centered[indices]
            aligned_mean = (aligned @ aligned.transpose(0, 2, 1) / X.shape[-1]).mean(axis=0)
            np.testing.assert_allclose(aligned_mean, np.eye(4), atol=1e-11)
            for index, values in zip(indices, aligned):
                expected, _ = oas(values.T, assume_centered=False)
                expected += np.eye(4) * (learners.SPD_RIDGE * np.trace(expected) / 4)
                np.testing.assert_allclose(actual[index, band], expected, atol=1e-11)
            before, _ = oas(centered[indices[0]].T)
            pre_oas_congruence_differences.append(np.linalg.norm(actual[indices[0], band] - whitener @ before @ whitener.T))
    assert max(pre_oas_congruence_differences) > 1e-3
    assert len(audit["subject_bands"]) == len(np.unique(subjects)) * len(model._derived_bands())
    assert max(e["empirical_identity_residual_fro"] for e in audit["subject_bands"]) < 1e-10
    assert audit["labels_received"] is False


def test_target_ea_is_subject_local_label_free_and_does_not_update_training(reference, trials):
    X, y, subjects = trials
    fit = subjects < 4
    model = learner("ea_fbcsp", upstream_adaptation="none").fit(X[fit], y[fit], subjects[fit])
    before = pickle.dumps(model)
    target, groups = X[~fit], subjects[~fit]
    probability, audit = model.predict_proba(target, groups, return_audit=True)
    assert audit["subject_ids"] == [4, 5]
    assert audit["overlap_with_training_subjects"] == []
    assert audit["target_labels_received"] is False and not audit["supervised_model_updated"]
    assert {e["subject"] for e in audit["adaptation"]["subject_bands"]} == {4, 5}
    one_subject = groups == 4
    np.testing.assert_allclose(probability[one_subject], model.predict_proba(target[one_subject], groups[one_subject]), atol=1e-12)
    changed = target.copy()
    changed[groups == 5, 0] *= 30
    changed_probability, changed_audit = model.predict_proba(changed, groups, return_audit=True)
    np.testing.assert_allclose(probability[one_subject], changed_probability[one_subject], atol=1e-12)
    first_audit = [e for e in audit["adaptation"]["subject_bands"] if e["subject"] == 4]
    assert first_audit == [e for e in changed_audit["adaptation"]["subject_bands"] if e["subject"] == 4]
    assert audit["adaptation"] != changed_audit["adaptation"]
    assert pickle.dumps(model) == before
    with pytest.raises(TypeError):
        model.predict(target, subjects=groups, labels=y[~fit])
    with pytest.raises(ValueError, match="requires subjects"):
        model.predict(target)
    with pytest.raises(LearnerNotApplicable, match="at least two"):
        model.predict(target[:1], groups[:1])


def test_subject_batch_ea_depends_on_same_subject_unlabelled_peers(reference, trials):
    X, y, subjects = trials
    fit = subjects < 4
    model = learner("ea_fbcsp", upstream_adaptation="none").fit(X[fit], y[fit], subjects[fit])
    target, groups = X[subjects == 4], subjects[subjects == 4]
    original, first = model._covariances(target, groups, return_audit=True)
    changed = target.copy()
    changed[1:, 0] *= 10  # First trial unchanged, but its allowed batch reference changes.
    updated, second = model._covariances(changed, groups, return_audit=True)
    assert first["subject_bands"][0]["reference_sha256"] != second["subject_bands"][0]["reference_sha256"]
    assert not np.allclose(original[0], updated[0])
    order = np.random.default_rng(99).permutation(len(target))
    np.testing.assert_allclose(model.predict_proba(target, groups)[order],
                               model.predict_proba(target[order], groups[order]), atol=1e-10)


def test_ea_references_ignore_training_labels_and_are_per_band_per_subject(reference, trials):
    X, y, subjects = trials
    first = learner("ea_fbcsp", upstream_adaptation="none").fit(X, y, subjects)
    changed_labels = np.roll(y, 3)
    second = learner("ea_fbcsp", upstream_adaptation="none").fit(X, changed_labels, subjects)
    assert first.describe()["adaptation"] == second.describe()["adaptation"]
    rows = first.describe()["adaptation"]["subject_bands"]
    assert all(row["trials"] == 12 for row in rows)
    assert len({row["reference_sha256"] for row in rows}) == len(rows)
    assert {row["subject"] for row in rows} == set(range(6))


@pytest.mark.parametrize("shrinkage", [0, 0.1])
def test_ea_rank_deficiency_regularization_and_units(reference, trials, shrinkage):
    X, y, subjects = trials
    X = X.copy()
    X[:, 3] = X[:, 2]
    options = {"upstream_adaptation": "none", "ea_shrinkage": shrinkage}
    first = learner("ea_fbcsp", **options).fit(X, y, subjects)
    second = learner("ea_fbcsp", **options).fit(X * 1e-6, y, subjects)
    assert first.describe()["adaptation"]["ea_shrinkage"] == shrinkage
    np.testing.assert_allclose(first.predict_proba(X, subjects),
                               second.predict_proba(X * 1e-6, subjects), atol=2e-5)
    assert all(e["regularized_whitening_residual_fro"] < 1e-3 for e in first.describe()["adaptation"]["subject_bands"])


def test_ea_inner_cache_is_exactly_subject_separable(reference, trials):
    X, y, subjects = trials
    model = learner("ea_fbcsp", upstream_adaptation="none")
    full = model._covariances(X, subjects)
    for train, valid in GroupKFold(n_splits=3).split(X, y, subjects):
        np.testing.assert_array_equal(full[train], model._covariances(X[train], subjects[train]))
        np.testing.assert_array_equal(full[valid], model._covariances(X[valid], subjects[valid]))


def test_ea_zero_reference_fails_and_prediction_audit_is_json(reference, trials):
    X, y, subjects = trials
    model = learner("ea_fbcsp", upstream_adaptation="none").fit(X, y, subjects)
    _, audit = model.predict(X, subjects, return_audit=True)
    decoded = json.loads(json.dumps(audit))
    assert decoded["overlap_with_training_subjects"] == list(range(6))
    assert decoded["implementation_revision"] == "subject-band-ea-v2"
    with pytest.raises(ValueError, match="zero covariance"):
        model.fit(np.zeros_like(X), y, subjects)
    with pytest.raises(NotFittedError):
        model.predict(X, subjects)
