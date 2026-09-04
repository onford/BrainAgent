import pytest

from app.core.exceptions import ExternalToolUnavailableError, ToolNotFoundError
from app.runtime.context import AgentContext
from app.tools.python_runner import PythonRunnerTool
from app.tools.registry import ToolRegistry


class UnavailableExternalRegistry:
    async def get_client(self, tool_id, context):
        raise ExternalToolUnavailableError("internal provider detail")


@pytest.mark.asyncio
async def test_safe_python_runner() -> None:
    tool = PythonRunnerTool()
    result = await tool.execute(expression="(2 + 3) * 4")
    assert result.success
    assert result.output == 20
    unsafe = await tool.execute(expression="__import__('os').system('whoami')")
    assert not unsafe.success


def test_tool_registry() -> None:
    registry = ToolRegistry()
    registry.register(PythonRunnerTool())
    assert registry.get("python_runner").name == "python_runner"
    with pytest.raises(ToolNotFoundError):
        registry.get("missing")


@pytest.mark.asyncio
async def test_tool_registry_executes_local_tool_through_unified_api() -> None:
    registry = ToolRegistry()
    registry.register(PythonRunnerTool())
    context = AgentContext(
        owner_id="test-user",
        session_id="test-session",
        user_message="calculate",
    )

    catalog = await registry.catalog(context)
    result = await registry.execute(
        "python_runner", context, expression="(2 + 3) * 4"
    )

    assert catalog == [
        {
            "name": "python_runner",
            "description": PythonRunnerTool.description,
            "kind": "local",
            "available": True,
        }
    ]
    assert result.success
    assert result.output == 20


@pytest.mark.asyncio
async def test_tool_registry_returns_safe_external_error() -> None:
    registry = ToolRegistry(UnavailableExternalRegistry())  # type: ignore[arg-type]
    context = AgentContext(
        owner_id="test-user",
        session_id="test-session",
        user_message="search",
    )

    result = await registry.execute("arxiv", context, query="EEG")

    assert not result.success
    assert result.error == "外部服务暂时不可用，请稍后重试。"
    assert result.metadata["error_code"] == "service_unavailable"
    assert "internal provider detail" not in result.error
