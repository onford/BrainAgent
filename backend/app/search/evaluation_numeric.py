"""Streaming numerical primitives for the fold-trained CSP benchmark.

Epoch covariance uses temporal centering and population normalization. CSP uses
the mean epoch covariance per training class, 0.1 spherical shrinkage, and the
four generalized eigenvectors furthest from 0.5 (capped by channel count).
Only compact feature matrices reach sklearn; signals/covariances stay on disk.
"""


import numpy as np
from scipy.linalg import eigh
from sklearn.covariance import LedoitWolf


REGULARIZATION = 0.1
VARIANCE_FLOOR = 1e-20
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


def signal_manifest(sources, panel):
    from app.preprocessing.storage import file_hash
    from pathlib import Path

    return dict(version="2", unit="V", channels=panel["output_contract"]["channels"],
                records={rid: dict(subject=panel["records"][rid]["subject"],
                                   array_path=str(Path(path).resolve()), array_sha256=file_hash(path),
                                   shape=shape, unit="V") for path, rows, shape, rid in sources})
