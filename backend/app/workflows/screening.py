"""Model selects source passages; code supplies quotations and observed metrics."""

from itertools import islice
import re
from typing import Annotated, Literal, Union

from pydantic import Field, create_model

from app.preprocessing.schemas import Contract
from .cognition_contracts import Finding
from .source_reader import abstract_only
from .survey_contracts import LiteratureEntry, LiteratureScreening, QualitySignals


def urls(value):
    if isinstance(value, dict):
        return set().union(*(urls(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(urls(v) for v in value)) if value else set()
    return (
        {value}
        if isinstance(value, str) and value.startswith(("https://", "http://"))
        else set()
    )


def associated_results(doc, sources):
    origins = {doc.url} | {
        o.action.url
        for o in sources.observations
        if o.success and o.output and o.output.get("source_id") == doc.id
    }
    return [
        (o.sequence, item)
        for o in sources.observations
        if o.success
        for item in (o.output or {}).get("items", [])
        if urls(item) & origins
    ]


def observed_quality(doc, sources):
    values, used = {}, set()
    for sequence, item in sorted(
        associated_results(doc, sources), reverse=True, key=lambda pair: pair[0]
    ):
        for key in ("venue", "citations", "stars"):
            value = item.get(key)
            valid = (
                isinstance(value, str) and bool(value.strip())
                if key == "venue"
                else type(value) is int and value >= 0
            )
            if key not in values and valid:
                values[key] = value
                used.add(sequence)
    return QualitySignals(**values, observation_ids=sorted(used))


def passage_catalog(doc, sources):
    """Bind preview and verified query excerpts to the same source snapshot.

    read.query stores strings, so recover offsets using its literal query and
    1500/2500-character window, accepting only exact matches to saved excerpts.
    A repeated string alone must not resolve to an unrelated earlier occurrence.
    Offsets index decoded doc.text; source_sha256 identifies the source bytes.
    """
    ranges = [(0, min(24000, len(doc.text)))]
    for observation in sources.observations:
        output = observation.output or {}
        query = observation.action.query
        excerpts = output.get("excerpts")
        if (
            not observation.success
            or observation.action.action != "read"
            or not query
            or output.get("source_id") != doc.id
            or output.get("url", doc.url) != doc.url
            or not isinstance(excerpts, list)
        ):
            continue
        matches = islice(re.finditer(re.escape(query), doc.text, re.IGNORECASE), 4)
        for match, excerpt in zip(matches, excerpts):
            start = max(0, match.start() - 1500)
            end = min(len(doc.text), match.start() + 2500)
            if end > 24000 and doc.text[start:end] == excerpt:
                ranges.append((start, end))

    # Merge overlapping supplements without adding unread gaps or changing the
    # existing preview passage IDs at the 24000-character boundary.
    supplements = []
    for start, end in sorted(ranges[1:]):
        if supplements and start <= supplements[-1][1]:
            supplements[-1] = (supplements[-1][0], max(end, supplements[-1][1]))
        else:
            supplements.append((start, end))
    catalog = {}
    for lower, upper in [ranges[0], *supplements]:
        for start in range(lower, upper, 850):
            end = min(start + 1000, upper)
            if end - start < 12:
                continue
            identity = f"{doc.id}:{doc.sha256[:12]}:{start}:{end}"
            catalog[identity] = {
                "id": identity,
                "source_id": doc.id,
                "source_sha256": doc.sha256,
                "start": start,
                "end": end,
                "text": doc.text[start:end],
            }
    return catalog


class ScreeningSelection:
    """Runtime-only selection contract; published LiteratureReview stays fixed."""

    def __init__(self, sources):
        self.sources = sources
        self.documents = {d.id: d for d in sources.documents}
        self.passages, self.context, variants = {}, [], []
        self.passage_catalog = {}
        for index, doc in enumerate(sources.documents):
            if doc.kind not in {"paper", "code"}:
                continue
            catalog = passage_catalog(doc, sources)
            passages = {key: passage["text"] for key, passage in catalog.items()}
            if not passages:
                continue
            self.passages[doc.id] = passages
            self.passage_catalog[doc.id] = catalog
            finding = create_model(
                f"Source{index}FindingSelection",
                __base__=Contract,
                **{
                    k: (v.annotation, v)
                    for k, v in Finding.model_fields.items()
                    if k not in {"quote", "source_id"}
                },
                passage_id=(Literal[tuple(passages)], ...),
            )
            links = sorted(
                set(doc.links)
                | {doc.url}
                | urls([item for _, item in associated_results(doc, sources)])
                | {
                    o.action.url
                    for o in sources.observations
                    if o.success
                    and o.output
                    and o.output.get("source_id") == doc.id
                    and o.action.url
                }
            )
            scopes = (
                ("repository_docs", "code")
                if doc.kind == "code"
                else (
                    ("abstract",)
                    if abstract_only(doc)
                    else ("partial_text", "full_text")
                    if not doc.truncated and len(doc.text) <= 24000
                    else ("partial_text",)
                )
            )
            variants.append(
                create_model(
                    f"Source{index}LiteratureSelection",
                    __base__=Contract,
                    **{
                        k: (v.annotation, v)
                        for k, v in LiteratureEntry.model_fields.items()
                        if k
                        not in {
                            "findings",
                            "quality",
                            "source_id",
                            "medium",
                            "reading_scope",
                            "related_urls",
                        }
                    },
                    source_id=(Literal[doc.id], ...),
                    medium=(
                        Literal["paper" if doc.kind == "paper" else "repository"],
                        "paper" if doc.kind == "paper" else "repository",
                    ),
                    reading_scope=(Literal[scopes], ...),
                    findings=(list[finding], Field(max_length=8)),
                    related_urls=(list[Literal[tuple(links)]], ...),
                )
            )
            self.context.append(
                {
                    "source_id": doc.id,
                    "title": doc.title,
                    "url": doc.url,
                    "kind": doc.kind,
                    "reading_scopes": scopes,
                    "related_urls": links,
                    "observed_quality": observed_quality(doc, sources).model_dump(),
                    "passages": list(catalog.values()),
                }
            )
        entry = (
            Annotated[Union[tuple(variants)], Field(discriminator="source_id")]
            if len(variants) > 1
            else variants[0]
            if variants
            else str
        )
        self.model = create_model(
            "LiteratureScreening",
            __base__=Contract,
            summary=(str, ...),
            entries=(list[entry], Field(max_length=40 if variants else 0)),
            gaps=(list[str], ...),
        )

    def project(self, value):
        result = value.model_dump(mode="json")
        for entry in result["entries"]:
            doc = self.documents[entry["source_id"]]
            entry["quality"] = observed_quality(doc, self.sources).model_dump()
            for finding in entry["findings"]:
                identity = finding.pop("passage_id")
                passage = self.passage_catalog[doc.id][identity]
                if (
                    passage["source_id"] != doc.id
                    or passage["source_sha256"] != doc.sha256
                    or doc.text[passage["start"] : passage["end"]] != passage["text"]
                ):
                    raise ValueError(
                        "selected passage no longer matches its source snapshot"
                    )
                finding["source_id"] = doc.id
                finding["quote"] = passage["text"]
        return LiteratureScreening.model_validate(result)
