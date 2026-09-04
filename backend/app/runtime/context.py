from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.runtime.events import ExecutionEvent
from app.runtime.result import AgentResult, Artifact
from app.runtime.state import RunStatus, StepStatus


class AgentTask(BaseModel):
    instruction: str
    step: int | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanStep(BaseModel):
    step: int
    agent: str
    task: str
    depends_on: list[int] = Field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0


class Plan(BaseModel):
    goal: str
    steps: list[PlanStep]


class AgentContext(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    owner_id: str
    user_message: str
    conversation_history: list[dict[str, str]] = Field(default_factory=list)
    plan: Plan | None = None
    current_step: int | None = None
    agent_results: list[AgentResult] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    shared_memory: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: RunStatus = RunStatus.PENDING
    error: str | None = None
    final_answer: str | None = None
    events: list[ExecutionEvent] = Field(default_factory=list)

    def record_result(self, result: AgentResult) -> None:
        self.agent_results.append(result)
        self.artifacts.extend(result.artifacts)
        self.observations.extend(result.observations)
        self.shared_memory[result.agent_name] = result.output

    def emit(
        self,
        event_type: str,
        message: str,
        agent_name: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> ExecutionEvent:
        event = ExecutionEvent(
            event_type=event_type,
            agent_name=agent_name,
            step=self.current_step,
            message=message,
            data=data or {},
        )
        self.events.append(event)
        return event
