from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository.session import SessionRepository
from app.schemas.session import SessionResponse


class SessionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.sessions = SessionRepository(db)

    async def create(self) -> SessionResponse:
        model = await self.sessions.create()
        await self.db.commit()
        return SessionResponse(
            id=model.id,
            created_at=model.created_at,
            updated_at=model.updated_at,
            messages=[],
        )

    async def get(self, session_id: str) -> SessionResponse | None:
        model = await self.sessions.get(session_id)
        return SessionResponse.model_validate(model) if model else None

    async def list(self) -> list[SessionResponse]:
        models = await self.sessions.list()
        return [SessionResponse.model_validate(model) for model in models]

    async def delete(self, session_id: str) -> bool:
        deleted = await self.sessions.delete(session_id)
        if deleted:
            await self.db.commit()
        return deleted
