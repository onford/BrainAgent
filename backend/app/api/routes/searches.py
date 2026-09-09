from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from app.api.deps import get_current_user
from app.api.routes.workflows import checked
from app.search.contracts import SearchRequest

router = APIRouter(prefix="/searches", tags=["offline-search"])


@router.get("")
def index(request: Request, user=Depends(get_current_user)):
    return request.app.state.searches.list(user.owner_id)


@router.post("", status_code=202)
async def create(body: SearchRequest, request: Request, user=Depends(get_current_user)):
    return checked(request.app.state.searches.create, user.owner_id, body)


@router.get("/{identity}")
def get(
    identity: str,
    request: Request,
    include_artifacts: bool = True,
    user=Depends(get_current_user),
):
    return checked(
        request.app.state.searches.describe, user.owner_id, identity, include_artifacts
    )


@router.post("/{identity}/retry")
async def retry(identity: str, request: Request, user=Depends(get_current_user)):
    return checked(request.app.state.searches.retry, user.owner_id, identity)


@router.post("/{identity}/cancel")
async def cancel(identity: str, request: Request, user=Depends(get_current_user)):
    return checked(request.app.state.searches.cancel, user.owner_id, identity)


@router.get("/{identity}/artifacts/{name:path}")
def artifact(
    identity: str,
    name: str,
    request: Request,
    download: bool = True,
    user=Depends(get_current_user),
):
    path = checked(request.app.state.searches.artifact, user.owner_id, identity, name)
    return FileResponse(
        path,
        filename=path.name if download else None,
        media_type="text/html"
        if path.suffix == ".html"
        else "application/octet-stream",
        headers={
            "Cache-Control": "private, no-cache",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'",
        },
    )
