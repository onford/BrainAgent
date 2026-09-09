"""Streaming numerical primitives; adaptation never accepts labels.

Epoch covariance uses temporal centering and population normalization. CSP uses
the mean epoch covariance per training class, 0.1 spherical shrinkage, and the
four generalized eigenvectors furthest from 0.5 (capped by channel count).
Only compact feature matrices reach sklearn; signals/covariances stay on disk.
"""

from pathlib import Path

import numpy as np
from scipy.linalg import eigh
from sklearn.covariance import LedoitWolf

from app.preprocessing.storage import digest, file_hash

REGULARIZATION = 0.1
VARIANCE_FLOOR = 1e-20
CONDITION_RELATIVE_FLOOR = 1e-12
RANK_RELATIVE_TOLERANCE = 1e-8
LDA_RIDGE = 1e-12


def covariance(epoch):
    values = np.array(epoch, dtype=np.float64, copy=True)
    if not np.isfinite(values).all():
        raise RuntimeError("nonfinite signal")
    with np.errstate(over="raise", invalid="raise"):
        values -= values.mean(axis=-1, keepdims=True)
        return values @ values.T / values.shape[-1]


def regularized(matrix):
    scale = max(float(np.trace(matrix) / len(matrix)), VARIANCE_FLOOR)
    return (1 - REGULARIZATION) * matrix + REGULARIZATION * scale * np.eye(len(matrix))


def spectral_diagnostics(matrix):
    """Unit-invariant descriptive spectrum; nullspaces are reported separately.

    Normalize by mean channel variance without an absolute voltage floor.
    The zero matrix has rank zero and neutral condition/gate values of one.
    Tiny negative eigenvalues of a computed PSD covariance are clipped to zero.
    The gate uses all eigenvalues, with linear percentile interpolation.
    """
    scale = float(np.trace(matrix) / len(matrix))
    if scale <= 0:
        return 1.0, 0, 1.0
    normalized = matrix / scale
    eigenvalues = np.maximum(np.linalg.eigvalsh((normalized + normalized.T) / 2), 0)
    largest = float(eigenvalues[-1])
    condition = max(
        1.0, largest / max(float(eigenvalues[0]), largest * CONDITION_RELATIVE_FLOOR)
    )
    rank = int(np.count_nonzero(eigenvalues > largest * RANK_RELATIVE_TOLERANCE))
    shrunk = (1 - REGULARIZATION) * eigenvalues + REGULARIZATION
    low, high = np.quantile(shrunk, [0.1, 0.9], method="linear")
    return condition, rank, max(1.0, float(high / low))


def anisotropy(matrix):
    return spectral_diagnostics(matrix)[0]


def alignment(matrix, policy):
    """Gate and fit use only one subject's pooled unlabelled epoch covariance."""
    _, _, gate_value = spectral_diagnostics(matrix)
    requested = policy["adaptation"]
    passed = requested == "euclidean_alignment" or (
        requested == "conditional_alignment"
        and gate_value >= policy["alignment_threshold"]
    )
    if passed:
        eigenvalues, vectors = eigh(regularized(matrix))
        transform = (vectors * (1 / np.sqrt(eigenvalues))) @ vectors.T
    elif requested in {"subject_scale", "conditional_alignment"}:
        scale = max(float(np.trace(matrix) / len(matrix)), VARIANCE_FLOOR)
        transform = np.eye(len(matrix)) / np.sqrt(scale)
    else:
        transform = np.eye(len(matrix))
    return transform, passed, gate_value


