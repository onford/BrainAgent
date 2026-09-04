from pathlib import Path
from typing import Any

from app.tools.base import BaseTool, ToolResult


class FileSystemTool(BaseTool):
    name = "filesystem"
    description = "Reads and writes text files inside an explicitly configured workspace."

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def _safe_path(self, relative_path: str) -> Path:
        path = (self.workspace / relative_path).resolve()
        if path != self.workspace and self.workspace not in path.parents:
            raise ValueError("Path escapes the configured workspace")
        return path

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            action = str(kwargs.get("action", "read"))
            path = self._safe_path(str(kwargs["path"]))
            if action == "read":
                return ToolResult(success=True, output=path.read_text(encoding="utf-8"))
            if action == "write":
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(str(kwargs.get("content", "")), encoding="utf-8")
                return ToolResult(success=True, output={"path": str(path)})
            return ToolResult(success=False, error=f"Unsupported action: {action}")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
