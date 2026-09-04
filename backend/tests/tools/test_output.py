from app.tools.output import normalize_tool_output


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
