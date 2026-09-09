"""Typed local observations. Source facts and research judgements remain separate."""

import json
from collections import Counter
from math import isclose
from typing import Annotated, Literal, get_args

from pydantic import Field, model_validator
from app.preprocessing.schemas import Contract

CoverageKey = Literal[
    "scope.inventory",
    "organization.records",
    "organization.entities",
    "organization.bids",
    "signal.header",
    "signal.arrays",
    "signal.channels",
    "signal.acquisition",
    "signal.coordinates",
    "events.timeline",
    "events.bounds",
    "events.sidecars",
    "events.protocol",
    "metadata.subjects",
    "metadata.dataset",
    "metadata.behavior",
    "statistics.aggregate",
]


class ObservationScope(Contract):
    source_root: str
    inventory_path: Literal["source-inventory.tsv"] = "source-inventory.tsv"
    discovered_files: int = Field(ge=0)
    discovered_subjects: int = Field(ge=0)
    discovered_recordings: int = Field(ge=0)
    selected_subjects: list[str]
    selected_runs: list[int]
    selection_basis: str


class DecodedSignal(Contract):
    axes: tuple[Literal["channel"], Literal["sample"]] = ("channel", "sample")
    shape: tuple[Annotated[int, Field(gt=0)], Annotated[int, Field(gt=0)]]
    dtype: str
    unit: Literal["V"] = "V"
    nonfinite_count: int = Field(ge=0)


class EDFSignalHeader(Contract):
    label: str
    transducer: str
    physical_dimension: str
    physical_min: float
    physical_max: float
    digital_min: int
    digital_max: int
    prefilter: str
    samples_per_record: int = Field(gt=0)


class EDFHeader(Contract):
    format: Literal["EDF", "EDF+C", "EDF+D"]
    header_bytes: int
    data_records: int
    record_duration_s: float = Field(gt=0)
    signals: list[EDFSignalHeader]
    recording_identification: str
    patient_identification: str
    start_date: str
    start_time: str


class EventTable(Contract):
    path: Literal["local-events.tsv"] = "local-events.tsv"
    record_key: str
    counts: dict[str, Annotated[int, Field(ge=0)]]
    time_origin: Literal["recording_start"] = "recording_start"


class ObservationRecord(Contract):
    subject_id: str
    session_id: str | None = None
    run_id: int
    task_id: str | None = None
    condition_id: str | None = None
    acquisition_id: str | None = None
    identity_basis: Literal["adapter_filename"] = "adapter_filename"
    source_file: str
    sha256: str | None = Field(pattern=r"^[a-f0-9]{64}$")
    read_status: Literal["readable", "read_error"]
    error: str | None = None
    storage: EDFHeader | None = None
    storage_error: str | None = None
    form: Literal["continuous", "discontinuous"] | None = None
    decoded_signal: DecodedSignal | None = None
    sampling_rate_hz: float | None = Field(default=None, gt=0)
    duration_s: float | None = Field(default=None, gt=0)
    channel_set_ref: str | None = None
    acquisition_set_ref: str | None = None
    events: EventTable | None = None


class AcquisitionSet(Contract):
    transducers: list[str]
    prefilters: list[str]
    device: str | None = None
    reference: str | None = None
    ground: str | None = None
    electrode_medium: str | None = None
    line_frequency_hz: float | None = None


class SubjectMetadata(Contract):
    age: float | None = None
    sex: str | None = None
    health: str | None = None
    handedness: str | None = None
    group: str | None = None


class DatasetMetadata(Contract):
    name: str | None = None
    version: str | None = None
    license: str | None = None


class CoverageItem(Contract):
    group: Literal[
        "scope", "organization", "signal", "events", "metadata", "statistics"
    ]
    label: str
    status: Literal[
        "observed",
        "partial",
        "not_checked",
        "not_found",
        "read_error",
        "not_applicable",
    ]
    checked: int = Field(ge=0)
    total: int = Field(ge=0)
    reason: str
    refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def bounds(self):
        if self.checked > self.total:
            raise ValueError("coverage checked exceeds total")
        return self


class ObservationStatistics(Contract):
    selected_records: int
    readable_records: int
    failed_records: int
    duration_s: float
    events: int
    sampling_rates: dict[str, int]
    channel_counts: dict[str, int]


class ObservationProvenance(Contract):
    inspector: str
    inspected_at: str
    mne_version: str
    field_sources: dict[str, str]


