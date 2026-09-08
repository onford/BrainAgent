"""Minimal training example; run in the extracted delivery directory.

Requires numpy and scikit-learn. This checks training compatibility;
it does not compare preprocessing methods or estimate generalization quality.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def train(folder):
    folder = Path(folder)
    X = np.load(folder / "X.npy", allow_pickle=False)
    y = np.load(folder / "y.npy", allow_pickle=False)
    splits = np.load(folder / "split.npy", allow_pickle=False)
    subjects = np.load(folder / "subjects.npy", allow_pickle=False)
    if X.ndim != 3 or not (len(X) == len(y) == len(splits) == len(subjects)):
        raise ValueError("Arrays must be aligned by trial")
    if not np.isfinite(X).all() or not set(splits) <= {"train", "validation", "test"}:
        raise ValueError("Invalid signal or split values")
    for subject in np.unique(subjects):
        if len(set(splits[subjects == subject])) != 1:
            raise ValueError("A subject crosses training and held-out groups")
    mask = splits == "train"
    if set(y[mask]) != {0, 1}:
        raise ValueError("Training needs both left-hand and right-hand trials")
    # Per-trial log variance: no statistics fitted on held-out subjects.
    features = np.log(np.maximum(X.astype(np.float64).var(axis=2), 1e-20))
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
