"""Fresh formal API workflow with configured providers and unchanged numerics.

This is an acceptance driver, never imported by production. No DI overrides,
saved-survey replay, injected candidates or evaluator parameter changes.
"""

import argparse
import asyncio
import re
import shutil
from pathlib import Path

import httpx

from app.core.config import Settings
from app.main import create_app
from app.preprocessing.storage import file_hash, digest
from app.search.io import read, write
from app.search.method_provenance import participation


def hashes(paths, root):
    return {p.relative_to(root).as_posix(): file_hash(p) for p in sorted(paths) if p.is_file()}


def code_hashes(root):
    return hashes([p for p in root.rglob("*") if "__pycache__" not in p.parts], root)


def source_scope(source, output, subjects):
    """Freeze the actual local scope before creating any acceptance artifacts."""
    source = source.resolve(strict=True)
    output = output.resolve()
    if output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("Source and acceptance output trees must be disjoint")
    available = sorted(p.name for p in source.iterdir()
                       if p.is_dir() and re.fullmatch(r"S[0-9]{3}", p.name))
    if not subjects or len(subjects) != len(set(subjects)) or set(subjects) - set(available):
        raise ValueError("Declare unique, existing EEGMMIDB participant directories")
    selected = sorted(subjects)
    # Include dataset-level metadata even for a declared panel. Re-enumeration
    # after the run detects added/deleted files, not only changes to known paths.
    paths = [p for p in source.iterdir() if p.is_file()]
    selected_paths = [p for subject in selected for p in (source / subject).rglob("*") if p.is_file()]
    if not selected_paths:
        raise ValueError("No declared source files")
    paths += selected_paths
    if any(not p.resolve().is_relative_to(source) for p in paths):
        raise ValueError("Source file resolves outside the declared dataset")
    complete = selected == [f"S{i:03d}" for i in range(1, 110)] and selected == available
    scope = {"selected_participants": selected, "available_participants": available,
             "full_eegmmidb_participant_scope": complete,
             "covers_all_local_participant_directories": selected == available,
             "scope_limitation": (
                 "Full EEGMMIDB participant scope (109); MI task selection and frozen grouped development folds remain explicit. This is not independent validation."
                 if complete else
                 "Declared local participant panel; not verified as the full EEGMMIDB dataset or independent validation.")}
    return hashes(paths, source), scope


