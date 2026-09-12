from app.tools.output import normalize_tool_output
from app.core.exceptions import ExternalToolUnavailableError
import pytest


def test_arxiv_xml_is_normalized_and_truncated() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
      <opensearch:totalResults>42</opensearch:totalResults>
      <entry>
        <id>http://arxiv.org/abs/1234.5678v1</id>
        <title>An EEG Dataset</title>
        <published>2025-01-02T00:00:00Z</published>
        <author><name>Ada Lovelace</name></author>
        <summary>Dataset details.</summary>
      </entry>
    </feed>"""

    result = normalize_tool_output("arxiv", xml)

    assert result == {
        "source": "arxiv",
        "result_count": 1,
        "items": [
            {
                "title": "An EEG Dataset",
                "url": "http://arxiv.org/abs/1234.5678v1",
                "published": "2025-01-02T00:00:00Z",
                "authors": ["Ada Lovelace"],
                "summary": "Dataset details.",
            }
        ],
        "total_results": 42,
    }
    assert "<?xml" not in str(result)


def test_malformed_arxiv_xml_does_not_echo_raw_response() -> None:
    result = normalize_tool_output("arxiv", "<feed>private upstream detail")

    assert result["items"] == []
    assert "private upstream detail" not in str(result)


def test_unpaywall_search_unwraps_actual_papers_and_empty_results():
    result = normalize_tool_output(
        "unpaywall",
        {
            "results": [
                {
                    "score": 1.2,
                    "response": {
                        "doi": "10.1234/eeg",
                        "title": "EEG methods",
                        "is_oa": True,
                        "best_oa_location": {
                            "url_for_pdf": "https://example.org/eeg.pdf"
                        },
                    },
                }
            ]
        },
    )
    assert result["result_count"] == 1
    assert result["items"][0]["title"] == "EEG methods"
    assert result["items"][0]["full_text_url"] == "https://example.org/eeg.pdf"
    assert normalize_tool_output("unpaywall", {"results": []})["result_count"] == 0


@pytest.mark.parametrize(
    "provider",
    ["semantic_scholar", "openalex", "crossref", "europe_pmc", "unpaywall", "arxiv"],
)
def test_provider_errors_are_not_silently_converted_to_empty_searches(provider):
    with pytest.raises(ExternalToolUnavailableError):
        normalize_tool_output(provider, {"error": "maintenance"})


def test_arxiv_exposes_pdf_and_rejects_error_entries():
    result = normalize_tool_output(
        "arxiv",
        """<feed xmlns="http://www.w3.org/2005/Atom">
        <entry><id>https://arxiv.org/abs/1234.5678</id><title>EEG</title>
        <link title="pdf" type="application/pdf" href="https://arxiv.org/pdf/1234.5678"/></entry></feed>""",
    )
    assert result["items"][0]["full_text_url"] == "https://arxiv.org/pdf/1234.5678"
    with pytest.raises(ExternalToolUnavailableError):
        normalize_tool_output(
            "arxiv",
            """<feed xmlns="http://www.w3.org/2005/Atom">
            <entry><id>http://arxiv.org/api/errors#incorrect_id_format</id><title>Error</title></entry></feed>""",
        )


@pytest.mark.parametrize(
    ("provider", "payload"),
    [
        (
            "openalex",
            {
                "results": [
                    {
                        "display_name": "EEG",
                        "abstract_inverted_index": {
                            "imagery": [2],
                            "EEG": [0],
                            "motor": [1],
                        },
                        "authorships": [],
                    }
                ]
            },
        ),
        (
            "semantic_scholar",
            {
                "data": [
                    {"title": "EEG", "abstract": "EEG motor imagery", "authors": []}
                ]
            },
        ),
        (
            "europe_pmc",
            {
                "resultList": {
                    "result": [
                        {
                            "title": "EEG",
                            "abstractText": "EEG motor imagery",
                            "source": "MED",
                            "id": "123",
                        }
                    ]
                }
            },
        ),
        (
            "crossref",
            {
                "message": {
                    "items": [{"title": ["EEG"], "abstract": "EEG motor imagery"}]
                }
            },
        ),
    ],
)
def test_search_summaries_keep_abstracts_for_relevance_screening(provider, payload):
    assert (
        normalize_tool_output(provider, payload)["items"][0]["summary"]
        == "EEG motor imagery"
    )
