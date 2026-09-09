from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.workflows.cognition import WorkflowCognition
from app.workflows.cognition_contracts import (
    ResearchSources,
    SourceDocument,
    ToolObservation,
)
from app.workflows.screening import ScreeningSelection
from app.workflows.survey_research import validate_screening


def document(identity, kind="paper", text=None):
    return SourceDocument(
        id=identity,
        url=f"https://example.org/{identity}",
        title=identity,
        kind=kind,
        text=text
        or "Trials were extracted from EEGMMIDB. Left and right motor imagery were classified.",
        retrieved_at="2026-09-09T00:00:00Z",
        sha256="a" * 64,
        links=[],
        truncated=False,
    )


def selection(contract):
    doc = contract.context[0]
    return {
        "summary": "已筛选",
        "gaps": [],
        "entries": [
            {
                "id": "entry",
                "source_id": doc["source_id"],
                "medium": "paper",
                "target": "usage_algorithm",
                "decision": "included",
                "reason": "实际使用目标数据集",
                "reading_scope": "partial_text",
                "related_urls": [doc["url"]],
                "findings": [
                    {
                        "id": "finding",
                        "topic": "task",
                        "statement": "左右手想象分类",
                        "passage_id": doc["passages"][0]["id"],
                    }
                ],
            }
        ],
    }


def test_selected_passage_is_expanded_exactly_and_cannot_cross_sources():
    sources = ResearchSources(
        documents=[document("one"), document("two")], observations=[]
    )
    contract = ScreeningSelection(sources)
    value = selection(contract)
    result = contract.project(contract.model.model_validate(value))
    finding = result.entries[0].findings[0]
    assert finding.quote == sources.documents[0].text
    assert finding.source_id == "one"
    validate_screening(
        SimpleNamespace(validate_findings=WorkflowCognition.validate_findings),
        result,
        sources,
    )
    bad = deepcopy(value)
    bad["entries"][0]["findings"][0]["passage_id"] = contract.context[1]["passages"][0][
        "id"
    ]
    with pytest.raises(ValueError, match="literal_error"):
        contract.model.model_validate(bad)
    bad = deepcopy(value)
    bad["entries"][0]["quality"] = {"citations": 9999}
    with pytest.raises(ValueError, match="extra_forbidden"):
        contract.model.model_validate(bad)
    bad = deepcopy(value)
    bad["entries"][0]["findings"][0]["quote"] = "Invented quotation"
    with pytest.raises(ValueError, match="extra_forbidden"):
        contract.model.model_validate(bad)
    with pytest.raises(ValueError, match="unique across"):
        validate_screening(
            SimpleNamespace(validate_findings=WorkflowCognition.validate_findings),
            result,
            sources,
            ["finding"],
        )


def test_quality_comes_only_from_successful_associated_results():
    doc = document("one")
    observations = [
        ToolObservation(
            sequence=i,
            action={
                "action": "search",
                "tool": "search",
                "query": "EEG",
                "rationale": "检索",
            },
            success=success,
            output={"items": [{"url": url, **metrics}]},
            error=None,
        )
        for i, success, url, metrics in [
            (1, True, doc.url, {"venue": "Measured venue", "citations": 12}),
            (
                2,
                True,
                "https://example.org/unrelated",
                {"venue": "Wrong", "citations": 999, "stars": 900},
            ),
            (3, False, doc.url, {"citations": 100}),
        ]
    ]
    sources = ResearchSources(documents=[doc], observations=observations)
    contract = ScreeningSelection(sources)
    result = contract.project(contract.model.model_validate(selection(contract)))
    assert result.entries[0].quality.model_dump() == {
        "venue": "Measured venue",
        "citations": 12,
        "stars": None,
        "observation_ids": [1],
    }
    validate_screening(
        SimpleNamespace(validate_findings=WorkflowCognition.validate_findings),
        result,
        sources,
    )


def test_preview_and_abstract_scopes_are_structurally_constrained():
    contract = ScreeningSelection(
        ResearchSources(
            documents=[document("long", text="Relevant paper. " * 2000)],
            observations=[],
        )
    )
    value = selection(contract)
    value["entries"][0]["reading_scope"] = "full_text"
    with pytest.raises(ValueError, match="literal_error"):
        contract.model.model_validate(value)
    assert all(12 <= len(p["text"]) <= 1200 for p in contract.context[0]["passages"])
    abstract = ScreeningSelection(
        ResearchSources(
            documents=[
                document(
                    "abstract",
                    text="[Abstract] Only a summary of the dataset is available.",
                )
            ],
            observations=[],
        )
    )
    value = selection(abstract)
    with pytest.raises(ValueError, match="literal_error"):
        abstract.model.model_validate(value)
    empty = ScreeningSelection(
        ResearchSources(
            documents=[document("official", kind="official")], observations=[]
        )
    )
    assert (
        empty.project(
            empty.model(summary="无可筛选来源", entries=[], gaps=["文献缺口"])
        ).entries
        == []
    )
