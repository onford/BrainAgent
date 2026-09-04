from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MessageModel, SessionModel
from app.db.models.base import utcnow


class MessageRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, session_id: str, role: str, content: str) -> MessageModel:
        model = MessageModel(session_id=session_id, role=role, content=content)
        self.db.add(model)
        await self.db.flush()
        await self.db.execute(
            update(SessionModel)
            .where(SessionModel.id == session_id)
            .values(updated_at=utcnow())
        )
        return model
