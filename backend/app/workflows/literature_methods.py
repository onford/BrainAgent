"""Recoverable preprocessing substage using this workflow's included read sources."""

import asyncio
from time import monotonic

from app.preprocessing.literature import (
    extraction_inputs, materialize,
)
from app.preprocessing.schemas import Evidence, PreprocessInput, Ref
from app.preprocessing.storage import digest
from app.preprocessing.units import engine_hash
from app.search.io import read, write
from .cognition import WorkflowCognition
from .schemas import MethodResearchBudget
from app.preprocessing.research_budget import open_budget


async def extract_methods(service, state):
    folder = service.folder(state["id"])
    data = PreprocessInput.model_validate(read(folder / "collection/input.json"))
    review_path, sources_path = folder / "survey/literature.json", folder / "survey/sources.json"
    review = read(review_path) if review_path.exists() else {}
    sources = read(sources_path) if sources_path.exists() else {}
    shared_output = {"sfreq": 160.0, "tmin": state["request"]["tmin"], "tmax": state["request"]["tmax"]}
    limits = MethodResearchBudget.model_validate(state["request"].get("method_research_budget", {}))
    fingerprint = digest({"version": 4, "review": review, "sources": sources,
                          "input": data.model_dump(mode="json"), "output": shared_output,
                          "engine": engine_hash(), "recovery_budget": limits.model_dump()})
    root = folder / "preprocessing/literature-methods"
    checkpoint = root / "manifest.json"
    if checkpoint.exists():
        saved = read(checkpoint)
        if saved["fingerprint"] != fingerprint:
            raise ValueError("literature method inputs changed; start a new workflow instead of mixing evidence snapshots")
        for ref in saved["methods"]:
            service.preprocessing.store.get(state["owner"], Ref.model_validate(ref), "method")
        return saved
    included = [e for e in review.get("entries", []) if e["decision"] == "included"
                and e["reading_scope"] != "abstract"]
    documents = {d["id"]: d for d in sources.get("documents", [])}
    cognition = WorkflowCognition(service, state, "data_preprocessing") if included else None
    budget = open_budget(root / 'budget.json', limits.model_dump(), fingerprint)
    manifest = {"schema_version": "3", "fingerprint": fingerprint, "workflow_id": state["id"],
                "recovery_budget": limits.model_dump(),
                "shared_output": shared_output, "methods": [], "sources": [], "absence_reasons": []}
    async def process(source_id):
        entries = [e for e in included if e["source_id"] == source_id]
        source = documents.get(source_id)
        item = {"source_id": source_id, "entry_ids": [e["id"] for e in entries], "methods": []}
        manifest["sources"].append(item)
        if source is None:
            item.update(status="blocked", reason="included source has no stored read document")
            return
        if monotonic() >= budget["deadline"]:
            item.update(status="blocked", reason="method research time budget exhausted before source extraction; no source method was inferred")
            return
        evidence = []
        for entry in entries:
            for finding in entry["findings"]:
                quote = finding["quote"]
                offset = source["text"].find(quote)
                if offset < 0:
                    raise ValueError("included finding is absent from the frozen read source")
                value = Evidence(source_url=source["url"], source_version=source["sha256"],
                    locator=f"{source_id}/{entry['id']}/{finding['id']}; text offsets {offset}:{offset + len(quote)}",
                    text=quote)
                if value not in evidence:
                    evidence.append(value)
        if not evidence:
            item.update(status="blocked", reason="included source has no located method evidence")
            return
        # Screening findings establish inclusion, but can omit later parameter
        # paragraphs. Index the actual read text as well, without fetching or
        # silently upgrading a partial document to full-text coverage.
        for offset in range(0, len(source["text"]), 1250):
            quote = source["text"][offset:offset + 1400]
            evidence.append(Evidence(source_url=source["url"], source_version=source["sha256"],
                locator=f"{source_id}; read-text offsets {offset}:{offset + len(quote)}; truncated={source['truncated']}", text=quote))
        source_ref = service.preprocessing.store.put(state["owner"], "evidence", {**source, "content": source["text"]})
        evidence = [e.model_copy(update={"artifact_ref": source_ref}) for e in evidence]
        identity = {"workflow_id": state["id"], "source_id": source_id, "source_ref": source_ref.model_dump(),
                    "entry_ids": item["entry_ids"], "source_sha256": source["sha256"], "source_url": source["url"]}
        source_key = digest(identity)[:20]
        inputs = extraction_inputs({k: v for k, v in source.items() if k != "text"}, evidence, data, shared_output)
        inputs["included_entries"] = entries
        source_root = root / source_key
        write(source_root / "input.json", inputs)
        draft_path = source_root / "extraction.json"
        request_hash = digest(inputs)
        item["input_hash"] = request_hash
        try:
            from .source_extraction import extract_source
            extraction, evidence, recovery = await extract_source(
                cognition, inputs, evidence, data, identity, source_root, budget)
            item["recovery"] = recovery
            draft_path = source_root / "resolved-extraction.json"
            methods = materialize(extraction, evidence, data, identity)
            for method in methods:
                method.lineage["extraction_path"] = draft_path.relative_to(folder).as_posix()
                method.lineage["extraction_hash"] = digest(extraction.model_dump(mode="json"))
                ref = service.preprocessing.register_method(state["owner"], method)
                manifest["methods"].append(ref.model_dump())
                item["methods"].append(ref.model_dump())
                write(source_root / f"{method.lineage['branch_id']}.json", method.model_dump(mode="json"))
            item.update(status="extracted", excluded_branches=[b.model_dump(mode="json") for b in extraction.excluded_branches],
                        reason=extraction.absence_reason)
        except (ValueError, RuntimeError, TimeoutError) as exc:
            # A failed source cannot silently disappear or stop all basic methods.
            item.update(status="blocked", reason=f"method extraction failed: {type(exc).__name__}: {exc}" +
                        ("; method research time budget exhausted" if isinstance(exc, TimeoutError) else ""))
    # Independent sources share one absolute deadline and one action ledger.
    # A slow first document must not prevent every other included source from
    # being examined. This is a concurrency cap, not a quota or a paper order.
    semaphore = asyncio.Semaphore(3)
    async def bounded(source_id):
        async with semaphore:
            await process(source_id)
    tasks = [asyncio.create_task(bounded(source_id))
             for source_id in dict.fromkeys(e["source_id"] for e in included)]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    manifest["methods"] = [ref for source in manifest["sources"] for ref in source["methods"]]
    if not included:
        manifest["absence_reasons"].append("本轮调研没有已纳入且具备正文或代码阅读证据的文献来源。")
    manifest["absence_reasons"].extend(s["reason"] for s in manifest["sources"] if s.get("reason"))
    manifest["recovery_actions_used"] = budget["used"]
    write(checkpoint, manifest)
    return manifest
