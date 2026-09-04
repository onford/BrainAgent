from app.agents.base import BaseAgent
from app.agents.planner.prompt import PLANNER_SYSTEM_PROMPT
from app.llm.client import LLMClient
from app.runtime.context import AgentContext, AgentTask
from app.runtime.decision import AgentDecision
from app.runtime.result import AgentResult


class PlannerAgent(BaseAgent):
    name = "planner"
    description = "Turns a user request into an executable agent plan."

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def decide(
        self, context: AgentContext, available_agents: list[dict[str, str]]
    ) -> AgentDecision:
        recent_history = context.conversation_history[-20:]
        return await self.llm.structured_output(
            [
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
            ],
            AgentDecision,
        )

    async def run(self, task: AgentTask, context: AgentContext) -> AgentResult:
        try:
            decision = await self.decide(context, [])
            return AgentResult(
                agent_name=self.name, success=True, output=decision.model_dump()
            )
        except Exception as exc:
            return AgentResult(agent_name=self.name, success=False, error=str(exc))
