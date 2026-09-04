from datetime import UTC, datetime
from collections.abc import AsyncIterator
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import Orchestrator
from app.core.logging import log_context
from app.db.models import MessageModel
from app.db.repository.agent_run import AgentRunRepository
from app.db.repository.execution_event import ExecutionEventRepository
from app.db.repository.message import MessageRepository
from app.db.repository.session import SessionRepository
from app.runtime.context import AgentContext
from app.runtime.events import ExecutionEvent
from app.schemas.chat import ChatRequest, ChatResponse


logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self, db: AsyncSession, orchestrator: Orchestrator) -> None:
        self.db = db
        self.orchestrator = orchestrator
        self.sessions = SessionRepository(db)
        self.messages = MessageRepository(db)
        self.runs = AgentRunRepository(db)
        self.execution_events = ExecutionEventRepository(db)

    async def chat(self, request: ChatRequest, owner_id: str) -> ChatResponse | None:
        session = await self.sessions.get(request.session_id)
        if session is None:
            return None
        history = self._history(session.messages)
        await self.messages.create(request.session_id, "user", request.message)
        context = await self.orchestrator.execute(
            AgentContext(
                session_id=request.session_id,
                owner_id=owner_id,
                user_message=request.message,
                conversation_history=history,
            )
        )
        return await self._persist_and_build(request, context)

    async def session_exists(self, session_id: str) -> bool:
        return await self.sessions.get(session_id) is not None

    async def stream_chat(
        self, request: ChatRequest, owner_id: str
    ) -> AsyncIterator[ExecutionEvent]:
        session = await self.sessions.get(request.session_id)
        history = self._history(session.messages) if session else []
        await self.messages.create(request.session_id, "user", request.message)
        context = AgentContext(
            session_id=request.session_id,
            owner_id=owner_id,
            user_message=request.message,
            conversation_history=history,
        )
        try:
            async for event in self.orchestrator.stream(context):
                yield event
            response = await self._persist_and_build(request, context)
            yield ExecutionEvent(
                event_type="stream_completed",
                agent_name="planner",
                message="响应已持久化",
                data={"response": response.model_dump(mode="json")},
            )
        except BaseException:
            logger.exception(
                "stream_chat_failed",
                extra=log_context(
                    run_id=context.run_id,
                    session_id=context.session_id,
                    agent="chat_service",
                ),
            )
            await self.db.rollback()
            raise

    async def _persist_and_build(
        self, request: ChatRequest, context: AgentContext
    ) -> ChatResponse:
        instruction_by_agent = {
            step.agent: step.task for step in context.plan.steps
        } if context.plan else {}
        finished_at = datetime.now(UTC).replace(tzinfo=None)
        for result in context.agent_results:
            await self.runs.create_from_result(
                context.run_id,
                request.session_id,
                instruction_by_agent.get(result.agent_name, request.message),
                result,
                finished_at,
            )
        final_answer = self._final_answer(context)
        assistant_message = await self.messages.create(
            request.session_id, "assistant", str(final_answer)
        )
        await self.execution_events.create_many(
            message_id=assistant_message.id,
            session_id=request.session_id,
            run_id=context.run_id,
            events=context.events,
        )
        await self.db.commit()
        return ChatResponse(
            run_id=context.run_id,
            session_id=context.session_id,
            status=context.status,
            plan=context.plan,
            results=context.agent_results,
            events=context.events,
            final_answer=final_answer,
            error=context.error,
        )

    @staticmethod
    def _final_answer(context: AgentContext) -> str | dict | list | None:
        if context.final_answer:
            return context.final_answer
        if not context.agent_results:
            return context.error
        output = context.agent_results[-1].output
        if isinstance(output, dict) and "report" in output:
            return str(output["report"])
        return output

    @staticmethod
    def _history(messages: list[MessageModel]) -> list[dict[str, str]]:
        return [
            {"role": str(message.role), "content": str(message.content)}
            for message in messages
            if getattr(message, "role", None) in {"user", "assistant"}
        ]
