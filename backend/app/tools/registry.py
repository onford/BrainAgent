from __future__ import annotations

from collections.abc import Iterable
import logging
from time import perf_counter
from typing import Any

from app.core.exceptions import (
    ExternalToolRateLimitError,
    ExternalToolUnavailableError,
    ToolCredentialInvalidError,
    ToolDisabledError,
    ToolNotConfiguredError,
    ToolNotFoundError,
)
from app.core.logging import log_context
from app.integrations.definitions import TOOL_DEFINITIONS
from app.integrations.clients.base import ExternalToolClient
from app.integrations.registry import ExternalToolRegistry, ToolAvailability
from app.runtime.context import AgentContext
from app.tools.base import BaseTool, ToolResult
from app.tools.output import normalize_tool_output


logger = logging.getLogger(__name__)


class ToolRegistry:
    """Unified facade for local executable tools and user-scoped integrations."""

    def __init__(self, external: ExternalToolRegistry | None = None) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._external = external

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"Unknown tool: {name}") from exc

    def list(self) -> Iterable[BaseTool]:
        return tuple(self._tools.values())

    async def catalog(self, context: AgentContext) -> list[dict[str, Any]]:
        """Describe tools without exposing credentials or concrete clients."""
        tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "kind": "local",
                "available": True,
            }
            for tool in self.list()
        ]
        if self._external is None:
            return tools
        for definition in TOOL_DEFINITIONS:
            availability = await self.is_available(definition.id, context)
            tools.append(
                {
                    "name": definition.id,
                    "description": definition.description,
                    "kind": "external",
                    "category": definition.category,
                    "available": availability.available,
                    "status": availability.status.value,
                }
            )
        return tools

    async def execute(
        self, name: str, context: AgentContext, **kwargs: Any
    ) -> ToolResult:
        """Execute a local tool or an external tool's default search operation."""
        started_at = perf_counter()
        kind = "local" if name in self._tools else "external"
        tool_log_extra = log_context(
            run_id=context.run_id,
            session_id=context.session_id,
            agent="data_survey",
            tool=name,
        )
        logger.info(
            "tool_execute_started tool=%s kind=%s argument_keys=%s",
            name,
            kind,
            sorted(kwargs),
            extra=tool_log_extra,
        )
        if name in self._tools:
            result = await self._tools[name].execute(**kwargs)
            if result.success:
                result.output = normalize_tool_output(name, result.output)
            else:
                logger.warning(
                    "local_tool_call_failed error=%s",
                    result.error or "unknown",
                    extra=log_context(
                        run_id=context.run_id,
                        session_id=context.session_id,
                        agent="data_survey",
                        tool=name,
                        error_code="local_tool_error",
                    ),
                )
                result.error = "工具执行失败，请查看后端日志。"
                result.metadata.update(
                    {"tool": name, "kind": "local", "error_code": "local_tool_error"}
                )
            logger.info(
                "tool_execute_completed tool=%s kind=local success=%s "
                "output_type=%s duration_ms=%.1f",
                name,
                result.success,
                type(result.output).__name__ if result.success else "-",
                (perf_counter() - started_at) * 1000,
                extra=tool_log_extra,
            )
            return result
        try:
            client = await self.get_client(name, context)
            query = str(kwargs.pop("query"))
            output = await client.search(query, **kwargs)
            normalized_output = normalize_tool_output(
                name, output, limit=max(1, min(int(kwargs.get("limit", 5)), 5))
            )
            result_count = (
                normalized_output.get("result_count", "-")
                if isinstance(normalized_output, dict)
                else "-"
            )
            logger.info(
                "tool_execute_completed tool=%s kind=external success=true "
                "result_count=%s duration_ms=%.1f",
                name,
                result_count,
                (perf_counter() - started_at) * 1000,
                extra=tool_log_extra,
            )
            return ToolResult(
                success=True,
                output=normalized_output,
                metadata={"tool": name, "kind": "external"},
            )
        except Exception as exc:
            error_code, safe_error = self._safe_error(exc)
            log_extra = log_context(
                run_id=context.run_id,
                session_id=context.session_id,
                agent="data_survey",
                tool=name,
                error_code=error_code,
            )
            if error_code == "unexpected_error":
                logger.exception(
                    "tool_call_failed duration_ms=%.1f",
                    (perf_counter() - started_at) * 1000,
                    extra=log_extra,
                )
            else:
                logger.warning(
                    "tool_call_failed exception_type=%s duration_ms=%.1f",
                    type(exc).__name__,
                    (perf_counter() - started_at) * 1000,
                    extra=log_extra,
                )
            return ToolResult(
                success=False,
                error=safe_error,
                metadata={
                    "tool": name,
                    "kind": "external",
                    "error_code": error_code,
                },
            )

    @staticmethod
    def _safe_error(exc: Exception) -> tuple[str, str]:
        if isinstance(exc, ToolNotConfiguredError):
            return "not_configured", "该工具尚未配置。"
        if isinstance(exc, ToolDisabledError):
            return "disabled", "该工具已被禁用。"
        if isinstance(exc, ToolCredentialInvalidError):
            return "invalid_credentials", "工具认证失败，请检查集成配置。"
        if isinstance(exc, ExternalToolRateLimitError):
            return "rate_limited", "外部服务请求过于频繁，请稍后重试。"
        if isinstance(exc, ExternalToolUnavailableError):
            return "service_unavailable", "外部服务暂时不可用，请稍后重试。"
        if isinstance(exc, KeyError) and exc.args == ("query",):
            return "invalid_arguments", "工具参数不完整：缺少 query。"
        return "unexpected_error", "工具调用失败，请查看后端日志。"

    async def get_client(
        self, tool_id: str, context: AgentContext
    ) -> ExternalToolClient:
        if self._external is None:
            raise RuntimeError("External tool registry is not configured")
        return await self._external.get_client(tool_id, context)

    async def is_available(
        self, tool_id: str, context: AgentContext
    ) -> ToolAvailability:
        if self._external is None:
            raise RuntimeError("External tool registry is not configured")
        return await self._external.is_available(tool_id, context)
