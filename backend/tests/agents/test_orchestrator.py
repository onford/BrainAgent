import logging

import pytest

from app.agents import build_agent_registry
from app.agents.orchestrator import Orchestrator
from app.agents.planner.agent import PlannerAgent
from app.runtime.context import AgentContext
from app.runtime.state import RunStatus
from tests.fakes import ScriptedLLMClient, finish, full_workflow_responses


@pytest.mark.asyncio
async def test_chain_stops_when_real_preprocessing_inputs_are_missing() -> None:
    registry = build_agent_registry()
    registry.register(PlannerAgent(ScriptedLLMClient(full_workflow_responses())))
    orchestrator = Orchestrator(registry)
    context = await orchestrator.execute(
        AgentContext(owner_id="test-user", session_id="test-session", user_message="请执行 EEG 数据的完整流程")
    )
    assert context.status is RunStatus.COMPLETED
    assert [result.agent_name for result in context.agent_results] == [
        "data_survey",
        "data_collection",
        "data_preprocessing",
    ]
    assert "data_evaluation" not in context.shared_memory
    assert context.shared_memory["data_preprocessing"]["execution_status"] == "needs_input"
    assert context.final_answer is not None
    assert [event.event_type for event in context.events].count("thought") == 3


@pytest.mark.asyncio
async def test_orchestrator_can_finish_without_subagent() -> None:
    registry = build_agent_registry()
    registry.register(
        PlannerAgent(ScriptedLLMClient([finish("你好！有什么 EEG 任务需要处理？")]))
    )
    context = await Orchestrator(registry).execute(
        AgentContext(owner_id="test-user", session_id="test-session", user_message="你好")
    )
    assert context.status is RunStatus.COMPLETED
    assert context.agent_results == []
    assert "你好" in (context.final_answer or "")


@pytest.mark.asyncio
async def test_orchestrator_logs_failure_context_without_exposing_it_to_client(
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = build_agent_registry()
    registry.register(PlannerAgent(ScriptedLLMClient([])))
    context = AgentContext(
        owner_id="test-user",
        session_id="test-session",
        user_message="触发测试错误",
    )

    with caplog.at_level(logging.INFO, logger="app.agents.orchestrator"):
        await Orchestrator(registry).execute(context)

    failure = next(
        record
        for record in caplog.records
        if record.getMessage() == "planner_decision_failed"
    )
    assert failure.run_id == context.run_id
    assert failure.session_id == context.session_id
    assert failure.agent == "planner"
    assert failure.iteration == 1
    assert context.error == "规划阶段失败，请查看后端日志。"
    assert "No scripted LLM response remains" not in context.error
