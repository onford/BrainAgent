from __future__ import annotations

from typing import Any
from xml.etree import ElementTree


def normalize_tool_output(tool_name: str, output: Any, *, limit: int = 10) -> Any:
    """Return compact, JSON-safe evidence suitable for model and API consumption."""
    normalized = {
        "arxiv": _arxiv,
        "github": _github,
        "semantic_scholar": _semantic_scholar,
        "openalex": _openalex,
        "crossref": _crossref,
        "europe_pmc": _europe_pmc,
        "unpaywall": _unpaywall,
    }.get(tool_name)
    if normalized is not None:
        return normalized(output, limit)
    return _compact(output, depth=0, limit=limit)


def _arxiv(output: Any, limit: int) -> dict[str, Any]:
    if not isinstance(output, str):
        return _envelope("arxiv", [])
    try:
        root = ElementTree.fromstring(output)
    except ElementTree.ParseError:
        return _envelope("arxiv", [], warning="上游返回了无法解析的 Atom XML。")
    atom = "{http://www.w3.org/2005/Atom}"
    open_search = "{http://a9.com/-/spec/opensearch/1.1/}"
    items = []
    for entry in root.findall(f"{atom}entry")[:limit]:
        authors = [
            _text(author.find(f"{atom}name"))
            for author in entry.findall(f"{atom}author")
        ]
        items.append(
            {
                "title": _text(entry.find(f"{atom}title")),
                "url": _text(entry.find(f"{atom}id")),
                "published": _text(entry.find(f"{atom}published")),
                "authors": [author for author in authors if author][:8],
                "summary": _shorten(_text(entry.find(f"{atom}summary")), 700),
            }
        )
    total_text = _text(root.find(f"{open_search}totalResults"))
    total = int(total_text) if total_text.isdigit() else None
    return _envelope("arxiv", items, total=total)


def _github(output: Any, limit: int) -> dict[str, Any]:
    rows = output.get("items", []) if isinstance(output, dict) else []
    items = [
        {
            "name": row.get("full_name"),
            "url": row.get("html_url"),
            "description": _shorten(row.get("description"), 500),
            "stars": row.get("stargazers_count"),
            "updated_at": row.get("updated_at"),
        }
        for row in rows[:limit]
        if isinstance(row, dict)
    ]
    total = output.get("total_count") if isinstance(output, dict) else None
    return _envelope("github", items, total=total)


def _semantic_scholar(output: Any, limit: int) -> dict[str, Any]:
    rows = output.get("data", []) if isinstance(output, dict) else []
    items = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        authors = row.get("authors", [])
        items.append(
            {
                "title": row.get("title"),
                "url": row.get("url"),
                "year": row.get("year"),
                "open_access_pdf": (row.get("openAccessPdf") or {}).get("url"),
                "authors": [
                    author.get("name")
                    for author in authors[:8]
                    if isinstance(author, dict)
                ],
            }
        )
    total = output.get("total") if isinstance(output, dict) else None
    return _envelope("semantic_scholar", items, total=total)


def _openalex(output: Any, limit: int) -> dict[str, Any]:
    rows = output.get("results", []) if isinstance(output, dict) else []
    items = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        authorships = row.get("authorships", [])
        items.append(
            {
                "title": row.get("display_name"),
                "url": row.get("doi") or row.get("id"),
                "year": row.get("publication_year"),
                "full_text_url": (
                    (row.get("best_oa_location") or {}).get("pdf_url")
                    or (row.get("best_oa_location") or {}).get("landing_page_url")
                ),
                "authors": [
                    item.get("author", {}).get("display_name")
                    for item in authorships[:8]
                    if isinstance(item, dict) and isinstance(item.get("author"), dict)
                ],
            }
        )
    meta = output.get("meta", {}) if isinstance(output, dict) else {}
    total = meta.get("count") if isinstance(meta, dict) else None
    return _envelope("openalex", items, total=total)


def _crossref(output: Any, limit: int) -> dict[str, Any]:
    message = output.get("message", {}) if isinstance(output, dict) else {}
    rows = message.get("items", []) if isinstance(message, dict) else []
    items = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        title = row.get("title", [])
        items.append(
            {
                "title": title[0] if isinstance(title, list) and title else title,
                "url": row.get("URL"),
                "doi": row.get("DOI"),
                "type": row.get("type"),
                "authors": [
                    " ".join(filter(None, [author.get("given"), author.get("family")]))
                    for author in row.get("author", [])[:8]
                    if isinstance(author, dict)
                ],
            }
        )
    total = message.get("total-results") if isinstance(message, dict) else None
    return _envelope("crossref", items, total=total)


def _europe_pmc(output: Any, limit: int) -> dict[str, Any]:
    result_list = output.get("resultList", {}) if isinstance(output, dict) else {}
    rows = result_list.get("result", []) if isinstance(result_list, dict) else []
    items = [
        {
            "title": row.get("title"),
            "url": f"https://europepmc.org/article/{row.get('source')}/{row.get('id')}",
            "year": row.get("pubYear"),
            "authors": _shorten(row.get("authorString"), 300),
            "doi": row.get("doi"),
            "pmcid": row.get("pmcid"),
            "full_text_url": f"https://www.ebi.ac.uk/europepmc/webservices/rest/{row['pmcid']}/fullTextXML"
            if row.get("pmcid") and row.get("isOpenAccess") == "Y"
            else None,
        }
        for row in rows[:limit]
        if isinstance(row, dict)
    ]
    total = output.get("hitCount") if isinstance(output, dict) else None
    return _envelope("europe_pmc", items, total=total)


def _unpaywall(output: Any, limit: int) -> dict[str, Any]:
    rows = output if isinstance(output, list) else [output]
    items = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        location = row.get("best_oa_location") or {}
        url = None
        if isinstance(location, dict):
            url = location.get("url_for_pdf") or location.get("url")
        items.append(
            {
                "title": row.get("title"),
                "doi": row.get("doi"),
                "url": url,
                "is_oa": row.get("is_oa"),
            }
        )
    return _envelope("unpaywall", items)


def _envelope(
    source: str,
    items: list[dict[str, Any]],
    *,
    total: Any = None,
    warning: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source": source,
        "result_count": len(items),
        "items": items,
    }
    if total is not None:
        result["total_results"] = total
    if warning:
        result["warning"] = warning
    return result


def _compact(value: Any, *, depth: int, limit: int) -> Any:
    if depth >= 4:
        return "[内容已截断]"
    if isinstance(value, str):
        return _shorten(value, 2_000)
    if isinstance(value, dict):
        return {
            str(key): _compact(item, depth=depth + 1, limit=limit)
            for key, item in list(value.items())[:30]
        }
    if isinstance(value, (list, tuple)):
        return [_compact(item, depth=depth + 1, limit=limit) for item in value[:limit]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _shorten(str(value), 2_000)


def _shorten(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if len(text) <= max_length:
        return text
    return f"{text[:max_length].rstrip()}…"


def _text(element: ElementTree.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return " ".join(element.text.split())
