"""Real configured LLM + production search HTTP routes + real numerical workers.

Run from backend with .venv-eeg/Scripts/python.exe -m scripts.neural_prior_smoke
--input PATH/collection/input.json --output PATH. No generated signals or model mocks.
The owner dependency alone is replaced for an isolated, in-process HTTP smoke test.
"""
import argparse
import asyncio
import shutil
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI

from app.api.deps import get_current_user
from app.api.routes.searches import router
from app.core.config import Settings
from app.llm.client import create_llm_client
from app.llm.config import LLMConfig
from app.preprocessing.schemas import PreprocessInput
from app.preprocessing.storage import digest, file_hash, within
from app.search.io import read, write
from app.search.service import SearchService


async def main(args):
    settings = Settings()
    if not settings.llm_api_key:
        raise RuntimeError("Configured agent API key is missing; live test cannot be substituted")
    output = Path(args.output).resolve()
    raw = read(Path(args.input).resolve())
    selected = [r for r in raw["collection"]["selected_record_ids"] if r[:4] in {"S001", "S002", "S003", "S004"}]
    if len(selected) != 12:
        raise ValueError("Smoke expects exactly S001-S004 R04/R08/R12, frozen before scoring")
    raw["collection"]["records"] = [r for r in raw["collection"]["records"] if r["id"] in selected]
    raw["collection"]["selected_record_ids"] = selected
    raw["collection"]["selection_reason"] = "Predeclared engineering smoke: S001-S003 train; S004 development; R04/R08/R12. Not full-cohort scientific evidence."
    original_root = Path(raw["collection"]["root"]).resolve()
    copied_root = output / "input-bids"
    manifest = {}
    for record in raw["collection"]["records"]:
        for relative, expected in record["files"].items():
            if relative in manifest:
                if manifest[relative] != expected:
                    raise ValueError("Conflicting source hashes")
                continue
            src, dest = within(original_root, relative), within(copied_root, relative)
            if file_hash(src) != expected:
                raise ValueError("Original source hash mismatch: " + relative)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            if file_hash(dest) != expected or file_hash(src) != expected:
                raise ValueError("Source/copy changed during materialization")
            manifest[relative] = expected
    write(output / "input-copy-receipt.json", {"original_root": str(original_root), "copy_root": str(copied_root),
                                               "files": manifest, "source_unchanged_verified": True})
    raw["collection"]["root"] = str(copied_root)
    data = PreprocessInput.model_validate(raw)
    source = output / "source"
    write(source / "collection/input.json", data.model_dump(mode="json"))
    source_state = {"outputs": {"data_collection": {}, "data_survey": {"records": [
        {"id": r, "subject": r[:4]} for r in selected]}}, "request": {"tmin": 0.0, "tmax": 2.0}}
    config = LLMConfig(api_key=settings.llm_api_key, base_url=settings.llm_base_url, model=settings.llm_model,
                       timeout_seconds=settings.llm_timeout_seconds,
                       reasoning_effort=settings.workflow_reasoning_effort if urlsplit(settings.llm_base_url).hostname == "api.deepseek.com" else None)
    workflows = SimpleNamespace(get=lambda *a: source_state, folder=lambda _: source,
                                preprocessing=SimpleNamespace(allowed_roots=[Path(data.collection.root)]),
                                llm=create_llm_client(config))
    service = SearchService(output / "searches", workflows)
    app = FastAPI()
    app.state.searches = service
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(owner_id="neural-prior-smoke")
    request = {"workflow_id": "0" * 32, "strategy": "adaptive", "train_subjects": ["S001", "S002", "S003"],
               "development_subjects": ["S004"], "budget": {"max_candidates": args.candidates, "max_proposals": 18,
               "max_diagnostics": 6, "max_evidence_reads": 6, "max_seconds": args.seconds, "max_retries": 1}}
    write(output / "test-design.json", {"input_digest": digest(raw), "records": selected, "request": request,
          "real_provider": True, "model": settings.llm_model, "http_transport": "in_process_ASGI_production_routes",
          "auth_scope": "isolated owner dependency; authentication not tested", "numerical_workers": "unmodified_production",
          "scope": "engineering smoke only; same development subjects may have been used historically"})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://smoke.local", timeout=60) as client:
        response = await client.post("/api/searches", json=request)
        response.raise_for_status()
        identity = response.json()["id"]
        write(output / "active.json", {"search_id": identity, "root": str(service.folder(identity))})
        print("LIVE search created", identity, "model", settings.llm_model, flush=True)
        task = service.tasks[identity]
        while not task.done():
            await asyncio.wait({task}, timeout=15)
            state = service.get("neural-prior-smoke", identity)
            print(state["phase"], "candidates", state["usage"]["candidates"], "llm", state["usage"]["llm_calls"],
                  "diagnostics", state["usage"].get("diagnostics"), flush=True)
        await task
        response = await client.get(f"/api/searches/{identity}", params={"include_artifacts": False})
        response.raise_for_status()
        state = response.json()
        links = []
        for d in state.get("diagnostics", []):
            r = await client.get(f"/api/searches/{identity}/artifacts/{d['artifact']['path']}")
            links.append({"path": d["artifact"]["path"], "http_status": r.status_code,
                          "matches_ledger": r.is_success and r.json() == {k: v for k, v in d.items() if k != "artifact"}})
        result = {"search_id": identity, "status": state["status"], "error": state.get("error"),
                  "stop_reason": state.get("stop_reason"), "usage": state["usage"], "selected_candidate_id": state.get("selected_candidate_id"),
                  "actions": [{k: a.get(k) for k in ("index", "action", "status", "reason", "error", "result")} for a in state["actions"]],
                  "candidates": [{"id": c["id"], "status": c["status"], "selection_score": (c.get("receipt") or {}).get("assessment", {}).get("selection_score")} for c in state["candidates"]],
                  "diagnostic_links": links, "model": settings.llm_model, "scope": "4 subjects / 12 records; engineering smoke, no scientific generalization claim"}
        write(output / "result.json", result)
        print("RESULT", state["status"], state.get("stop_reason"), "saved", output / "result.json", flush=True)
        cited = [a for a in state["actions"] if a["action"] == "propose_candidate" and a["status"] == "completed"
                 and (a.get("result") or {}).get("prior_evidence", {}).get("status") == "cited_by_agent"]
        if (state["status"] == "failed" or len([c for c in state["candidates"] if c["status"] == "evaluated"]) < 2
                or not cited or not state["usage"]["llm_calls"] or not links or not all(r["matches_ledger"] for r in links)):
            raise RuntimeError("Live smoke did not demonstrate model-driven verified diagnostic use; inspect saved result")
    await service.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--candidates", type=int, default=2)
    parser.add_argument("--seconds", type=int, default=1200)
    asyncio.run(main(parser.parse_args()))
