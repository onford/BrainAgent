import pytest

from app.agents.planner.agent import PlannerAgent
from app.runtime.context import AgentContext
from tests.fakes import ScriptedLLMClient, delegate


@pytest.mark.asyncio
async def test_planner_uses_structured_llm_decision() -> None:
    llm = ScriptedLLMClient([delegate("data_survey", "调研数据集")])
    planner = PlannerAgent(llm)
    decision = await planner.decide(
        AgentContext(owner_id="test-user", session_id="test", user_message="调研这个数据集"),
        [{"name": "data_survey", "description": "survey"}],
    )
    assert decision.agent_name == "data_survey"
    assert decision.instruction == "调研数据集"
    assert "Available agents" in llm.messages_seen[0][1]["content"]
