from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.exceptions import (
    ExternalToolRateLimitError,
    ExternalToolUnavailableError,
    ToolCredentialInvalidError,
    ToolDisabledError,
    ToolNotConfiguredError,
)
from app.db.session import Database
from app.integrations.clients import GitHubClient, HttpExternalToolClient
from app.integrations.clients.base import ExternalToolClient
from app.integrations.credentials import CredentialService
from app.integrations.definitions import CredentialRequirement
from app.integrations.security import CredentialCipher
from app.runtime.context import AgentContext
from app.schemas.integration import ToolIntegrationUpdate, ToolValidationResponse


class ToolAvailabilityStatus(StrEnum):
    AVAILABLE = "available"
    NOT_CONFIGURED = "not_configured"
    DISABLED = "disabled"
    INVALID = "invalid"


class ToolAvailability(BaseModel):
    tool_id: str
    status: ToolAvailabilityStatus
    available: bool


class ExternalToolRegistry:
    def __init__(
        self,
        database: Database,
        cipher: CredentialCipher,
        *,
        timeout_seconds: float = 10,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        state_root=None,
    ) -> None:
        self._database = database
        self._cipher = cipher
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._transport = transport
        from app.integrations.clients.state import ProviderState
        self._provider_state = ProviderState(state_root) if state_root is not None else None
        self._client_factories = {
            "http": HttpExternalToolClient,
            "github": GitHubClient,
        }

    def register_client_kind(self, kind: str, factory: type[ExternalToolClient]) -> None:
        if kind in self._client_factories:
            raise ValueError(f"External client kind '{kind}' is already registered")
        self._client_factories[kind] = factory

    async def get_client(
        self, tool_id: str, context: AgentContext
    ) -> ExternalToolClient:
        return await self.get_client_for_owner(tool_id, context.owner_id)

    async def get_client_for_owner(
        self, tool_id: str, owner_id: str
    ) -> ExternalToolClient:
        async with self._database.session_factory() as db:
            service = CredentialService(db, self._cipher)
            definition = service.definition(tool_id)
            integration = await service.integration(owner_id, tool_id)
            credentials = await service.credentials(owner_id, tool_id)
            if integration is not None and not integration.enabled:
                raise ToolDisabledError(f"{tool_id} is disabled")
            if integration is not None and integration.status == "invalid":
                raise ToolCredentialInvalidError(
                    f"{tool_id} has invalid configured credentials"
                )
            if (
                definition.credential_requirement == CredentialRequirement.REQUIRED
                and integration is None
            ):
                raise ToolNotConfiguredError(f"{tool_id} is not configured")
            required = {
                field.key for field in definition.credential_schema if field.required
            }
            if required - set(credentials):
                raise ToolNotConfiguredError(f"{tool_id} is missing required credentials")
            client = self._build_client(definition, credentials)
            if isinstance(client, HttpExternalToolClient) and self._provider_state is not None:
                client.attach_state(self._provider_state, owner_id)
            return client

    async def is_available(
        self, tool_id: str, context: AgentContext
    ) -> ToolAvailability:
        try:
            await self.get_client(tool_id, context)
        except ToolNotConfiguredError:
            status = ToolAvailabilityStatus.NOT_CONFIGURED
        except ToolDisabledError:
            status = ToolAvailabilityStatus.DISABLED
        except ToolCredentialInvalidError:
            status = ToolAvailabilityStatus.INVALID
        else:
            status = ToolAvailabilityStatus.AVAILABLE
        return ToolAvailability(
            tool_id=tool_id,
            status=status,
            available=status == ToolAvailabilityStatus.AVAILABLE,
        )

    async def validate(self, tool_id: str, owner_id: str) -> ToolValidationResponse:
        async with self._database.session_factory() as db:
            service = CredentialService(db, self._cipher)
            integration = await service.integration(owner_id, tool_id)
            if integration is None:
                await service.save(owner_id, tool_id, ToolIntegrationUpdate())
        client = await self.get_client_for_owner(tool_id, owner_id)
        valid = True
        validation_status = "valid"
        safe_error: str | None = None
        try:
            await client.validate_connection()
        except ToolCredentialInvalidError:
            valid = False
            validation_status = "invalid"
            safe_error = "Credentials were rejected by the external service"
        except ExternalToolRateLimitError:
            valid = False
            validation_status = "unvalidated"
            safe_error = "External service rate limit exceeded; try again later"
        except ExternalToolUnavailableError:
            valid = False
            validation_status = "unvalidated"
            safe_error = "External service is currently unavailable"
        async with self._database.session_factory() as db:
            validated_at = await CredentialService(db, self._cipher).set_validation(
                owner_id,
                tool_id,
                validation_status=validation_status,
                safe_error=safe_error,
            )
        return ToolValidationResponse(
            tool_id=tool_id,
            valid=valid,
            status=validation_status,
            message="Connection validated" if valid else str(safe_error),
            validated_at=validated_at,
        )

    def _build_client(
        self, definition: Any, credentials: dict[str, Any]
    ) -> ExternalToolClient:
        try:
            client_type = self._client_factories[definition.client_kind]
        except KeyError as exc:
            raise RuntimeError(
                f"No external client registered for kind '{definition.client_kind}'"
            ) from exc
        return client_type(
            definition,
            credentials,
            timeout_seconds=self._timeout_seconds,
            max_retries=self._max_retries,
            transport=self._transport,
        )
