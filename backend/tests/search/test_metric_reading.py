import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from app.llm.client import LLMClient
from app.preprocessing.storage import digest, file_hash
from app.search.interpretation import interpretation_guide
from app.search.io import read, write
from app.search.metric_reading import MetricReader, ReadingRequest, compact, context, measurement


@pytest.fixture
def saved(tmp_path):
    recipe = {"nodes": []}
    guide = interpretation_guide()
    write(tmp_path / "interpretation-guide.json", guide)
    folder = tmp_path / "candidates/c/assessment/quality"
    detail = {"record_id": "r", "stages": {"processed_task": {
        "sfreq": 160, "unit": "V", "channel_names": ["C3", "C4"], "n_samples_per_epoch": 321,
        "metadata": {"history": {"operations": [{"operator": "average_reference", "frozen_parameters": {"ref_channels": "average"}}]}},
        "metrics": [{"metricID": "flat_fraction", "status": "not_applicable", "reason": "no_contiguous_5_second_epoch"}]}}}
    write(folder / "record.json", detail)
    q = {"candidate_id": "c", "input_hash": "input", "panel_hash": "panel", "candidate_recipe_hash": digest(recipe),
         "stages": {"processed_task": {"flat_fraction": {"value": None, "unit": "ratio", "status": "not_applicable",
                    "reason": "no_available_members", "denominator": {"available_subjects": 0, "expected_subjects": 1}},
                    "numerical_rank": {"value": 1, "status": "ok"}}},
         "detail_artifacts": [{"record_id": "r", "path": "record.json", "sha256": file_hash(folder / "record.json")}]}
    write(folder / "data-quality.json", q)
    ref = {"path": "quality/data-quality.json", "sha256": file_hash(folder / "data-quality.json")}
    state = {"candidates": [{"id": "c", "status": "evaluated", "receipt": {
        "assessment_path": "assessment", "assessment": {"quality": {"receipt_artifact": ref}}}}],
        "registry": [{"id": "c", "recipe": recipe}], "panel": {"panel_hash": "panel"},
        "protocol": {"input_hash": "input", "interpretation_guide_hash": digest(guide)}}
    return tmp_path, state, ReadingRequest(candidate_id="c", stage="processed_task", metric_id="flat_fraction")


class FakeLLM(LLMClient):
    def __init__(self, change=None):
        self.calls = 0
        self.change = change
        self.config = SimpleNamespace(model="test", base_url="https://example.test", reasoning_effort=None)

    async def chat(self, messages):
        self.calls += 1
        await asyncio.sleep(.01)
        ctx = json.loads(messages[-1]["content"])["context"]
        self.context = ctx
        card = ctx["cards"][0]
        result = {"assessment": "insufficient", "claims": [{"text": "任务片段不足五秒，无法用持续平坦条件判断平坦占比。",
                  "evidence_ids": ["metric:flat_fraction", "missing", "execution"],
                  "card_ids": [card["id"]], "source_ids": [card["source_ids"][0]]}], "next_check": None}
        if self.change:
            self.change(result)
        return json.dumps(result)


def test_context_resolves_record_reason_and_actual_execution(saved):
    root, state, req = saved
    ctx = context(root, state, req)
    assert ctx["evidence"]["missing"]["record_reason_counts"] == {"no_contiguous_5_second_epoch": 1}
    assert ctx["evidence"]["execution"]["profiles"][0]["executed_operations"][0]["operator"] == "average_reference"
    assert ctx["evidence"]["metric:flat_fraction"]["value"] is None
    assert all("flat_fraction" in c["metrics"] for c in ctx["cards"])


def test_small_threshold_curves_preserve_their_axes_but_large_arrays_are_not_fake_curves():
    row = {"value": [.01, .001, 0], "axes": {"thresholds_uv": [30, 50, 100]}}
    assert measurement(row) == row
    summary = compact(list(range(100)))
    assert summary["array_summary_only"] is True
    assert summary["minimum"] == 0 and summary["maximum"] == 99


