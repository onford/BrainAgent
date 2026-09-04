from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExecutionEventModel
from app.runtime.events import ExecutionEvent


class ExecutionEventRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_many(
        self,
        *,
        message_id: str,
        session_id: str,
        run_id: str,
        events: list[ExecutionEvent],
    ) -> list[ExecutionEventModel]:
        models = [
            ExecutionEventModel(
                message_id=message_id,
                session_id=session_id,
                run_id=run_id,
                sequence=sequence,
                event_type=event.event_type,
                agent_name=event.agent_name,
                step=event.step,
                message=event.message,
                data=event.data,
                created_at=event.timestamp.replace(tzinfo=None),
            )
            for sequence, event in enumerate(events, start=1)
        ]
        self.db.add_all(models)
        await self.db.flush()
        return models
