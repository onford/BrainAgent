import json
from app.preprocessing.methods import extraction_contracts
from app.preprocessing.operation_context import factor, expand
from app.workflows.cognition_contracts import ResearchSources
from app.workflows.retrieval_context import navigation_context


def test_operation_factoring_is_lossless_for_every_registered_profile():
    full = extraction_contracts("2")
    compact = factor(full)
    assert expand(compact) == full

    def size(v):
        return len(json.dumps(v, ensure_ascii=False).encode())

    assert size(compact) < 0.8 * size(full)


def test_navigation_preserves_all_urls_actions_and_source_identity_without_fulltext_claim():
    url = "https://example.org/paper"
    payload = dict(
        documents=[
            dict(
                id="source-1",
                url=url,
                title="Source",
                kind="paper",
                retrieved_at="now",
                sha256="a" * 64,
                text="Literal text. " * 10000,
                links=[url + "/supplement"],
                truncated=True,
            )
        ],
        observations=[
            dict(
                sequence=1,
                action=dict(
                    action="search",
                    tool="test",
                    query="dataset analysis",
                    rationale="read evidence",
                ),
                success=True,
                error=None,
                output=dict(
                    items=[
                        dict(
                            title="Source",
                            url=url,
                            abstract="abstract " * 10000,
                            citations=7,
                            links=[url + "/code"],
                        )
                    ]
                ),
            )
        ],
    )
    sources = ResearchSources.model_validate(payload)
    before = sources.model_dump()
    compact = navigation_context(sources)
    assert sources.model_dump() == before
    doc = compact["sources"][0]
    assert doc["sha256"] == "a" * 64 and doc["links"] == [url + "/supplement"]
    assert doc["preview_is_full_source"] is False and doc["truncated"] is True
    observation = compact["observations"][0]
    assert observation["action"] == before["observations"][0]["action"]
    assert observation["output"]["urls"] == [url, url + "/code"]
    assert observation["output"]["items"][0]["citations"] == 7
    assert len(json.dumps(compact)) < len(json.dumps(before)) / 10
