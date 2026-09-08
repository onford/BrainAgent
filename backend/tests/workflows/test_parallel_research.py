import asyncio
import json
from types import SimpleNamespace

import pytest

from app.workflows import cognition as runtime
from app.workflows.cognition import WorkflowCognition
from app.workflows.cognition_contracts import (
    ResearchAction,
    ResearchBatch,
    ResearchSources,
)
from tests.workflows.fakes import Reader, WorkflowLLM


def make_cognition(tmp_path, reader, llm=None):
    events = []
    service = SimpleNamespace(
        folder=lambda identity: tmp_path,
        llm=llm,
        tools=None,
        source_reader=reader,
        event=lambda state, stage, status, message: events.append(message),
        save=lambda state: None,
    )
    return WorkflowCognition(
        service, {"id": "test", "owner": "test", "request": {}}, "data_survey"
    )


def actions(count):
    return [
        ResearchAction(
            action="read", rationale="阅读独立来源", url=f"https://example.org/{i}"
        )
        for i in range(count)
    ]


@pytest.mark.asyncio
async def test_parallel_reads_are_bounded_ordered_and_failure_isolated(tmp_path):
    class ControlledReader(Reader):
        def __init__(self):
            self.active = self.peak = 0
            self.started, self.release = asyncio.Event(), asyncio.Event()

        async def read(self, url, kind):
            self.active += 1
            self.peak = max(self.peak, self.active)
            if self.active == 4:
                self.started.set()
            try:
                await self.release.wait()
                if url.endswith("/2"):
                    raise ValueError("one inaccessible paper")
                doc = await super().read(url, kind)
                return doc.model_copy(update={"id": url})
            finally:
                self.active -= 1

    reader = ControlledReader()
    agent = make_cognition(tmp_path, reader)
    sources = ResearchSources(documents=[], observations=[])
    task = asyncio.create_task(agent.research_batch(actions(8), sources, set()))
    try:
        await asyncio.wait_for(reader.started.wait(), 2)
        assert reader.active == 4
    finally:
        reader.release.set()
        await task
    assert reader.peak == 4 and reader.active == 0
    assert [o.sequence for o in sources.observations] == list(range(1, 9))
    assert [o.action.url for o in sources.observations] == [a.url for a in actions(8)]
    assert sum(o.success for o in sources.observations) == 7
    assert sources.observations[2].error == "one inaccessible paper"
    saved = ResearchSources.model_validate_json(
        (tmp_path / "survey/sources.json").read_text(encoding="utf-8")
    )
    assert saved == sources and len(saved.documents) == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_or_cancellation_preserves_completed_reads(
    tmp_path, monkeypatch, cancel
):
    class HangingReader(Reader):
        active = 0

        async def read(self, url, kind):
            self.active += 1
            try:
                if url.endswith("/0"):
                    await asyncio.Event().wait()
                doc = await super().read(url, kind)
                return doc.model_copy(update={"id": url})
            finally:
                self.active -= 1

    reader = HangingReader()
    agent = make_cognition(tmp_path, reader)
    persisted = asyncio.Event()
    agent.service.event = (
        lambda state, stage, status, message: persisted.set()
        if "已返回" in message
        else None
    )
    monkeypatch.setattr(runtime, "RESEARCH_TIMEOUT_SECONDS", 60 if cancel else 0.02)
    sources = ResearchSources(documents=[], observations=[])
    task = asyncio.create_task(agent.research_batch(actions(2), sources, set()))
    await asyncio.wait_for(persisted.wait(), 2)
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await task
        assert sources.observations[0].success is False
        assert "超过" in sources.observations[0].error
    assert reader.active == 0 and len(sources.documents) == 1
    saved = ResearchSources.model_validate_json(
        (tmp_path / "survey/sources.json").read_text(encoding="utf-8")
    )
    assert saved == sources
    # A cancelled earlier task leaves a gap, never a duplicate sequence on resume.
    await agent.research_batch(actions(3)[2:], sources, set())
    numbers = [o.sequence for o in sources.observations]
    assert numbers == sorted(set(numbers)) and numbers[-1] == 3


@pytest.mark.parametrize(
    "batch",
    [
        [],
        actions(5),
        [actions(1)[0]] * 2,
        [actions(1)[0], ResearchAction(action="finish", rationale="结束")],
    ],
)
def test_batch_schema_rejects_invalid_action_groups(batch):
    with pytest.raises(ValueError):
        ResearchBatch(actions=batch)


@pytest.mark.asyncio
async def test_research_budget_counts_actions_not_batches(tmp_path):
    class BatchLLM(WorkflowLLM):
        remaining = []

        async def structured_output(self, messages, model):
            if model.__name__ == "ResearchBatch":
                remaining = json.loads(messages[1]["content"])["remaining_actions"]
                self.remaining.append(remaining)
                return model(actions=actions(min(4, remaining)))
            return await super().structured_output(messages, model)

    llm = BatchLLM()
    agent = make_cognition(tmp_path, Reader(), llm)
    from tests.workflows.fakes import ResearchTools

    agent.tools = ResearchTools()
    survey = {k: {} for k in ("profile", "statistics", "checks", "records", "evidence")}
    with pytest.raises(ValueError, match="调研动作达到上限"):
        await agent.research(survey)
    assert llm.remaining == [18, 14, 10, 6, 2]
    saved = ResearchSources.model_validate_json(
        (tmp_path / "survey/sources.json").read_text(encoding="utf-8")
    )
    assert len(saved.observations) == 18
