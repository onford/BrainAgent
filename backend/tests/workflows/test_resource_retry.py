# ruff: noqa: F811
import pytest
from collections import Counter

from app.agents import build_agent_registry
from app.preprocessing.resources import ResourceError
from app.preprocessing.service import PreprocessingService
from app.workflows.schemas import WorkflowRequest
from tests.workflows.fakes import WorkflowLLM, workflow_service
from tests.workflows.test_workflow import OWNER, finish, source  # noqa: F401


@pytest.mark.asyncio
async def test_search_setup_resource_failure_retains_research_on_workflow_retry(
    source, tmp_path, monkeypatch
):  # noqa: F811
    prep = PreprocessingService(tmp_path / "prep")
    llm = WorkflowLLM()
    service = workflow_service(tmp_path / "flows", [source], prep, llm=llm)
    service.registry = build_agent_registry(preprocessing=prep, workflow=service)
    searches = service.search_service()
    original = searches.create

    def unavailable(*args, **kwargs):
        raise ResourceError("磁盘资源不足：预计需要 100 MiB，当前预算 10 MiB")

    monkeypatch.setattr(searches, "create", unavailable)
    state = service.create(
        OWNER,
        WorkflowRequest(source_root=str(source), search_budget={"max_candidates": 1}),
    )
    await service.tasks[state["id"]]
    failed = service.get(OWNER, state["id"])
    assert failed["status"] == "failed" and "磁盘资源不足" in failed["error"]
    folder = service.folder(state["id"])
    research = {
        p.relative_to(folder): p.read_bytes()
        for prefix in ("survey", "collection")
        for p in (folder / prefix).rglob("*.json")
    }
    calls = Counter(llm.calls)
    assert not failed.get("search_id")
    monkeypatch.setattr(searches, "create", original)
    service.retry(OWNER, state["id"])
    completed = await finish(service, state["id"])
    assert completed["status"] == "completed", completed["error"]
    assert {name: Counter(llm.calls)[name] for name in calls} == dict(calls)
    assert research == {p: (folder / p).read_bytes() for p in research}
    assert completed["search_id"]
