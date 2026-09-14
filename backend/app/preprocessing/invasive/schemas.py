from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field, model_validator

from app.preprocessing.schemas import Contract, Ref


Representation = Literal[
    "raw_voltage",
    "lfp",
    "spike_times",
    "threshold_crossings",
    "behavior",
    "stimulus",
    "mask",
    "trials",
    "unknown",
]


_NOT_PROVIDED = {"", "not_provided", "not provided", "none", "null", "default"}
_TASK_TEXT_KEYS = (
    "description",
    "objective",
    "goal",
    "task",
    "purpose",
    "output",
    "validation",
    "analysis",
)


def _optional_inputs(value: Any, optional_fields: set[str]) -> Any:
    """Treat model/tool omission sentinels exactly like omitted optional fields."""
    if not isinstance(value, dict):
        return value
    normalized = dict(value)
    for key in optional_fields:
        item = normalized.get(key)
        if item is None or isinstance(item, str) and item.strip().casefold() in _NOT_PROVIDED:
            normalized.pop(key, None)
    return normalized


def _task_text(value: Any, *, depth: int = 0) -> Any:
    """Normalize common LLM task envelopes without inventing task semantics."""

    if isinstance(value, str):
        return value.strip()
    if depth > 2:
        return value
    candidates: list[Any] = []
    if isinstance(value, dict):
        candidates = [value[key] for key in _TASK_TEXT_KEYS if key in value]
        if not candidates:
            candidates = list(value.values())
    elif isinstance(value, (list, tuple)):
        candidates = list(value)
    else:
        return value
    parts: list[str] = []
    for candidate in candidates:
        normalized = _task_text(candidate, depth=depth + 1)
        if isinstance(normalized, str) and normalized and normalized not in parts:
            parts.append(normalized)
    return "; ".join(parts) if parts else value


