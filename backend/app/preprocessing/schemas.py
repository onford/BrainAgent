from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Ref(Contract):
    id: str = Field(pattern=r"^[a-f0-9]{64}$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Evidence(Contract):
    source_url: str
    locator: str = Field(min_length=1)
    text: str = Field(min_length=1)
    artifact_ref: Ref | None = None
    source_version: str = Field(min_length=1)


class Scope(Contract):
    role: Literal["train", "calibration"]
    ids: list[str] = Field(min_length=1)


class Interval(Contract):
    id: str
    role: Literal["train", "calibration", "test"]
    start: int = Field(ge=0)
    stop: int = Field(gt=0)


class RecordSpec(Contract):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    bids_path: str
    files: dict[str, str] = Field(min_length=1)
    sfreq: float = Field(gt=0)
    samples: int = Field(gt=0)
    channels: dict[str, Literal["eeg", "eog", "ecg", "emg", "misc", "stim"]]
    channel_order: list[str] = Field(min_length=1)
    reference: str = Field(min_length=1)
    intervals: list[Interval] = Field(default_factory=list)

    @model_validator(mode="after")
    def intervals_valid(self):
        if len(self.channel_order) != len(set(self.channel_order)) or set(
            self.channel_order
        ) != set(self.channels):
            raise ValueError("channel_order must name every channel exactly once")
        ordered = sorted(self.intervals, key=lambda i: i.start)
        if len({i.id for i in ordered}) != len(ordered):
            raise ValueError("duplicate partition ids")
        for i, item in enumerate(ordered):
            if item.start >= item.stop or item.stop > self.samples:
                raise ValueError("partition outside recording")
            if i and ordered[i - 1].stop > item.start:
                raise ValueError("overlapping partitions")
        return self


class SurveySnapshot(Contract):
    dataset_id: str
    dataset_version: str
    survey_run_id: str
    task: str
    event_id: dict[str, int]
    processing_history: list[str]
    facts: list[Evidence] = Field(min_length=1)
    unresolved: list[str] = Field(default_factory=list)


class CollectionSnapshot(Contract):
    dataset_id: str
    dataset_version: str
    root: str
    standard: Literal["BIDS-EEG"] = "BIDS-EEG"
    standard_version: str
    validation_evidence: Evidence
    selection_reason: str = Field(min_length=1)
    selected_record_ids: list[str] = Field(min_length=1)
    records: list[RecordSpec] = Field(min_length=1)


class PreprocessInput(Contract):
    schema_version: Literal["1"] = "1"
    purpose: Literal["production", "development_fixture"]
    survey: SurveySnapshot
    collection: CollectionSnapshot

    @model_validator(mode="after")
    def consistent(self):
        s, c = self.survey, self.collection
        if (s.dataset_id, s.dataset_version) != (c.dataset_id, c.dataset_version):
            raise ValueError("Survey and Collection versions differ")
        ids = [r.id for r in c.records]
        if len(ids) != len(set(ids)) or len(c.selected_record_ids) != len(
            set(c.selected_record_ids)
        ):
            raise ValueError("record ids must be unique")
        if not set(c.selected_record_ids) <= set(ids):
            raise ValueError("selection contains unknown recordings")
        if not s.task or s.unresolved:
            raise ValueError("Survey requires a task and resolved blocking facts")
        if any(type(v) is not int or v <= 0 for v in s.event_id.values()):
            raise ValueError("event codes must be positive integers")
        if len(s.event_id.values()) != len(set(s.event_id.values())):
            raise ValueError("event codes must be unique")
        return self


class Step(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    unit_id: str
    op: str
    profile: Literal["source"] = "source"
    implementation_version: Literal["1"] = "1"
    input: str = "raw"
    model_from: str | None = None
    decision_from: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    fit_scope: Scope | None = None
    evidence_indices: list[int] = Field(min_length=1)


class MethodDraft(Contract):
    """Model-authored recipe; evidence indices refer to the supplied source list."""
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]+$")
    version: str = Field(min_length=1)
    title: str
    source: Literal["classic", "survey_literature"]
    status: Literal["draft", "validated", "retired"] = "draft"
    mechanism: str = Field(min_length=1)
    recipe: list[Step] = Field(min_length=1)
    output: str
    applicability: dict[str, Any] = Field(default_factory=dict)
    adaptations: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)
    validation: list[Ref] = Field(default_factory=list)
    # Exact parameter profiles actually exercised by validation runs.
    validated_profiles: list[str] = Field(default_factory=list)


class MethodSpec(MethodDraft):
    evidence: list[Evidence] = Field(min_length=1)


class RepositoryEvidence(Contract):
    url: str
    version: str = Field(min_length=1)
    code_ref: Ref | None = None
    relation_to_paper: str


class Paper(Contract):
    paper_id: str
    title: str
    doi: str | None = None
    year: int | None = None
    survey_bucket: Literal[
        "papers_using_dataset", "preprocessing_papers", "papers_discussing_dataset"
    ]
    relation_to_dataset: str
    inclusion_reason: str
    landing_url: str
    pdf_ref: Ref | None = None
    fulltext_ref: Ref | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    repositories: list[RepositoryEvidence] = Field(default_factory=list)
    retrieval_status: Literal["complete", "partial", "unavailable"] = "partial"
    conflicts: list[str] = Field(default_factory=list)
    quality_metadata: dict[str, Any] = Field(default_factory=dict)
    missing_items: list[str] = Field(default_factory=list)


class SurveyLiteratureBundle(Contract):
    schema_version: Literal["1"] = "1"
    survey_run_id: str
    dataset_id: str
    dataset_version: str
    papers: list[Paper]


class PlanRequest(Contract):
    input_ref: Ref
    methods: list[Ref] = Field(min_length=1)
    mode: Literal["production", "validation", "exploratory"] = "production"
    parameters: dict[str, Any] = Field(default_factory=dict)
    max_candidates: int = Field(default=3, ge=1, le=32)
    selection: Literal["all", "diverse"] = "diverse"
    max_memory_mb: int = Field(default=2048, ge=64, le=65536)
    max_disk_mb: int = Field(default=8192, ge=64)


class Screening(Contract):
    method_ref: Ref
    status: Literal["selected", "duplicate", "deferred", "blocked"]
    reasons: list[str]
    duplicate_of: Ref | None = None


class RecordPlan(Contract):
    method_ref: Ref
    record_id: str
    steps: list[Step]
    output: str
    code_hashes: dict[str, str]


class ExecutionPlan(Contract):
    schema_version: Literal["1"] = "1"
    request: PlanRequest
    input_snapshot: PreprocessInput
    screening: list[Screening]
    records: list[RecordPlan]
    environment: dict[str, str]
    engine_sha256: str
    estimated_disk_bytes: int = Field(default=0, ge=0)
    required_outputs: list[str] = ["data", "events", "provenance", "delta"]


class UnitSpec(Contract):
    id: str
    source: dict[str, Any]
    implementation: dict[str, Any]
    validation: dict[str, Any]


class RunResult(Contract):
    job_id: str
    plan_ref: Ref
    status: Literal[
        "queued",
        "running",
        "completed",
        "partial",
        "failed",
        "interrupted",
        "cancelled",
    ]
    records: list[dict[str, Any]]
    completed: int
    total: int
    cancel_requested: bool
