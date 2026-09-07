"""Read-only Collection contract checks and the bounded BrainVision BIDS reader."""

import csv
import json
from pathlib import Path
import re

from .schemas import PreprocessInput, RecordSpec
from .storage import file_hash, within


def validate_input(
    data: PreprocessInput, allowed_roots: list[Path], output_root: Path, *, hashes=True
):
    root = Path(data.collection.root).resolve(strict=True)
    if not any(root.is_relative_to(p.resolve()) for p in allowed_roots):
        raise ValueError("dataset root is not in PREPROCESSING_INPUT_ROOTS")
    if root.is_relative_to(output_root) or output_root.is_relative_to(root):
        raise ValueError("input and output roots must be disjoint")
    inventory = {}
    for record in data.collection.records:
        for relative, expected in record.files.items():
            path = within(root, relative)
            if not re.fullmatch(r"[a-f0-9]{64}", expected):
                raise ValueError("invalid Collection checksum")
            if relative in inventory and inventory[relative] != expected:
                raise ValueError("conflicting Collection checksums")
            inventory[relative] = expected
            if not path.is_file():
                raise ValueError("Collection file is missing")
        path = within(root, record.bids_path)
        if (
            path.suffix != ".vhdr"
            or path.parent.name != "eeg"
            or not path.name.endswith("_eeg.vhdr")
        ):
            raise ValueError("first release accepts BIDS EEG BrainVision groups")
        prefix = record.bids_path[: -len("eeg.vhdr")]
        required = {
            record.bids_path,
            prefix + "eeg.eeg",
            prefix + "eeg.vmrk",
            prefix + "eeg.json",
            prefix + "channels.tsv",
            prefix + "events.tsv",
            "dataset_description.json",
        }
        if not required <= set(record.files):
            raise ValueError(
                "incomplete BrainVision file group or required BIDS sidecars"
            )
        for header in [path, path.with_suffix(".vmrk")]:
            content = header.read_text(encoding="utf-8-sig")
            for key, value in re.findall(
                r"^(DataFile|MarkerFile)=(.+)$", content, re.MULTILINE
            ):
                expected_name = path.with_suffix(
                    ".eeg" if key == "DataFile" else ".vmrk"
                ).name
                if value.strip() != expected_name:
                    raise ValueError(
                        "BrainVision references must stay in the frozen file group"
                    )
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError(
                "linked dataset entries require a materialized Collection copy"
            )
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            actual.add(relative)
            if hashes and (
                relative not in inventory or file_hash(path) != inventory[relative]
            ):
                raise ValueError(f"input inventory/checksum changed: {relative}")
    if actual != set(inventory):
        raise ValueError(
            "Collection inventory must cover the complete standardized input tree"
        )
    description = json.loads(
        (root / "dataset_description.json").read_text(encoding="utf-8")
    )
    if (
        not description.get("Name")
        or description.get("BIDSVersion") != data.collection.standard_version
        or description.get("DatasetType", "raw") != "raw"
    ):
        raise ValueError("BIDS root metadata differs from Collection")
    return root


def read_record(root: Path, record: RecordSpec, event_id: dict):
    import numpy as np
    from mne_bids import get_bids_path_from_fname, read_raw_bids

    path = within(root, record.bids_path)
    bids_path = get_bids_path_from_fname(path).update(root=root)
    raw = read_raw_bids(bids_path, extra_params={"preload": True}, verbose="ERROR")
    if raw.n_times != record.samples or raw.info["sfreq"] != record.sfreq:
        raise ValueError("sample count/rate differs from Collection")
    if (
        record.channel_order != raw.ch_names
        or [record.channels[n] for n in record.channel_order] != raw.get_channel_types()
    ):
        raise ValueError("channel identity/order/type differs from Collection")
    if not np.isfinite(raw.get_data()).all() or raw.info["projs"]:
        raise ValueError(
            "enabled operations require finite input and resolved projections"
        )
    for name in raw.ch_names:
        if record.channels[name] in {
            "eeg",
            "eog",
            "ecg",
            "emg",
        } and raw._orig_units.get(name) not in {"V", "mV", "µV", "uV", "nV"}:
            raise ValueError("source voltage unit is not recognized")
    eeg_meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    if eeg_meta.get("EEGReference") != record.reference:
        raise ValueError("reference differs from Collection")
    rows = list(
        csv.DictReader(
            (path.parent / path.name.replace("eeg.vhdr", "events.tsv")).open(
                encoding="utf-8-sig", newline=""
            ),
            delimiter="\t",
        )
    )
    events, mapping = [], []
    for i, row in enumerate(rows):
        label = row.get("trial_type")
        if label not in event_id:
            raise ValueError(f"Survey does not define event meaning: {label}")
        onset = float(row["onset"])
        duration = float(row["duration"])
        sample = int(round(onset * record.sfreq))
        if (
            not np.isfinite([onset, duration]).all()
            or duration < 0
            or sample < 0
            or sample >= record.samples
        ):
            raise ValueError("event outside recording")
        if row.get("sample", "n/a") != "n/a" and abs(float(row["sample"]) - sample) > 0:
            raise ValueError("events.tsv sample/onset mismatch")
        if row.get("value", "n/a") != "n/a" and float(row["value"]) != event_id[label]:
            raise ValueError("events.tsv code differs from Survey")
        events.append([sample + raw.first_samp, 0, event_id[label]])
        mapping.append(
            {
                "event_id": f"{record.id}:event:{i}",
                "trial_id": row.get("trial_id") or f"{record.id}:event:{i}",
                "source_row": i + 2,
                "original_sample": sample + raw.first_samp,
                "original_onset_s": onset,
                "duration_s": duration,
                "code": event_id[label],
                "label": label,
                "quantization_error_s": sample / record.sfreq - onset,
            }
        )
    event_array = np.asarray(events, dtype=int).reshape(-1, 3)
    if len(events) > 1 and np.any(np.diff(event_array[:, 0]) <= 0):
        raise ValueError("events must have unique increasing samples")
    return raw, event_array, mapping
