# ruff: noqa: F811
import pytest

from app.agents import build_agent_registry
from app.preprocessing.resources import ResourceError
from app.preprocessing.service import PreprocessingService
from app.workflows.schemas import WorkflowRequest
from tests.workflows.fakes import WorkflowLLM, workflow_service
from tests.workflows.test_workflow import OWNER, finish, source  # noqa: F401


@pytest.mark.asyncio
async def test_resource_failure_retains_design_and_retry_does_not_call_model_again(
    source, tmp_path, monkeypatch
):  # noqa: F811
    prep = PreprocessingService(tmp_path / "prep")
    llm = WorkflowLLM()
    service = workflow_service(tmp_path / "flows", [source], prep, llm=llm)
    service.registry = build_agent_registry(preprocessing=prep, workflow=service)
    original = prep.plan

    def unavailable(*args, **kwargs):
        raise ResourceError("磁盘资源不足：预计需要 100 MiB，当前预算 10 MiB")

    monkeypatch.setattr(prep, "plan", unavailable)
    state = service.create(
        OWNER, WorkflowRequest(source_root=str(source), subjects=["S001"])
    )
    await service.tasks[state["id"]]
    failed = service.get(OWNER, state["id"])
    assert failed["status"] == "failed" and "磁盘资源不足" in failed["error"]
    assert llm.calls.count("MethodDesign") == 1
    folder = service.folder(state["id"])
    assert (folder / "preprocessing/design.json").exists()
    assert not (folder / "preprocessing/revisions.json").exists()
    monkeypatch.setattr(prep, "plan", original)
    service.retry(OWNER, state["id"])
    completed = await finish(service, state["id"])
    assert completed["status"] == "completed", completed["error"]
    assert llm.calls.count("MethodDesign") == 1
