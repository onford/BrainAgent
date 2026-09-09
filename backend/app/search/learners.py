"""Fold-local traditional MI learners on (trial, channel, time) arrays.

Inference never accepts labels. ea_fbcsp requires subject IDs and complete
unlabelled subject batches to fit per-subject/per-band EA before OAS and CSP.
broadband_ea_fbcsp explicitly names the older upstream-adapted engineering variant.
pyriemann==0.7 is an optional, deliberately pinned reference implementation.
See .local/research/learner-design.md for recipes and integration obligations.
"""

from copy import deepcopy
from functools import partial
from hashlib import sha256
from importlib import import_module
from itertools import product
import warnings

import numpy as np
from scipy.signal import butter, sosfiltfilt
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.covariance import oas
from sklearn.exceptions import ConvergenceWarning, NotFittedError
from sklearn.feature_selection import SelectKBest, mutual_info_classif
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits


PYRIEMANN_VERSION = "0.7"
FBCSP_METHODS = ("fbcsp", "ea_fbcsp", "broadband_ea_fbcsp")
METHODS = FBCSP_METHODS + ("ts_lr", "fgmdm")
SPD_RIDGE = 1e-10  # Relative to mean channel variance; independent of voltage unit.


class LearnerUnavailable(RuntimeError):
    """An optional reference implementation is missing or unaudited."""


class LearnerNotApplicable(ValueError):
    """The candidate cannot support the requested method or validation protocol."""


class LearnerMemoryLimit(MemoryError):
    """The unchanged numerical recipe exceeds its explicit working-array budget."""


def _reference_classes():
    try:
        package = import_module("pyriemann")
    except ImportError as exc:
        raise LearnerUnavailable("Install optional pyriemann==0.7; no fallback learner is used") from exc
    if package.__version__ != PYRIEMANN_VERSION:
        raise LearnerUnavailable("This recipe requires audited pyriemann==0.7")
    return (
        import_module("pyriemann.spatialfilters").CSP,
        import_module("pyriemann.tangentspace").TangentSpace,
        import_module("pyriemann.classification").FgMDM,
    )


