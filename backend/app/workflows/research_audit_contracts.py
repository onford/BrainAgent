from typing import Literal

from pydantic import Field
from app.preprocessing.schemas import Contract
from .survey_contracts import QualitySignals


class RetrievalActionProgress(Contract):
    sequence: int = Field(ge=1)
    action: Literal['read', 'search']
    target: str | None
    medium: str | None
    status: Literal['outcome_unknown', 'completed', 'failed']
    reused: bool
    new_document_contents: int = Field(ge=0)
    new_search_urls: int = Field(ge=0)
    new_returned_excerpts: int = Field(ge=0)


class RetrievalProgress(Contract):
    schema_version: Literal['research-progress-1']
    purpose: Literal['dataset_verification', 'literature_review']
    stop_reason: Literal['running', 'model_finished', 'deadline_expired', 'action_budget_exhausted']
    stop_rationale: str | None
    max_actions: int = Field(ge=1)
    reserved_actions: int = Field(ge=0)
    remaining_actions: int = Field(ge=0)
    expires_at: float
    seconds_left: float = Field(ge=0)
    missing_requirements: list[str]
    unique_document_contents: int = Field(ge=0)
    unique_search_urls: int = Field(ge=0)
    returned_excerpts: int = Field(ge=0)
    actions: list[RetrievalActionProgress]
    systematic_review_complete: Literal[False]
    interpretation: str


class LocatedFinding(Contract):
    finding_id: str
    source_sha256: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote_sha256: str
    duplicate_span_count: int = Field(ge=1)


class EvidenceGrade(Contract):
    entry_id: str
    source_id: str
    source_url: str
    source_sha256: str
    retrieved_at: str
    reading_scope: str
    access_grade: Literal['abstract_only', 'located_source_text', 'source_text_without_located_findings']
    source_truncated: bool
    decision: Literal['included', 'deferred', 'excluded']
    finding_spans: list[LocatedFinding]
    scientific_parameter_support: Literal['requires_method_parameter_review']
    execution_grade: Literal['not_established_by_literature_screening']
    independent_reproduction: Literal['not_established']
    observed_popularity: QualitySignals


class EvidenceGrades(Contract):
    schema_version: Literal['evidence-grades-1']
    review_sha256: str
    rows: list[EvidenceGrade]
    interpretation: str
