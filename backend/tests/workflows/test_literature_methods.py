"""Production substage/registration/space wiring with explicitly simulated extraction."""

import json
from types import SimpleNamespace

import pytest

from app.preprocessing.service import PreprocessingService
from app.preprocessing.schemas import Ref
from app.search.io import read, write
from app.search.service import SearchService
from app.search.contracts import SearchRequest
from app.workflows.literature_methods import extract_methods
from app.workflows.schemas import WorkflowRequest
from app.workflows.service import WorkflowService
from tests.search.test_literature_space import branch, EVIDENCE, review_double
from tests.preprocessing.conftest import make_dataset


class ExtractionDouble:
    def __init__(self, malformed_role=False):
        self.calls = 0
        self.malformed_role = malformed_role

    async def structured_output(self, messages, model):
        if model.__name__ == 'SemanticReview':
            return review_double(model, json.loads(messages[1]['content']))
        assert model.__name__ == "LiteratureExtraction"
        self.calls += 1
        inputs = json.loads(messages[1]["content"])
        assert inputs["target"]["task"] == "left_right_motor_imagery"
        assert inputs["indexed_evidence"][0]["text"] == EVIDENCE[0].text
        branches = [branch(), branch("erp", 1, .5, 20.)]
        if self.malformed_role and self.calls == 1:
            branches[0]['method']['output_roles'] = {'data': 'motor imagery epochs, 1 to 4 seconds'}
        return model.model_validate({"branches": branches})


@pytest.mark.asyncio
@pytest.mark.parametrize('malformed_role', [False, True])
async def test_main_substage_registers_multiple_methods_before_space_and_resumes(tmp_path, malformed_role):
    data = make_dataset(tmp_path / "bids", subjects=3)
    data.survey.dataset_id = data.collection.dataset_id = "eegmmidb"
    data.survey.task = "left_right_motor_imagery"
    llm = ExtractionDouble(malformed_role)
    prep = PreprocessingService(tmp_path / "methods", [data.collection.root], llm)
    workflow = WorkflowService(tmp_path / "workflows", [data.collection.root], prep, llm)
    state = workflow.create("owner", WorkflowRequest(source_root=data.collection.root), start=False)
    root = workflow.folder(state["id"])
    write(root / "collection/input.json", data.model_dump(mode="json"))
    write(root / "survey/survey.json", {"records": [{"id": r.id, "subject": r.id} for r in data.collection.records]})
    write(root / "collection/collection.json", {})
    state["outputs"] = {"data_survey": {}, "data_collection": {}}
    workflow.save(state)
    write(root / "survey/sources.json", {"documents": [{"id": "read-paper", "text": "\n".join(e.text for e in EVIDENCE),
        "title": "Test paper", "url": "fixture://paper", "sha256": "a" * 64, "truncated": False}]})
    write(root / "survey/literature.json", {"entries": [{"id": "included", "source_id": "read-paper", "decision": "included",
        "reading_scope": "full_text", "findings": [{"id": str(i), "quote": e.text} for i, e in enumerate(EVIDENCE)]}]})
    result = await extract_methods(workflow, state)
    assert len(result["methods"]) == 2 and llm.calls == 1 + int(malformed_role)
    for ref in result["methods"]:
        method = prep.store.get("owner", Ref.model_validate(ref), "method")
        assert method["lineage"]["extraction_hash"]
        assert method["lineage"]["workflow_id"] == state["id"]
    assert await extract_methods(workflow, state) == result
    assert llm.calls == 1 + int(malformed_role)
    search = SearchService(tmp_path / "searches", workflow)
    created = search.create("owner", SearchRequest(workflow_id=state["id"]), start=False)
    assert len([m for m in created["protocol"]["method_intake"]["methods"] if m["status"] == "eligible"]) == 2
    assert {r["origin"] for r in created["registry"]} >= {"basic", "literature"}
    assert (search.folder(created["id"]) / "method-status.json").exists()
    # Numerical workers have a separate owner/database: evidence references
    # must survive this boundary, not merely work in the extraction store.
    from app.preprocessing.schemas import MethodSpec
    from app.search.source_evidence import import_evidence
    engine = PreprocessingService(tmp_path / "engine", [data.collection.root])
    search_root = search.folder(created["id"])
    row = created["protocol"]["method_intake"]["methods"][0]
    compiled = MethodSpec.model_validate(read(search_root / row["compiled_method_path"]))
    import_evidence(search_root, compiled, engine.store, "offline-search")
    engine.register_method("offline-search", compiled)
    frozen_source = next(iter(created["protocol"]["source_evidence"].values()))
    write(search_root / frozen_source["path"], {"content": "tampered source"})
    with pytest.raises(ValueError, match="checksum differs"):
        import_evidence(search_root, compiled, engine.store, "offline-search")
    source = read(root / "survey/sources.json")
    source["documents"][0]["text"] += " modified"
    write(root / "survey/sources.json", source)
    with pytest.raises(ValueError, match="inputs changed"):
        await extract_methods(workflow, state)


