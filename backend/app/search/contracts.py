from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from app.preprocessing.schemas import Contract
from .evaluation_contracts import EvaluationReceipt
from .space_contracts import CandidateRecipe, PipelineEdit


class SearchBudget(Contract):
    max_diagnostics: int = Field(default=32, ge=0, le=256)
    max_candidates: int = Field(default=48, ge=1, le=256)
    max_proposals: int = Field(default=128, ge=0, le=1024)
    max_evidence_reads: int = Field(default=32, ge=0, le=256)
    max_seconds: float = Field(default=86400, gt=0)
    max_memory_mb: int | None = Field(default=None, ge=64)
    max_disk_mb: int | None = Field(default=None, ge=64)
    max_retries: int = Field(default=4, ge=0, le=32)


class SearchRequest(Contract):
    workflow_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    strategy: Literal["adaptive", "random", "exhaustive", "one_shot"] = "adaptive"
    budget: SearchBudget = Field(default_factory=SearchBudget)
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    train_subjects: list[str] = Field(default_factory=list)
    development_subjects: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def roles(self):
        a, b = self.train_subjects, self.development_subjects
        if bool(a) != bool(b) or set(a) & set(b):
            raise ValueError("训练和开发被试须同时指定且互不重叠")
        if len(set(a)) != len(a) or len(set(b)) != len(b):
            raise ValueError("被试不能重复")
        return self


class ObservationReference(Contract):
    candidate_id: str
    metric: str = Field(
        min_length=1,
        description="Exact dot-separated numeric receipt path, e.g. macro_ba or diagnostics.floor_fraction",
    )


class ExperimentalPrediction(Contract):
    kind: Literal["signal", "utility"]
    metric: str = Field(
        min_length=1,
        description="Exact numeric receipt path to compare against the parent",
    )
    direction: Literal["increase", "decrease", "unchanged"]
    tolerance: float = Field(default=1e-9, ge=0, allow_inf_nan=False)
    explanation: str = Field(min_length=1)


class MechanismHypothesis(Contract):
    explanation: str = Field(min_length=1)
    competing_explanation: str = Field(min_length=1)
    observations: list[ObservationReference] = Field(min_length=1, max_length=12)
    predictions: list[ExperimentalPrediction] = Field(min_length=2, max_length=12)
    weakened_by: str = Field(min_length=1)

    @model_validator(mode="after")
    def separate_predictions(self):
        if {p.kind for p in self.predictions} != {"signal", "utility"}:
            raise ValueError("分别登记信号变化预测与效用预测")
        for p in self.predictions:
            utility = (
                p.metric in {"macro_ba", "secondary_macro_ba", "mean_delta"}
                or p.metric.endswith(".ba")
                or p.metric.startswith("secondary_subjects.")
                or p.metric in {"assessment.selection_score", "assessment.core_csp_macro_ba"}
                or p.metric.startswith("assessment.utility.")
            )
            signal = p.metric.startswith(("diagnostics.", "assessment.quality.", "assessment.reconstruction."))
            if (p.kind == "utility" and not utility) or (
                p.kind == "signal" and not signal
            ):
                raise ValueError(f"{p.kind} prediction path {p.metric!r} is not supported; copy an exact path from numeric_metric_index. Utility includes assessment.selection_score and assessment.core_csp_macro_ba; signal includes diagnostics.* and assessment.quality.summary.metrics.<id>.value")
        return self


class ProposeCandidate(Contract):
    model_config = ConfigDict(json_schema_extra={"oneOf": [
        {"required": ["candidate_id", "edits"], "properties": {
            "candidate_id": {"type": "string", "minLength": 1}, "edits": {"maxItems": 0}}},
        {"required": ["candidate_id", "edits", "title"], "properties": {
            "candidate_id": {"type": "null"}, "edits": {"minItems": 1}, "title": {"type": "string", "minLength": 1}}},
    ]})
    action: Literal["propose_candidate"]
    candidate_id: str | None = None
    edits: list[PipelineEdit] = Field(default_factory=list, max_length=8)
    title: str | None = Field(default=None, max_length=160)
    prior_challenges: dict[str, str] = Field(default_factory=dict)
    base_candidate_id: str
    reason: str = Field(min_length=1)
    expected_result: str = Field(min_length=1)
    decision_branches: dict[Literal["improvement", "no_improvement"], str]
    hypothesis: MechanismHypothesis
    diagnostic_ids: list[str] = Field(default_factory=list, max_length=8)
    prior_rule_ids: list[str] = Field(default_factory=list, max_length=12)
    prior_claims: dict[str, Literal["true", "false", "unknown"]] = Field(default_factory=dict,
        description="For every cited prior_rule_id, copy its actual condition_state from the cited diagnostics. Unknown must remain unknown.")

    @model_validator(mode="after")
    def branches(self):
        if bool(self.candidate_id) == bool(self.edits):
            raise ValueError("选择已有方法起点，或提交父方案编辑；两者必须恰选一个")
        if self.edits and not (self.title or "").strip():
            raise ValueError("编辑候选需要简洁的方案名称")
        if set(self.decision_branches) != {"improvement", "no_improvement"} or not all(
            self.decision_branches.values()
        ):
            raise ValueError("必须说明改善与未改善两种结果如何影响后续决定")
        return self


