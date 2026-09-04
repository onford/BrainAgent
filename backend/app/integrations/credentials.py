import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import CredentialValidationError, ToolNotFoundError
from app.db.models.user_tool_integration import UserToolIntegrationModel
from app.db.repository.tool_integration import ToolIntegrationRepository
from app.integrations.definitions import (
    TOOL_DEFINITION_BY_ID,
    TOOL_DEFINITIONS,
    CredentialFieldDefinition,
    CredentialFieldType,
    ToolDefinition,
)
from app.integrations.security import CredentialCipher
from app.schemas.integration import (
    CredentialFieldResponse,
    ToolIntegrationResponse,
    ToolIntegrationUpdate,
)


class CredentialService:
    MASK = "********"

    def __init__(self, db: AsyncSession, cipher: CredentialCipher) -> None:
        self.db = db
        self.cipher = cipher
        self.repository = ToolIntegrationRepository(db)

    def definition(self, tool_id: str) -> ToolDefinition:
        try:
            return TOOL_DEFINITION_BY_ID[tool_id]
        except KeyError as exc:
            raise ToolNotFoundError(f"Unknown external tool: {tool_id}") from exc

    async def list(self, owner_id: str) -> list[ToolIntegrationResponse]:
        integrations = {
            item.tool_id: item for item in await self.repository.list_for_owner(owner_id)
        }
        return [
            self._response(definition, integrations.get(definition.id))
            for definition in TOOL_DEFINITIONS
        ]

    async def get(self, owner_id: str, tool_id: str) -> ToolIntegrationResponse:
        definition = self.definition(tool_id)
        integration = await self.repository.get(owner_id, tool_id)
        return self._response(definition, integration)

    async def credentials(self, owner_id: str, tool_id: str) -> dict[str, Any]:
        self.definition(tool_id)
        integration = await self.repository.get(owner_id, tool_id)
        return self.cipher.decrypt(integration.credentials_encrypted) if integration else {}

    async def integration(
        self, owner_id: str, tool_id: str
    ) -> UserToolIntegrationModel | None:
        self.definition(tool_id)
        return await self.repository.get(owner_id, tool_id)

    async def save(
        self, owner_id: str, tool_id: str, payload: ToolIntegrationUpdate
    ) -> ToolIntegrationResponse:
        definition = self.definition(tool_id)
        existing = await self.repository.get(owner_id, tool_id)
        merged = self.cipher.decrypt(existing.credentials_encrypted) if existing else {}
        allowed = {field.key: field for field in definition.credential_schema}

        unknown = (set(payload.credentials) | set(payload.remove_credentials)) - set(allowed)
        if unknown:
            raise CredentialValidationError(
                f"Unknown credential fields: {', '.join(sorted(unknown))}"
            )
        for key in payload.remove_credentials:
            merged.pop(key, None)
        for key, value in payload.credentials.items():
            field = allowed[key]
            if field.is_secret and (value is None or value == "" or value == self.MASK):
                continue
            if value is None or value == "":
                merged.pop(key, None)
                continue
            merged[key] = self._validate_value(field, value)

        missing = [
            field.label
            for field in definition.credential_schema
            if field.required and field.key not in merged
        ]
        if payload.enabled and missing:
            raise CredentialValidationError(
                f"Missing required credentials: {', '.join(missing)}"
            )
        model = await self.repository.upsert(
            owner_id,
            tool_id,
            enabled=payload.enabled,
            credentials_encrypted=self.cipher.encrypt(merged),
        )
        await self.db.commit()
        return self._response(definition, model)

    async def delete(self, owner_id: str, tool_id: str) -> bool:
        self.definition(tool_id)
        deleted = await self.repository.delete(owner_id, tool_id)
        await self.db.commit()
        return deleted

    async def set_validation(
        self,
        owner_id: str,
        tool_id: str,
        *,
        validation_status: str,
        safe_error: str | None,
    ) -> datetime:
        integration = await self.repository.get(owner_id, tool_id)
        if integration is None:
            raise CredentialValidationError("Save this integration before validation")
        validated_at = datetime.now(UTC).replace(tzinfo=None)
        if validation_status not in {"unvalidated", "valid", "invalid"}:
            raise ValueError("Unsupported integration validation status")
        integration.status = validation_status
        integration.last_validated_at = validated_at
        integration.last_validation_error = safe_error
        await self.db.commit()
        return validated_at

    def _response(
        self,
        definition: ToolDefinition,
        integration: UserToolIntegrationModel | None,
    ) -> ToolIntegrationResponse:
        values = (
            self.cipher.decrypt(integration.credentials_encrypted) if integration else {}
        )
        fields = []
        for field in definition.credential_schema:
            configured = field.key in values
            fields.append(
                CredentialFieldResponse(
                    **field.model_dump(),
                    configured=configured,
                    value=None if field.is_secret else values.get(field.key),
                    masked_value=self.MASK if field.is_secret and configured else None,
                )
            )
        return ToolIntegrationResponse(
            id=definition.id,
            name=definition.name,
            description=definition.description,
            category=definition.category,
            credential_requirement=definition.credential_requirement,
            credential_schema=fields,
            cost_policy=definition.cost_policy,
            configured=integration is not None,
            enabled=integration.enabled if integration else True,
            status=integration.status if integration else "unvalidated",
            last_validated_at=integration.last_validated_at if integration else None,
            last_validation_error=(
                integration.last_validation_error if integration else None
            ),
        )

    @staticmethod
    def _validate_value(field: CredentialFieldDefinition, value: Any) -> Any:
        if field.type in {
            CredentialFieldType.TEXT,
            CredentialFieldType.EMAIL,
            CredentialFieldType.SECRET,
            CredentialFieldType.SELECT,
        } and not isinstance(value, str):
            raise CredentialValidationError(f"{field.label} must be text")
        if field.type == CredentialFieldType.EMAIL and not re.fullmatch(
            r"[^\s@]+@[^\s@]+\.[^\s@]+", value
        ):
            raise CredentialValidationError(f"{field.label} must be a valid email")
        if field.type == CredentialFieldType.NUMBER and (
            not isinstance(value, (int, float)) or isinstance(value, bool)
        ):
            raise CredentialValidationError(f"{field.label} must be a number")
        if field.type == CredentialFieldType.BOOLEAN and not isinstance(value, bool):
            raise CredentialValidationError(f"{field.label} must be true or false")
        if field.type == CredentialFieldType.SELECT:
            options = {option.value for option in field.options}
            if value not in options:
                raise CredentialValidationError(f"{field.label} has an invalid option")
        return value
