from contextlib import contextmanager
from contextvars import ContextVar
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


_CONTEXT_FIELDS = ("run_id", "session_id", "agent", "iteration", "step")
_LOG_CONTEXT: ContextVar[dict[str, Any]] = ContextVar("brain_agent_log_context", default={})
_MANAGED_HANDLER = "_brain_agent_managed_handler"


class ContextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = _LOG_CONTEXT.get()
        for field in _CONTEXT_FIELDS:
            if not hasattr(record, field):
                setattr(record, field, context.get(field, "-"))
        return super().format(record)


class LoggerPrefixFilter(logging.Filter):
    def __init__(self, prefixes: tuple[str, ...]) -> None:
        super().__init__()
        self.prefixes = prefixes

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.startswith(self.prefixes)


def configure_logging(
    log_dir: Path,
    *,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Configure console output and separate rotating runtime/LLM log files."""
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = ContextFormatter(
        "%(asctime)s %(levelname)s %(name)s "
        "run_id=%(run_id)s session_id=%(session_id)s agent=%(agent)s "
        "iteration=%(iteration)s step=%(step)s %(message)s"
    )
    for handler in tuple(root.handlers):
        if getattr(handler, _MANAGED_HANDLER, False):
            root.removeHandler(handler)
            handler.close()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    setattr(console, _MANAGED_HANDLER, True)
    root.addHandler(console)

    runtime_file = _rotating_handler(
        log_dir / "brain_agent.log", formatter, max_bytes, backup_count
    )
    runtime_file.addFilter(
        LoggerPrefixFilter(
            ("app.agents", "app.tools", "app.integrations", "app.services.chat_service")
        )
    )
    root.addHandler(runtime_file)

    llm_file = _rotating_handler(
        log_dir / "llm.log", formatter, max_bytes, backup_count
    )
    llm_file.addFilter(LoggerPrefixFilter(("app.llm",)))
    root.addHandler(llm_file)


def _rotating_handler(
    path: Path,
    formatter: logging.Formatter,
    max_bytes: int,
    backup_count: int,
) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path,
        maxBytes=max(1, max_bytes),
        backupCount=max(0, backup_count),
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    setattr(handler, _MANAGED_HANDLER, True)
    return handler


@contextmanager
def log_scope(**fields: Any):
    """Make run metadata available to nested LLM calls without changing their API."""
    token = _LOG_CONTEXT.set({**_LOG_CONTEXT.get(), **fields})
    try:
        yield
    finally:
        _LOG_CONTEXT.reset(token)


def current_log_context(**fields: Any) -> dict[str, Any]:
    context = _LOG_CONTEXT.get()
    return {
        "run_id": context.get("run_id", "-"),
        "session_id": context.get("session_id", "-"),
        "agent": context.get("agent", "llm"),
        "iteration": context.get("iteration", "-"),
        "step": context.get("step", "-"),
        **fields,
    }


def log_context(
    *,
    run_id: str,
    session_id: str,
    agent: str | None = None,
    iteration: int | str | None = None,
    step: int | str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Build consistent, non-secret contextual fields for agent logs."""
    return {
        "run_id": run_id,
        "session_id": session_id,
        "agent": agent or "-",
        "iteration": iteration if iteration is not None else "-",
        "step": step if step is not None else "-",
        **fields,
    }
