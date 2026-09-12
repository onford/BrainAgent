"""The shared recipe contract cannot silently revive withdrawn subject fitting."""
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError
from app.search.space_contracts import PipelineEdit, PipelineRecipe
from app.search.evaluation_contracts import EvaluationReceipt
from app.search.evaluation import evaluate
from app.preprocessing.schemas import Step
from tests.search.test_evaluation_v2 import cv_case


@pytest.mark.parametrize("mode", ["none", "subject_scale", "euclidean_alignment", "conditional_alignment"])
def test_retired_policy_and_edit_rejected(mode):
    with pytest.raises(ValidationError):
        TypeAdapter(PipelineEdit).validate_python({"action": "set_adaptation", "policy": {"adaptation": mode}})
    with pytest.raises(ValidationError):
        PipelineRecipe.model_validate({"nodes": [{"id": "epoch", "operator": "epoch"}], "adaptation": {"adaptation": mode}})


@pytest.mark.parametrize("scope", ["subject_unlabeled", "online"])
def test_removed_fit_scopes_rejected(scope):
    with pytest.raises(ValidationError):
        Step(id="fit", unit_id="EEG-ICA", op="ica_fit", implementation_version="2", adaptation_scope=scope)


def test_scoring_uses_original_physical_arrays_and_strict_manifest(tmp_path):
    result, plan, root, panel = cv_case(tmp_path)
    receipt = evaluate(result, plan, root, panel, tmp_path / "score")
    assert receipt["status"] == "evaluated", receipt
    assert receipt["evaluator_version"] == 4
    assert set(receipt["representation"]) == {"version", "unit", "channels", "records"}
    for rid, row in receipt["representation"]["records"].items():
        assert Path(row["array_path"]) == (root / rid / "signal_V.npy").resolve()
        assert row["unit"] == "V"
    assert not list((tmp_path / "score").rglob("*.npy"))
    for key, value in [("unit", "dimensionless"), ("subjects", {}), ("policy", {})]:
        invalid = deepcopy(receipt)
        invalid["representation"][key] = value
        with pytest.raises(ValidationError):
            EvaluationReceipt.model_validate(invalid)
