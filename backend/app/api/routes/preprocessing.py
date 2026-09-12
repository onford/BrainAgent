from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import Field
from app.api.deps import get_current_user
from app.preprocessing.schemas import (
    Contract,
    MethodSpec,
    PlanRequest,
    PreprocessInput,
    Ref,
    SurveyLiteratureBundle,
)
from app.preprocessing.service import PreprocessingService
from app.preprocessing.assets import AssetRegistration
from app.preprocessing.units import catalog
from app.runtime.context import AgentContext

router = APIRouter(prefix="/preprocessing", tags=["preprocessing"])


def service(request: Request) -> PreprocessingService:
    return request.app.state.preprocessing


def checked(fn, *args):
    try:
        return fn(*args)
    except KeyError as exc:
        raise HTTPException(404, "Resource not found") from exc
    except (ValueError, OSError, ImportError) as exc:
        raise HTTPException(422, str(exc)) from exc


class Submission(Contract):
    plan_ref: Ref


class Publication(Contract):
    method_ref: Ref
    job_ids: list[str] = Field(min_length=1)


class EvidenceUpload(Contract):
    source_url: str
    locator: str
    content: str = Field(min_length=1, max_length=12_000_000)
    source_version: str


class ResearchRequest(Contract):
    query: str = Field(min_length=1, max_length=2000)


@router.get("/units")
def units():
    return catalog()


@router.post('/assets',status_code=201)
def register_scientific_asset(body:AssetRegistration,svc=Depends(service),user=Depends(get_current_user)):
    from app.preprocessing.assets import register
    return checked(register,svc,user.owner_id,body)


@router.get("/capabilities")
def unit_capabilities():
    from app.preprocessing.capabilities import capabilities
    return capabilities()


@router.get("/graph-search/space")
def graph_search_space():
    from app.search.unit_graph_space import operation_space
    return operation_space()


from app.search.unit_graph_space import GraphSweep


@router.post("/graph-search/plans",status_code=201)
def graph_search_plans(body:GraphSweep,svc=Depends(service),user=Depends(get_current_user)):
    from app.search.unit_graph_space import plan_sweep
    return checked(plan_sweep,svc,user.owner_id,body)


@router.post("/capabilities/check")
def check_unit_capabilities(body: PreprocessInput):
    from app.preprocessing.capabilities import capabilities
    return capabilities(body)


@router.post('/capabilities/input')
def check_registered_capabilities(body:Ref,svc=Depends(service),user=Depends(get_current_user)):
    from app.preprocessing.capabilities import capabilities
    data=checked(svc.store.get,user.owner_id,body,'input')
    return capabilities(PreprocessInput.model_validate(data))


@router.post("/inputs", status_code=201)
def register_input(
    body: PreprocessInput, svc=Depends(service), user=Depends(get_current_user)
):
    return checked(svc.register_input, user.owner_id, body)


@router.post("/evidence", status_code=201)
def register_evidence(
    body: EvidenceUpload, svc=Depends(service), user=Depends(get_current_user)
):
    from app.tools.evidence import sanitize_evidence

    return svc.store.put(
        user.owner_id, "evidence", sanitize_evidence(body.model_dump())
    )


@router.get("/methods")
def methods(svc=Depends(service), user=Depends(get_current_user)):
    svc.methods.seed(user.owner_id)
    return svc.store.list_objects(user.owner_id, "method")


@router.get('/classic-pipelines')
def classic_pipeline_contracts():
    from app.preprocessing.classic_pipelines import catalog as pipeline_catalog
    return pipeline_catalog()


from app.preprocessing.classic_pipelines import PipelineConfiguration


@router.post('/classic-pipelines/configurations',status_code=201)
def classic_pipeline_configuration(body:PipelineConfiguration,svc=Depends(service),user=Depends(get_current_user)):
    from app.preprocessing.classic_pipelines import register_configuration
    return checked(register_configuration,svc.store,user.owner_id,body)


@router.post("/methods", status_code=201)
def register_method(
    body: MethodSpec, svc=Depends(service), user=Depends(get_current_user)
):
    return checked(svc.register_method, user.owner_id, body)


@router.post("/methods/publish", status_code=201)
def publish(body: Publication, svc=Depends(service), user=Depends(get_current_user)):
    return checked(svc.publish, user.owner_id, body.method_ref, body.job_ids)


@router.post("/literature", status_code=201)
async def literature(
    body: SurveyLiteratureBundle, svc=Depends(service), user=Depends(get_current_user)
):
    try:
        ref = svc.register_bundle(user.owner_id, body)
        result = await svc.methods.intake(user.owner_id, body)
        return {"bundle_ref": ref, **result}
    except KeyError as exc:
        raise HTTPException(404, "Evidence resource not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/methods/research")
async def research(
    body: ResearchRequest, request: Request, user=Depends(get_current_user)
):
    from app.agents.data_preprocessing.classic_survey import ClassicPipelineSurveyAgent

    svc = request.app.state.preprocessing
    agent = ClassicPipelineSurveyAgent(
        svc.methods.llm, request.app.state.tool_registry, svc.store
    )
    return await agent.update_library(
        AgentContext(
            owner_id=user.owner_id,
            session_id="library-maintenance",
            user_message=body.query,
        ),
        body.query,
    )


@router.post("/plans", status_code=201)
def plans(body: PlanRequest, svc=Depends(service), user=Depends(get_current_user)):
    ref, plan = checked(svc.plan, user.owner_id, body)
    return {"plan_ref": ref, "plan": plan}


@router.get("/plans/{identity}")
def plan(identity: str, svc=Depends(service), user=Depends(get_current_user)):
    return checked(
        lambda: svc.store.get(user.owner_id, Ref(id=identity, sha256=identity), "plan")
    )


@router.post("/jobs", status_code=202)
def jobs(body: Submission, svc=Depends(service), user=Depends(get_current_user)):
    return checked(svc.submit, user.owner_id, body.plan_ref)


@router.get("/plans/{identity}/job")
def plan_job(identity: str, svc=Depends(service), user=Depends(get_current_user)):
    return checked(svc.store.job_for_plan, user.owner_id, identity)


@router.get("/jobs/{job_id}")
def job(job_id: str, svc=Depends(service), user=Depends(get_current_user)):
    return checked(svc.store.status, user.owner_id, job_id)


from app.preprocessing.decisions import Confirmations


@router.get('/jobs/{job_id}/decisions')
def pending_decisions(job_id:str,svc=Depends(service),user=Depends(get_current_user)):
    from app.preprocessing.decisions import pending
    return checked(pending,svc,user.owner_id,job_id)


@router.post('/jobs/{job_id}/decisions',status_code=201)
def confirm_decisions(job_id:str,body:Confirmations,svc=Depends(service),user=Depends(get_current_user)):
    from app.preprocessing.decisions import confirm
    return checked(confirm,svc,user.owner_id,job_id,body)


@router.post("/jobs/{job_id}/{action}")
def control(
    job_id: str,
    action: Literal["cancel", "retry"],
    svc=Depends(service),
    user=Depends(get_current_user),
):
    return checked(svc.store.control, user.owner_id, job_id, action)


@router.get("/jobs/{job_id}/artifacts/{key}/{name:path}")
def artifact(
    job_id: str,
    key: str,
    name: str,
    svc=Depends(service),
    user=Depends(get_current_user),
):
    path = checked(svc.store.artifact, user.owner_id, job_id, key, name)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")
