from pathlib import Path

from app.tools.filesystem import FileSystemTool
from app.tools.python_runner import PythonRunnerTool
from app.tools.registry import ToolRegistry


def build_tool_registry(workspace: Path | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(FileSystemTool(workspace or Path("./workspace")))
    registry.register(PythonRunnerTool())
    return registry
