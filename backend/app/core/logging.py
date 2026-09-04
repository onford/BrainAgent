import logging
from typing import Any


_CONTEXT_FIELDS = ("run_id", "session_id", "agent", "iteration", "step")


class ContextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        for field in _CONTEXT_FIELDS:
            if not hasattr(record, field):
                setattr(record, field, "-")
        return super().format(record)


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = ContextFormatter(
        "%(asctime)s %(levelname)s %(name)s "
        "run_id=%(run_id)s session_id=%(session_id)s agent=%(agent)s "
        "iteration=%(iteration)s step=%(step)s %(message)s"
    )
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    for handler in root.handlers:
        handler.setFormatter(formatter)


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
