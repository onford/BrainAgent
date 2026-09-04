from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.integrations.definitions import (
    CostPolicy,
    CredentialFieldType,
    CredentialOption,
    CredentialRequirement,
)


class CredentialFieldResponse(BaseModel):
    key: str
    label: str
    type: CredentialFieldType
    required: bool
    description: str | None = None
    placeholder: str | None = None
    options: list[CredentialOption] = Field(default_factory=list)
    configured: bool = False
    value: Any | None = None
    masked_value: str | None = None


class ToolIntegrationResponse(BaseModel):
    id: str
    name: str
    description: str
    category: str
    credential_requirement: CredentialRequirement
    credential_schema: list[CredentialFieldResponse]
    cost_policy: CostPolicy
    configured: bool
    enabled: bool
    status: str
    last_validated_at: datetime | None = None
    last_validation_error: str | None = None


class ToolIntegrationUpdate(BaseModel):
    enabled: bool = True
    credentials: dict[str, Any] = Field(default_factory=dict)
    remove_credentials: list[str] = Field(default_factory=list)


class ToolValidationResponse(BaseModel):
    tool_id: str
    valid: bool
    status: str
    message: str
    validated_at: datetime
