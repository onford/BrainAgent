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


@pytest.mark.asyncio
async def test_planner_safely_fills_omitted_delegate_fields_from_action_registry() -> None:
    llm = ScriptedLLMClient(
        [
            {
                "action": "delegate",
                "rationale": "先检查 NWB 元数据",
                "inputs": {
                    "action": "invasive_inspect",
                    "request": {"path": "/data/session.nwb"},
                },
            }
        ]
    )
    planner = PlannerAgent(llm)
    context = AgentContext(
        owner_id="test-user",
        session_id="test",
        user_message="请处理 /data/session.nwb",
    )
    decision = await planner.decide(
        context,
        [
            {
                "name": "data_preprocessing",
                "description": "preprocessing",
                "actions": ["invasive_inspect", "invasive_plan", "invasive_run"],
            }
        ],
    )

    assert decision.agent_name == "data_preprocessing"
    assert decision.instruction == context.user_message
    assert decision.inputs["action"] == "invasive_inspect"
    assert len(llm.messages_seen) == 1


@pytest.mark.asyncio
async def test_planner_retries_conflicting_agent_and_action_once() -> None:
    llm = ScriptedLLMClient(
        [
            {
                "action": "delegate",
                "rationale": "检查文件",
                "agent_name": "data_survey",
                "instruction": "检查 NWB",
                "inputs": {"action": "invasive_inspect", "request": {"path": "/data/session.nwb"}},
            },
            {
                "action": "delegate",
                "rationale": "修正目标 Agent",
                "agent_name": "data_preprocessing",
                "instruction": "检查 NWB",
                "inputs": {"action": "invasive_inspect", "request": {"path": "/data/session.nwb"}},
            },
        ]
    )
    planner = PlannerAgent(llm)
    decision = await planner.decide(
        AgentContext(owner_id="test-user", session_id="test", user_message="检查 NWB"),
        [
            {"name": "data_survey", "description": "survey", "actions": []},
            {
                "name": "data_preprocessing",
                "description": "preprocessing",
                "actions": ["invasive_inspect"],
            },
        ],
    )

    assert decision.agent_name == "data_preprocessing"
    assert len(llm.messages_seen) == 2
    assert "not executable" in llm.messages_seen[1][-1]["content"]


@pytest.mark.asyncio
async def test_planner_preflights_registered_action_request_contract() -> None:
    ref = {"id": "a" * 64, "sha256": "a" * 64}
    llm = ScriptedLLMClient(
        [
            {
                "action": "delegate",
                "rationale": "规划预处理",
                "inputs": {
                    "action": "invasive_plan",
                    "request": {"snapshot_ref": ref, "task": {"unsupported": 123}},
                },
            },
            {
                "action": "delegate",
                "rationale": "修正任务描述",
                "inputs": {
                    "action": "invasive_plan",
                    "request": {"snapshot_ref": ref, "task": "生成 T×N 矩阵"},
                },
            },
        ]
    )
    planner = PlannerAgent(llm)

    decision = await planner.decide(
        AgentContext(owner_id="test-user", session_id="test", user_message="处理 NWB"),
        [
            {
                "name": "data_preprocessing",
                "description": "preprocessing",
                "actions": ["invasive_plan"],
            }
        ],
    )

    assert decision.inputs["request"]["task"] == "生成 T×N 矩阵"
    assert len(llm.messages_seen) == 2
    assert "invalid invasive_plan request" in llm.messages_seen[1][-1]["content"]
