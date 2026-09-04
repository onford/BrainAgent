from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class ExecutionEvent(BaseModel):
    event_type: str
    agent_name: str | None = None
    step: int | None = None
    message: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)
