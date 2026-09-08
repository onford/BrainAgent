import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.preprocessing.inputs import read_record
from app.preprocessing.schemas import PreprocessInput
from app.preprocessing.service import PreprocessingService
from app.workflows import dataset
from app.workflows.cognition_contracts import CollectionReview
from app.workflows.collection_contracts import (
    CATEGORIES,
    IntakeAudit,
    ReportedExclusion,
)
from app.workflows.intake import literature_matches
from app.workflows.schemas import WorkflowRequest
from tests.workflows.test_workflow import source as source_fixture

source = source_fixture


def test_file_changing_during_scan_invalidates_the_observations(
    source, tmp_path, monkeypatch
):
    import mne

    original = mne.io.read_raw_edf

    def read(path, **kwargs):
        raw = original(path, **kwargs)
        Path(path).write_bytes(b"changed during read")
        return raw

    monkeypatch.setattr(mne.io, "read_raw_edf", read)
    with pytest.raises(dataset.SourceChangedError, match="读取期间"):
        dataset.inspect(
            source,
            WorkflowRequest(source_root=str(source), runs=[4]),
            tmp_path / "survey",
        )


def load(folder, name):
    return json.loads((folder / name).read_text(encoding="utf-8"))


def collect(source, tmp_path):
    request = WorkflowRequest(
        source_root=str(source), subjects=["S001", "S002", "S003"], runs=[4]
    )
    survey = dataset.inspect(source, request, tmp_path / "survey")
    service = PreprocessingService(tmp_path / "prep", allowed_roots=[tmp_path])
    result = dataset.collect(survey, tmp_path / "collection", "test", service, "owner")
    return result, tmp_path / "collection"


def test_complete_events_are_preserved_but_context_is_not_training(
    source, tmp_path, monkeypatch
):
    import mne_bids

    writer = mne_bids.write_raw_bids

    def write(*args, **kwargs):
        audit = load(tmp_path / "collection", "audit.json")
        # All records have been inspected before the first standardized file is created.
        assert {
            c["object_key"]
            for c in audit["checks"]
            if c["check_category"] == "format_readability"
        } == {"S001R04", "S002R04", "S003R04"}
        assert (tmp_path / "collection/pre-screen.json").exists()
        return writer(*args, **kwargs)

    monkeypatch.setattr(mne_bids, "write_raw_bids", write)
    result, folder = collect(source, tmp_path)
    data = PreprocessInput.model_validate(load(folder, "input.json"))
    raw, events, mapping = read_record(
        Path(data.collection.root),
        data.collection.records[0],
        data.survey.event_id,
        data.survey.context_event_id,
    )
    assert len(raw.annotations) == 5 and len(events) == 4
    assert {x[2] for x in events} == {1, 2}
    assert {x["label"] for x in mapping} == {"left_hand", "right_hand"}
    audit = IntakeAudit.model_validate(load(folder, "audit.json"))
    assert {c.check_category for c in audit.checks} == set(CATEGORIES)
    standard = load(folder, "standardization.json")
    assert (
        standard["source_events"],
        standard["standardized_events"],
        standard["training_events"],
    ) == (15, 15, 12)
    assert standard["official_validator"] == "not_run"
    assert result["statistics"]["behavior_records"] is None
    assert result["statistics"]["channel_observations"] == 192
    integrity = load(folder, "source-integrity.json")
    assert (
        integrity["unchanged"]
        and integrity["checked_after"]
        and len(integrity["files"]) == 3
    )


def test_nonfinite_record_is_excluded_with_specific_category_and_delta(
    source, tmp_path, monkeypatch
):
    import mne

    original = mne.io.read_raw_edf

    def read(path, **kwargs):
        raw = original(path, **kwargs)
        if Path(path).parent.name == "S002":
            raw._data[0, 10] = float("nan")
        return raw

    monkeypatch.setattr(mne.io, "read_raw_edf", read)
    result, folder = collect(source, tmp_path)
    assert result["statistics"]["subjects"] == 2
    assert result["excluded"][0]["object_key"] == "S002R04"
    audit = load(folder, "audit.json")
    assert any(
        c["check_category"] == "dimensions_units_values" and c["action"] == "排除"
        for c in audit["checks"]
    )
    with (folder / "delta.tsv").open(encoding="utf-8", newline="") as stream:
        delta = {r["metric"]: r for r in csv.DictReader(stream, delimiter="\t")}
    assert float(delta["trials"]["change"]) == -4
    assert "S002R04" in delta["trials"]["reason"]
    assert delta["sessions"]["before"] == "" and delta["sessions"]["change"] == ""


def test_no_readable_record_keeps_audit_and_unknown_counts_without_bids(
    source, tmp_path
):
    request = WorkflowRequest(source_root=str(source), subjects=["S099"], runs=[4])
    survey = dataset.inspect(source, request, tmp_path / "survey")
    with pytest.raises(ValueError, match="没有通过"):
        dataset.collect(
            survey, tmp_path / "collection", "test", SimpleNamespace(), "owner"
        )
    folder = tmp_path / "collection"
    assert not (folder / "bids").exists()
    assert load(folder, "pre-screen.json")["trials"] is None
    assert load(folder, "post-screen.json")["trials"] == 0
    IntakeAudit.model_validate(load(folder, "audit.json"))


def test_reported_subject_exclusions_are_matched_without_automatic_deletion():
    review = CollectionReview(
        compatible=True,
        rationale="matched",
        supporting_facts=["f1"],
        conflicts=[],
        limitations=[],
        literature_exclusions=[
            ReportedExclusion(
                entry_id="paper",
                object_type="subject",
                reported_ids=ids,
                finding_ids=["f1"],
                reason="reported anomaly",
            )
            for ids in (["1"], ["S088"], ["unknown"])
        ],
    )
    result = literature_matches(
        review, {"records": [{"id": "S001R04", "subject": "S001"}]}
    )
    assert [r.match_status for r in result.records] == [
        "selected",
        "outside_selection",
        "unresolved",
    ]
    assert result.records[0].local_objects == ["S001R04"]
    assert result.records[0].action == "保留标记"
