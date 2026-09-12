"""Search selection and the exact evaluated representation survive delivery."""
# Optional imports and shared pytest fixture follow the workflow test convention.
# ruff: noqa: E402, F811

import copy
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("mne_bids")

from app.preprocessing.schemas import Ref
from app.preprocessing.storage import digest, file_hash
from app.search.catalog import BASELINE_ID
from app.search.method_space import basic_space, seed_entries, edited_entry
from app.workflows import outputs
from tests.workflows.test_outputs_scaling import delivery_case  # noqa: F401
from tests.workflows.test_outputs_scaling import freeze_evidence
from tests.workflows.test_outputs_scaling import numeric_metadata


@pytest.fixture
def selection_case(tmp_path, monkeypatch):
    root = tmp_path / "search/engine"
    root.mkdir(parents=True)
    space = basic_space().model_dump(mode="json")
    (root.parent / "protocol.json").write_text(json.dumps(dict(space=space, space_hash=digest(space))), encoding="utf-8")
    (root.parent / "registry.json").write_text(json.dumps(seed_entries(space)), encoding="utf-8")
    method = {"id": BASELINE_ID}
    method_ref = {"id": digest(method), "sha256": digest(method)}
    plan = {
        "request": {"methods": [method_ref]},
        "input_snapshot": {"collection": {"selected_record_ids": ["r1"]}},
    }
    plan_ref = {"id": digest(plan), "sha256": digest(plan)}
    directory = root.parent / "candidates" / BASELINE_ID
    directory.mkdir(parents=True)
    predictions = directory / "originalpredictions.tsv"
    predictions.write_text("trial\tprediction\n1\t0\n", encoding="utf-8")
    array = root / "r1.npy"
    np.save(array, np.ones((2, 2, 3)))
    coverage = dict(
        original=2,
        eligible=2,
        available=2,
        predicted=2,
        missing=0,
        common_invalid=0,
        common_invalid_reasons={},
    )
    receipt = dict(
        evaluation_mode="subject_holdout",
        folds=[
            dict(id="fold-1", train_subjects=["S001"], development_subjects=["S002"])
        ],
        secondary_macro_ba=0.5,
        secondary_subjects={"S002": 0.5},
        representation=dict(
            version="2", unit="V", channels=["C3", "C4"],
            records={
                "r1": dict(
                    subject="S002",
                    array_path=str(array),
                    array_sha256=file_hash(array),
                    shape=[2, 2, 3],
                    unit="V",
                )
            },
        ),
        status="evaluated",
        candidate_id=BASELINE_ID,
        macro_ba=0.75,
        panel_hash="c" * 64,
        job_id="job",
        plan_ref=plan_ref,
        predictions_path=str(predictions),
        predictions_sha256=file_hash(predictions),
        subjects={
            "S002": dict(
                recalls={"left": 0.5, "right": 1.0},
                recall_left=0.5,
                recall_right=1.0,
                ba=0.75,
                delta=None,
                original_trials=2,
                eligible_trials=2,
                available_trials=2,
                predicted_trials=2,
                missing=0,
            )
        },
        coverage={
            **coverage,
            "development": coverage,
            "train": {**coverage, "predicted": 0},
        },
    )
    numeric_metadata(receipt, receipt["representation"])
    (directory / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    candidate = dict(
        id=BASELINE_ID,
        status="evaluated",
        job_id="job",
        plan_ref=plan_ref,
        receipt=receipt,
    )
    search = dict(
        id="a" * 32,
        status="stopped",
        selected_candidate_id=BASELINE_ID,
        request={"seed": 42},
        protocol={"metric": "subject_macro_balanced_accuracy"},
        panel={"panel_hash": "c" * 64},
        candidates=[candidate],
    )
    result = SimpleNamespace(
        status="completed",
        plan_ref=Ref.model_validate(plan_ref),
        records=[
            dict(
                record_id="r1",
                method_id=method_ref["id"],
                status="completed",
                result={
                    "artifacts": [
                        dict(
                            name="signal_V.npy", path="r1.npy", sha256=file_hash(array)
                        )
                    ]
                },
            )
        ],
    )

    def get(owner, ref, kind):
        assert owner == "offline-search"
        assert ref.id == (plan_ref if kind == "plan" else method_ref)["id"]
        return plan if kind == "plan" else method

    def status(owner, job):
        assert owner == "offline-search" and job == "job"
        return result

    store = SimpleNamespace(root=root, get=get, status=status)
    monkeypatch.setattr(outputs, "verify_result", lambda root, result: True)
    return SimpleNamespace(
        search=search,
        plan=plan,
        store=store,
        result=result,
        predictions=predictions,
        directory=directory,
    )


def test_measured_selection_uses_numeric_reference_and_private_owner(selection_case):
    c = selection_case
    selection = outputs.choose(c.search, c.plan, c.store)
    assert selection["selection_policy"] == "development_score"
    assert selection["quality_evaluated"] is True
    assert selection["independent_confirmation"] is False
    assert selection["score"] == 0.75
    assert selection["selected_method_ref"] == c.plan["request"]["methods"][0]
    assert selection["selected_method_ref"]["id"] != BASELINE_ID
    assert selection["candidate_summary"] == [
        {
            "candidate_id": BASELINE_ID,
            "status": "evaluated",
            "score": 0.75,
            "error": None,
        }
    ]


@pytest.mark.parametrize(
    "problem",
    [
        "running",
        "winner",
        "duplicate",
        "nan",
        "plan",
        "panel",
        "predictions",
        "receipt",
        "partial",
        "missing",
        "artifact",
    ],
)
def test_selection_rejects_unverified_or_inconsistent_results(
    selection_case, monkeypatch, problem
):
    c = selection_case
    if problem == "running":
        c.search["status"] = "running"
    elif problem == "winner":
        c.search["selected_candidate_id"] = "other"
    elif problem == "duplicate":
        c.search["candidates"].append(copy.deepcopy(c.search["candidates"][0]))
    elif problem == "nan":
        c.search["candidates"][0]["receipt"]["macro_ba"] = float("nan")
    elif problem == "plan":
        c.plan["request"]["methods"] = []
    elif problem == "panel":
        c.search["panel"]["panel_hash"] = "d" * 64
    elif problem == "predictions":
        c.predictions.write_text("changed")
    elif problem == "receipt":
        value = json.loads((c.directory / "receipt.json").read_text())
        value["job_id"] = "other"
        (c.directory / "receipt.json").write_text(json.dumps(value))
    elif problem == "partial":
        c.result.status = "partial"
    elif problem == "missing":
        c.result.records = []
    elif problem == "artifact":
        monkeypatch.setattr(outputs, "verify_result", lambda *args: False)
    with pytest.raises(ValueError):
        outputs.choose(c.search, c.plan, c.store)






@pytest.mark.parametrize(
    "problem",
    [
        "array_hash",
        "shape",
        "subject",
        "channels",
        "missing",
        "escape",
        "mixed",
        "receipt",
    ],
)
def test_shared_delivery_rejects_mismatched_physical_arrays(delivery_case, problem):
    case = delivery_case()
    selection = case.state["outputs"]["data_evaluation"]
    rep = selection["representation"]
    entry = next(iter(rep["records"].values()))
    if problem == "array_hash":
        Path(entry["array_path"]).write_bytes(b"corrupt")
    elif problem == "shape":
        entry["shape"][2] += 1
    elif problem == "subject":
        entry["subject"] = "S999"
    elif problem == "channels":
        rep["channels"].reverse()
    elif problem == "missing":
        rep["records"].pop(next(iter(rep["records"])))
    elif problem == "escape":
        entry["array_path"] = "../../escape.npy"
    elif problem == "mixed":
        rep["unit"] = "mixed"
    elif problem == "receipt":
        selection["representation"] = None
    if problem != "receipt":
        selection["selected_receipt"]["representation"] = copy.deepcopy(rep)
    with pytest.raises(ValueError):
        outputs.deliver(case.state, case.folder, case.store)
    assert not (case.folder.parent / "training-data.zip").exists()


def test_invalid_fold_membership_cannot_be_exported_as_train(delivery_case):
    case = delivery_case()
    folds = case.state["outputs"]["data_evaluation"]["panel"]["folds"]
    folds[0]["train_subjects"].extend(folds[0]["development_subjects"])
    with pytest.raises(ValueError):
        outputs.deliver(case.state, case.folder, case.store)


def test_report_describes_shared_physical_representation(
    delivery_case, monkeypatch
):
    from app.preprocessing.methods import baseline_methods
    from app.workflows.contracts import ReportData
    from app.workflows import reporting

    case = delivery_case()
    selection = case.state["outputs"]["data_evaluation"]
    stats = dict(
        subjects=3, recordings=4, trials=19, duration_s=1.0, unknown_recordings=0
    )
    method = baseline_methods()[0]
    for step in method.recipe:
        if step.op == "epoch":
            step.params.update(tmin=0.0, tmax=2.0)
    data = ReportData(
        dataset_name="<script>dataset</script>",
        dataset_version="1",
        license="fixture",
        subjects=["S001", "S002", "S003"],
        runs=[4],
        sfreq=160,
        channel_count=2,
        before=stats,
        after=stats,
        method=dict(
            ref=selection["selected_method_ref"],
            title=method.title,
            recipe=method.recipe,
        ),
        records=[],
        selection_reason=selection["reason"],
        seed=42,
        selection=selection,
        references=[],
        limitations=[],
    )
    monkeypatch.setattr(reporting, "report_data", lambda folder: data)
    folder = case.folder.parent / "projected-report"
    result = reporting.render_report(folder)
    document = (folder / "report.html").read_text(encoding="utf-8")
    assert "&lt;script&gt;dataset&lt;/script&gt;" in document
    assert "0.7500" in document and "单位：V" in document
    assert "EEG 通道" in document and "独立确认" in document
    assert "随机" not in document and "未进行质量排名" not in document
    assert result["quality_evaluated"] is True
    assert result["independent_confirmation"] is False


def test_holdout_archive_preserves_roles_and_has_no_test_set(delivery_case):
    case = delivery_case()
    panel = case.state["outputs"]["data_evaluation"]["panel"]
    panel.update(
        evaluation_mode="subject_holdout",
        train_subjects=["S001", "S003"],
        development_subjects=["S002"],
        folds=[
            dict(
                id="fold-1",
                train_subjects=["S001", "S003"],
                development_subjects=["S002"],
            )
        ],
    )
    freeze_evidence(case.store, case.state["outputs"]["data_evaluation"])
    result = outputs.deliver(case.state, case.folder, case.store)
    assert result["subject_split"] == {
        "S001": "train",
        "S002": "validation",
        "S003": "train",
    }
    assert result["split_counts"] == {"train": 15, "validation": 4, "test": 0}
