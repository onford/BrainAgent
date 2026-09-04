from collections.abc import AsyncIterator
from typing import Protocol, cast

from app.agents.registry import AgentRegistry
from app.runtime.context import AgentContext, AgentTask, Plan, PlanStep
from app.runtime.decision import AgentDecision, DecisionAction
from app.runtime.events import ExecutionEvent
from app.runtime.result import AgentResult
from app.runtime.state import RunStatus, StepStatus


class ReActPlanner(Protocol):
    name: str

    async def decide(
        self, context: AgentContext, available_agents: list[dict[str, str]]
    ) -> AgentDecision: ...


class Orchestrator:
    """Serial runtime; step execution is isolated for future scheduling strategies."""

    def __init__(
        self, registry: AgentRegistry, planner_name: str = "planner", max_iterations: int = 12
    ) -> None:
        self.registry = registry
        self.planner = cast(ReActPlanner, registry.get(planner_name))
        self.max_iterations = max_iterations

    async def execute(self, context: AgentContext) -> AgentContext:
        async for _ in self.stream(context):
            pass
        return context

    async def stream(self, context: AgentContext) -> AsyncIterator[ExecutionEvent]:
        context.status = RunStatus.PLANNING
        context.plan = context.plan or Plan(goal=context.user_message, steps=[])
        yield context.emit(
            "run_started",
            "主 Agent 开始分析请求",
            self.planner.name,
            {"run_id": context.run_id, "session_id": context.session_id},
        )
        available_agents = [
            {"name": agent.name, "description": agent.description}
            for agent in self.registry.list()
            if agent.name != self.planner.name
        ]

        for iteration in range(1, self.max_iterations + 1):
            context.status = RunStatus.PLANNING
            try:
                decision = await self.planner.decide(context, available_agents)
            except Exception as exc:
                self._fail(context, f"Planner decision failed: {exc}")
                yield context.emit("run_failed", context.error or "规划失败", self.planner.name)
                return
            yield context.emit(
                "thought",
                decision.rationale,
                self.planner.name,
                {"iteration": iteration, "action": decision.action.value},
            )
            if decision.action is DecisionAction.FINISH:
                context.status = RunStatus.COMPLETED
                context.current_step = None
                context.final_answer = decision.final_answer
                yield context.emit(
                    "run_completed",
                    "主 Agent 已完成回答",
                    self.planner.name,
                    {"final_answer": context.final_answer},
                )
                return

            agent_name = decision.agent_name or ""
            if agent_name == self.planner.name:
                self._fail(context, "Planner cannot delegate to itself")
                yield context.emit("run_failed", context.error or "无效调用")
                return
            try:
                agent = self.registry.get(agent_name)
            except Exception as exc:
                self._fail(context, str(exc))
                yield context.emit("run_failed", context.error or "Agent 不存在")
                return

            step_number = len(context.plan.steps) + 1
            step = PlanStep(
                step=step_number,
                agent=agent_name,
                task=decision.instruction or context.user_message,
                depends_on=[step_number - 1] if step_number > 1 else [],
            )
            context.plan.steps.append(step)
            context.current_step = step.step
            step.status = StepStatus.RUNNING
            step.attempts += 1
            context.status = RunStatus.RUNNING
            yield context.emit(
                "agent_started", step.task, step.agent, {"step": step.model_dump(mode="json")}
            )
            try:
                result = await agent.run(
                    AgentTask(instruction=step.task, step=step.step), context
                )
            except Exception as exc:
                result = AgentResult(agent_name=step.agent, success=False, error=str(exc))
            context.record_result(result)
            if not result.success:
                step.status = StepStatus.FAILED
                self._fail(context, result.error or f"Agent {step.agent} failed")
                yield context.emit(
                    "observation",
                    result.error or "执行失败",
                    step.agent,
                    {"result": result.model_dump(mode="json"), "step": step.model_dump(mode="json")},
                )
                yield context.emit("run_failed", context.error or "子 Agent 执行失败", step.agent)
                return
            step.status = StepStatus.COMPLETED
            yield context.emit(
                "observation",
                f"{step.agent} 执行完成，结果已写入共享 Context。",
                step.agent,
                {"result": result.model_dump(mode="json"), "step": step.model_dump(mode="json")},
            )

        self._fail(context, f"ReAct exceeded {self.max_iterations} iterations")
        yield context.emit("run_failed", context.error or "超过最大循环次数")

    @staticmethod
    def _fail(context: AgentContext, error: str) -> AgentContext:
        context.status = RunStatus.FAILED
        context.error = error
        return context
