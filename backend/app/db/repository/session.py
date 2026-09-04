from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import MessageModel, SessionModel


class SessionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self) -> SessionModel:
        model = SessionModel()
        self.db.add(model)
        await self.db.flush()
        return model

    async def get(self, session_id: str) -> SessionModel | None:
        query = (
            select(SessionModel)
            .where(SessionModel.id == session_id)
            .options(
                selectinload(SessionModel.messages).selectinload(
                    MessageModel.execution_events
                )
            )
        )
        return await self.db.scalar(query)

    async def list(self) -> list[SessionModel]:
        query = (
            select(SessionModel)
            .options(
                selectinload(SessionModel.messages).selectinload(
                    MessageModel.execution_events
                )
            )
            .order_by(SessionModel.updated_at.desc())
        )
        result = await self.db.scalars(query)
        return list(result.all())

    async def delete(self, session_id: str) -> bool:
        model = await self.get(session_id)
        if model is None:
            return False
        await self.db.delete(model)
        await self.db.flush()
        return True
