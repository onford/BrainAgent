from types import SimpleNamespace

import pytest

from app.workflows.cognition_contracts import (
    ResearchAction,
    ResearchSources,
    ToolObservation,
)
from app.workflows.survey_contracts import SearchGoal
from app.workflows.survey_research import missing_tasks, retrieve
from tests.workflows.fakes import Reader
from tests.workflows.test_parallel_research import make_cognition
from app.tools.base import ToolResult


GOAL = SearchGoal(
    target="preprocessing_methods",
    medium="paper",
    question="EEG methods",
    query="EEG preprocessing",
)
CATALOG = [
    {"name": name, "category": "literature", "available": True}
    for name in ("arxiv", "europe_pmc")
]


def observation(
    sequence,
    *,
    action="search",
    tool="arxiv",
    query="EEG",
    url=None,
    success=False,
    output=None,
):
    return ToolObservation(
        sequence=sequence,
        action=ResearchAction(
            action=action,
            tool=tool,
            query=query,
            url=url,
            rationale="test",
            purpose="literature_review",
            target=GOAL.target,
            medium="paper",
        ),
        success=success,
        output=output,
        error=None if success else "unavailable",
    )


def gaps(sources, *, pending=False, catalog=CATALOG):
    return missing_tasks(
        sources, [GOAL], catalog, "literature_review", actionable_only=pending
    )


@pytest.mark.parametrize("success", [True, False])
def test_empty_or_failed_search_requires_fallback_and_preserves_exhausted_gap(success):
    sources = ResearchSources(
        documents=[],
        observations=[observation(1, success=success, output={"items": []})],
    )
    assert gaps(sources) and gaps(sources, pending=True)
    sources.observations.append(
        observation(2, tool="europe_pmc", success=success, output={"items": []})
    )
    assert gaps(sources) and not gaps(sources, pending=True)


def test_single_provider_requires_a_distinct_reformulated_query():
    sources = ResearchSources(
        documents=[], observations=[observation(1), observation(2)]
    )
    assert gaps(sources, pending=True, catalog=CATALOG[:1])
    sources.observations.append(
        observation(3, query="electroencephalography preprocessing")
    )
    assert not gaps(sources, pending=True, catalog=CATALOG[:1])
    assert gaps(sources, catalog=CATALOG[:1])


@pytest.mark.asyncio
async def test_failed_or_abstract_read_requires_full_text_alternative():
    hit = {
        "url": "https://example.org/abstract",
        "full_text_url": "https://example.org/fulltext",
    }
    sources = ResearchSources(
        documents=[],
        observations=[
            observation(1, success=True, output={"items": [hit]}),
            observation(2, action="read", url=hit["url"]),
        ],
    )
    assert gaps(sources, pending=True)
    abstract = (await Reader().read(hit["url"], "paper")).model_copy(
        update={"text": "[Abstract] EEG methods"}
    )
    sources.documents.append(abstract)
    sources.observations[1] = observation(
        2,
        action="read",
        url=hit["url"],
        success=True,
        output={"source_id": abstract.id},
    )
    assert gaps(sources, pending=True)
    full = await Reader().read(hit["full_text_url"], "paper")
    sources.documents = [full]
    sources.observations.append(
        observation(
            3,
            action="read",
            url=hit["full_text_url"],
            success=True,
            output={"source_id": full.id},
        )
    )
    assert not gaps(sources)


@pytest.mark.asyncio
async def test_workflow_rejects_premature_finish_then_searches_backup_and_reads(
    tmp_path,
):
    class AgentLLM:
        rejected_finish = False

        async def structured_output(self, messages, model):
            import json

            data = json.loads(messages[1]["content"])
            seen = data["observations"]
            if not seen:
                action = observation(1).action
            elif not self.rejected_finish:
                self.rejected_finish = True
                action = ResearchAction(
                    action="finish",
                    rationale="incorrect premature finish",
                    purpose="literature_review",
                    target=GOAL.target,
                    medium="paper",
                )
            elif len(seen) == 1:
                action = observation(2, tool="europe_pmc").action
            elif len(seen) == 2:
                action = observation(
                    3, action="read", url="https://example.org/paper"
                ).action
            else:
                action = ResearchAction(
                    action="finish",
                    rationale="read evidence",
                    purpose="literature_review",
                    target=GOAL.target,
                    medium="paper",
                )
            return model(actions=[action.model_dump()])

    class Tools:
        async def execute(self, name, context, **kwargs):
            assert kwargs["limit"] == 10
            if name == "arxiv":
                return ToolResult(success=False, error="rate limited")
            return ToolResult(
                success=True,
                output={
                    "items": [{"title": "EEG", "url": "https://example.org/paper"}]
                },
            )

    agent = make_cognition(tmp_path, Reader(), AgentLLM())
    agent.tools = Tools()
    sources = ResearchSources(documents=[], observations=[])
    missing = await retrieve(
        agent,
        SimpleNamespace(literature=[GOAL]),
        {},
        sources,
        CATALOG,
        "literature_review",
        6,
    )
    assert missing == []
    assert [o.success for o in sources.observations] == [False, True, True]
    assert len(sources.documents) == 1
