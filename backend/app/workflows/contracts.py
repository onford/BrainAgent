"""Versioned process contracts. Agent outputs are validated before publication."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.preprocessing.schemas import Contract, Ref, Step
from .schemas import WorkflowRequest
from .cognition_contracts import ResearchFindings, ReportNarrative

Count = Annotated[int, Field(ge=0)]


class Statistics(Contract):
    subjects: Count
    recordings: Count
    trials: Count
    duration_s: float = Field(ge=0)
    unknown_recordings: Count


class Citation(Contract):
    title: str
    url: str
    doi: str | None = None


class DatasetProfile(Contract):
    dataset_id: str
    name: str
    version: str
    doi: str
    publisher: str
    published: str
    license: str
    source_url: str
    profile_reviewed: str
    task: str
    expected_sfreq: float = Field(gt=0)
    expected_eeg_channels: int = Field(gt=0)
    trigger_map: dict[str, str]
    run_scope: list[int]
    references: list[Citation]
    unknown_fields: list[str]
    literature_status: str


class SourceRecord(Contract):
    id: str
    subject: str
    run: int
    source_path: str


class ReadableRecord(SourceRecord):
    status: Literal["readable"]
    sfreq: float = Field(gt=0)
    samples: int = Field(gt=0)
    channel_set: str
    duration_s: float = Field(gt=0)
    event_counts: dict[str, Count]
    task_trials: Count
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ExcludedRecord(SourceRecord):
    status: Literal["excluded"]
    reason: str = Field(min_length=1)


class InspectionCheck(Contract):
    object_key: str
    check_category: str
    status: str
    severity: str
    action: str
    observed_evidence: str


class SourceEvidence(Contract):
    source_url: str
    locator: str
    type: str


class SurveyOutput(Contract):
    profile: DatasetProfile
    source_root: str
    available_subjects: Count
    available_recordings: Count
    selected_subjects: list[str]
    channel_sets: dict[str, list[str]]
    records: list[
        Annotated[ReadableRecord | ExcludedRecord, Field(discriminator="status")]
    ]
    checks: list[InspectionCheck]
    statistics: Statistics
    evidence: list[SourceEvidence]
    scope: str

    @model_validator(mode="after")
    def channel_references_exist(self):
        for record in self.records:
            if (
                isinstance(record, ReadableRecord)
                and record.channel_set not in self.channel_sets
            ):
                raise ValueError("record references an unknown channel set")
        return self


class Exclusion(Contract):
    object_key: str
    reason: str


class CollectionOutput(Contract):
    input_ref: Ref
    standardized_root: str
    statistics: Statistics
    excluded: list[Exclusion]
    source_unchanged: Literal[True]
    validation: str
    adaptations: list[str]


class CandidateMethod(Contract):
    ref: Ref
    title: str
    recipe: list[Step]


class RecordOutcome(Contract):
    record_id: str
    method_id: str
    status: str
    attempt: Count
    artifact_root: str | None = None
    events_before: Count | None = None
    events_retained: Count | None = None
    shape: list[Count] | None = None
    error: str | None = None


class PreprocessingOutput(Contract):
    execution_status: Literal["completed", "partial"]
    job_id: str
    plan_ref: Ref
    completed: Count
    total: Count
    methods: list[CandidateMethod] = Field(min_length=1)
    records: list[RecordOutcome] = Field(min_length=1)


class ExcludedCandidate(Contract):
    method_ref: Ref
    missing_or_invalid_records: list[str]


class EvaluationOutput(Contract):
    selection_policy: Literal["random"]
    quality_evaluated: Literal[False]
    seed: Count
    eligible_candidates: list[Ref] = Field(min_length=1)
    excluded_candidates: list[ExcludedCandidate]
    selected_method_ref: Ref
    best_output: None
    reason: str

    @model_validator(mode="after")
    def selected_is_eligible(self):
        if self.selected_method_ref not in self.eligible_candidates:
            raise ValueError("selected method must be an eligible candidate")
        return self


class ReportOutput(Contract):
    report_path: str
    format: Literal["HTML"]
    quality_evaluated: Literal[False]


class DeliveryOutput(Contract):
    archive: str
    manifest: str
    shape: list[int] = Field(min_length=3, max_length=3)
    classes: dict[str, Count]
    split_counts: dict[str, Count]
    subject_split: dict[str, Literal["train", "validation", "test"]]
    selection_policy: Literal["random"]
    quality_evaluated: Literal[False]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_unchanged: Literal[True]


class ProcessData(Contract):
    """Schema root; each optional property is a separate module record on disk."""

    data_survey: SurveyOutput | None = None
    data_collection: CollectionOutput | None = None
    data_preprocessing: PreprocessingOutput | None = None
    data_evaluation: EvaluationOutput | None = None
    data_report: ReportOutput | None = None
    data_delivery: DeliveryOutput | None = None


class StageRecord(Contract):
    name: str
    label: str
    status: str
    data_path: str | None = None
    schema_ref: str
    error: str | None = None


class ProcessIndex(Contract):
    schema_version: Literal["1"] = "1"
    workflow_id: str
    request: WorkflowRequest
    stages: list[StageRecord]


class ReportData(Contract):
    """Only fields used by the report template, extracted from process records."""

    dataset_name: str
    dataset_version: str
    license: str
    subjects: list[str]
    runs: list[int]
    sfreq: float
    channel_count: int
    before: Statistics
    after: Statistics
    method: CandidateMethod
    records: list[RecordOutcome]
    selection_reason: str
    seed: Count
    references: list[Citation]
    limitations: list[str]
    research: ResearchFindings | None = None
    narrative: ReportNarrative | None = None


STAGE_CONTRACTS = {
    "data_survey": (SurveyOutput, "survey/survey.json"),
    "data_collection": (CollectionOutput, "collection/collection.json"),
    "data_preprocessing": (PreprocessingOutput, "preprocessing/summary.json"),
    "data_evaluation": (EvaluationOutput, "evaluation/selection.json"),
    "data_report": (ReportOutput, "report/output.json"),
    "data_delivery": (DeliveryOutput, "delivery/output.json"),
}
