from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import Orchestrator
from app.api.deps import get_current_user, get_db, get_orchestrator
from app.api.user import CurrentUser
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[Orchestrator, Depends(get_orchestrator)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> ChatResponse:
    response = await ChatService(db, orchestrator).chat(payload, user.owner_id)
    if response is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return response


@router.post("/stream", response_class=StreamingResponse)
async def stream_chat(
    payload: ChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    orchestrator: Annotated[Orchestrator, Depends(get_orchestrator)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> StreamingResponse:
    service = ChatService(db, orchestrator)
    if not await service.session_exists(payload.session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    async def event_source():
        async for event in service.stream_chat(payload, user.owner_id):
            yield f"data: {event.model_dump_json()}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
