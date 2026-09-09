"""Supplemental reads remain selectable without exposing the unread document."""

from copy import deepcopy
import hashlib
from types import SimpleNamespace

import pytest

from app.workflows.cognition import WorkflowCognition
from app.workflows.cognition_contracts import (
    ResearchAction,
    ResearchSources,
    SourceDocument,
)
from app.workflows.screening import ScreeningSelection
from app.workflows.survey_research import validate_screening


QUERY = "Subjects were excluded after signal inspection."


def document():
    text = "Introductory material. " * 1400 + QUERY + " Background. " * 3000
    return SourceDocument(
        id="paper",
        url="https://example.org/paper",
        title="Dataset methods",
        kind="paper",
        text=text,
        retrieved_at="2026-09-09T00:00:00Z",
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        links=[],
        truncated=False,
    )


async def read_query(doc):
    async def read(url, kind):
        return doc

    agent = WorkflowCognition.__new__(WorkflowCognition)
    agent.reader = SimpleNamespace(read=read)
    agent.progress = lambda *args: None
    sources = ResearchSources(documents=[], observations=[])
    await agent.research_tool(
        ResearchAction(
            action="read",
            url=doc.url,
            kind="paper",
            query=QUERY,
            rationale="Read the reported exclusions beyond the preview",
        ),
        sources,
        set(),
    )
    # Exercise the persisted observation format, not a richer invented protocol.
    return ResearchSources.model_validate_json(sources.model_dump_json())


def select(contract, passage_id):
    return contract.model.model_validate(
        {
            "summary": "Reviewed supplemental evidence",
            "gaps": [],
            "entries": [
                {
                    "id": "entry",
                    "source_id": "paper",
                    "medium": "paper",
                    "target": "dataset_discussion",
                    "decision": "included",
                    "reason": "Reported exclusions",
                    "reading_scope": "partial_text",
                    "related_urls": [],
                    "findings": [
                        {
                            "id": "finding",
                            "topic": "exclusions",
                            "statement": "Subjects were excluded after signal inspection.",
                            "passage_id": passage_id,
                        }
                    ],
                }
            ],
        }
    )


@pytest.mark.asyncio
async def test_tail_query_is_selectable_with_exact_source_hash_offsets_and_quote():
    sources = await read_query(document())
    doc = sources.documents[0]
    contract = ScreeningSelection(sources)
    passages = contract.context[0]["passages"]
    selected = next(p for p in passages if QUERY in p["text"])
    assert selected["start"] > 24000
    assert selected["source_id"] == doc.id
    assert selected["source_sha256"] == doc.sha256
    assert selected["text"] == doc.text[selected["start"] : selected["end"]]
    assert selected["id"] == (
        f"{doc.id}:{doc.sha256[:12]}:{selected['start']}:{selected['end']}"
    )
    result = contract.project(select(contract, selected["id"]))
    assert result.entries[0].findings[0].quote == selected["text"]
    assert result.entries[0].findings[0].source_id == doc.id
    validate_screening(
        SimpleNamespace(validate_findings=WorkflowCognition.validate_findings),
        result,
        sources,
    )
    # Only the original preview and the returned 4000-character window are exposed.
    query_start = doc.text.index(QUERY)
    for passage in passages:
        assert 12 <= len(passage["text"]) <= 1000
        assert passage["text"] == doc.text[passage["start"] : passage["end"]]
        assert passage["end"] <= 24000 or (
            query_start - 1500
            <= passage["start"]
            < passage["end"]
            <= query_start + 2500
        )
    assert max(p["end"] for p in passages) < len(doc.text)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid", ["failed", "source", "url", "search", "query", "tampered", "stale"]
)
async def test_unverified_excerpts_do_not_enter_catalog(invalid):
    sources = await read_query(document())
    observation = sources.observations[0]
    if invalid == "failed":
        observation.success = False
    elif invalid == "source":
        observation.output["source_id"] = "another-paper"
    elif invalid == "url":
        observation.output["url"] = "https://example.org/another-paper"
    elif invalid == "search":
        observation.action.action = "search"
    elif invalid == "query":
        observation.action.query = None
    elif invalid == "tampered":
        observation.output["excerpts"][0] += " invented evidence"
    else:
        sources.documents[0].text = sources.documents[0].text.replace(
            QUERY, "Changed source"
        )
    contract = ScreeningSelection(sources)
    assert all(p["end"] <= 24000 for p in contract.context[0]["passages"])


@pytest.mark.asyncio
async def test_repeated_excerpt_text_keeps_real_offsets_and_duplicate_reads_are_deduplicated():
    doc = document()
    doc.text = "x" * 30000 + QUERY + "x" * 10000 + QUERY + "x" * 10000
    doc.sha256 = hashlib.sha256(doc.text.encode()).hexdigest()
    sources = await read_query(doc)
    assert len(sources.observations[0].output["excerpts"]) == 2
    assert len(set(sources.observations[0].output["excerpts"])) == 1
    first = ScreeningSelection(sources)
    sources.observations.append(deepcopy(sources.observations[0]))
    repeated = ScreeningSelection(sources)
    assert repeated.context == first.context
    hits = [p for p in first.context[0]["passages"] if QUERY in p["text"]]
    actual_positions = {p["start"] + p["text"].index(QUERY) for p in hits}
    assert actual_positions == {30000, 40000 + len(QUERY)}


@pytest.mark.asyncio
async def test_query_crossing_preview_boundary_is_not_split_or_promoted_to_full_text():
    doc = document()
    doc.text = "背景。" * 7996 + "xx" + QUERY + " Unread ending." * 1000
    doc.sha256 = hashlib.sha256(doc.text.encode()).hexdigest()
    assert doc.text.index(QUERY) == 23990
    sources = await read_query(doc)
    contract = ScreeningSelection(sources)
    passage = next(p for p in contract.context[0]["passages"] if QUERY in p["text"])
    assert passage["start"] < 24000 < passage["end"]
    assert passage["text"] == doc.text[passage["start"] : passage["end"]]
    assert contract.context[0]["reading_scopes"] == ("partial_text",)
    assert (
        QUERY
        in contract.project(select(contract, passage["id"]))
        .entries[0]
        .findings[0]
        .quote
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["hash", "text"])
async def test_projection_rechecks_the_selected_source_snapshot(changed):
    sources = await read_query(document())
    contract = ScreeningSelection(sources)
    passage = next(p for p in contract.context[0]["passages"] if QUERY in p["text"])
    value = select(contract, passage["id"])
    doc = sources.documents[0]
    if changed == "hash":
        doc.sha256 = "f" * 64
    else:
        doc.text = doc.text.replace(QUERY, "Changed source")
    with pytest.raises(ValueError, match="source snapshot"):
        contract.project(value)
