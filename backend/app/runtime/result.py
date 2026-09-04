from typing import Any

from pydantic import BaseModel, Field


class Artifact(BaseModel):
    name: str
    kind: str = "data"
    uri: str | None = None
    data: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    agent_name: str
    success: bool
    output: Any = None
    artifacts: list[Artifact] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
