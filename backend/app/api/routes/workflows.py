from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from app.api.deps import get_current_user
from app.workflows.schemas import WorkflowRequest

router = APIRouter(prefix="/workflows", tags=["workflows"])


def checked(fn, *args):
    try:
        return fn(*args)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(404, "Resource not found") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/sources")
def sources(request: Request, user=Depends(get_current_user)):
    service = request.app.state.workflows
    return {
        "allowed_roots": [str(p) for p in service.input_roots],
        "adapters": ["eegmmidb"],
    }


@router.get("")
def index(request: Request, user=Depends(get_current_user)):
    return request.app.state.workflows.list(user.owner_id)


@router.post("", status_code=202)
async def create(
    body: WorkflowRequest, request: Request, user=Depends(get_current_user)
):
    return checked(request.app.state.workflows.create, user.owner_id, body)


@router.get("/{identity}")
def get(identity: str, request: Request, user=Depends(get_current_user)):
    return checked(request.app.state.workflows.describe, user.owner_id, identity)


@router.post("/{identity}/retry")
async def retry(identity: str, request: Request, user=Depends(get_current_user)):
    return checked(request.app.state.workflows.retry, user.owner_id, identity)


@router.get("/{identity}/artifacts/{name:path}")
def artifact(
    identity: str,
    name: str,
    request: Request,
    download: bool = True,
    user=Depends(get_current_user),
):
    path = checked(request.app.state.workflows.artifact, user.owner_id, identity, name)
    media = "text/html" if path.suffix == ".html" else "application/octet-stream"
    return FileResponse(
        path,
        media_type=media,
        filename=path.name if download else None,
        headers={
            "Cache-Control": "private, no-cache",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; base-uri 'none'",
            "X-Content-Type-Options": "nosniff",
        },
    )
