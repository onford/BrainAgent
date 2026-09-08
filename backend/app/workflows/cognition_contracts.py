"""Fixed schemas for research, decisions and executable method design."""

from typing import Any, Literal

from pydantic import Field, model_validator

from app.preprocessing.schemas import Contract, Scope

Bucket = Literal[
    "dataset",
    "papers_using_dataset",
    "papers_discussing_dataset",
    "preprocessing_papers",
    "code",
]


class ResearchQuestion(Contract):
    category: Bucket
    question: str = Field(min_length=1)
    query: str = Field(min_length=1)


class ResearchPlan(Contract):
    objective: str
    questions: list[ResearchQuestion] = Field(min_length=4, max_length=10)

    @model_validator(mode="after")
    def coverage(self):
        if not {
            "dataset",
            "papers_using_dataset",
            "papers_discussing_dataset",
            "preprocessing_papers",
        } <= {q.category for q in self.questions}:
            raise ValueError(
                "research must cover the dataset and all three literature categories"
            )
        return self


class SourceDocument(Contract):
    id: str
    url: str
    title: str
    kind: Literal["official", "paper", "code", "documentation"]
    retrieved_at: str
    sha256: str
    text: str
    links: list[str]
    truncated: bool


class Finding(Contract):
    id: str
    topic: str
    statement: str
    source_id: str
    quote: str = Field(min_length=12, max_length=1200)


class LiteratureItem(Contract):
    source_id: str
    category: Literal[
        "papers_using_dataset", "papers_discussing_dataset", "preprocessing_papers"
    ]
    relevance: str
    reading_scope: Literal["abstract", "full_text", "partial_text"]


class ProfileFact(Contract):
    field: Literal["name", "version", "doi", "publisher", "published", "license"]
    value: str | None
    finding_ids: list[str]


class ResearchFindings(Contract):
    summary: str
    facts: list[Finding] = Field(min_length=3, max_length=30)
    literature: list[LiteratureItem] = Field(min_length=1, max_length=15)
    gaps: list[str]
    conflicts: list[str]
    metadata: list[ProfileFact] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def metadata_complete(self):
        if {item.field for item in self.metadata} != {
            "name",
            "version",
            "doi",
            "publisher",
            "published",
            "license",
        }:
            raise ValueError(
                "metadata must contain each fixed dataset field exactly once"
            )
        ids = {fact.id for fact in self.facts}
        for item in self.metadata:
            if not set(item.finding_ids) <= ids or (
                item.value is not None and not item.finding_ids
            ):
                raise ValueError(
                    "known metadata must cite findings; use null for unknown metadata"
                )
        return self


class ResearchAction(Contract):
    action: Literal["search", "read", "finish"]
    rationale: str
    category: Bucket = "dataset"
    tool: str | None = None
    query: str | None = None
    url: str | None = None
    kind: Literal["official", "paper", "code", "documentation"] = "paper"

    @model_validator(mode="after")
    def arguments(self):
        if self.action == "search" and not (self.tool and self.query):
            raise ValueError("search requires tool and query")
        if self.action == "read" and not self.url:
            raise ValueError("read requires URL")
        return self


class CollectionReview(Contract):
    compatible: bool
    rationale: str
    supporting_facts: list[str] = Field(min_length=1)
    conflicts: list[str]
    limitations: list[str]


class PlannedStep(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    unit_id: str
    op: str
    input: str
    model_from: str | None = None
    decision_from: str | None = None
    params: dict[str, Any]
    fit_scope: Scope | None = None
    basis: Literal["source", "engineering"]
    finding_ids: list[str]
    rationale: str = Field(min_length=1)


class CandidateDesign(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]+$")
    title: str
    mechanism: str
    rationale: str
    steps: list[PlannedStep] = Field(min_length=1, max_length=12)
    output: str
    adaptations: list[str]


class MethodDesign(Contract):
    objective: str
    candidates: list[CandidateDesign] = Field(min_length=2, max_length=3)
    limitations: list[str]
    supplement_requests: list[ResearchAction] = Field(
        default_factory=list, max_length=3
    )

    @model_validator(mode="after")
    def executable_requests(self):
        if any(r.action == "finish" for r in self.supplement_requests):
            raise ValueError("supplement requests must be search or read actions")
        return self


class ReportNarrative(Contract):
    overview: str
    data_interpretation: str
    method_reasoning: str
    limitations: list[str]
    finding_ids: list[str]


class DecisionRecord(Contract):
    sequence: int
    stage: str
    operation: str
    model: str
    status: Literal["accepted", "rejected", "failed"]
    result: dict[str, Any] | None
    error: str | None


class ToolObservation(Contract):
    sequence: int
    action: ResearchAction
    success: bool
    output: dict[str, Any] | None
    error: str | None


class ResearchSources(Contract):
    documents: list[SourceDocument]
    observations: list[ToolObservation]


class DecisionLog(Contract):
    records: list[DecisionRecord]


class DesignRevision(Contract):
    attempt: int
    design: MethodDesign
    error: str


class DesignRevisions(Contract):
    attempts: list[DesignRevision]
