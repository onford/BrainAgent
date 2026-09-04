from enum import StrEnum

from pydantic import BaseModel, model_validator


class DecisionAction(StrEnum):
    DELEGATE = "delegate"
    FINISH = "finish"


class AgentDecision(BaseModel):
    """One public, auditable ReAct decision made by the orchestrator planner."""

    action: DecisionAction
    rationale: str
    agent_name: str | None = None
    instruction: str | None = None
    final_answer: str | None = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> "AgentDecision":
        if self.action is DecisionAction.DELEGATE and not (
            self.agent_name and self.instruction
        ):
            raise ValueError("delegate requires agent_name and instruction")
        if self.action is DecisionAction.FINISH and not self.final_answer:
            raise ValueError("finish requires final_answer")
        return self
