from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DecisionAction(StrEnum):
    DELEGATE = "delegate"
    FINISH = "finish"


class AgentDecision(BaseModel):
    """One public, auditable ReAct decision made by the orchestrator planner."""

    action: DecisionAction
    rationale: str
    agent_name: str | None = None
    instruction: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
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


class PlannerProposal(BaseModel):
    """A deliberately tolerant model-facing decision envelope.

    Provider JSON mode guarantees JSON syntax, not adherence to our execution
    contract.  This model therefore parses a proposal first; the dispatcher
    turns it into the strict ``AgentDecision`` only after checking the registry.
    """

    model_config = ConfigDict(extra="ignore")

    action: DecisionAction
    rationale: str = ""
    agent_name: str | None = None
    instruction: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    final_answer: str | None = None


class DecisionNormalizationError(ValueError):
    """The model proposal cannot be made executable without guessing."""


def normalize_planner_proposal(
    proposal: PlannerProposal,
    available_agents: list[dict[str, Any]],
    *,
    user_message: str,
) -> AgentDecision:
    """Resolve safe omissions using the registered action ownership table."""

    rationale = proposal.rationale.strip() or "已生成可执行的下一步。"
    if proposal.action is DecisionAction.FINISH:
        final_answer = (proposal.final_answer or "").strip()
        if not final_answer:
            raise DecisionNormalizationError("finish decision is missing final_answer")
        return AgentDecision(
            action=DecisionAction.FINISH,
            rationale=rationale,
            final_answer=final_answer,
        )

    known_agents = {
        str(item.get("name")): item
        for item in available_agents
        if isinstance(item.get("name"), str) and item.get("name")
    }
    requested_action = proposal.inputs.get("action")
    owners = [
        name
        for name, item in known_agents.items()
        if isinstance(requested_action, str)
        and requested_action in item.get("actions", [])
    ]

    agent_name = (proposal.agent_name or "").strip()
    if not agent_name:
        if len(owners) != 1:
            detail = (
                f"action {requested_action!r} has {len(owners)} registered owners"
                if requested_action
                else "delegate decision is missing agent_name and inputs.action"
            )
            raise DecisionNormalizationError(detail)
        agent_name = owners[0]
    elif known_agents and agent_name not in known_agents:
        raise DecisionNormalizationError(f"unknown agent_name {agent_name!r}")
    elif owners and agent_name not in owners:
        raise DecisionNormalizationError(
            f"action {requested_action!r} is not registered for agent {agent_name!r}"
        )
    elif isinstance(requested_action, str):
        registered_actions = known_agents.get(agent_name, {}).get("actions", [])
        if registered_actions and requested_action not in registered_actions:
            raise DecisionNormalizationError(
                f"unknown action {requested_action!r} for agent {agent_name!r}"
            )

    instruction = (proposal.instruction or "").strip() or user_message.strip()
    if not instruction:
        raise DecisionNormalizationError("delegate decision is missing instruction")
    return AgentDecision(
        action=DecisionAction.DELEGATE,
        rationale=rationale,
        agent_name=agent_name,
        instruction=instruction,
        inputs=proposal.inputs,
    )