async def main(args):
    root, source = Path(args.output).resolve(), Path(args.source).resolve()
    if root.exists():
        raise ValueError("Acceptance output must be a new directory; historical evidence is immutable")
    before, scope = source_scope(source, root, args.subjects)
    original = Settings(_env_file=args.config) if args.config else Settings()
    if args.database_url:
        original = original.model_copy(update={"database_url_override": args.database_url})
    if not original.llm_api_key:
        raise ValueError("Configured model credentials are required")
    root.mkdir(parents=True)
    settings = original.model_copy(update={"workflow_root": str(root / "workflows"),
        "preprocessing_root": str(root / "methods"), "log_dir": root / "logs", "db_create_tables": False})
    code = Path(__file__).resolve().parents[1] / "app"
    code_before = code_hashes(code)
    driver_before = file_hash(Path(__file__))
    request = {"source_root": str(source), "subjects": args.subjects,
        "search_budget": {"max_candidates": args.candidates, "max_seconds": args.seconds,
                          "max_memory_mb": args.memory_mb, "max_disk_mb": args.disk_mb},
        "method_research_budget": {"max_recovery_actions": 6, "max_seconds": args.method_research_seconds}}
    recovery = None
    if args.resume_checkpoint:
        checkpoint = Path(args.resume_checkpoint).resolve()
        saved = read(checkpoint / "workflow.json")
        if saved["status"] not in {"failed", "interrupted"} or saved.get("search_id"):
            raise ValueError("Recovery driver accepts only failed upstream checkpoints with no numerical search")
        if Path(saved["request"]["source_root"]).resolve() != source or saved["request"]["subjects"] != args.subjects:
            raise ValueError("Recovery request scope must match the immutable upstream checkpoint")
        request = saved["request"]
        recovery = {"checkpoint": str(checkpoint), "workflow_id": saved["id"],
                    "hashes": hashes(checkpoint.rglob("*"), checkpoint),
                    "entry": "POST /api/workflows/{id}/retry; restored immutable upstream checkpoint, no stage override"}
        shutil.copytree(checkpoint, root / "workflows" / saved["id"])
    write(root / "design.json", {"entry": "POST /api/workflows via full create_app lifespan and ASGI HTTP transport",
        "request": request, "model": original.llm_model, "provider": original.llm_base_url,
        "database_configuration": args.database_url or "Settings default", "config_file": args.config,
        "recovery": recovery,
        "dependency_overrides": [], "numerical_overrides": [], "retrieval": "fresh live provider tools and SourceReader",
        **scope, "driver_sha256": driver_before,
        "source_hashes": before, "code_hashes": code_before, "code_digest": digest(code_before)})
    app = create_app(settings)
    result = {"status": "failed", "acceptance_passed": False}
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://brainagent.local", timeout=180) as client:
                response = await client.post(f"/api/workflows/{recovery['workflow_id']}/retry") if recovery else await client.post("/api/workflows", json=request)
                response.raise_for_status()
                identity = response.json()["id"]
                write(root / "active.json", {"workflow_id": identity})
                print("WORKFLOW", identity, flush=True)
                task = app.state.workflows.tasks[identity]
                previous = None
                while not task.done():
                    await asyncio.wait({task}, timeout=15)
                    response = await client.get(f"/api/workflows/{identity}")
                    response.raise_for_status()
                    state = response.json()
                    progress = (state["status"], state.get("current_stage"), state.get("message"))
                    if progress != previous:
                        print("PROGRESS", *progress, flush=True)
                        previous = progress
                await task
                state = (await client.get(f"/api/workflows/{identity}")).json()
                result.update(status=state["status"], workflow_id=identity,
                    stages=state["stages"], error=state.get("error"), search_id=state.get("search_id"))
                if state.get("search_id"):
                    search = (await client.get(f"/api/searches/{state['search_id']}")).json()
                    result["literature_participation"] = participation(search)
                    result["selected_candidate_id"] = search["selected_candidate_id"]
                    result["candidates"] = [{"id": c["id"], "status": c["status"], "error": c.get("error"),
                        "score": ((c.get("receipt") or {}).get("assessment") or {}).get("selection_score")}
                        for c in search["candidates"]]
                    distinct = result["literature_participation"]["substantive_literature_evaluated_ids"]
                    # This mechanical gate is necessary, not a substitute for source/parameter and actual effect review.
                    result["mechanical_gate_passed"] = bool(distinct and state["status"] == "completed")
                    result["review_required"] = "Verify source parameters, non-preset semantics, subsequent model use and final selection accounting."
    except Exception as exc:
        result["failure"] = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, httpx.HTTPStatusError):
            result["http_error_detail"] = exc.response.text[:8000]
        print("FAILED", type(exc).__name__, str(exc), flush=True)
    finally:
        try:
            source_after, scope_after = source_scope(source, root, args.subjects)
            result["original_data_unchanged"] = source_after == before and scope_after == scope
        except Exception as exc:
            result["original_data_unchanged"] = False
            result["source_verification_error"] = f"{type(exc).__name__}: {exc}"
        try:
            after = code_hashes(code)
            result["code_unchanged_during_run"] = after == code_before
            result["driver_unchanged_during_run"] = file_hash(Path(__file__)) == driver_before
            result["code_digest_after"] = digest(after)
        except Exception as exc:
            result["code_unchanged_during_run"] = False
            result["driver_unchanged_during_run"] = False
            result["code_verification_error"] = f"{type(exc).__name__}: {exc}"
        if recovery:
            checkpoint = Path(recovery["checkpoint"])
            result["upstream_checkpoint_unchanged"] = hashes(checkpoint.rglob("*"), checkpoint) == recovery["hashes"]
        write(root / "result.json", result)
        print("RESULT", result["status"], "mechanical_gate", result.get("mechanical_gate_passed", False), flush=True)
    return 0 if result.get("mechanical_gate_passed") and result["original_data_unchanged"] and result["code_unchanged_during_run"] and result["driver_unchanged_during_run"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--subjects", nargs="+", required=True)
    parser.add_argument("--candidates", type=int, default=6)
    parser.add_argument("--seconds", type=float, default=3600)
    parser.add_argument("--memory-mb", type=int, default=16384)
    parser.add_argument("--disk-mb", type=int, default=65536)
    parser.add_argument("--method-research-seconds", type=float, default=900)
    parser.add_argument("--config", help="Original project .env file, never copied into evidence")
    parser.add_argument("--database-url", help="Explicit runtime database URL; use the actual service configuration")
    parser.add_argument("--resume-checkpoint", help="Restore an immutable failed upstream checkpoint into this NEW output root, then call the formal retry API")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
