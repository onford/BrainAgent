from collections.abc import AsyncIterator
import logging
from time import perf_counter
from typing import Protocol, cast

from app.agents.registry import AgentRegistry
from app.core.logging import log_context
from app.runtime.context import AgentContext, AgentTask, Plan, PlanStep
from app.runtime.decision import AgentDecision, DecisionAction
from app.runtime.events import ExecutionEvent
from app.runtime.result import AgentResult
from app.runtime.state import RunStatus, StepStatus


logger = logging.getLogger(__name__)


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
        run_started_at = perf_counter()
        logger.info(
            "react_run_started",
            extra=log_context(
                run_id=context.run_id,
                session_id=context.session_id,
                agent=self.planner.name,
            ),
        )
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
            planner_started_at = perf_counter()
            log_extra = log_context(
                run_id=context.run_id,
                session_id=context.session_id,
                agent=self.planner.name,
                iteration=iteration,
                step=context.current_step,
            )
            logger.info("planner_decision_started", extra=log_extra)
            try:
                decision = await self.planner.decide(context, available_agents)
            except Exception:
                logger.exception("planner_decision_failed", extra=log_extra)
                self._fail(context, "规划阶段失败，请查看后端日志。")
                yield context.emit("run_failed", context.error or "规划失败", self.planner.name)
                return
            logger.info(
                "planner_decision_completed action=%s target_agent=%s duration_ms=%.1f",
                decision.action.value,
                decision.agent_name or "-",
                (perf_counter() - planner_started_at) * 1000,
                extra=log_extra,
            )
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
                logger.info(
                    "react_run_completed iterations=%d duration_ms=%.1f",
                    iteration,
                    (perf_counter() - run_started_at) * 1000,
                    extra=log_extra,
                )
                return

            agent_name = decision.agent_name or ""
            if agent_name == self.planner.name:
                logger.error("planner_self_delegation_rejected", extra=log_extra)
                self._fail(context, "规划器不能调用自身，请查看后端日志。")
                yield context.emit("run_failed", context.error or "无效调用")
                return
            try:
                agent = self.registry.get(agent_name)
            except Exception:
                logger.exception(
                    "agent_resolution_failed target_agent=%s",
                    agent_name,
                    extra=log_extra,
                )
                self._fail(context, "规划器选择了不存在的 Agent，请查看后端日志。")
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
            agent_started_at = perf_counter()
            agent_log_extra = log_context(
                run_id=context.run_id,
                session_id=context.session_id,
                agent=step.agent,
                iteration=iteration,
                step=step.step,
            )
            logger.info("agent_execution_started", extra=agent_log_extra)
            try:
                result = await agent.run(
                    AgentTask(instruction=step.task, step=step.step), context
                )
            except Exception:
                logger.exception("agent_execution_failed", extra=agent_log_extra)
                result = AgentResult(
                    agent_name=step.agent,
                    success=False,
                    error="Agent 执行失败，请查看后端日志。",
                )
            context.record_result(result)
            if not result.success:
                logger.error(
                    "agent_returned_failure error=%s duration_ms=%.1f",
                    result.error or "unknown",
                    (perf_counter() - agent_started_at) * 1000,
                    extra=agent_log_extra,
                )
                step.status = StepStatus.FAILED
                public_error = "Agent 执行失败，请查看后端日志。"
                result.error = public_error
                self._fail(context, public_error)
                yield context.emit(
                    "observation",
                    public_error,
                    step.agent,
                    {
                        "result": {
                            **result.model_dump(mode="json"),
                            "error": public_error,
                        },
                        "step": step.model_dump(mode="json"),
                    },
                )
                yield context.emit("run_failed", context.error or "子 Agent 执行失败", step.agent)
                return
            step.status = StepStatus.COMPLETED
            logger.info(
                "agent_execution_completed duration_ms=%.1f artifacts=%d observations=%d",
                (perf_counter() - agent_started_at) * 1000,
                len(result.artifacts),
                len(result.observations),
                extra=agent_log_extra,
            )
            yield context.emit(
                "observation",
                f"{step.agent} 执行完成，结果已写入共享 Context。",
                step.agent,
                {"result": result.model_dump(mode="json"), "step": step.model_dump(mode="json")},
            )

        logger.error(
            "react_iteration_limit_exceeded max_iterations=%d duration_ms=%.1f",
            self.max_iterations,
            (perf_counter() - run_started_at) * 1000,
            extra=log_context(
                run_id=context.run_id,
                session_id=context.session_id,
                agent=self.planner.name,
                iteration=self.max_iterations,
                step=context.current_step,
            ),
        )
        self._fail(context, "Agent 编排超过最大循环次数，请调整任务或查看后端日志。")
        yield context.emit("run_failed", context.error or "超过最大循环次数")

    @staticmethod
    def _fail(context: AgentContext, error: str) -> AgentContext:
        context.status = RunStatus.FAILED
        context.error = error
        return context
