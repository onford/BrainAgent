"""Run the formal search API on an immutable, actually completed survey/intake.

The upstream survey, intake and method extraction must be complete. Their frozen
evidence and stage states are copied unchanged. A concurrent upstream numerical
search may continue; this run has its own candidates and selection.
"""
import argparse
import asyncio
import shutil
from pathlib import Path

import httpx

from app.core.config import Settings
from app.main import create_app
from app.preprocessing.storage import digest
from app.search.io import read, write
from app.search.method_provenance import participation
from scripts.release_workflow_acceptance import hashes


async def main(args):
    root, upstream = Path(args.output).resolve(), Path(args.upstream).resolve()
    if root.exists():
        raise ValueError("Use a new evidence directory")
    saved = read(upstream / "workflow.json")
    if "data_collection" not in saved["outputs"] or not (upstream / "preprocessing/literature-methods/manifest.json").exists():
        raise ValueError("Upstream must have completed the actual survey, intake and extraction")
    root.mkdir(parents=True)
    def prerequisites():
        return [p for name in ("survey", "collection", "preprocessing/literature-methods") for p in (upstream / name).rglob("*")]
    before = hashes(prerequisites(), upstream)
    settings = Settings(_env_file=args.config)
    settings = settings.model_copy(update={"workflow_root": str(root / "workflows"),
        "preprocessing_root": str(Path(args.methods).resolve()), "log_dir": root / "logs", "db_create_tables": False,
        "database_url_override": args.database_url,
        "preprocessing_input_roots": [*settings.preprocessing_input_roots, str(upstream)]})
    code = Path(__file__).resolve().parents[1] / "app"
    code_before = hashes([p for p in code.rglob("*") if p.suffix in {".py", ".json"}], code)
    request = {"workflow_id": saved["id"], "budget": {"max_candidates": args.candidates, "max_seconds": args.seconds,
        "max_proposals": 24, "max_memory_mb": 8192}}
    write(root / "design.json", {"entry": "POST /api/searches on the completed current-session survey and intake",
        "upstream": str(upstream), "upstream_hashes": before, "request": request,
        "dependency_overrides": [], "numerical_overrides": [], "model": settings.llm_model,
        "code_digest": digest(code_before), "code_hashes": code_before,
        "scope": saved["request"], "retrieval": "See immutable upstream current-session live workflow; no new retrieval in this search run"})
    app = create_app(settings)
    result = {"acceptance_passed": False}
    try:
        async with app.router.lifespan_context(app):
            # Restore the prerequisite snapshot after startup so restoring a live
            # parent does not auto-resume its independent numerical search here.
            # No status or completed-stage flag is edited.
            shutil.copytree(upstream, root / "workflows" / saved["id"])
            if hashes(prerequisites(), upstream) != before:
                raise ValueError("Upstream prerequisite evidence changed during snapshot")
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://brainagent.local", timeout=180) as client:
                response = await client.post("/api/searches", json=request)
                response.raise_for_status()
                state = response.json()
                identity = state["id"]
                write(root / "active.json", {"workflow_id": saved["id"], "search_id": identity})
                print("SEARCH", identity, flush=True)
                task = app.state.searches.tasks[identity]
                while not task.done():
                    await asyncio.wait({task}, timeout=15)
                    state = (await client.get(f"/api/searches/{identity}")).json()
                    print(state["phase"], state["usage"]["candidates"], state["message"], flush=True)
                await task
                state = (await client.get(f"/api/searches/{identity}")).json()
                result.update(status=state["status"], stop_reason=state["stop_reason"], error=state.get("error"), search_id=identity,
                    literature_participation=participation(state), selected_candidate_id=state["selected_candidate_id"],
                    candidates=[{"id": c["id"], "status": c["status"], "error": c.get("error"),
                                 "score": ((c.get("receipt") or {}).get("assessment") or {}).get("selection_score")} for c in state["candidates"]])
                result["mechanical_gate_passed"] = bool(participation(state)["substantive_literature_evaluated_ids"] and state["selected_candidate_id"] and state["status"] in {"completed", "stopped"})
    except Exception as exc:
        result.update(status="failed", failure=f"{type(exc).__name__}: {exc}")
        print(result["failure"], flush=True)
    finally:
        result["upstream_prerequisites_unchanged"] = hashes(prerequisites(), upstream) == before
        result["code_unchanged_during_run"] = hashes([p for p in code.rglob("*") if p.suffix in {".py", ".json"}], code) == code_before
        write(root / "result.json", result)
        print("RESULT", result, flush=True)
    return 0 if result.get("mechanical_gate_passed") and result["upstream_prerequisites_unchanged"] and result["code_unchanged_during_run"] else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for name in ("output", "upstream", "methods", "config", "database-url"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--candidates", type=int, default=6)
    p.add_argument("--seconds", type=float, default=3600)
    raise SystemExit(asyncio.run(main(p.parse_args())))