def prepare_representation(sources, panel, output, policy, mapped):
    """Fit once per subject across all records, save separate derived artifacts.

    At most one signal epoch plus one subject covariance/transform is resident.
    Subject transforms are fitted without any label array or fold label access.
    Unadapted records retain their original V representation and source hashes.
    """
    directory = Path(output) / "adaptation"
    directory.mkdir(parents=True, exist_ok=True)
    rep = dict(
        policy=policy,
        unit="V",
        transductive=policy["adaptation"] != "none",
        channels=panel["output_contract"]["channels"],
        subjects={},
        records={},
    )
    diagnostics, derived = {}, {}
    for subject in sorted({r["subject"] for r in panel["records"].values()}):
        selected = [s for s in sources if panel["records"][s[3]]["subject"] == subject]
        channels = len(rep["channels"])
        pooled, flat, count = np.zeros((channels, channels)), np.zeros(channels), 0
        for path, rows, shape, rid in selected:
            with mapped(path) as values:
                if list(values.shape) != shape or values.dtype.kind not in "fiu":
                    raise ValueError("signal shape/dtype differs")
                for row in rows:
                    cov = covariance(values[row["epoch_index"]])
                    pooled += cov
                    flat += np.diag(cov) <= VARIANCE_FLOOR
                    count += 1
        pooled /= count
        transform, passed, gate_value = alignment(pooled, policy)
        condition, rank_before, _ = spectral_diagnostics(pooled)
        transformed_covariance = transform @ pooled @ transform.T
        condition_after, rank_after, _ = spectral_diagnostics(transformed_covariance)
        diagnostics[subject] = dict(
            channel_variance=np.diag(pooled).tolist(),
            channel_flat_fraction=(flat / count).tolist(),
            covariance_condition=condition,
            covariance_condition_before=condition,
            covariance_condition_after=condition_after,
            effective_rank_before=rank_before,
            effective_rank_after=rank_after,
            mean_channel_variance_before=float(np.trace(pooled) / channels),
            mean_channel_variance_after=float(
                np.trace(transformed_covariance) / channels
            ),
        )
        unit = "dimensionless" if policy["adaptation"] != "none" else "V"
        info = dict(
            applied_adaptation="euclidean_alignment"
            if passed
            else ("scale_only" if policy["adaptation"] != "none" else "none"),
            gate_passed=passed,
            covariance_anisotropy=condition,
            gate_metric_value=gate_value,
            fallback_reason="保持空间结构，仅统一无量纲尺度"
            if (policy["adaptation"] == "conditional_alignment" and not passed)
            else None,
            fit_trials=count,
            unit=unit,
            transform_path=None,
            transform_sha256=None,
        )
        if policy["adaptation"] != "none":
            transform_path = directory / f"subject-{digest(subject)}-transform.npy"
            np.save(transform_path, transform, allow_pickle=False)
            info.update(
                transform_path=str(transform_path.resolve()),
                transform_sha256=file_hash(transform_path),
            )
        rep["subjects"][subject] = info
        for path, rows, shape, rid in selected:
            target = path
            # Conditional declines retain spatial structure with scalar normalization.
            if policy["adaptation"] != "none":
                target = directory / f"record-{digest(rid)}-signal.npy"
                destination = np.lib.format.open_memmap(
                    target, mode="w+", dtype="float64", shape=tuple(shape)
                )
                try:
                    with mapped(path) as values:
                        for row in rows:
                            index = row["epoch_index"]
                            destination[index] = transform @ np.array(
                                values[index], dtype=np.float64
                            )
                    destination.flush()
                finally:
                    destination._mmap.close()
            rep["records"][rid] = dict(
                subject=subject,
                array_path=str(Path(target).resolve()),
                array_sha256=file_hash(target),
                shape=shape,
                unit=unit,
            )
            derived[rid] = (target, rows, shape, rid)
    rep["unit"] = "V" if policy["adaptation"] == "none" else "dimensionless"
    conditional = policy["adaptation"] == "conditional_alignment"
    rep["gate_subject_count"] = len(rep["subjects"]) if conditional else 0
    rep["gate_passed_subject_count"] = (
        sum(s["gate_passed"] for s in rep["subjects"].values()) if conditional else 0
    )
    rep["gate_fraction"] = (
        rep["gate_passed_subject_count"] / rep["gate_subject_count"]
        if conditional
        else None
    )
    return [derived[s[3]] for s in sources], diagnostics, rep


def fit_csp(covariances, indices, train_labels):
    """Only caller-supplied fold training indices contribute to spatial filters."""
    means = []
    for label in np.unique(train_labels):
        members = [i for i, value in zip(indices, train_labels) if value == label]
        mean = np.zeros(covariances.shape[1:], dtype=np.float64)
        for index in members:
            mean += covariances[index]
        means.append(regularized(mean / len(members)))
    if len(means) != 2:
        raise ValueError("CSP requires two training classes")
    eigenvalues, vectors = eigh(means[0], means[0] + means[1])
    order = np.argsort(-np.abs(eigenvalues - 0.5), kind="stable")[
        : min(4, len(vectors))
    ]
    return vectors[:, order].T


def csp_features(covariances, filters):
    features = np.empty((len(covariances), len(filters)))
    for i, cov in enumerate(covariances):
        power = np.einsum("ij,jk,ik->i", filters, cov, filters)
        features[i] = np.log(np.maximum(power, VARIANCE_FLOOR))
    return features


class StableShrinkageCovariance(LedoitWolf):
    """Ledoit-Wolf shrinkage with a fixed numerical ridge for constant fixtures.

    LDA fits this separately within each training class. The ridge prevents
    exactly zero within-class covariance from erasing a separable class mean.
    """

    def fit(self, X, y=None):
        super().fit(X, y)
        scale = max(float(np.trace(self.covariance_) / len(self.covariance_)), 1.0)
        self.covariance_ += np.eye(len(self.covariance_)) * scale * LDA_RIDGE
        return self


def paired_ci(deltas, seed):
    values = np.asarray(deltas, dtype=np.float64)
    rng = np.random.default_rng(seed % (2**32))
    means = np.empty(2000)
    # Avoid allocating n_resamples * nsubjects for larger panels.
    for i in range(len(means)):
        means[i] = values[rng.integers(0, len(values), size=len(values))].mean()
    low, high = np.quantile(means, [0.025, 0.975])
    return dict(low=float(low), high=float(high), n_subjects=len(values), seed=seed)
