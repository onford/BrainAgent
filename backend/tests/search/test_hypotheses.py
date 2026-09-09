import pytest

from app.search.contracts import ProposeCandidate
from app.search.hypotheses import check_predictions, validate_hypothesis
from app.search.reasoning import measured_feedback
from tests.search.test_controller import propose


def test_predictions_keep_failed_mechanism_separate_from_improved_utility():
    proposal = ProposeCandidate.model_validate(
        propose("bp1-40-average")["decision"]
    ).model_dump()
    parent = {
        "status": "evaluated",
        "macro_ba": 0.5,
        "diagnostics": {"floor_fraction": 0.0},
    }
    current = {
        "status": "evaluated",
        "macro_ba": 0.7,
        "diagnostics": {"floor_fraction": 0.2},
    }
    checks = check_predictions(proposal, parent, current)["checks"]
    assert [row["status"] for row in checks] == ["contradicted", "matched"]
    assert checks[0]["difference"] == 0.2


def test_invented_observation_rejected_before_execution():
    proposal = propose("bp1-40-average")["decision"]
    proposal["hypothesis"]["observations"][0]["metric"] = "invented"
    with pytest.raises(ValueError, match="不存在"):
        validate_hypothesis(
            proposal,
            [
                {
                    "id": "bp8-30-average",
                    "status": "evaluated",
                    "receipt": {"macro_ba": 0.5},
                }
            ],
        )


def test_failure_never_counts_as_disconfirming_score():
    proposal = propose("bp1-40-average")["decision"]
    result = check_predictions(proposal, {}, {"status": "resource_failure"})
    assert all(
        c["status"] == "unavailable" and c["difference"] is None
        for c in result["checks"]
    )


@pytest.mark.parametrize(
    "metric",
    [
        "macro_ba",
        "secondary_macro_ba",
        "secondary_subjects.S001",
        "cost_seconds",
        "coverage",
    ],
)
def test_signal_prediction_cannot_relabel_accuracy(metric):
    proposal = propose("bp1-40-average")["decision"]
    proposal["hypothesis"]["predictions"][0]["metric"] = metric
    with pytest.raises(ValueError, match="必须分开"):
        ProposeCandidate.model_validate(proposal)


def test_feedback_keeps_measured_paths_without_per_file_or_channel_payloads():
    receipt = {
        "status": "evaluated",
        "macro_ba": 0.7,
        "diagnostics": {
            "summary": {"mean_condition_before": 7.5},
            "subjects": {"S001": {"channel_variance": [1.0] * 64}},
        },
        "representation": {"records": {"record": {"array_path": "a.npy"}}},
        "operator_usage": {"summary": {"operators": {"asr": {"applied": 0, "not_applicable": 327}}}, "artifact": {"path": "full.json"}},
    }
    result = measured_feedback({"id": "candidate", "receipt": receipt})["receipt"]
    assert result["macro_ba"] == 0.7
    assert result["diagnostics"]["summary"]["mean_condition_before"] == 7.5
    assert "subjects" not in result["diagnostics"] and "representation" not in result
    assert "subjects" in receipt["diagnostics"]  # Source receipt remains complete.
    assert result["operator_usage"] == {"summary": receipt["operator_usage"]["summary"]}
