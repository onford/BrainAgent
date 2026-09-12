"""Bounded source recovery; supplementary reads never overwrite survey evidence."""

import asyncio
import httpx
import re
from time import monotonic
from typing import Literal
from urllib.parse import urljoin, urlsplit

from pydantic import Field

from app.preprocessing.literature import LiteratureExtraction, INSTRUCTION, materialize
from app.preprocessing.schemas import Contract, Evidence
from app.search.io import write
from app.search.literature_space import build_workflow_space
from app.preprocessing.literature_verification import verify_extraction, verified_claims, claims_for
from app.preprocessing.research_budget import reserve
from app.preprocessing.storage import digest
from app.search.io import read


class RecoveryAction(Contract):
    action: Literal["read_source", "reextract", "retain_blocked"]
    reason: str = Field(min_length=1)
    question: str = Field(min_length=1)
    url: str | None = None


def dependency_links(source, evidence):
    """Resolve explicitly written repository file paths, never guess filenames."""
    location = urlsplit(source["url"])
    match = re.match(r"/repos/([^/]+)/([^/]+)/", location.path) if location.hostname == "api.github.com" else re.match(r"/([^/]+)/([^/]+)/", location.path) if location.hostname == "github.com" else None
    if match is None:
        return []
    prefix = f"https://github.com/{match[1]}/{match[2]}/blob/"
    bases = [u for u in source.get("links", []) if u.startswith(prefix) and re.fullmatch(r"https://github\.com/[^/]+/[^/]+/blob/[^/]+/.+", u)]
    if not bases:
        return []
    base = bases[0]
    repository_prefix = "/".join(base.split("/")[:7]) + "/"
    result = {}
    for item in evidence:
        if item.source_url != source["url"]:
            continue
        for path in re.findall(r"(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.(?:py|ya?ml|json|toml|md|rst|cfg|txt|cff))\b", item.text):
            url = urljoin(repository_prefix, path)
            if not url.startswith(repository_prefix):
                continue
            result[url] = {"url": url, "referenced_path": path, "evidence_locator": item.locator,
                           "basis": "Literal file path in the read repository document; existence and content remain unverified until read."}
    return list(result.values())


async def recover(cognition, extraction, inputs, evidence, data, identity, root, budget):
    """A shared workflow budget bounds actual repair actions and elapsed time."""
    current, context = extraction, dict(inputs)
    records, links = [], set(inputs["source"].get("links", []))
    checkpoint = root / 'recovery-state.json'
    input_hash = digest(inputs)
    if checkpoint.exists():
        saved = read(checkpoint)
        if saved['input_hash'] != input_hash:
            raise ValueError('recovery checkpoint source/input changed')
        current = LiteratureExtraction.model_validate(saved['extraction'])
        evidence = [Evidence.model_validate(e) for e in saved['evidence']]
        records, links = saved['records'], set(saved['links'])
        identity['semantic_verification'] = saved.get('semantic_verification', {})
    dependencies = dependency_links(inputs["source"], evidence)
    links.update(d["url"] for d in dependencies)
    context["dependency_references"] = dependencies
    links.add(inputs["source"]["url"])
    while True:
        remaining = budget['deadline'] - monotonic()
        if cognition is not None and remaining > 0 and len(verified_claims(current, evidence, identity, data)) != len(claims_for(current)):
            async with asyncio.timeout(remaining):
                identity['semantic_verification'] = await verify_extraction(cognition.ask, current, evidence, data)
            write(root / 'semantic-verification.json', identity['semantic_verification'])
        methods = materialize(current, evidence, data, identity)
        _, _, intake = build_workflow_space(data, inputs["shared_output"],
            [({"id": f"recovery-{i}", "sha256": "0" * 64}, m) for i, m in enumerate(methods)])
        # A source window remains non-comparable in its native form while its
        # explicitly recorded scoring adapter can already be executable. Do not
        # ask the model to "repair" that preserved source into a different method.
        eligible_refs = {r["method_ref"]["id"] for r in intake["methods"] if r["status"] == "eligible"}
        blocked = [r for r in intake["methods"] if r["status"] == "blocked"
                   and r["method_ref"]["id"] not in eligible_refs]
        if not blocked and methods:
            return current, evidence, records
        remaining = budget["deadline"] - monotonic()
        if budget["used"] >= budget["max_actions"] or remaining <= 0:
            records.append({"status": "budget_exhausted", "blockers": blocked,
                            "absence_reason": current.absence_reason})
            write(root / "recovery.json", records)
            return current, evidence, records
        context.update(blockers=blocked, previous_extraction=current.model_dump(mode="json"),
                       allowed_source_urls=sorted(links), remaining_actions=budget["max_actions"] - budget["used"])
        reserve(budget, {'source': inputs['source']['url'], 'action': 'recovery_decision'})
        record = {"sequence": budget["used"], "status": "running", "blockers": blocked}
        records.append(record)
        try:
            async with asyncio.timeout(remaining):
                action = await cognition.ask("决定文献方法定向修复", RecoveryAction, context,
                    "Select a concrete repair for the reported compiler/evidence blockers. Read only a supplied URL. "
                    "Do not discard required source steps, invent scientific parameters or weaken output contracts. "
                    "Use retain_blocked if no supported repair remains; reextract only when existing evidence resolves the blocker.")
                record["decision"] = action.model_dump(mode="json")
                if action.action == "retain_blocked":
                    record["status"] = "retained_blocked"
                    write(root / "recovery.json", records)
                    return current, evidence, records
                if action.action == "read_source":
                    if action.url not in links:
                        raise ValueError("recovery URL is absent from the read source's actual links")
                    kind = "code" if urlsplit(action.url).hostname in {"github.com", "api.github.com"} else "paper"
                    document = await cognition.reader.read(action.url, kind)
                    source = document.model_dump(mode="json")
                    write(root / f"supplement-{budget['used']}.json", source)
                    ref = cognition.service.preprocessing.store.put(cognition.owner, "evidence", {**source, "content": source["text"]})
                    links.update(source.get("links", []))
                    for offset in range(0, len(source["text"]), 1250):
                        quote = source["text"][offset:offset + 1400]
                        evidence.append(Evidence(source_url=source["url"], source_version=source["sha256"],
                            artifact_ref=ref, locator=f"supplement-{budget['used']}; text offsets {offset}:{offset + len(quote)}; truncated={source['truncated']}", text=quote))
                    record["read_source"] = {k: v for k, v in source.items() if k != "text"}
                context["indexed_evidence"] = [{"index": i, **e.model_dump(mode="json")} for i, e in enumerate(evidence)]
                revised = await cognition.ask("依据证据修订被阻塞的方法", LiteratureExtraction, context,
                    INSTRUCTION + "\nResolve the recorded blockers using the indexed evidence. Preserve unsupported branches as blocked; "
                    "never drop them to report success. Record engineering changes explicitly. Do not change a source window to evade the shared output check.",
                    lambda value: materialize(value, evidence, data, identity))
                old_ids = {b.branch_id for b in current.branches}
                if not old_ids <= {b.branch_id for b in revised.branches}:
                    raise ValueError("recovery removed an existing source branch")
                current = revised
                record.update(status="reextracted", extraction=current.model_dump(mode="json"))
        except (ValueError, RuntimeError, TimeoutError, OSError, httpx.HTTPError) as exc:
            record.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
        finally:
            write(root / "recovery.json", records)
            write(checkpoint, dict(input_hash=input_hash, extraction=current.model_dump(mode='json'),
                evidence=[e.model_dump(mode='json') for e in evidence], records=records, links=sorted(links),
                semantic_verification=identity.get('semantic_verification', {})))
