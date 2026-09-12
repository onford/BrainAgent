import json

from app.workflows.context import results_context


def test_report_context_retains_measured_scope_without_large_file_payloads():
    records = {f"record-{n}": {"array_path": f"private/{n}.npy"} for n in range(2000)}
    selection = {
        "score": 0.63,
        "evaluation_scope": "development",
        "selected_candidate_id": "bp8-30-original-ea",
        "representation": {
            "unit": "dimensionless",
            "policy": {"adaptation": "euclidean_alignment"},
            "records": records,
            "transductive": True,
        },
        "panel": {
            "records": records,
            "trial_count": 5000,
            "eligible_count": 4990,
            "development_subjects": [f"S{n:03}" for n in range(109)],
            "folds": [
                {
                    "id": "fold-01",
                    "train_subjects": ["S001"],
                    "development_subjects": ["S002"],
                }
            ],
        },
        "selected_receipt": {
            "macro_ba": 0.63,
            "secondary_macro_ba": 0.61,
            "diagnostics": {"summary": {"mean_anisotropy": 9.5}, "subjects": records},
        },
        "evaluation_protocol": {
            "evaluation_mode": "group_cross_validation",
            "confirmation": "not_performed",
        },
    }
    compact = results_context({"data_evaluation": selection})["data_evaluation"]
    assert compact["score"] == 0.63 and compact["metrics"]["secondary_macro_ba"] == 0.61
    assert compact["panel"]["record_count"] == 2000
    assert compact["panel"]["development_subject_count"] == 109
    assert compact["panel"]["eligible_count"] == 4990
    assert compact["representation"]["unit"] == "dimensionless"
    assert compact["protocol"]["confirmation"] == "not_performed"
    text = json.dumps(compact)
    assert len(text) < 2500 and "private/" not in text
    assert len(selection["representation"]["records"]) == 2000


def test_context_only_describes_physical_representation():
    selection = {"representation": {"version": "2", "unit": "V", "channels": ["C3"], "records": {}}}
    value = results_context({"data_evaluation": selection})["data_evaluation"]["representation"]
    assert value == {"version": "2", "unit": "V", "channels": ["C3"]}