class RequestEvidence(Contract):
    action: Literal["request_evidence"]
    source_id: str
    question: str = Field(min_length=1)
    query: str = Field(min_length=1)
    affects_choice: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class Finish(Contract):
    untried_candidate_reasons: dict[str, str] = Field(default_factory=dict)
    action: Literal["finish"]
    reason: str = Field(min_length=1)
    unresolved: list[str]
    unexplored_edit_reasons: dict[str, str] = Field(default_factory=dict)


class RequestDiagnostic(Contract):
    action: Literal["request_diagnostic"]
    kind: Literal["signal_profile", "paired_comparison"]
    candidate_id: str
    reference_candidate_id: str | None = None
    stage: Literal["source_raw", "source_task", "processed_task", "processed_continuous"] = "source_raw"
    question: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def paired(self):
        if (self.kind == "paired_comparison") != (self.reference_candidate_id is not None):
            raise ValueError("paired comparison requires a reference; signal profile does not")
        return self


class Decision(Contract):
    decision: Annotated[
        ProposeCandidate | RequestEvidence | RequestDiagnostic | Finish, Field(discriminator="action")
    ]


class InitialSchedule(Contract):
    candidate_ids: list[str] = Field(max_length=256)
    reason: str = Field(min_length=1)


class Usage(Contract):
    diagnostics: int = 0
    diagnostic_seconds: float = 0
    candidates: int = 0
    proposals: int = 0
    evidence_reads: int = 0
    llm_calls: int = 0
    retries: int = 0
    elapsed_seconds: float = 0
    peak_worker_memory_bytes: int = 0
    disk_bytes: int = 0
    llm_seconds: float = 0
    preprocessing_seconds: float = 0
    evaluation_seconds: float = 0


class Candidate(Contract):
    id: str
    title: str
    parameters: dict
    status: str = "reserved"
    attempts: int = 0
    job_id: str | None = None
    plan_ref: dict | None = None
    receipt: EvaluationReceipt | None = None
    error: str | None = None
    cost_seconds: float = 0


class ActionRecord(Contract):
    index: int
    action: str
    status: str = "reserved"
    reason: str = ""
    candidate_id: str | None = None
    base_candidate_id: str | None = None
    expected_result: str | None = None
    decision_branches: dict | None = None
    request: dict | None = None
    result: dict | None = None
    error: str | None = None
    cost_seconds: float = 0


class SearchState(Contract):
    schema_version: Literal["1"] = "1"
    id: str
    owner: str
    workflow_id: str
    status: Literal[
        "preparing",
        "running",
        "completed",
        "stopped",
        "failed",
        "cancelled",
        "interrupted",
    ]
    request: SearchRequest
    budget: SearchBudget
    created_at: str
    updated_at: str
    deadline: float
    phase: str = "freeze_panel"
    message: str = "冻结数据与评价协议"
    error: str | None = None
    panel: dict | None = None
    protocol: dict
    usage: Usage = Field(default_factory=Usage)
    candidates: list[Candidate] = Field(default_factory=list)
    registry: list[dict] = Field(default_factory=list)  # Stored history; execution validates the frozen registry.
    actions: list[ActionRecord] = Field(default_factory=list)
    diagnostics: list[dict] = Field(default_factory=list)
    schedule: list[str] | None = None
    selected_candidate_id: str | None = None
    stop_reason: str | None = None
    unresolved: list[str] = Field(default_factory=list)
    artifacts: list[dict] = Field(default_factory=list)
