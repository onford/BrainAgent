from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any, Iterator

from .schemas import (
    NeuroDatasetSnapshot,
    SignalCollection,
    SourceFingerprint,
    TimebaseSnapshot,
)


def _h5py():
    try:
        import h5py
    except ImportError as exc:  # pragma: no cover - exercised by deployment checks
        raise ImportError("NWB inspection requires the 'invasive' extra (h5py)") from exc
    return h5py


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if hasattr(value, "item"):
        try:
            value = value.item()
        except ValueError:
            pass
    return str(value)


def _attr_text(obj, name: str) -> str | None:
    value = obj.attrs.get(name)
    return None if value is None else _text(value)


def _identifier(path: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", path.strip("/")) or "root"


def _objects(root) -> Iterator[tuple[str, Any]]:
    """Walk hard links only; an NWB cannot escape its containing file by link."""
    h5py = _h5py()
    seen: set[int] = set()

    def walk(group, prefix: str):
        for name in group:
            link = group.get(name, getlink=True)
            if not isinstance(link, h5py.HardLink):
                continue
            obj = group.get(name)
            if obj is None:
                continue
            path = f"{prefix}/{name}"
            yield path, obj
            if isinstance(obj, h5py.Group):
                address = int(h5py.h5o.get_info(obj.id).addr)
                if address not in seen:
                    seen.add(address)
                    yield from walk(obj, path)

    yield from walk(root, "")


@dataclass
class _Budget:
    maximum: int
    used: int = 0

    def scalar(self, dataset, index=()):
        if self.used >= self.maximum:
            return None
        self.used += 1
        return dataset[index]


def _dataset_text(root, path: str, budget: _Budget) -> str | None:
    obj = root.get(path)
    if obj is None or not hasattr(obj, "shape") or obj.shape not in ((), (1,)):
        return None
    value = budget.scalar(obj, () if obj.shape == () else 0)
    return None if value is None else _text(value)


def _timebase(group, path: str, data, budget: _Budget) -> TimebaseSnapshot | None:
    timestamps = group.get("timestamps")
    if timestamps is not None and len(timestamps.shape) == 1:
        count = int(timestamps.shape[0])
        start = _text(budget.scalar(timestamps, 0)) if count else None
        stop = _text(budget.scalar(timestamps, count - 1)) if count else None
        return TimebaseSnapshot(
            id=_identifier(path + "/time"),
            kind="timestamps",
            count=count,
            timestamps_path=path + "/timestamps",
            observed_start=float(start) if start is not None else None,
            observed_stop=float(stop) if stop is not None else None,
        )
    starting = group.get("starting_time")
    rate = None
    initial = None
    if starting is not None:
        rate_value = starting.attrs.get("rate")
        if rate_value is not None:
            rate = float(rate_value)
        value = budget.scalar(starting)
        if value is not None:
            initial = float(value)
    if rate and data.shape:
        return TimebaseSnapshot(
            id=_identifier(path + "/time"),
            kind="rate",
            count=int(data.shape[0]),
            starting_time=initial,
            rate_hz=rate,
            observed_start=initial,
            observed_stop=None if initial is None or not data.shape[0] else initial + (data.shape[0] - 1) / rate,
        )
    return None


def _series_kind(path: str, group) -> tuple[str, str, str]:
    lowered = path.lower()
    neurodata_type = (_attr_text(group, "neurodata_type") or "").lower()
    if "eval_mask" in lowered or "evaluation_mask" in lowered:
        return "behavior", "mask", "sample"
    if "emg" in lowered:
        return "behavior", "behavior", "sample"
    if "threshold" in lowered and any(token in lowered for token in ("cross", "event", "spike")):
        return "ecephys", "threshold_crossings", "threshold_channel"
    if "electricalseries" in neurodata_type or "electrical" in lowered:
        if "lfp" in lowered:
            return "ecephys", "lfp", "electrode"
        return "ecephys", "raw_voltage", "electrode"
    if path.startswith("/stimulus/") or "stimulus" in lowered:
        return "stimulus", "stimulus", "sample"
    if "behavior" in lowered or any(token in lowered for token in ("position", "running", "pupil", "velocity")):
        return "behavior", "behavior", "sample"
    if "twophoton" in neurodata_type or "roiresponseseries" in neurodata_type or "fluorescence" in lowered:
        return "ophys", "unknown", "roi"
    return "unknown", "unknown", "sample"


def inspect_nwb(path: Path, *, hash_source: bool = False, max_scalar_reads: int = 4096) -> NeuroDatasetSnapshot:
    h5py = _h5py()
    path = path.resolve(strict=True)
    if not path.is_file() or path.suffix.lower() != ".nwb":
        raise ValueError("source must be an existing .nwb file")
    stat = path.stat()
    source_hash = None
    if hash_source:
        with path.open("rb") as stream:
            source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    budget = _Budget(max_scalar_reads)
    collections: list[SignalCollection] = []
    timebases: list[TimebaseSnapshot] = []
    warnings: list[str] = [
        "Bounded structural inspection is not a full PyNWB schema validation."
    ]
    processing_history: list[str] = []
    with h5py.File(path, "r", swmr=True) as root:
        nwb_version = _attr_text(root, "nwb_version")
        if not nwb_version:
            raise ValueError("HDF5 file does not declare an NWB version")
        dataset_id = _dataset_text(root, "identifier", budget) or path.stem
        session_id = _dataset_text(root, "session_id", budget) or dataset_id
        subject_id = _dataset_text(root, "general/subject/subject_id", budget)
        descriptors = [
            dataset_id,
            session_id,
            _dataset_text(root, "session_description", budget) or "",
        ]
        devices = root.get("general/devices")
        if devices is not None:
            for name in devices:
                device = devices.get(name)
                descriptors.extend([name, _attr_text(device, "description") or ""])
        processing = root.get("processing")
        if processing is not None:
            processing_history = sorted(processing.keys())
        descriptor_text = " ".join(descriptors).lower()
        falcon_profile = "/falcon/" in path.as_posix().lower() or (
            root.get("acquisition/preprocessed_emg") is not None
            and "neuropixel" not in descriptor_text
        )

        electrodes = root.get("general/extracellular_ephys/electrodes")
        if electrodes is not None and electrodes.get("id") is not None:
            electrode_ids = electrodes["id"]
            collections.append(
                SignalCollection(
                    id="electrodes",
                    path="/general/extracellular_ephys/electrodes",
                    modality="ecephys",
                    representation="unknown",
                    entity_axis="electrode",
                    entity_ids_path="/general/extracellular_ephys/electrodes/id",
                    shape=[int(electrode_ids.shape[0])],
                    dtype="table",
                    upstream_processed=False,
                    metadata={"columns": sorted(electrodes.keys())},
                )
            )

        units = root.get("units")
        if units is not None and units.get("spike_times") is not None:
            spikes = units["spike_times"]
            ids = units.get("id")
            unit_count = int(ids.shape[0]) if ids is not None else int(units["spike_times_index"].shape[0])
            timebase = TimebaseSnapshot(
                id="units_spike_times",
                kind="event",
                count=int(spikes.shape[0]),
                timestamps_path="/units/spike_times",
            )
            timebases.append(timebase)
            metadata = {
                "unit_count": unit_count,
                "columns": sorted(name for name in units.keys() if name not in {"spike_times", "spike_times_index", "id"}),
            }
            collections.append(
                SignalCollection(
                    id="units",
                    path="/units/spike_times",
                    modality="ecephys",
                    representation="threshold_crossings" if falcon_profile else "spike_times",
                    entity_axis="unit",
                    entity_ids_path="/units/id" if ids is not None else None,
                    shape=[int(spikes.shape[0]), unit_count],
                    dtype=str(spikes.dtype),
                    physical_units="seconds",
                    timebase_id=timebase.id,
                    chunks=list(spikes.chunks) if spikes.chunks else None,
                    compression=str(spikes.compression) if spikes.compression else None,
                    upstream_processed=True,
                    metadata={
                        **metadata,
                        "event_semantics": "multiunit_threshold_crossings" if falcon_profile else "sorted_unit_spikes",
                        "dataset_profile": "falcon-m1" if falcon_profile else None,
                    },
                )
            )

        trials = root.get("intervals/trials")
        if trials is not None and trials.get("start_time") is not None:
            starts = trials["start_time"]
            count = int(starts.shape[0])
            timebase = TimebaseSnapshot(id="trials", kind="interval", count=count, timestamps_path="/intervals/trials/start_time")
            timebases.append(timebase)
            collections.append(
                SignalCollection(
                    id="trials",
                    path="/intervals/trials",
                    modality="intervals",
                    representation="trials",
                    entity_axis="trial",
                    shape=[count],
                    dtype="table",
                    timebase_id=timebase.id,
                    upstream_processed=True,
                    metadata={"columns": sorted(trials.keys())},
                )
            )

        for object_path, obj in _objects(root):
            if not isinstance(obj, h5py.Group) or obj.get("data") is None:
                continue
            if object_path.startswith("/units"):
                continue
            data = obj.get("data")
            if not isinstance(data, h5py.Dataset):
                continue
            modality, representation, entity_axis = _series_kind(object_path, obj)
            if modality == "unknown" and "neurodata_type" not in obj.attrs:
                continue
            timebase = _timebase(obj, object_path, data, budget)
            if timebase:
                if timebase.id not in {item.id for item in timebases}:
                    timebases.append(timebase)
            unit = _attr_text(data, "unit") or _attr_text(obj, "unit")
            collections.append(
                SignalCollection(
                    id=_identifier(object_path),
                    path=object_path + "/data",
                    modality=modality,
                    representation=representation,
                    entity_axis=entity_axis,
                    shape=[int(value) for value in data.shape],
                    dtype=str(data.dtype),
                    physical_units=unit,
                    timebase_id=timebase.id if timebase else None,
                    chunks=list(data.chunks) if data.chunks else None,
                    compression=str(data.compression) if data.compression else None,
                    upstream_processed=object_path.startswith("/processing/") or "preprocessed" in object_path.lower(),
                    metadata={"neurodata_type": _attr_text(obj, "neurodata_type")},
                )
            )

        if not collections:
            warnings.append("No supported Units, trials, or TimeSeries collections were found")
        descriptor = descriptor_text
        signal_modalities = {item.modality for item in collections}
        if falcon_profile:
            modality = "intracortical_array"
        elif "neuropixel" in descriptor:
            modality = "neuropixels"
        elif any(token in descriptor for token in ("utah", "intracortical", "microelectrode array", "mea")):
            modality = "intracortical_array"
        elif "ophys" in signal_modalities and "ecephys" in signal_modalities:
            modality = "mixed"
        elif "ophys" in signal_modalities:
            modality = "ophys"
        elif "ecephys" in signal_modalities:
            modality = "extracellular_ephys"
        else:
            modality = "unknown"

    return NeuroDatasetSnapshot(
        dataset_id=dataset_id,
        session_id=session_id,
        subject_id=subject_id,
        standard_version=nwb_version,
        source=SourceFingerprint(
            path=str(path),
            size_bytes=stat.st_size,
            modified_ns=stat.st_mtime_ns,
            sha256=source_hash,
        ),
        modality=modality,
        collections=collections,
        timebases=timebases,
        processing_history=processing_history,
        warnings=warnings,
        inspected_values=budget.used,
    )