def _positive_int(value, name, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [1, {maximum}]")
    return int(value)


def _ids(values, n, name):
    result = np.asarray(values)
    if result.ndim != 1 or len(result) != n or result.dtype.kind not in "biufUS":
        raise ValueError(f"{name} must be a one-dimensional numeric or string array matching trials")
    if result.dtype.kind in "f" and not np.isfinite(result).all():
        raise ValueError(f"{name} must be finite")
    if result.dtype.kind in "US" and np.any(result == ""):
        raise ValueError(f"{name} must not contain empty IDs")
    if result.dtype.kind == "S":
        result = result.astype(str)
    return result


def _matrix_hash(matrix):
    return sha256(np.asarray(matrix, dtype="<f8", order="C").tobytes()).hexdigest()


def _ea_whitener(reference, shrinkage, ridge):
    """Mean SCM -> optional spherical regularization -> official inverse root.

    No labels enter this function. Return the actual transform and a compact
    fingerprint/geometry audit rather than thousands of matrices in each receipt.
    """
    reference = (reference + reference.T) * 0.5
    scale = float(np.trace(reference) / len(reference))
    if not np.isfinite(reference).all() or not np.isfinite(scale) or scale <= 0:
        raise ValueError("EA subject/band has invalid or zero covariance")
    identity = np.eye(len(reference))
    regularized = (1 - shrinkage) * reference + (shrinkage + ridge) * scale * identity
    np.linalg.cholesky(regularized)
    whitener = import_module("pyriemann.utils.base").invsqrtm(regularized)
    if not np.isfinite(whitener).all():
        raise FloatingPointError("Nonfinite EA inverse square root")
    residual = float(np.linalg.norm(whitener @ regularized @ whitener.T - identity, ord="fro"))
    if residual > 1e-3:
        raise FloatingPointError("EA whitening residual exceeds numerical tolerance")
    eigenvalues = np.linalg.eigvalsh(regularized)
    return whitener, {
        "reference_sha256": _matrix_hash(reference), "whitener_sha256": _matrix_hash(whitener),
        "mean_channel_variance": scale, "regularized_min_eigenvalue": float(eigenvalues[0]),
        "regularized_max_eigenvalue": float(eigenvalues[-1]),
        "regularized_whitening_residual_fro": residual,
        "empirical_identity_residual_fro": float(np.linalg.norm(whitener @ reference @ whitener.T - identity, ord="fro")),
    }


class _FilterBankCSP(TransformerMixin, BaseEstimator):
    """Each input band already contains label-free per-trial OAS covariances."""

    def __init__(self, n_components=4):
        self.n_components = n_components

    def fit(self, X, y):
        CSP, _, _ = _reference_classes()
        self.filters_ = [
            CSP(nfilter=self.n_components, metric="euclid", log=True).fit(X[:, band], y)
            for band in range(X.shape[1])
        ]
        return self

    def transform(self, X):
        return np.concatenate([csp.transform(X[:, band]) for band, csp in enumerate(self.filters_)], axis=1)


class TraditionalLearner:
    """Binary learner with explicit subject-grouped inner selection and audit.

    ``fit(X, y, subjects)`` receives ONLY an outer training partition. ``X`` is
    band-limited; ``available_band`` declares that support. ``ea_fbcsp`` requires
    PRE-adaptation arrays with upstream_adaptation="none". Its inference needs
    complete subject batches and IDs, never target labels. The old upstream EA
    variant is explicitly named ``broadband_ea_fbcsp``.
    The caller must keep upstream *learned* preprocessing fold-local, apart from
    an explicitly declared, label-free target-subject EA permission.

    Tuning is opt-in. It refits all supervised features, reference means and
    scalers inside each GroupKFold split, then refits the winner on outer train.
    EA is independently fitted per complete subject; GroupKFold never splits a
    subject, so label-free subject transforms can be cached across inner splits.
    Inner-validation EA uses only that validation subject's unlabelled batch. Grid
    values are constructor design choices, never inferred from outer test data.
    """

    def __init__(
        self, learner, *, sfreq, available_band, upstream_adaptation="unspecified",
        params=None, tune=False, param_grid=None, inner_splits=3, random_state=0,
        band_width=4.0, bands=None, blas_threads=1, max_working_bytes=8 * 1024**3,
        ea_shrinkage=0.0, ea_ridge=SPD_RIDGE,
    ):
        if learner not in METHODS:
            raise ValueError(f"learner must be one of {METHODS}")
        self.learner = learner
        self.sfreq = float(sfreq)
        self.available_band = tuple(float(v) for v in available_band)
        if (not np.isfinite(self.sfreq) or self.sfreq <= 0 or len(self.available_band) != 2
                or not np.isfinite(self.available_band).all()
                or not 0 < self.available_band[0] < self.available_band[1] < self.sfreq / 2):
            raise ValueError("available_band must lie strictly between zero and Nyquist")
        self.band_width = float(band_width)
        if not np.isfinite(self.band_width) or self.band_width <= 0:
            raise ValueError("band_width must be positive")
        self.bands = None if bands is None else tuple(tuple(float(v) for v in band) for band in bands)
        if self.bands is not None:
            low, high = self.available_band
            if (not self.bands or len(self.bands) > 12
                    or any(len(b) != 2 or not np.isfinite(b).all() or not low <= b[0] < b[1] <= high
                           for b in self.bands)
                    or len(set(self.bands)) != len(self.bands)):
                raise ValueError("Explicit bands must be distinct, at most 12, and inside available_band")
        if learner in {"ts_lr", "fgmdm"} and self.bands is not None:
            raise ValueError("bands apply only to FBCSP")
        if upstream_adaptation not in {"unspecified", "none", "euclidean_alignment", "conditional_alignment", "subject_scale"}:
            raise ValueError("Unknown upstream_adaptation declaration")
        self.upstream_adaptation = upstream_adaptation
        self.per_band_ea = learner == "ea_fbcsp"
        self.ea_shrinkage, self.ea_ridge = float(ea_shrinkage), float(ea_ridge)
        if not np.isfinite(self.ea_shrinkage) or not 0 <= self.ea_shrinkage <= 1:
            raise ValueError("ea_shrinkage must be in [0, 1]")
        if not np.isfinite(self.ea_ridge) or not 0 <= self.ea_ridge <= 1:
            raise ValueError("ea_ridge must be in [0, 1]")
        if not self.per_band_ea and (self.ea_shrinkage != 0 or self.ea_ridge != SPD_RIDGE):
            raise ValueError("EA regularization parameters apply only to ea_fbcsp")
        self.params = deepcopy(params or {})
        self.tune = bool(tune)
        self.param_grid = deepcopy(param_grid)
        if param_grid is not None and not tune:
            raise ValueError("param_grid requires tune=True")
        self.inner_splits = _positive_int(inner_splits, "inner_splits", 5)
        if self.inner_splits < 2:
            raise ValueError("inner_splits must be at least 2")
        if isinstance(random_state, bool) or not isinstance(random_state, (int, np.integer)) or not 0 <= random_state < 2**32:
            raise ValueError("random_state must be an integer in [0, 2**32)")
        self.random_state = int(random_state)
        self.blas_threads = _positive_int(blas_threads, "blas_threads", 20)
        self.max_working_bytes = _positive_int(max_working_bytes, "max_working_bytes", 48 * 1024**3)

    def _derived_bands(self):
        if self.learner not in FBCSP_METHODS:
            return ()
        if self.bands is not None:
            return self.bands
        low, high = self.available_band
        count = int(np.floor((high - low) / self.band_width + 1e-12))
        if count > 12:
            raise LearnerNotApplicable("More than 12 derived bands; increase band_width")
        return tuple((low + i * self.band_width, min(high, low + (i + 1) * self.band_width)) for i in range(count))

    def _signal_settings(self):
        return (self.learner, self.sfreq, self.available_band, self.band_width, self.bands,
                self.upstream_adaptation, self.per_band_ea, self.ea_shrinkage, self.ea_ridge)

    def applicability(self):
        """Spectral applicability only; dependency/data checks happen at fit."""
        reasons = []
        try:
            bands = self._derived_bands()
        except LearnerNotApplicable as exc:
            bands, reasons = (), [str(exc)]
        if self.learner in FBCSP_METHODS and len(bands) < 2:
            reasons.append("FBCSP requires at least two supported bands; use a single-band learner")
        if self.learner == "broadband_ea_fbcsp" and self.upstream_adaptation != "euclidean_alignment":
            reasons.append("broadband_ea_fbcsp requires an explicit upstream euclidean_alignment declaration")
        if self.per_band_ea and self.upstream_adaptation != "none":
            reasons.append("ea_fbcsp requires PRE-adaptation signals with upstream_adaptation='none'")
        return {
            "applicable": not reasons, "reasons": reasons, "available_band_hz": list(self.available_band),
            "derived_bands_hz": [list(band) for band in bands],
            "scope": "spectral/declaration checks; numerical and dependency checks deferred to fit",
            "upstream_adaptation": self.upstream_adaptation,
            "order": ("within-support band filtering -> per-subject unlabelled EA -> OAS -> fold-local learner"
                      if self.per_band_ea else "upstream adaptation -> within-support band filtering -> OAS -> fold-local learner"
                      if self.learner in FBCSP_METHODS else "upstream adaptation -> OAS -> fold-local learner"),
            "per_band_ea_refit": self.per_band_ea,
            "prediction_subject_ids_required": self.per_band_ea,
        }

    def _check_trials(self, X, *, fitting):
        X = np.asarray(X)
        if X.ndim != 3 or X.dtype.kind not in "fiu" or len(X) == 0 or X.shape[1] < 2 or X.shape[2] < 4:
            raise ValueError("Expected nonempty real trials with shape (n, channels>=2, samples>=4)")
        if X.shape[1] > 64:
            raise LearnerNotApplicable("This bounded recipe supports at most 64 channels")
        if not fitting and X.shape[1:] != self.input_shape_:
            raise ValueError("Prediction channel/sample geometry differs from training")
        n, channels, samples = X.shape
        nbands = max(1, len(self._derived_bands()))
        features = channels * (channels + 1) // 2
        # Conservative array working-set estimate; input is borrowed, not copied
        # wholesale. Covers inner covariance copies and FgMDM dense TS/LDA arrays.
        estimate = (4 * n * nbands * channels**2 + 4 * n * features
                    + 12 * features**2 + 8 * channels * samples) * 8
        if estimate > self.max_working_bytes:
            raise LearnerMemoryLimit(f"Estimated working arrays {estimate} bytes exceed configured budget")
        # Validate one trial at a time to avoid a signal-sized boolean temporary.
        if any(not np.isfinite(trial).all() for trial in X):
            raise ValueError("Nonfinite trial data")
        return X, int(estimate)

    def _covariances(self, X, subjects=None, *, return_audit=False):
        """Label-free covariances, optionally after per-subject/per-band EA."""
        bands = self._derived_bands()
        filters = [butter(4, band, btype="bandpass", fs=self.sfreq, output="sos") for band in bands]
        result = np.empty((len(X), max(1, len(bands)), X.shape[1], X.shape[1]), dtype=np.float64)
        audit = {"per_band_ea": self.per_band_ea, "labels_received": False, "subject_bands": [],
                 "reference_estimator": "mean of centered per-trial empirical covariances / T" if self.per_band_ea else None,
                 "ea_shrinkage": self.ea_shrinkage if self.per_band_ea else None,
                 "ea_ridge_relative": self.ea_ridge if self.per_band_ea else None,
                 "full_subject_batch": "required; completeness guaranteed by caller" if self.per_band_ea else "not required by this learner",
                 "post_ea_covariance": "OAS on transformed signals; not a congruence of pre-EA OAS" if self.per_band_ea else None}
        if self.per_band_ea:
            if subjects is None:
                raise ValueError("Per-band EA requires subjects and complete unlabelled subject batches")
            subjects = _ids(subjects, len(X), "subjects")
            groups = [(subject, np.flatnonzero(subjects == subject)) for subject in np.unique(subjects)]
            if any(len(indices) < 2 for _, indices in groups):
                raise LearnerNotApplicable("Per-band EA needs at least two trials per complete subject batch")
        else:
            groups = [(None, np.arange(len(X)))]
        for band, sos in enumerate(filters or [None]):
            for subject, indices in groups:
                whitener = None
                if self.per_band_ea:
                    reference = np.zeros((X.shape[1], X.shape[1]), dtype=np.float64)
                    # Two streaming passes avoid retaining all filtered signals.
                    for i in indices:
                        values = sosfiltfilt(sos, np.asarray(X[i], dtype=np.float64), axis=-1)
                        values -= values.mean(axis=-1, keepdims=True)
                        reference += (values @ values.T / values.shape[-1]) / len(indices)
                    whitener, entry = _ea_whitener(reference, self.ea_shrinkage, self.ea_ridge)
                    audit["subject_bands"].append({"subject": subject.item(), "band_hz": list(bands[band]),
                                                   "trials": len(indices), **entry})
                for i in indices:
                    trial = np.asarray(X[i], dtype=np.float64)
                    values = trial if sos is None else sosfiltfilt(sos, trial, axis=-1)
                    if whitener is not None:
                        values = whitener @ (values - values.mean(axis=-1, keepdims=True))
                    matrix, _ = oas(values.T, assume_centered=False)
                    scale = float(np.trace(matrix) / len(matrix))
                    if not np.isfinite(matrix).all() or not np.isfinite(scale) or scale <= 0:
                        raise ValueError(f"Trial {i}, band {band} has invalid or zero covariance")
                    matrix = (matrix + matrix.T) * 0.5 + (SPD_RIDGE * scale) * np.eye(len(matrix))
                    np.linalg.cholesky(matrix)
                    result[i, band] = matrix
        result = result if bands else result[:, 0]
        return (result, audit) if return_audit else result

    def _resolved_params(self, overrides, channels):
        base = {"C": 1.0}
        if self.learner in FBCSP_METHODS:
            base.update(n_components=4, k_best=10)
        if self.learner == "fgmdm":
            base = {}
        if set(overrides) - set(base):
            raise ValueError(f"Unsupported parameters: {sorted(set(overrides) - set(base))}")
        base.update(overrides)
        if "C" in base:
            if isinstance(base["C"], bool) or not isinstance(base["C"], (int, float, np.integer, np.floating)):
                raise ValueError("C must be a numeric scalar")
            base["C"] = float(base["C"])
            if not np.isfinite(base["C"]) or base["C"] <= 0:
                raise ValueError("C must be finite and positive")
        if "n_components" in base:
            base["n_components"] = min(channels, _positive_int(base["n_components"], "n_components", 64))
            n_features = len(self._derived_bands()) * base["n_components"]
            base["k_best"] = min(n_features, _positive_int(base["k_best"], "k_best", 768))
        return base

    def _candidates(self, channels):
        base = self._resolved_params(self.params, channels)
        if not self.tune:
            return [base]
        if self.learner == "fgmdm":
            raise LearnerNotApplicable("FgMDM has a fixed recipe; use tune=False")
        grid = self.param_grid
        if grid is None:
            grid = {"C": [0.1, 1.0, 10.0]}
            if self.learner in FBCSP_METHODS:
                grid.update(n_components=[4, 6], k_best=[10, 20])
        if not isinstance(grid, dict) or not grid or set(grid) - set(base):
            raise ValueError("param_grid must contain supported parameter names")
        sizes = []
        for values in grid.values():
            if not isinstance(values, (list, tuple)) or not values:
                raise ValueError("Each grid value must be a nonempty list or tuple")
            sizes.append(len(values))
        if np.prod(sizes, dtype=object) > 24:
            raise LearnerNotApplicable("At most 24 inner candidates are supported")
        result = []
        for values in product(*(grid[key] for key in sorted(grid))):
            candidate = self._resolved_params({**base, **dict(zip(sorted(grid), values))}, channels)
            if candidate not in result:
                result.append(candidate)
        return result

    def _pipeline(self, params):
        _, TangentSpace, FgMDM = _reference_classes()
        if self.learner == "fgmdm":
            return Pipeline([("classifier", FgMDM(metric="riemann", tsupdate=False, n_jobs=1))])
        if self.learner in FBCSP_METHODS:
            steps = [
                ("features", _FilterBankCSP(n_components=params["n_components"])),
                ("selection", SelectKBest(partial(mutual_info_classif, random_state=self.random_state), k=params["k_best"])),
            ]
        else:
            steps = [("features", TangentSpace(metric="riemann", tsupdate=False))]
        return Pipeline(steps + [
            ("scale", StandardScaler()),
            ("classifier", LogisticRegression(C=params["C"], penalty="l2", solver="lbfgs",
                                               class_weight="balanced", max_iter=1000, tol=1e-6,
                                               random_state=self.random_state)),
        ])

    def fit(self, X, y, subjects):
        # A failed refit must never leave a stale, apparently successful model.
        for attribute in ("model_", "metadata_", "classes_", "input_shape_", "_fitted_signal_settings_"):
            self.__dict__.pop(attribute, None)
        applicability = self.applicability()
        if not applicability["applicable"]:
            raise LearnerNotApplicable("; ".join(applicability["reasons"]))
        _reference_classes()
        X, estimate = self._check_trials(X, fitting=True)
        y, subjects = _ids(y, len(X), "labels"), _ids(subjects, len(X), "subjects")
        classes = np.unique(y)
        if len(classes) != 2 or min(np.sum(y == label) for label in classes) < 2:
            raise ValueError("Binary training requires at least two trials in each class")
        candidates = self._candidates(X.shape[1])
        splits, roles = [], []
        if self.tune:
            if len(np.unique(subjects)) < self.inner_splits:
                raise LearnerNotApplicable("Insufficient subjects for requested inner GroupKFold")
            splits = list(GroupKFold(n_splits=self.inner_splits).split(np.empty(len(y)), y, subjects))
            for train, valid in splits:
                if len(np.unique(y[train])) != 2 or min(np.sum(y[train] == c) for c in classes) < 2:
                    raise LearnerNotApplicable("Every inner training fold needs both classes with >=2 trials")
                if any(len(np.unique(y[valid][subjects[valid] == s])) != 2 for s in np.unique(subjects[valid])):
                    raise LearnerNotApplicable("Subject-macro BA requires both labels in each inner validation subject")
                roles.append({"fit_subjects": np.unique(subjects[train]).tolist(),
                              "validation_subjects": np.unique(subjects[valid]).tolist(),
                              "fit_trials": len(train), "validation_trials": len(valid),
                              "ea_scope": "each complete subject separately, no labels" if self.per_band_ea else None})
        history = []
        with threadpool_limits(limits=self.blas_threads), warnings.catch_warnings():
            # Nonconvergence/invalid geometry is a failed candidate, not a score.
            warnings.filterwarnings("error", category=RuntimeWarning)
            warnings.filterwarnings("error", category=ConvergenceWarning)
            warnings.filterwarnings("error", message=".*[Cc]onverg.*")
            covs, adaptation_audit = self._covariances(X, subjects, return_audit=True)
            for params in candidates if self.tune else []:
                subject_scores, fold_scores = [], []
                for train, valid in splits:
                    model = self._pipeline(params).fit(covs[train], y[train])
                    predicted = model.predict(covs[valid])
                    scores = [float(balanced_accuracy_score(y[valid][subjects[valid] == s], predicted[subjects[valid] == s]))
                              for s in np.unique(subjects[valid])]
                    subject_scores.extend(scores)
                    fold_scores.append(float(np.mean(scores)))
                history.append({"params": deepcopy(params), "fold_subject_macro_ba": fold_scores,
                                "subject_macro_ba": float(np.mean(subject_scores))})
            # Stable first-in-grid tie breaking; never consult an outer score.
            winner = int(np.argmax([row["subject_macro_ba"] for row in history])) if history else 0
            selected = candidates[winner]
            model = self._pipeline(selected).fit(covs, y)
        self.model_, self.classes_, self.input_shape_ = model, classes, X.shape[1:]
        self._fitted_signal_settings_ = self._signal_settings()
        fbcsp = self.learner in FBCSP_METHODS
        self.metadata_ = {
            "implementation_revision": "subject-band-ea-v2",
            "learner": self.learner, "params": deepcopy(selected),
            "requested_params": {key: value.item() if isinstance(value, np.generic) else value
                                 for key, value in self.params.items()},
            "recipe": {"covariance": "sklearn.oas per trial, centered", "relative_spd_ridge": SPD_RIDGE,
                       "tsupdate": False, "csp_mean_metric": "euclid" if fbcsp else None,
                       "geometry_metric": None if fbcsp else "riemann",
                       "classifier": "FgMDM" if self.learner == "fgmdm" else "L2 balanced logistic regression",
                       "scaling": "none" if self.learner == "fgmdm" else "training StandardScaler",
                       "filter": "butter order=4 bandpass, sosfiltfilt default odd padding on each epoch" if fbcsp else "no additional filtering",
                       "sfreq_hz": self.sfreq, "band_width_hz": self.band_width,
                       "random_state": self.random_state,
                       "logistic_settings": None if self.learner == "fgmdm" else
                       {"solver": "lbfgs", "penalty": "l2", "class_weight": "balanced", "max_iter": 1000, "tol": 1e-6},
                       "selection": {"score": "mutual_info_classif", "n_neighbors": 3} if fbcsp else None},
            "classes": classes.tolist(), "positive_class": classes[1].item(),
            "input_shape": list(X.shape), "applicability": applicability,
            "adaptation": {"role": "outer_training_subjects_only", **adaptation_audit},
            "fit_subject_roles": {"outer_training": np.unique(subjects).tolist(), "target_labels_received": False,
                                  "target_statistics_fitted_by_learner": False,
                                  "predict_target_statistics_permission": "per-subject full unlabelled batch EA" if self.per_band_ea else "none",
                                  "upstream_adaptation": self.upstream_adaptation,
                                  "upstream_subject_roles": "caller must attach adaptation manifest; not inferred"},
            "inner_cv": {"enabled": self.tune, "splitter": "GroupKFold" if self.tune else None,
                         "n_splits": len(splits), "selection_metric": "subject-macro balanced accuracy",
                         "roles": roles, "candidates": history, "selected_index": winner,
                         "tie_break": "first candidate", "refit": "all outer training trials",
                         "fold_local_stages": (["CSP", "MI selection", "scaler", "classifier"] if fbcsp else
                                               ["TS reference", "scaler", "classifier"] if self.learner == "ts_lr" else
                                               ["FGDA TS reference", "FGDA LDA", "MDM class means"]),
                         "shared_stage": ("per-subject/per-band unlabelled EA + fixed filtering/OAS; full subject groups never split"
                                          if self.per_band_ea else "label-free fixed per-trial filtering and OAS only")},
            "probability_kind": "uncalibrated distance softmax" if self.learner == "fgmdm" else "logistic; no separate calibration",
            "resources": {"blas_threads": self.blas_threads, "parallel_fits": 1, "riemann_jobs": 1,
                          "estimated_working_array_bytes": estimate, "budget_bytes": self.max_working_bytes,
                          "budget_scope": "estimate excludes caller-owned input and process overhead; not a hard RSS limit"},
            "dependencies": {name: import_module(name).__version__ for name in ("numpy", "scipy", "sklearn", "pyriemann")},
        }
        return self

    def describe(self):
        """A detached JSON-compatible audit; calling it cannot mutate fit state."""
        if not hasattr(self, "model_"):
            raise NotFittedError("TraditionalLearner has not completed fit")
        return deepcopy(self.metadata_)

    def _infer(self, X, operation, subjects, return_audit):
        if not hasattr(self, "model_"):
            raise NotFittedError("TraditionalLearner has not completed fit")
        if self._signal_settings() != self._fitted_signal_settings_:
            raise ValueError("Signal settings changed since fit; refit before prediction")
        X, _ = self._check_trials(X, fitting=False)
        if subjects is not None:
            subjects = _ids(subjects, len(X), "subjects")
        with threadpool_limits(limits=self.blas_threads), warnings.catch_warnings():
            warnings.filterwarnings("error", category=RuntimeWarning)
            covs, adaptation_audit = self._covariances(X, subjects, return_audit=True)
            if operation == "decision_function" and self.learner == "fgmdm":
                distances = self.model_.named_steps["classifier"].transform(covs)
                # Native FgMDM softmax is exp(-distance**2); same positive-class log odds.
                result = distances[:, 0] ** 2 - distances[:, 1] ** 2
            else:
                result = getattr(self.model_, operation)(covs)
        if operation != "predict" and not np.isfinite(result).all():
            raise FloatingPointError("Nonfinite learner output")
        if return_audit:
            subject_ids = np.unique(subjects).tolist() if subjects is not None else []
            return result, {
                "implementation_revision": "subject-band-ea-v2",
                "learner": self.learner, "role": "prediction_unlabelled_subject_batches",
                "subject_ids": subject_ids, "target_labels_received": False,
                "supervised_model_updated": False,
                "overlap_with_training_subjects": [s for s in subject_ids if s in self.metadata_["fit_subject_roles"]["outer_training"]],
                "classes": self.classes_.tolist(), "positive_class": self.classes_[1].item(),
                "adaptation": adaptation_audit,
            }
        return result

    def predict(self, X, subjects=None, *, return_audit=False):
        return self._infer(X, "predict", subjects, return_audit)

    def predict_proba(self, X, subjects=None, *, return_audit=False):
        """EA needs full subject batches. Optionally return (probabilities, audit)."""
        return self._infer(X, "predict_proba", subjects, return_audit)

    def decision_function(self, X, subjects=None, *, return_audit=False):
        """AUC score increasing toward classes_[1]."""
        return self._infer(X, "decision_function", subjects, return_audit)

    def decision_score(self, X, subjects=None, *, return_audit=False):
        return self.decision_function(X, subjects, return_audit=return_audit)


def make_learner(learner, **kwargs):
    """Factory without fitting or reading external data."""
    return TraditionalLearner(learner, **kwargs)
