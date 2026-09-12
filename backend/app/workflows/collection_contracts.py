"""Fixed intake checks, literature claims and standardization evidence."""

from typing import Literal
from pydantic import Field, model_validator
from app.preprocessing.schemas import Contract

Category = Literal[
    "scope_files",
    "directory_identity",
    "format_readability",
    "subjects_groups",
    "acquisition_parameters",
    "channels_auxiliary",
    "electrodes_coordinates",
    "dimensions_units_values",
    "timing",
    "events",
    "trial_protocol",
    "behavior",
    "stimulus_sync",
    "raw_processed",
    "notes_exclusions",
]
CATEGORIES = list(Category.__args__)
CATEGORY_LABELS = dict(
    zip(
        CATEGORIES,
        [
            "范围与文件",
            "目录、命名与标识",
            "格式与可读性",
            "被试与分组",
            "采集参数",
            "通道与辅助信号",
            "电极与坐标",
            "维度、单位与数值",
            "时长与时间轴",
            "事件",
            "流程与 Trial",
            "行为",
            "刺激与同步",
            "原始与标准副本对应",
            "备注与排除",
        ],
    )
)
Status = Literal["一致", "部分一致", "不一致", "资料未说明", "无法核查", "不适用"]
Severity = Literal["structural-hard-fail", "retain-with-flag", "information-only"]
Action = Literal["排除", "建立工作副本", "修复元数据", "保留标记", "不处理"]


class IntakeCheck(Contract):
    check_category: Category
    object_key: str
    expected_statement: str
    observed_evidence: str
    status: Status
    severity: Severity
    action: Action
    provenance: str

    @model_validator(mode="after")
    def exclusion_requires_failure(self):
        if self.action == "排除" and (
            self.status != "不一致" or self.severity != "structural-hard-fail"
        ):
            raise ValueError("exclusion requires a confirmed structural failure")
        return self


class CheckProvenance(Contract):
    checked_at: str
    implementation: str
    code_sha256: dict[str, str]
    versions: dict[str, str]
    parameters: dict[str, str | float | int]
    output: str


class IntakeAudit(Contract):
    scope: str
    policy: str
    provenance: CheckProvenance
    checks: list[IntakeCheck]

    @model_validator(mode="after")
    def coverage(self):
        if {c.check_category for c in self.checks} != set(CATEGORIES):
            raise ValueError("intake audit must account for all 15 check categories")
        return self


class ReportedExclusion(Contract):
    entry_id: str
    # Default reads legacy artifacts; the current model-facing schema requires
    # an explicit classification and literal object span.
    claim_type: Literal['exclusion', 'inclusion_scope', 'held_out', 'unspecified'] = 'exclusion'
    object_quote: str | None = None
    object_type: Literal["subject", "recording", "channel", "trial", "unspecified"]
    reported_ids: list[str]
    finding_ids: list[str] = Field(min_length=1)
    reason: str


class MatchedExclusion(ReportedExclusion):
    local_objects: list[str]
    match_status: Literal["selected", "outside_selection", "unresolved", "scope_only"]
    action: Literal["保留标记", "不处理"]


class LiteratureExclusions(Contract):
    policy: str
    records: list[MatchedExclusion]


class SourceClaimCheck(Contract):
    entry_id: str
    proposed: ReportedExclusion
    effective: ReportedExclusion
    status: Literal['unresolved', 'literal_scope_verified']
    reason: str | None
    automatic_exclusion_authorized: Literal[False]


class SourceClaimReview(Contract):
    schema_version: Literal['source-claim-review-1']
    checks: list[SourceClaimCheck]
    policy: str


class SourceIntegrity(Contract):
    scope: str
    files: dict[str, str]
    checked_after: bool
    unchanged: bool


class Standardization(Contract):
    standard: Literal["BIDS-EEG"]
    version: str
    writer: str
    supported_scope: str
    unsupported_modalities: list[str]
    validation: str
    official_validator: Literal["not_run"]
    coordinate_source: str
    source_events: int = Field(ge=0)
    standardized_events: int = Field(ge=0)
    training_events: int = Field(ge=0)
    file_count: int = Field(ge=0)
