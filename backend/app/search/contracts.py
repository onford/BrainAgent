from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.preprocessing.schemas import Contract
from .evaluation_contracts import EvaluationReceipt


class SearchBudget(Contract):
    max_candidates: int = Field(default=6, ge=1, le=32)
    max_proposals: int = Field(default=8, ge=0, le=64)
    max_evidence_reads: int = Field(default=2, ge=0, le=16)
    max_seconds: float = Field(default=3600, gt=0)
    max_memory_mb: int | None = Field(default=None, ge=64)
    max_disk_mb: int | None = Field(default=None, ge=64)
    max_retries: Literal[0, 1] = 1


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
            )
            signal = p.metric.startswith("diagnostics.")
            if (p.kind == "utility" and not utility) or (
                p.kind == "signal" and not signal
            ):
                raise ValueError("效用分数与信号诊断必须分开")
        return self


class ProposeCandidate(Contract):
    action: Literal["propose_candidate"]
    candidate_id: str
    base_candidate_id: str
    reason: str = Field(min_length=1)
    expected_result: str = Field(min_length=1)
    decision_branches: dict[Literal["improvement", "no_improvement"], str]
    hypothesis: MechanismHypothesis

    @model_validator(mode="after")
    def branches(self):
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
    action: Literal["finish"]
    reason: str = Field(min_length=1)
    unresolved: list[str]


class Decision(Contract):
    decision: Annotated[
        ProposeCandidate | RequestEvidence | Finish, Field(discriminator="action")
    ]


class InitialSchedule(Contract):
    candidate_ids: list[str] = Field(max_length=64)
    reason: str = Field(min_length=1)


class Usage(Contract):
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
    actions: list[ActionRecord] = Field(default_factory=list)
    schedule: list[str] | None = None
    selected_candidate_id: str | None = None
    stop_reason: str | None = None
    unresolved: list[str] = Field(default_factory=list)
    artifacts: list[dict] = Field(default_factory=list)
