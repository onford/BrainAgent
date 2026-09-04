import pytest

from app.core.exceptions import ToolNotFoundError
from app.tools.python_runner import PythonRunnerTool
from app.tools.registry import ToolRegistry


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
