from typing import Any

from pydantic import BaseModel, Field

from app.runtime.context import Plan
from app.runtime.events import ExecutionEvent
from app.runtime.result import AgentResult
from app.runtime.state import RunStatus


class ChatRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1, max_length=20_000)


class ChatResponse(BaseModel):
    run_id: str
    session_id: str
    status: RunStatus
    plan: Plan | None
    results: list[AgentResult]
    events: list[ExecutionEvent]
    final_answer: Any = None
    error: str | None = None
