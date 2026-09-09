"""Minimal training example; run in the extracted delivery directory.

Requires numpy and scikit-learn. This checks training compatibility;
it does not compare preprocessing methods or estimate generalization quality.
It is not the grouped-CV CSP/LDA search evaluator. CV exports mark every
development subject as train; evaluation/folds.json preserves the search folds.
Already adapted arrays must not be aligned a second time. Read channels.json
for physical-voltage versus dimensionless transformed-coordinate semantics.
"""

import argparse
from contextlib import ExitStack, contextmanager
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


_FEATURE_BLOCK_BYTES = 8 * 1024 * 1024


@contextmanager
def _mapped_array(path):
    values = np.load(path, mmap_mode="r", allow_pickle=False)
    try:
        yield values
    finally:
        # Release the file on Windows, including when validation or fitting fails.
        values._mmap.close()


def _log_variance(X):
    # Keep only the trial-by-channel features and bounded float64 working blocks.
    features = np.empty(X.shape[:2], dtype=np.float64)
    epoch_bytes = X.shape[1] * X.shape[2] * np.dtype(np.float64).itemsize
    block_trials = max(1, _FEATURE_BLOCK_BYTES // max(1, epoch_bytes))
    for start in range(0, len(X), block_trials):
        stop = min(start + block_trials, len(X))
        block = X[start:stop]
        if not np.isfinite(block).all():
            raise ValueError("Invalid signal or split values")
        block = block.astype(np.float64)
        # Per-trial log variance: no statistics fitted on held-out subjects.
        features[start:stop] = np.log(np.maximum(block.var(axis=2), 1e-20))
    return features


def train(folder):
    folder = Path(folder)
    with ExitStack() as stack:
        X, y, splits, subjects = (
            stack.enter_context(_mapped_array(folder / f"{name}.npy"))
            for name in ("X", "y", "split", "subjects")
        )
        if X.ndim != 3 or not (len(X) == len(y) == len(splits) == len(subjects)):
            raise ValueError("Arrays must be aligned by trial")
        features = _log_variance(X)
        if not set(splits) <= {"train", "validation", "test"}:
            raise ValueError("Invalid signal or split values")
        for subject in np.unique(subjects):
            if len(set(splits[subjects == subject])) != 1:
                raise ValueError("A subject crosses training and held-out groups")
        mask = splits == "train"
        if set(y[mask]) != {0, 1}:
            raise ValueError("Training needs both left-hand and right-hand trials")
        model = make_pipeline(
            StandardScaler(), LogisticRegression(max_iter=1000, random_state=42)
        )
        model.fit(features[mask], y[mask])
        prediction = model.predict(features)
        if not np.isfinite(model.predict_proba(features)).all():
            raise ValueError("Nonfinite model predictions")
        return {
            "model": "log-variance + StandardScaler + LogisticRegression",
            "training_trials": int(mask.sum()),
            "feature_count": features.shape[1],
            "prediction_count": len(prediction),
            "classes": model.classes_.tolist(),
            "fit_subjects": sorted(set(subjects[mask])),
            "quality_evaluated": False,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=".")
    parser.add_argument("--output", help="Optional path for a training smoke receipt")
    args = parser.parse_args()
    receipt = json.dumps(train(args.data), ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(receipt, encoding="utf-8")
    print(receipt)