class LocalObservation(Contract):
    schema_version: Literal["2"] = "2"
    scope: ObservationScope
    dataset_metadata: DatasetMetadata = Field(default_factory=DatasetMetadata)
    subjects: dict[str, SubjectMetadata]
    recordings: dict[str, ObservationRecord]
    channel_sets: dict[str, list[str]]
    acquisition_sets: dict[str, AcquisitionSet]
    statistics: ObservationStatistics
    coverage: dict[CoverageKey, CoverageItem]
    provenance: ObservationProvenance

    @model_validator(mode="after")
    def references(self):
        if set(self.coverage) != set(get_args(CoverageKey)):
            raise ValueError(
                "all fixed coverage checks must be present, including unperformed checks"
            )
        for key, record in self.recordings.items():
            if not key or any(c in key for c in "/~"):
                raise ValueError(
                    "record keys must be stable unescaped object identifiers"
                )
            if record.subject_id not in self.subjects:
                raise ValueError("unknown subject")
            if record.read_status == "read_error" and not record.error:
                raise ValueError("failed observations require a reason")
            if record.read_status == "readable":
                if not all(
                    [
                        record.decoded_signal,
                        record.events,
                        record.sampling_rate_hz,
                        record.duration_s,
                        record.sha256,
                    ]
                ):
                    raise ValueError(
                        "readable records require measured signal, events and input hash"
                    )
                if (
                    record.channel_set_ref not in self.channel_sets
                    or record.acquisition_set_ref not in self.acquisition_sets
                ):
                    raise ValueError("unknown shared configuration")
                if record.events.record_key != key or record.decoded_signal.shape[
                    0
                ] != len(self.channel_sets[record.channel_set_ref]):
                    raise ValueError("record dimensions or event reference mismatch")
                if (
                    abs(
                        record.duration_s
                        - record.decoded_signal.shape[1] / record.sampling_rate_hz
                    )
                    > 1e-8
                ):
                    raise ValueError(
                        "duration must match observed samples and sampling rate"
                    )
        readable = [r for r in self.recordings.values() if r.read_status == "readable"]
        s = self.statistics
        if (
            s.selected_records != len(self.recordings)
            or s.readable_records != len(readable)
            or s.failed_records != len(self.recordings) - len(readable)
            or s.events != sum(sum(r.events.counts.values()) for r in readable)
            or not isclose(
                s.duration_s, sum(r.duration_s for r in readable), abs_tol=1e-8
            )
            or s.sampling_rates
            != dict(Counter(str(r.sampling_rate_hz) for r in readable))
            or s.channel_counts
            != dict(Counter(str(r.decoded_signal.shape[0]) for r in readable))
        ):
            raise ValueError(
                "statistics must be derived from readable observation records"
            )
        data = self.model_dump()
        for item in self.coverage.values():
            for ref in item.refs:
                pointer_value(data, ref)
        return self

    @property
    def scope_text(self):
        s = self.scope
        return f"目录扫描：{s.discovered_files} 个文件；选择 {len(self.recordings)} 条记录，成功读取 {self.statistics.readable_records} 条。未选择记录未进行信号检查。"

    @property
    def facts(self):
        # Compatibility view for existing comparison/rendering interfaces only.
        # Never stored or sent as the authoritative observation representation.
        from .survey_contracts import LocalFact

        result = []

        def add(field, pointer, value, scope):
            result.append(
                LocalFact(
                    id=pointer,
                    field=field,
                    scope=scope,
                    value=json.dumps(value, ensure_ascii=False),
                    locator=pointer,
                )
            )

        add("directory_structure", "#/scope", self.scope.model_dump(), "目录与范围")
        add(
            "subjects",
            "#/scope/selected_subjects",
            self.scope.selected_subjects,
            "所选被试编号",
        )
        for key, r in self.recordings.items():
            root = f"#/recordings/{key}"
            if r.read_status != "readable":
                continue
            for field, path, value in [
                (
                    "file_format",
                    "storage/format",
                    r.storage.format if r.storage else None,
                ),
                (
                    "file_header",
                    "storage",
                    r.storage.model_dump() if r.storage else None,
                ),
                ("signal_arrays", "decoded_signal", r.decoded_signal.model_dump()),
                ("channels", "channel_set_ref", r.channel_set_ref),
                ("sampling_rate", "sampling_rate_hz", r.sampling_rate_hz),
                ("events", "events", r.events.model_dump()),
                ("task_runs", "run_id", r.run_id),
                ("recording_duration", "duration_s", r.duration_s),
                ("acquisition", "acquisition_set_ref", r.acquisition_set_ref),
            ]:
                if value is not None:
                    add(field, root + "/" + path, value, key)
        return result


class LocalEvent(Contract):
    record_id: str
    event_index: int = Field(ge=0)
    label: str
    onset_s: float
    duration_s: float = Field(ge=0)
    sample_position: float


def pointer_value(data, pointer):
    if not pointer.startswith("#/"):
        raise ValueError("observation reference must be a JSON Pointer")
    try:
        for part in pointer[2:].split("/"):
            key = part.replace("~1", "/").replace("~0", "~")
            data = data[int(key)] if isinstance(data, list) else data[key]
        return data
    except (KeyError, ValueError, IndexError, TypeError) as exc:
        raise ValueError(f"unknown observation reference: {pointer}") from exc


def read_local(path):
    from .survey_contracts import LocalInspection

    data = json.loads(path.read_text(encoding="utf-8"))
    return (
        LocalObservation if data.get("schema_version") == "2" else LocalInspection
    ).model_validate(data)
