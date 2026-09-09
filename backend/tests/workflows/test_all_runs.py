# ruff: noqa: F811
import csv
import json

import pytest

from app.preprocessing.service import PreprocessingService
from app.workflows import dataset
from app.workflows.local_contracts import read_local
from app.workflows.schemas import WorkflowRequest
from tests.workflows.test_workflow import source  # noqa: F401


def test_discovery_uses_actual_runs_per_subject(source, tmp_path):  # noqa: F811
    for subject, runs in {"S001": [1, 2, 3, 12, 14], "S002": [8]}.items():
        for run in runs:
            (source / subject / f"{subject}R{run:02}.edf").write_bytes(b"fixture")
    survey = dataset.inspect(
        source, WorkflowRequest(source_root=str(source)), tmp_path / "survey"
    )
    assert {r["id"] for r in survey["records"]} == {
        "S001R01",
        "S001R02",
        "S001R03",
        "S001R04",
        "S001R12",
        "S001R14",
        "S002R04",
        "S002R08",
        "S003R04",
    }
    assert all(r["status"] == "readable" for r in survey["records"])
    local = read_local(tmp_path / "survey/local-inspection.json")
    assert local.scope.selected_runs == [1, 2, 3, 4, 8, 12, 14]
    assert "runs" not in WorkflowRequest.model_json_schema()["properties"]


def test_all_runs_standardized_without_mixing_training_labels(
    source, tmp_path, monkeypatch
):  # noqa: F811
    import mne

    for run in range(1, 15):
        (source / "S001" / f"S001R{run:02}.edf").write_bytes(b"fixture")
    reader = mne.io.read_raw_edf

    def read(path, **kwargs):
        raw = reader(path, **kwargs)
        if path.stem in {"S001R01", "S001R02"}:
            raw.set_annotations(mne.Annotations([0], [20], ["T0"]))
        return raw

    monkeypatch.setattr(mne.io, "read_raw_edf", read)
    request = WorkflowRequest(source_root=str(source), subjects=["S001"])
    survey = dataset.inspect(source, request, tmp_path / "survey")
    service = PreprocessingService(tmp_path / "prep", allowed_roots=[tmp_path])
    result = dataset.collect(
        survey, tmp_path / "collection", "all-runs", service, "owner"
    )
    snapshot = json.loads(
        (tmp_path / "collection/input.json").read_text(encoding="utf-8")
    )
    assert len(snapshot["collection"]["records"]) == 14
    assert snapshot["collection"]["selected_record_ids"] == [
        "S001R04",
        "S001R08",
        "S001R12",
    ]
    assert result["excluded"] == []
    assert result["statistics"]["recordings"] == 14
    with (tmp_path / "collection/event-mapping.tsv").open(
        encoding="utf-8", newline=""
    ) as stream:
        events = list(csv.DictReader(stream, delimiter="\t"))
    for event in events:
        training = int(event["object_key"][-2:]) in {4, 8, 12}
        if not training:
            assert event["target_label"] == event["source_label"]
            assert event["training_selected"] == "False"
    assert len(list((tmp_path / "collection/bids").rglob("*.vhdr"))) == 14


def test_missing_explicit_subject_is_reported(source, tmp_path):  # noqa: F811
    with pytest.raises(ValueError, match="没有找到被试"):
        dataset.inspect(
            source,
            WorkflowRequest(source_root=str(source), subjects=["S099"]),
            tmp_path / "survey",
        )


@pytest.mark.asyncio
async def test_all_runs_flow_keeps_context_and_trains_only_target(source, tmp_path):  # noqa: F811
    from app.agents import build_agent_registry
    from tests.workflows.fakes import workflow_service
    from tests.workflows.test_workflow import finish, OWNER

    for subject in ("S001", "S002", "S003"):
        for run in (1, 3, 8, 12, 14):
            (source / subject / f"{subject}R{run:02}.edf").write_bytes(b"fixture")
    prep = PreprocessingService(tmp_path / "prep")
    service = workflow_service(tmp_path / "workflows", [source], prep)
    service.registry = build_agent_registry(preprocessing=prep, workflow=service)
    state = service.create(OWNER, WorkflowRequest(source_root=str(source)))
    result = await finish(service, state["id"])
    assert result["status"] == "completed", result["error"]
    assert len(result["outputs"]["data_survey"]["records"]) == 18
    assert result["outputs"]["data_collection"]["statistics"]["recordings"] == 18
    outcomes = result["outputs"]["data_preprocessing"]["records"]
    assert len({r["record_id"] for r in outcomes}) == 9
    assert all(int(r["record_id"][-2:]) in {4, 8, 12} for r in outcomes)