@pytest.mark.asyncio
async def test_concurrent_requests_and_restart_reuse_saved_reading(saved):
    root, state, req = saved
    llm = FakeLLM(); reader = MetricReader(llm)
    a, b = await asyncio.gather(reader.generate(root, state, req), reader.generate(root, state, req))
    assert a == b and llm.calls == 2
    c = await MetricReader(llm).generate(root, state, req)
    assert a == c and llm.calls == 2
    assert not (root / "search.json").exists()  # Reads never rewrite the search decision state.
    llm.config.model = "different-model"
    d = await MetricReader(llm).generate(root, state, req)
    assert d["input_hash"] != a["input_hash"] and llm.calls == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    lambda r: r.update(assessment="descriptive"),
    lambda r: r["claims"][0].update(evidence_ids=["invented-measurement"]),
    lambda r: r["claims"][0].update(card_ids=["invented-theory"]),
    lambda r: r["claims"][0].update(source_ids=["invented-paper"]),
    lambda r: r["claims"][0].update(evidence_ids=["execution"]),
])
async def test_rejects_unsupported_references_and_missing_as_measured(saved, change):
    root, state, req = saved
    with pytest.raises(ValueError):
        await MetricReader(FakeLLM(change)).generate(root, state, req)
    assert not list((root / "metric-readings").glob("*.json"))


@pytest.mark.asyncio
async def test_cache_does_not_hide_tampered_record_or_guide(saved):
    root, state, req = saved
    llm = FakeLLM(); reader = MetricReader(llm)
    await reader.generate(root, state, req)
    path = root / "candidates/c/assessment/quality/record.json"
    original = read(path)
    write(path, {**original, "record_id": "tampered"})
    with pytest.raises(ValueError, match="哈希"):
        await reader.generate(root, state, req)
    write(path, original)
    write(root / "interpretation-guide.json", {**interpretation_guide(), "reviewed_at": "changed"})
    with pytest.raises(ValueError, match="知识库哈希"):
        await reader.generate(root, state, req)
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_review_can_repair_invalid_draft_and_preserves_it_for_audit(saved):
    root, state, req = saved
    class RepairLLM(FakeLLM):
        async def chat(self, messages):
            output = await super().chat(messages)
            if self.calls == 1:
                value = json.loads(output)
                value["claims"][0]["source_ids"] = ["invented-paper"]
                return json.dumps(value)
            assert "invalid_draft" in json.loads(messages[-1]["content"])["draft"]
            return output
    llm = RepairLLM()
    result = await MetricReader(llm).generate(root, state, req)
    assert llm.calls == 2
    assert "invented-paper" in result["review"]["draft"]["invalid_draft"]
    assert "invented-paper" not in result["reading"]["claims"][0]["source_ids"]


@pytest.mark.asyncio
async def test_changed_saved_context_is_not_used_as_citation_evidence(saved):
    root, state, req = saved
    llm = FakeLLM()
    result = await MetricReader(llm).generate(root, state, req)
    path = root / "metric-readings" / f"{result['input_hash']}.json"
    result["context"]["sources"][0]["url"] = "https://unrelated.test"
    write(path, result)
    with pytest.raises(ValueError, match="完整性"):
        await MetricReader(llm).generate(root, state, req)
    assert llm.calls == 2


def test_old_runs_do_not_silently_use_current_knowledge_or_other_stages(saved):
    root, state, req = saved
    older = deepcopy(state); older["protocol"].pop("interpretation_guide_hash")
    with pytest.raises(ValueError, match="未冻结"):
        context(root, older, req)
    with pytest.raises(ValueError, match="阶段未保存"):
        context(root, state, req.model_copy(update={"stage": "source_raw"}))


@pytest.mark.asyncio
async def test_owner_is_checked_before_generation():
    from fastapi import HTTPException
    from app.api.routes.searches import metric_reading
    class Service:
        def get(self, owner, identity):
            raise KeyError("not owned")
    with pytest.raises(HTTPException) as error:
        await metric_reading("a" * 32, ReadingRequest(candidate_id="c", stage="source_raw", metric_id="flat_fraction"),
                             SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(searches=Service()))),
                             SimpleNamespace(owner_id="other"))
    assert error.value.status_code == 404
