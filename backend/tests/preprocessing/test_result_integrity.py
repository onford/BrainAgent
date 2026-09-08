import json
from pathlib import Path

import numpy as np
import pytest

from app.preprocessing.inputs import read_record, validate_input
from app.preprocessing.runner import run_record, verify_result
from app.preprocessing.storage import file_hash
from app.preprocessing.worker import Worker
from .test_execution import prepare


@pytest.mark.parametrize(
    "damage",
    ["missing_metadata", "frequency", "count", "channel_order", "unit", "type"],
)
def test_sidecars_are_semantically_checked_even_with_matching_hashes(
    dataset, tmp_path, damage
):
    root = Path(dataset.collection.root)
    record = dataset.collection.records[0]
    path = root / record.bids_path
    if damage in {"missing_metadata", "frequency", "count"}:
        target = path.with_suffix(".json")
        value = json.loads(target.read_text())
        if damage == "missing_metadata":
            del value["SoftwareFilters"]
        elif damage == "frequency":
            value["SamplingFrequency"] = record.sfreq / 2
        else:
            value["EEGChannelCount"] = 500
        target.write_text(json.dumps(value), encoding="utf-8")
    else:
        target = path.parent / path.name.replace("eeg.vhdr", "channels.tsv")
        lines = target.read_text(encoding="utf-8").splitlines()
        if damage == "channel_order":
            lines[1], lines[2] = lines[2], lines[1]
        else:
            row = lines[1].split("\t")
            field = "units" if damage == "unit" else "type"
            row[lines[0].split("\t").index(field)] = (
                "seconds" if damage == "unit" else "EOG"
            )
            lines[1] = "\t".join(row)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for item in dataset.collection.records:
        item.files[target.relative_to(root).as_posix()] = file_hash(target)
    with pytest.raises(ValueError, match="sidecar|channels.tsv|EEGChannelCount"):
        validate_input(dataset, [root], tmp_path / "output")


def test_context_event_with_invalid_duration_is_rejected(dataset):
    root = Path(dataset.collection.root)
    record = dataset.collection.records[0]
    path = root / record.bids_path.replace("eeg.vhdr", "events.tsv")
    lines = path.read_text(encoding="utf-8").splitlines()
    columns, row = lines[0].split("\t"), lines[1].split("\t")
    row[columns.index("trial_type")] = "rest"
    row[columns.index("value")] = "3"
    row[columns.index("duration")] = "9999"
    lines[1] = "\t".join(row)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="outside recording"):
        read_record(root, record, dataset.survey.event_id, {"rest": 3})


def test_output_verification_cross_checks_signal_events_and_statistics(
    service, dataset
):
    prepare(service, dataset)
    result = (
        Worker(service.store, service.allowed_roots).run_once().records[0]["result"]
    )
    assert verify_result(service.store.root, result)
    original = json.loads(json.dumps(result))
    for name in ("signal_V.npy", "events.json", "delta.json"):
        entry = next(a for a in result["artifacts"] if a["name"] == name)
        path = service.store.root / entry["path"]
        saved = path.read_bytes()
        if name == "signal_V.npy":
            signal = np.load(path, allow_pickle=False)
            signal[0, 0, 0] += 0.1
            np.save(path, signal, allow_pickle=False)
        else:
            data = json.loads(saved)
            if name == "events.json":
                next(e for e in data if e["retained"])["code"] = 99
            else:
                data["events_retained"] += 1
                result["delta"] = (
                    data  # Even a self-consistent altered summary is insufficient.
                )
            path.write_text(json.dumps(data), encoding="utf-8")
        entry["sha256"] = file_hash(path)
        assert not verify_result(service.store.root, result), name
        path.write_bytes(saved)
        result = json.loads(json.dumps(original))
    result["artifacts"] = [a for a in original["artifacts"] if a["kind"] == "data"]
    assert not verify_result(service.store.root, result)


def test_failure_before_first_operation_is_recorded(service, dataset, tmp_path):
    _, _, plan = prepare(service, dataset)
    source = Path(dataset.collection.root)
    (source / dataset.collection.records[0].bids_path).write_text(
        "changed", encoding="utf-8"
    )
    output = tmp_path / "failed-attempt"
    with pytest.raises(ValueError, match="source changed"):
        run_record(plan, plan.records[0], source, output, tmp_path)
    failure = json.loads((output / "failure.json").read_text())
    assert failure["completed_steps"] == [] and "source changed" in failure["error"]
