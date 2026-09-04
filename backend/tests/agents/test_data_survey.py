import pytest

from app.agents.data_survey.agent import DataSurveyAgent
from app.runtime.context import AgentContext, AgentTask
from app.tools.python_runner import PythonRunnerTool
from app.tools.registry import ToolRegistry
from tests.fakes import ScriptedLLMClient


def context() -> AgentContext:
    return AgentContext(
        owner_id="test-user",
        session_id="test-session",
        user_message="计算 2 + 3，并记录结果",
    )


@pytest.mark.asyncio
async def test_data_survey_agent_calls_registered_tool_and_returns_evidence() -> None:
    tools = ToolRegistry()
    tools.register(PythonRunnerTool())
    llm = ScriptedLLMClient(
        [
            {
                "action": "call_tool",
                "rationale": "需要计算",
                "tool_name": "python_runner",
                "arguments": {"expression": "2 + 3"},
            },
            {
                "action": "finish",
                "rationale": "证据充分",
                "summary": "计算结果为 5。",
            },
        ]
    )

    result = await DataSurveyAgent(llm, tools).run(
        AgentTask(instruction="计算 2 + 3"), context()
    )

    assert result.success
    assert result.output["summary"] == "计算结果为 5。"
    assert result.output["tool_calls"][0]["tool"] == "python_runner"
    assert result.output["tool_calls"][0]["output"] == 5
    assert result.metadata["tool_call_count"] == 1
    assert "Prior tool calls and results" in llm.messages_seen[1][-1]["content"]


@pytest.mark.asyncio
async def test_data_survey_agent_does_not_execute_unavailable_tool() -> None:
    llm = ScriptedLLMClient(
        [
            {
                "action": "call_tool",
                "rationale": "尝试未知工具",
                "tool_name": "missing",
                "arguments": {"query": "EEG"},
            },
            {
                "action": "finish",
                "rationale": "无法继续",
                "summary": "没有可用证据。",
            },
        ]
    )

    result = await DataSurveyAgent(llm, ToolRegistry()).run(
        AgentTask(instruction="检索 EEG"), context()
    )

    assert result.success
    call = result.output["tool_calls"][0]
    assert call["success"] is False
    assert call["error"] == "工具不存在或当前不可用。"
    assert call["metadata"]["error_code"] == "tool_unavailable"
