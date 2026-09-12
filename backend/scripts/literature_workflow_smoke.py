"""Replay saved read evidence through real extraction and production search workers.

No model or numerical doubles. Upstream survey/collection are reused snapshots,
not a new retrieval run. Example from backend:
  .venv-eeg/Scripts/python.exe -m scripts.literature_workflow_smoke --upstream PATH --output PATH --phase extract
  .venv-eeg/Scripts/python.exe -m scripts.literature_workflow_smoke --upstream PATH --output PATH --phase run
"""

import argparse
import asyncio
import shutil
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import Settings
from app.llm.client import create_llm_client
from app.llm.config import LLMConfig
from app.preprocessing.schemas import PreprocessInput
from app.preprocessing.inputs import working_files
from app.preprocessing.service import PreprocessingService
from app.preprocessing.storage import digest, file_hash
from app.search.contracts import SearchRequest
from app.search.io import read, write
from app.workflows.literature_methods import extract_methods
from app.workflows.schemas import WorkflowRequest
from app.workflows.service import WorkflowService


async def main(args):
    upstream, root = Path(args.upstream).resolve(), Path(args.output).resolve()
    settings = Settings()
    if not settings.llm_api_key:
        raise RuntimeError("Real extraction requires configured credentials")
    llm = create_llm_client(LLMConfig(api_key=settings.llm_api_key, base_url=settings.llm_base_url,
        model=settings.llm_model, timeout_seconds=settings.llm_timeout_seconds,
        reasoning_effort=settings.workflow_reasoning_effort if urlsplit(settings.llm_base_url).hostname == "api.deepseek.com" else None))
    data = PreprocessInput.model_validate(read(upstream / "collection/input.json"))
    prep = PreprocessingService(root / "methods", [data.collection.root], llm)
    workflows = WorkflowService(root / "workflows", [data.collection.root], prep, llm)
    active = root / "active.json"
    if not active.exists():
        state = workflows.create("literature-smoke", WorkflowRequest(source_root=data.collection.root,
            tmin=0., tmax=2., search_budget={"max_candidates": args.candidates}), start=False)
        folder = workflows.folder(state["id"])
        # Scope is declared before any score is observed; no source outcomes edited.
        ids = {"S001R04", "S002R04", "S003R04"}
        data.collection.records = [r for r in data.collection.records if r.id in ids]
        data.collection.selected_record_ids = [r.id for r in data.collection.records]
        if set(data.collection.selected_record_ids) != ids:
            raise ValueError("Replay requires the predeclared three real EEGMMIDB records")
        data.collection.selection_reason = "Predeclared three-subject software replay; all original eligible trials retained."
        original_root = Path(data.collection.root)
        copied_root = root / "input-bids"
        inventory = {}
        for record in data.collection.records:
            for relative, checksum in working_files(record).items():
                source_path = original_root / relative
                if file_hash(source_path) != checksum:
                    raise ValueError(f"selected source bytes differ from the saved inventory: {relative}")
                destination = copied_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_path, destination)
                if file_hash(destination) != checksum:
                    raise ValueError("copied source checksum differs")
                inventory[relative] = checksum
        for record in data.collection.records:
            record.files = inventory.copy()
        data.collection.root = str(copied_root)
        prep.allowed_roots.append(copied_root)
        write(folder / "collection/input.json", data.model_dump(mode="json"))
        for name in ("survey/survey.json", "collection/collection.json"):
            write(folder / name, read(upstream / name))
        review, sources = read(upstream / "survey/literature.json"), read(upstream / "survey/sources.json")
        # Optional source scope is recorded; never relabel an excluded source.
        if args.source_ids:
            requested = set(args.source_ids)
            present = {e["source_id"] for e in review["entries"] if e["decision"] == "included"}
            if not requested <= present:
                raise ValueError("source scope must use already included upstream sources")
            review["entries"] = [e for e in review["entries"] if e["source_id"] in requested]
            sources["documents"] = [d for d in sources["documents"] if d["id"] in requested]
        write(folder / "survey/literature.json", review)
        write(folder / "survey/sources.json", sources)
        state["outputs"] = {"data_survey": read(folder / "survey/survey.json"), "data_collection": read(folder / "collection/collection.json")}
        state["stages"][0]["status"] = state["stages"][1]["status"] = "completed"
        state["stages"][2]["status"] = "running"
        workflows.save(state)
        write(active, {"workflow_id": state["id"]})
        write(root / "design.json", {"upstream": str(upstream), "upstream_review_hash": file_hash(upstream / "survey/literature.json"),
            "selected_records": sorted(ids), "source_ids": args.source_ids or "all included", "real_model": settings.llm_model,
            "extraction": "real configured model", "numerics": "production engine and unchanged default EEGNet protocol",
            "retrieval": "reused local read snapshots; not a fresh retrieval", "input_hash": digest(data.model_dump(mode="json"))})
    state = workflows.get("literature-smoke", read(active)["workflow_id"])
    prep.allowed_roots.append(Path(read(workflows.folder(state["id"]) / "collection/input.json")["collection"]["root"]))
    if args.phase == "extract":
        result = await extract_methods(workflows, state)
        print("REAL EXTRACTION", "methods", len(result["methods"]), "sources", len(result["sources"]), flush=True)
        for source in result["sources"]:
            print(source["source_id"], source["status"], source.get("reason"), flush=True)
        return
    search = workflows.search_service()
    created = search.create("literature-smoke", SearchRequest(workflow_id=state["id"],
        strategy="one_shot" if args.verify_literature else "adaptive",
        budget={"max_candidates": args.candidates, "max_seconds": args.seconds, "max_proposals": 20,
                "max_diagnostics": 6, "max_retries": 1}), start=False)
    identity = created["id"]
    write(active, {"workflow_id": state["id"], "search_id": identity, "search_root": str(search.folder(identity))})
    intake = created["protocol"]["method_intake"]
    for method in intake["methods"]:
        print("CHECK", method["title"], method["status"], method["reasons"], flush=True)
    if not any(m["status"] == "eligible" for m in intake["methods"]):
        print("NO EXECUTABLE LITERATURE: exercising explicit basic-method fallback", flush=True)
    if args.verify_literature:
        # A directed acceptance run, explicitly distinct from model scheduling.
        # Existing one-shot execution still uses the frozen panel and real workers.
        from app.search.method_space import BASELINE_ID
        verified = search.get("literature-smoke", identity)
        ids = list(dict.fromkeys(m["candidate_id"] for m in intake["methods"] if m["status"] == "eligible"))
        verified["schedule"] = [i for i in ids if i != BASELINE_ID][:max(0, args.candidates - 1)]
        verified["usage"]["proposals"] = len(verified["schedule"])
        search.action(verified, "initial_schedule", status="completed", reason="定向文献方法验收；不是模型调度结果",
            result={"candidate_ids": verified["schedule"], "selection_origin": "directed_acceptance"})
    search.start("literature-smoke", identity)
    task = search.tasks[identity]
    while not task.done():
        await asyncio.wait({task}, timeout=15)
        progress = search.get("literature-smoke", identity)
        print(progress["phase"], progress["usage"]["candidates"], progress["message"], flush=True)
    await task
    result = search.get("literature-smoke", identity)
    write(root / ("result-verification.json" if args.verify_literature else "result.json"), {
        "scheduling": "directed_acceptance" if args.verify_literature else "real_model_adaptive",
        "status": result["status"], "stop_reason": result["stop_reason"],
        "eligible_literature_methods": sum(m["status"] == "eligible" for m in intake["methods"]),
        "search_id": identity, "selected_candidate_id": result["selected_candidate_id"],
        "candidates": [{"id": c["id"], "status": c["status"], "error": c["error"],
                        "selection_score": ((c.get("receipt") or {}).get("assessment") or {}).get("selection_score")}
                       for c in result["candidates"]]})
    print("REAL NUMERICAL RESULT", result["status"], result["stop_reason"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--phase", choices=["extract", "run"], required=True)
    parser.add_argument("--source-ids", nargs="*")
    parser.add_argument("--verify-literature", action="store_true", help="Directed one-shot acceptance; not evidence of model scheduling")
    parser.add_argument("--candidates", type=int, default=3)
    parser.add_argument("--seconds", type=float, default=1200)
    asyncio.run(main(parser.parse_args()))
