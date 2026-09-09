# ruff: noqa: F811
import csv
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.workflows import dataset
from app.workflows.local_contracts import LocalObservation, read_local
from app.workflows.local_observation import ObservationBuilder
from app.workflows.local_reporting import observation_html
from app.workflows.planning_contracts import verification_contract
from app.workflows.schemas import WorkflowRequest
from tests.workflows.test_workflow import source  # noqa: F401
from tests.workflows.test_survey_purposes import products  # noqa: F401


def test_objects_share_configs_preserve_missing_records_and_reject_inconsistent_values(
    source, tmp_path
):  # noqa: F811
    folder = tmp_path / "survey"
    dataset.inspect(
        source, WorkflowRequest(source_root=str(source), runs=[4, 8]), folder
    )
    local = read_local(folder / "local-inspection.json")
    assert isinstance(local, LocalObservation)
    assert "facts" not in local.model_dump()
    assert len(local.recordings) == 6
    assert local.statistics.readable_records == local.statistics.failed_records == 3
    assert len(local.channel_sets) == 1
    assert (
        local.coverage["signal.header"].status == "read_error"
    )  # Fixture substitutes decoding, not raw headers.
    assert local.coverage["metadata.subjects"].status == "not_checked"
    assert local.subjects["S001"].age is None
    assert local.recordings["S001R08"].read_status == "read_error"
    from app.workflows.records import write_readable

    with pytest.raises(ValidationError):
        write_readable(folder / "local-inspection.json", {"scope": "old", "facts": []})
    html = observation_html(local)
    assert html.count('class="observation-record"') == 6
    assert "读取失败" in html and "未检查" in html
    assert "local-1" not in html
    assert "范围与覆盖" in html and "统计、差异与待办" in html
    for mutate in (
        lambda v: v.update(coverage={}),
        lambda v: v["recordings"]["S001R04"].update(channel_set_ref="missing"),
        lambda v: v["recordings"]["S001R04"].update(duration_s=3),
        lambda v: v["statistics"].update(events=999),
        lambda v: v["coverage"]["scope.inventory"].update(
            refs=["#/recordings/unknown"]
        ),
    ):
        value = deepcopy(local.model_dump())
        mutate(value)
        with pytest.raises(ValidationError):
            LocalObservation.model_validate(value)


def test_runtime_schema_rejects_cross_field_and_invented_pointers(
    source, products, tmp_path
):  # noqa: F811
    folder = tmp_path / "survey"
    dataset.inspect(source, WorkflowRequest(source_root=str(source), runs=[4]), folder)
    local = read_local(folder / "local-inspection.json")
    model = verification_contract(local)
    value = products[3].model_dump()
    for row in value["comparisons"]:
        row["local_fact_ids"] = [f.id for f in local.facts if f.field == row["field"]]
    model.model_validate(value)
    sampling = next(r for r in value["comparisons"] if r["field"] == "sampling_rate")
    for pointer in (
        "#/recordings/unknown/sampling_rate_hz",
        "#/recordings/S001R04/run_id",
    ):
        sampling["local_fact_ids"] = [pointer]
        with pytest.raises(ValidationError):
            model.model_validate(value)


def test_fractional_event_samples_and_mixed_rates_are_preserved(source, tmp_path):  # noqa: F811
    import mne
    from app.preprocessing.storage import file_hash

    builder = ObservationBuilder(source, ["S001", "S002"], [4], [], 2, 2)
    records = []
    for i, subject in enumerate(["S001", "S002"]):
        raw = mne.io.read_raw_edf(source / subject / f"{subject}R04.edf")
        if i:
            raw.resample(80)
        raw.set_annotations(mne.Annotations([0.101], [0.103], ["T1"]))
        record = dict(
            id=subject + "R04",
            subject=subject,
            run=4,
            source_path=f"{subject}/{subject}R04.edf",
            sha256=file_hash(source / subject / f"{subject}R04.edf"),
            duration_s=raw.n_times / raw.info["sfreq"],
            status="readable",
        )
        records.append(record)
        builder.add(record, raw, raw.get_data())
    local = builder.finish({"records": records}, tmp_path)
    assert local.statistics.sampling_rates == {"160.0": 1, "80.0": 1}
    with (tmp_path / "local-events.tsv").open(encoding="utf-8", newline="") as file:
        events = list(csv.DictReader(file, delimiter="\t"))
    assert float(events[0]["sample_position"]) == pytest.approx(16.16)
    assert float(events[1]["sample_position"]) == pytest.approx(8.08)
    assert events[0]["duration_s"] == "0.103"
