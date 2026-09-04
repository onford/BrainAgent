import pytest

from app.agents import build_agent_registry
from app.agents.orchestrator import Orchestrator
from app.agents.planner.agent import PlannerAgent
from app.runtime.context import AgentContext
from app.runtime.state import RunStatus
from tests.fakes import ScriptedLLMClient, finish, full_workflow_responses


@pytest.mark.asyncio
async def test_full_agent_chain() -> None:
    registry = build_agent_registry()
    registry.register(PlannerAgent(ScriptedLLMClient(full_workflow_responses())))
    orchestrator = Orchestrator(registry)
    context = await orchestrator.execute(
        AgentContext(session_id="test-session", user_message="请执行 EEG 数据的完整流程")
    )
    assert context.status is RunStatus.COMPLETED
    assert [result.agent_name for result in context.agent_results] == [
        "data_survey",
        "data_collection",
        "data_preprocessing",
        "data_evaluation",
        "data_report",
        "data_delivery",
    ]
    assert context.shared_memory["data_evaluation"]["input_available"] is True
    assert context.final_answer is not None
    assert [event.event_type for event in context.events].count("thought") == 7


@pytest.mark.asyncio
async def test_orchestrator_can_finish_without_subagent() -> None:
    registry = build_agent_registry()
    registry.register(
        PlannerAgent(ScriptedLLMClient([finish("你好！有什么 EEG 任务需要处理？")]))
    )
    context = await Orchestrator(registry).execute(
        AgentContext(session_id="test-session", user_message="你好")
    )
    assert context.status is RunStatus.COMPLETED
    assert context.agent_results == []
    assert "你好" in (context.final_answer or "")