@pytest.mark.asyncio
async def test_missing_read_document_is_explicit_and_basics_can_continue(tmp_path):
    data = make_dataset(tmp_path / "bids")
    root = tmp_path / "wf"
    write(root / "collection/input.json", data.model_dump(mode="json"))
    write(root / "survey/literature.json", {"entries": [{"id": "missing", "source_id": "not-read", "decision": "included", "reading_scope": "partial_text"}]})
    prep = PreprocessingService(tmp_path / "methods", [data.collection.root])
    service = SimpleNamespace(folder=lambda _: root, preprocessing=prep, llm=None, tools=None, source_reader=None)
    state = {"id": "test", "owner": "owner", "request": {"tmin": 0, "tmax": 2}}
    result = await extract_methods(service, state)
    assert result["methods"] == []
    assert result["absence_reasons"] == ["included source has no stored read document"]


@pytest.mark.asyncio
async def test_shared_time_budget_stops_initial_extraction_and_preserves_unread_sources(tmp_path, monkeypatch):
    import asyncio
    from app.workflows.cognition import WorkflowCognition
    from app.preprocessing import literature_verification

    # This test measures the model-call concurrency/deadline, not disk-read
    # speed. Actual upstream preparation/coordinate checks have separate tests.
    monkeypatch.setattr(literature_verification, 'observed_preparation', lambda _: [])

    data = make_dataset(tmp_path / "bids")
    root = tmp_path / "wf"
    write(root / "collection/input.json", data.model_dump(mode="json"))
    source = {"text": EVIDENCE[0].text, "url": "fixture://paper", "sha256": "a" * 64, "truncated": False}
    write(root / "survey/sources.json", {"documents": [{**source, "id": f"read-{i}"} for i in range(5)]})
    write(root / "survey/literature.json", {"entries": [{"id": f"entry-{i}", "source_id": f"read-{i}", "decision": "included", "reading_scope": "full_text", "findings": [{"id": "quote", "quote": EVIDENCE[0].text}]} for i in range(5)]})
    called = []
    async def stalled(*args, **kwargs):
        called.append(True)
        await asyncio.sleep(10)
    monkeypatch.setattr(WorkflowCognition, "ask", stalled)
    prep = PreprocessingService(tmp_path / "methods", [data.collection.root])
    service = SimpleNamespace(folder=lambda _: root, preprocessing=prep, llm=None, tools=None, source_reader=None)
    state = {"id": "test", "owner": "owner", "request": {"tmin": 0, "tmax": 2, "method_research_budget": {"max_seconds": .2}}}
    result = await extract_methods(service, state)
    assert len(called) == 3 and not result["methods"]
    assert len(result["sources"]) == 5
    assert all(s["status"] == "blocked" and "time budget exhausted" in s["reason"] for s in result["sources"])
    assert "TimeoutError" in result["sources"][0]["reason"]

    assert all("before" in row["reason"] and "extraction" in row["reason"] for row in result["sources"][3:])
