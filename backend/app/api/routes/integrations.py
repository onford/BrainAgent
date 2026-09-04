from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_credential_cipher,
    get_current_user,
    get_db,
    get_external_tool_registry,
)
from app.api.user import CurrentUser
from app.core.exceptions import (
    BrainAgentError,
    CredentialValidationError,
    ToolDisabledError,
    ToolNotFoundError,
)
from app.integrations.credentials import CredentialService
from app.integrations.registry import ExternalToolRegistry
from app.integrations.security import CredentialCipher
from app.schemas.integration import (
    ToolIntegrationResponse,
    ToolIntegrationUpdate,
    ToolValidationResponse,
)

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/tools", response_model=list[ToolIntegrationResponse])
async def list_tools(
    db: Annotated[AsyncSession, Depends(get_db)],
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[ToolIntegrationResponse]:
    return await CredentialService(db, cipher).list(user.owner_id)


@router.get("/tools/{tool_id}", response_model=ToolIntegrationResponse)
async def get_tool(
    tool_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> ToolIntegrationResponse:
    try:
        return await CredentialService(db, cipher).get(user.owner_id, tool_id)
    except ToolNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/tools/{tool_id}", response_model=ToolIntegrationResponse)
async def save_tool(
    tool_id: str,
    payload: ToolIntegrationUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> ToolIntegrationResponse:
    try:
        return await CredentialService(db, cipher).save(user.owner_id, tool_id, payload)
    except ToolNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CredentialValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/tools/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(
    tool_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> Response:
    try:
        await CredentialService(db, cipher).delete(user.owner_id, tool_id)
    except ToolNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/tools/{tool_id}/validate", response_model=ToolValidationResponse)
async def validate_tool(
    tool_id: str,
    registry: Annotated[ExternalToolRegistry, Depends(get_external_tool_registry)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> ToolValidationResponse:
    try:
        return await registry.validate(tool_id, user.owner_id)
    except ToolNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ToolDisabledError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CredentialValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BrainAgentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
