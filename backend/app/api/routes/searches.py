from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from app.api.deps import get_current_user
from app.api.routes.workflows import checked
from app.search.contracts import SearchRequest
from app.search.metric_reading import ReadingRequest

router = APIRouter(prefix="/searches", tags=["offline-search"])


@router.get("")
def index(request: Request, user=Depends(get_current_user)):
    return request.app.state.searches.list(user.owner_id)


@router.post("", status_code=202)
async def create(body: SearchRequest, request: Request, user=Depends(get_current_user)):
    from app.workflows.literature_methods import extract_methods

    workflows = request.app.state.searches.workflows
    state = checked(workflows.get, user.owner_id, body.workflow_id)
    if "data_collection" in state["outputs"]:
        await extract_methods(workflows, {**state, "id": body.workflow_id, "owner": user.owner_id})
    return checked(request.app.state.searches.create, user.owner_id, body)


@router.get("/interpretation-guide")
def guide(user=Depends(get_current_user)):
    from app.search.interpretation import interpretation_guide

    return interpretation_guide()


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


@router.post("/{identity}/metric-reading")
async def metric_reading(identity: str, body: ReadingRequest, request: Request, user=Depends(get_current_user)):
    service = request.app.state.searches
    state = checked(service.get, user.owner_id, identity)
    root = checked(service.folder, identity)
    try:
        return await service.metric_reader.generate(root, state, body)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(404, "解读所需的测量或知识库不存在") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(422, "解读未通过证据或输出校验，请检查测量与知识库") from exc
    except RuntimeError as exc:
        raise HTTPException(502, "模型解读暂不可用，请稍后重试") from exc


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
