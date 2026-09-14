import json
from typing import Any

from app.agents.action_contracts import ActionInputError, normalize_action_inputs
from app.agents.base import BaseAgent
from app.agents.planner.prompt import PLANNER_SYSTEM_PROMPT
from app.llm.client import LLMClient, StructuredOutputError
from app.runtime.context import AgentContext, AgentTask
from app.runtime.decision import (
    AgentDecision,
    DecisionNormalizationError,
    PlannerProposal,
    normalize_planner_proposal,
)
from app.runtime.result import AgentResult


class PlannerDecisionError(ValueError):
    """The planner remained non-executable after one focused correction."""


class PlannerAgent(BaseAgent):
    name = "planner"
    description = "Turns a user request into an executable agent plan."

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def decide(
        self, context: AgentContext, available_agents: list[dict[str, Any]]
    ) -> AgentDecision:
        recent_history = context.conversation_history[-20:]
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            *recent_history,
            {
                "role": "user",
                "content": (
                    f"User request: {context.user_message}\n"
                    f"Available agents: {available_agents}\n"
                    f"Completed results: {[r.model_dump() for r in context.agent_results]}"
                ),
            },
        ]
        rejected: str | None = None
        problem: str | None = None
        for attempt in range(2):
            try:
                proposal = await self.llm.structured_output(messages, PlannerProposal)
                decision = normalize_planner_proposal(
                    proposal,
                    available_agents,
                    user_message=context.user_message,
                )
                return decision.model_copy(
                    update={"inputs": normalize_action_inputs(decision.inputs)}
                )
            except StructuredOutputError as exc:
                rejected = exc.content
                problem = str(exc)
            except DecisionNormalizationError as exc:
                rejected = proposal.model_dump_json()
                problem = str(exc)
            except ActionInputError as exc:
                rejected = proposal.model_dump_json()
                problem = str(exc)

            if attempt == 0:
                messages = [
                    *messages,
                    {"role": "assistant", "content": rejected or "{}"},
                    {
                        "role": "user",
                        "content": (
                            "The previous JSON was not executable: "
                            f"{problem}. Return one corrected JSON object. For delegate, "
                            "include a registered agent_name, a non-empty instruction, and "
                            "inputs.action when the target agent exposes actions. For finish, "
                            "include a non-empty final_answer. Do not add prose outside JSON.\n"
                            f"Available agents: {json.dumps(available_agents, ensure_ascii=False)}"
                        ),
                    },
                ]

        raise PlannerDecisionError(
            "planner output remained non-executable after one corrective retry"
        )

    async def run(self, task: AgentTask, context: AgentContext) -> AgentResult:
        try:
            decision = await self.decide(context, [])
            return AgentResult(
                agent_name=self.name, success=True, output=decision.model_dump()
            )
        except Exception as exc:
            return AgentResult(agent_name=self.name, success=False, error=str(exc))