def _duration_seconds(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    match = re.fullmatch(
        r"\s*(\d+(?:\.\d+)?)\s*(ms|millisecond(?:s)?|s|sec(?:ond)?s?)\s*",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return value
    amount = float(match.group(1))
    return amount / 1000 if match.group(2).lower().startswith("m") else amount


class SourceFingerprint(Contract):
    path: str
    size_bytes: int = Field(ge=0)
    modified_ns: int = Field(ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class TimebaseSnapshot(Contract):
    id: str
    kind: Literal["timestamps", "rate", "interval", "event"]
    count: int = Field(ge=0)
    starting_time: float | None = None
    rate_hz: float | None = Field(default=None, gt=0)
    timestamps_path: str | None = None
    observed_start: float | None = None
    observed_stop: float | None = None


class SignalCollection(Contract):
    id: str
    path: str
    modality: Literal["ecephys", "ophys", "behavior", "stimulus", "intervals", "unknown"]
    representation: Representation
    entity_axis: Literal["electrode", "unit", "threshold_channel", "roi", "sample", "trial", "unknown"]
    entity_ids_path: str | None = None
    shape: list[int] = Field(default_factory=list)
    dtype: str
    physical_units: str | None = None
    timebase_id: str | None = None
    chunks: list[int] | None = None
    compression: str | None = None
    upstream_processed: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class NeuroDatasetSnapshot(Contract):
    schema_version: Literal["1"] = "1"
    dataset_id: str
    session_id: str
    subject_id: str | None = None
    standard: Literal["NWB"] = "NWB"
    standard_version: str | None = None
    source: SourceFingerprint
    modality: Literal["extracellular_ephys", "neuropixels", "intracortical_array", "ophys", "mixed", "unknown"]
    collections: list[SignalCollection]
    timebases: list[TimebaseSnapshot]
    processing_history: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    inspected_values: int = Field(ge=0, description="Scalar values read from large datasets during bounded inspection")

    @model_validator(mode="after")
    def identities_are_closed(self):
        collection_ids = [item.id for item in self.collections]
        timebase_ids = [item.id for item in self.timebases]
        if len(collection_ids) != len(set(collection_ids)):
            raise ValueError("collection ids must be unique")
        if len(timebase_ids) != len(set(timebase_ids)):
            raise ValueError("timebase ids must be unique")
        if not {item.timebase_id for item in self.collections if item.timebase_id} <= set(timebase_ids):
            raise ValueError("collection references an unknown timebase")
        return self


class NWBInspectRequest(Contract):
    path: str
    hash_source: bool = False
    max_scalar_reads: int = Field(default=4096, ge=16, le=1_000_000)

    @model_validator(mode="before")
    @classmethod
    def normalize_agent_inputs(cls, value):
        value = _optional_inputs(value, {"hash_source", "max_scalar_reads"})
        if isinstance(value, dict) and isinstance(value.get("path"), str):
            value = dict(value)
            path = value["path"].strip().replace("\\_", "_")
            value["path"] = "/" + path if path.startswith("Users/") else path
        return value


class QCParameters(Contract):
    min_firing_rate_hz: float = Field(default=0.01, ge=0)
    max_isi_violation_ratio: float = Field(default=0.02, ge=0, le=1)
    isi_refractory_period_s: float = Field(default=0.002, gt=0, le=0.1)
    min_presence_ratio: float = Field(default=0.5, ge=0, le=1)
    stability_bins: int = Field(default=10, ge=2, le=1000)
    use_upstream_quality: bool = True
    accepted_upstream_quality: list[str] = Field(default_factory=lambda: ["good"])

    @model_validator(mode="before")
    @classmethod
    def normalize_agent_inputs(cls, value):
        return _optional_inputs(value, set(cls.model_fields))


class TransformParameters(Contract):
    representation: Literal["binned", "events", "both"] = "both"
    bin_size_s: float = Field(default=0.02, gt=0, le=60)
    smoothing_sigma_s: float | None = Field(default=None, gt=0, le=60)
    trial_pre_s: float = Field(default=0.0, ge=0, le=600)
    trial_post_s: float = Field(default=0.0, ge=0, le=600)
    target_series_path: str | None = None
    run_baseline: bool = True
    max_matrix_bytes: int = Field(default=2_000_000_000, ge=1024)

    @model_validator(mode="before")
    @classmethod
    def normalize_agent_inputs(cls, value):
        value = _optional_inputs(value, set(cls.model_fields))
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        for alias in ("bin_size_ms", "bin_ms"):
            milliseconds = normalized.pop(alias, None)
            if "bin_size_s" not in normalized and milliseconds is not None:
                if isinstance(milliseconds, (int, float)) and not isinstance(
                    milliseconds, bool
                ):
                    normalized["bin_size_s"] = milliseconds / 1000
                else:
                    try:
                        normalized["bin_size_s"] = float(milliseconds) / 1000
                    except (TypeError, ValueError):
                        normalized["bin_size_s"] = milliseconds
        if "bin_size_s" in normalized:
            normalized["bin_size_s"] = _duration_seconds(normalized["bin_size_s"])
        return normalized


class PlannedStep(Contract):
    id: str
    stage: Literal["survey", "plan", "qc", "alignment", "transform", "validate", "report"]
    operation: str
    status: Literal["run", "skip", "blocked", "optional"]
    reason: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    evidence_needed: list[str] = Field(default_factory=list)


class InvasivePlanRequest(Contract):
    snapshot_ref: Ref
    task: str = Field(min_length=1)
    qc: QCParameters = Field(default_factory=QCParameters)
    transform: TransformParameters = Field(default_factory=TransformParameters)
    method_profile: str | None = None
    literature_evidence_refs: list[Ref] = Field(default_factory=list)
    code_evidence_refs: list[Ref] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_agent_inputs(cls, value):
        value = _optional_inputs(
            value,
            {
                "qc",
                "transform",
                "method_profile",
                "literature_evidence_refs",
                "code_evidence_refs",
            },
        )
        if isinstance(value, dict) and "task" in value:
            value = dict(value)
            value["task"] = _task_text(value["task"])
        return value


class InvasiveExecutionPlan(Contract):
    schema_version: Literal["1"] = "1"
    snapshot_ref: Ref
    task: str
    modality: str
    input_representation: Representation
    strategy: Literal["consume_released_derivative", "reprocess_from_raw", "inspect_only"]
    executable: bool
    method_profile: str | None = None
    literature_evidence_refs: list[Ref] = Field(default_factory=list)
    code_evidence_refs: list[Ref] = Field(default_factory=list)
    qc: QCParameters
    transform: TransformParameters
    steps: list[PlannedStep]
    warnings: list[str] = Field(default_factory=list)


class InvasiveRunRequest(Contract):
    plan_ref: Ref
    output_name: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]+$")

    @model_validator(mode="before")
    @classmethod
    def normalize_agent_inputs(cls, value):
        return _optional_inputs(value, {"output_name"})
