"""Core-only versioning and equivalence to the preserved CSP pipeline."""

import csv
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError
from sklearn.linear_model import LogisticRegression

from app.search import evaluation
from app.search.evaluation_contracts import EvaluationReceipt, EvaluationRepresentation, LearnerMetadata
from tests.search.test_evaluation_v2 import cv_case


def test_core_preserves_representation_and_exact_csp_predictions(
    tmp_path, monkeypatch
):
    result, plan, root, panel = cv_case(tmp_path)
    prepared = []
    original_prepare = evaluation.signal_manifest

    def prepare(*args):
        value = original_prepare(*args)
        prepared.append(deepcopy((args[0], value)))
        return value

    def forbidden(*args, **kwargs):
        pytest.fail("v3 core fitted LogisticRegression")

    monkeypatch.setattr(evaluation, "signal_manifest", prepare)
    monkeypatch.setattr(LogisticRegression, "fit", forbidden)
    receipt = evaluation.evaluate(
        result, plan, root, panel, tmp_path / "core",
    )
    core_evaluated = EvaluationReceipt.model_validate(receipt)
    assert core_evaluated.status == "evaluated", receipt
    assert core_evaluated.macro_ba == receipt["macro_ba"]
    assert len(prepared) == 1
    sources, representation = prepared[0]
    assert receipt["representation"] == EvaluationRepresentation.model_validate(
        representation
    ).model_dump(mode="json")
    assert receipt["diagnostics"]["subjects"] == {}

    # Replay the v2 primary branch using exactly the delivered representation.
    # There is no secondary learner in this reference or the evaluator.
    covariances, identities = [], []
    for path, rows, shape, rid in sources:
        with evaluation._mapped(path) as values:
            for row in rows:
                covariances.append(evaluation.covariance(values[row["epoch_index"]]))
                identities.append(row["event_id"])
    covariances = np.asarray(covariances)
    frozen = {t["event_id"]: t for t in panel["trials"]}
    subjects = np.asarray([frozen[e]["subject"] for e in identities])
    labels = np.asarray([frozen[e]["label"] for e in identities])
    expected = {}
    for fold in panel["folds"]:
        train = np.flatnonzero(np.isin(subjects, fold["train_subjects"]))
        dev = np.flatnonzero(np.isin(subjects, fold["development_subjects"]))
        filters = evaluation.fit_csp(covariances, train, labels[train])
        features = evaluation.csp_features(covariances, filters)
        learner = evaluation.LinearDiscriminantAnalysis(
            solver="lsqr",
            covariance_estimator=evaluation.StableShrinkageCovariance(
                store_precision=False
            ),
        )
        learner.fit(features[train], labels[train])
        expected.update(zip(
            [identities[i] for i in dev], learner.predict(features[dev])
        ))
    with Path(receipt["predictions_path"]).open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    assert {r["event_id"]: r["prediction"] for r in rows if r["prediction"]} == expected
    assert all(r["primary_prediction"] == r["prediction"] for r in rows)
    assert all(r["secondary_prediction"] == "" for r in rows)


def test_v2_scores_read_unchanged_but_cannot_be_v3_baseline(tmp_path, monkeypatch):
    result, plan, root, panel = cv_case(tmp_path)
    receipt = evaluation.evaluate(result, plan, root, panel, tmp_path / "core")
    # Synthetic historical schema fixture, with deliberately different secondary BA.
    historical = {
        **receipt,
        "evaluator_version": 2,
        "secondary_learner": "logvariance_standardizer_logistic_regression",
        "secondary_macro_ba": 0.25,
        "secondary_subjects": {s: 0.25 for s in receipt["subjects"]},
        "learner_metadata": LearnerMetadata(
            csp_components=2, logistic_random_state=42
        ).model_dump(),
    }
    original = deepcopy(historical)
    parsed = EvaluationReceipt.model_validate(historical)
    assert parsed.model_dump(mode="json") == original
    assert historical == original
    assert parsed.macro_ba == receipt["macro_ba"]
    assert parsed.secondary_macro_ba == 0.25
    with pytest.raises(ValidationError):
        EvaluationReceipt.model_validate({**historical, "evaluator_version": 3})
    with pytest.raises(ValidationError):
        EvaluationReceipt.model_validate({**receipt, "evaluator_version": 2})

    def forbidden(*args, **kwargs):
        pytest.fail("mixed-version baseline must fail before signal access")

    monkeypatch.setattr(evaluation, "_mapped", forbidden)
    failed = evaluation.evaluate(
        result, plan, root, panel, tmp_path / "mixed", baseline=historical
    )
    assert failed["status"] == "data_unevaluable"
    assert failed["error_code"] == "baseline_invalid"


@pytest.mark.parametrize("version", [2, 3])
def test_early_failure_defaults_are_versioned(version):
    receipt = EvaluationReceipt.model_validate({
        "evaluator_version": version,
        "status": "data_unevaluable",
        "error": "invalid panel",
    })
    assert receipt.stop_search
    assert (receipt.secondary_learner is None) == (version == 3)
