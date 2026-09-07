from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRunModel
from app.runtime.result import AgentResult


class AgentRunRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_from_result(
        self,
        run_id: str,
        session_id: str,
        instruction: str,
        result: AgentResult,
        finished_at: datetime,
    ) -> AgentRunModel:
        output: Any = result.output
        model = AgentRunModel(
            run_id=run_id,
            session_id=session_id,
            agent_name=result.agent_name,
            status=result.metadata.get("execution_status", "completed" if result.success else "failed"),
            input={"instruction": instruction},
            output=output,
            error=result.error,
            finished_at=None if result.metadata.get("execution_status") in ("submitted", "queued", "running") else finished_at,
        )
        self.db.add(model)
        await self.db.flush()
        return model
