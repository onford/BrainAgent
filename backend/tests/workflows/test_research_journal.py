import json

import pytest

from app.workflows.cognition_contracts import ResearchSources
from app.workflows.research_journal import ResearchJournal
from tests.workflows.test_parallel_research import actions, make_cognition
from tests.workflows.fakes import Reader


def empty():
    return ResearchSources(documents=[], observations=[])


@pytest.mark.asyncio
async def test_completed_result_survives_crash_before_aggregate_save(tmp_path):
    class CountingReader(Reader):
        calls = 0

        async def read(self, url, kind):
            self.calls += 1
            return await super().read(url, kind)

    reader = CountingReader()
    first = make_cognition(tmp_path, reader)
    first.save = lambda *args: (_ for _ in ()).throw(OSError("aggregate disk failure"))
    with pytest.raises(OSError, match="aggregate disk failure"):
        await first.research_batch(actions(1), empty(), set())
    assert not (tmp_path / "survey/sources.json").exists()
    resumed = make_cognition(tmp_path, reader)
    restored = empty()
    await resumed.research_batch(actions(1), restored, set())
    assert reader.calls == 1
    assert len(restored.documents) == 1
    assert len(restored.observations) == 2
    assert all(o.success for o in restored.observations)


@pytest.mark.asyncio
async def test_unknown_request_is_not_resent_after_restart(tmp_path):
    journal = ResearchJournal(tmp_path / "survey/research-journal.json", empty())
    journal.reserve(actions(1))
    agent = make_cognition(tmp_path, Reader())

    async def forbidden(*args):
        pytest.fail("uncertain request was sent again")

    agent.research_tool = forbidden
    sources = empty()
    journal.restore(sources, include_uncertain=True)
    await agent.research_batch(actions(1), sources, set())
    assert len(sources.observations) == 2
    assert all(not o.success and "outcome unknown" in o.error for o in sources.observations)


def test_reservations_and_absolute_deadline_survive_restart(tmp_path):
    path = tmp_path / "journal.json"
    journal = ResearchJournal(path, empty())
    purpose = "literature_review"
    request = actions(1)[0].model_copy(update={"purpose": purpose})
    journal.bind_budget(purpose, 2, {"dataset": "frozen"}, 90)
    journal.reserve([request])
    restarted = ResearchJournal(path, empty())
    restarted.bind_budget(purpose, 2, {"dataset": "frozen"}, 90)
    assert restarted.remaining(purpose) == 1
    with pytest.raises(ValueError, match="changed"):
        restarted.bind_budget(purpose, 10, {"dataset": "frozen"}, 90)
    saved = json.loads(path.read_text(encoding="utf8"))
    saved["budgets"][purpose]["expires_at"] = 0
    path.write_text(json.dumps(saved), encoding="utf8")
    assert restarted.remaining(purpose) == 0
    with pytest.raises(TimeoutError):
        restarted.reserve([request])


def test_batch_reservation_is_atomic(tmp_path):
    journal = ResearchJournal(tmp_path / "journal.json", empty())
    purpose = "literature_review"
    journal.bind_budget(purpose, 1, {}, 90)
    with pytest.raises(TimeoutError):
        journal.reserve([a.model_copy(update={"purpose": purpose}) for a in actions(2)])
    assert journal.remaining(purpose) == 1
    assert journal.read()["actions"] == []
