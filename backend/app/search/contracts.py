from typing import Literal

from pydantic import Field, model_validator

from app.preprocessing.schemas import Contract
from .evaluation_contracts import EvaluationReceipt


class SearchBudget(Contract):
    max_candidates: int = Field(default=48, ge=1, le=256)
    max_seconds: float = Field(default=86400, gt=0)
    max_memory_mb: int | None = Field(default=None, ge=64)
    max_disk_mb: int | None = Field(default=None, ge=64)
    max_retries: int = Field(default=4, ge=0, le=32)


class SearchRequest(Contract):
    workflow_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    strategy: Literal["one_shot"] = "one_shot"
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


class InitialSchedule(Contract):
    candidate_ids: list[str] = Field(max_length=256)
    reason: str = Field(min_length=1)


class Usage(Contract):
    candidates: int = 0
    recommended_candidates: int = 0
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
    request: dict | None = None
    result: dict | None = None
    error: str | None = None
    cost_seconds: float = 0


class SearchState(Contract):
    schema_version: Literal["1"] = "1"
    cancellation_requested: bool = False
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
    schedule: list[str] | None = None
    recommendation: dict | None = None
    selected_candidate_id: str | None = None
    stop_reason: str | None = None
    unresolved: list[str] = Field(default_factory=list)
    artifacts: list[dict] = Field(default_factory=list)
