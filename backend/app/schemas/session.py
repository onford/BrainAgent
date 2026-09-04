from datetime import datetime

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ExecutionEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_type: str
    agent_name: str | None
    step: int | None
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(
        validation_alias=AliasChoices("timestamp", "created_at")
    )


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    role: str
    content: str
    created_at: datetime
    activities: list[ExecutionEventResponse] = Field(
        default_factory=list,
        validation_alias=AliasChoices("activities", "execution_events"),
    )


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse] = Field(default_factory=list)
