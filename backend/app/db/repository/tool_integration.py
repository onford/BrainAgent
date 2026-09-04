from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user_tool_integration import UserToolIntegrationModel


class ToolIntegrationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(
        self, owner_id: str, tool_id: str
    ) -> UserToolIntegrationModel | None:
        return await self.db.scalar(
            select(UserToolIntegrationModel).where(
                UserToolIntegrationModel.owner_id == owner_id,
                UserToolIntegrationModel.tool_id == tool_id,
            )
        )

    async def list_for_owner(self, owner_id: str) -> list[UserToolIntegrationModel]:
        result = await self.db.scalars(
            select(UserToolIntegrationModel).where(
                UserToolIntegrationModel.owner_id == owner_id
            )
        )
        return list(result.all())

    async def upsert(
        self,
        owner_id: str,
        tool_id: str,
        *,
        enabled: bool,
        credentials_encrypted: str,
    ) -> UserToolIntegrationModel:
        model = await self.get(owner_id, tool_id)
        if model is None:
            model = UserToolIntegrationModel(
                owner_id=owner_id,
                tool_id=tool_id,
                enabled=enabled,
                credentials_encrypted=credentials_encrypted,
            )
            self.db.add(model)
        else:
            model.enabled = enabled
            model.credentials_encrypted = credentials_encrypted
            model.status = "unvalidated"
            model.last_validated_at = None
            model.last_validation_error = None
        await self.db.flush()
        return model

    async def delete(self, owner_id: str, tool_id: str) -> bool:
        result = await self.db.execute(
            delete(UserToolIntegrationModel).where(
                UserToolIntegrationModel.owner_id == owner_id,
                UserToolIntegrationModel.tool_id == tool_id,
            )
        )
        return bool(result.rowcount)
