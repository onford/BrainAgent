"""Dataset verification and downstream literature are distinct research products."""

from typing import Literal

from pydantic import Field, model_validator

from app.preprocessing.schemas import Contract
from .cognition_contracts import Finding, ProfileFact

Target = Literal[
    "official_sources",
    "official_publication",
    "usage_analysis",
    "usage_algorithm",
    "dataset_discussion",
    "preprocessing_methods",
]
Medium = Literal["official", "paper", "repository"]
FIELDS = (
    "directory_structure",
    "file_format",
    "file_header",
    "signal_arrays",
    "channels",
    "sampling_rate",
    "events",
    "task_runs",
    "subjects",
    "recording_duration",
    "acquisition",
    "license",
    "dataset_version",
)
ComparisonField = Literal[*FIELDS]
LITERATURE_TARGETS = (
    "usage_analysis",
    "usage_algorithm",
    "dataset_discussion",
    "preprocessing_methods",
)
DESTINATIONS = {
    "usage_analysis": ["3.2", "3.4（待讨论）"],
    "usage_algorithm": ["3.2", "3.4（待讨论）"],
    "dataset_discussion": ["2.3"],
    "preprocessing_methods": ["3.2"],
}
SELECTION_CRITERIA = [
    "相关性：使用或讨论目标数据集；预处理资料允许同类数据、相同任务，必须说明适用范围。",
    "内容充分性：有可读取的方法、分析结果、数据问题或代码依据；仅有标题或摘要不足以纳入可执行方法依据。",
    "可追溯性：结论附原文与来源，paper/PDF/repo 链接只采用实际返回的地址。",
    "优先级：优先可信期刊、较高被引论文及较高星仓库；只记录检索返回的指标，未知留空，不以热度替代内容判断。",
]


class SearchGoal(Contract):
    target: Target
    medium: Medium
    question: str
    query: str


class SurveyPlan(Contract):
    objective: str
    verification: list[SearchGoal]
    literature: list[SearchGoal]

    @model_validator(mode="after")
    def distinct_purposes(self):
        if {(g.target, g.medium) for g in self.verification} != {
            ("official_sources", "official"),
            ("official_publication", "paper"),
        }:
            raise ValueError(
                "verification requires official sources and the official dataset publication"
            )
        if {(g.target, g.medium) for g in self.literature} != {
            (t, m) for t in LITERATURE_TARGETS for m in ("paper", "repository")
        }:
            raise ValueError(
                "literature requires analysis, algorithm, dataset discussion and preprocessing, each for paper AND repository"
            )
        return self


class LocalFact(Contract):
    id: str
    field: ComparisonField
    scope: str
    value: str
    locator: str


class LocalInspection(Contract):
    scope: str
    facts: list[LocalFact]


class SourceStatement(Contract):
    statement: str | None = Field(min_length=1)
    finding_ids: list[str]

    @model_validator(mode="after")
    def cited_or_unknown(self):
        if (self.statement is None) != (not self.finding_ids):
            raise ValueError(
                "a source statement must have citations; unknown statements use null and an empty citation list"
            )
        return self


class Comparison(Contract):
    field: ComparisonField
    local_fact_ids: list[str]
    official_sources: SourceStatement
    official_paper: SourceStatement
    status: Literal[
        "consistent",
        "partial",
        "conflict",
        "not_stated",
        "unverifiable",
        "not_applicable",
    ]
    conclusion: str


class OfficialPublication(Contract):
    source_id: str | None
    role: Literal["dataset_paper", "acquisition_system", "not_identified"]
    basis_finding_ids: list[str]
    explanation: str


class DatasetVerification(Contract):
    summary: str
    facts: list[Finding] = Field(min_length=3, max_length=50)
    metadata: list[ProfileFact] = Field(min_length=6, max_length=6)
    official_publication: OfficialPublication
    comparisons: list[Comparison] = Field(
        min_length=len(FIELDS), max_length=len(FIELDS)
    )
    gaps: list[str]
    conflicts: list[str]

    @model_validator(mode="after")
    def complete_fields(self):
        if {r.field for r in self.comparisons} != set(FIELDS):
            raise ValueError(
                "all fixed comparison fields are required, including unknowns"
            )
        if {m.field for m in self.metadata} != {
            "name",
            "version",
            "doi",
            "publisher",
            "published",
            "license",
        }:
            raise ValueError("all six metadata fields must occur exactly once")
        ids = {f.id for f in self.facts}
        for item in self.metadata:
            if not set(item.finding_ids) <= ids or (
                item.value is not None and not item.finding_ids
            ):
                raise ValueError("known metadata must cite verification findings")
        return self


class QualitySignals(Contract):
    venue: str | None = None
    citations: int | None = Field(default=None, ge=0)
    stars: int | None = Field(default=None, ge=0)
    observation_ids: list[int] = Field(default_factory=list)


class LiteratureEntry(Contract):
    id: str
    source_id: str
    target: Literal[
        "usage_analysis",
        "usage_algorithm",
        "dataset_discussion",
        "preprocessing_methods",
    ]
    medium: Literal["paper", "repository"]
    decision: Literal["included", "excluded", "deferred"]
    reason: str
    reading_scope: Literal[
        "abstract", "full_text", "partial_text", "repository_docs", "code"
    ]
    findings: list[Finding] = Field(max_length=8)
    related_urls: list[str]
    quality: QualitySignals
    exclusions: list[str] = Field(
        default_factory=list,
        description="Subject/run/channel exclusions reported by dataset discussion sources, not automatic local exclusion commands.",
    )


class LiteratureScreening(Contract):
    summary: str
    entries: list[LiteratureEntry] = Field(max_length=40)
    gaps: list[str]


class LiteratureCoverage(Contract):
    target: str
    medium: Literal["paper", "repository"]
    destinations: list[str]
    status: Literal["covered", "gap"]
    search_observation_ids: list[int]
    included_entry_ids: list[str]
    explanation: str


class LiteratureReview(LiteratureScreening):
    criteria: list[str]
    coverage: list[LiteratureCoverage] = Field(min_length=8, max_length=8)
    sources: list["LiteratureSource"]


class LiteratureSource(Contract):
    id: str
    title: str
    url: str
