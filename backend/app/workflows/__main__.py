"""Run the six-stage EEG workflow locally, including its independent worker.

python -m app.workflows --source-root E:/dataset/eeg/EEGMMIDB
"""

import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys

from app.core.config import get_settings
from app.main import create_app
from .schemas import WorkflowRequest


async def run(args):
    root = Path(args.root).resolve()
    source = Path(args.source_root).resolve(strict=True)
    settings = get_settings().model_copy(
        update={
            "preprocessing_root": str(root / "preprocessing"),
            "workflow_root": str(root / "workflows"),
            "workflow_input_roots": [str(source)],
        }
    )
    app = create_app(settings)
    try:
        if settings.db_create_tables:
            await app.state.database.create_tables()
        return await run_workflow(args, app.state.workflows, root, source)
    finally:
        await app.state.workflows.close()
        await app.state.database.dispose()


async def run_workflow(args, service, root, source):
    preprocessing = service.preprocessing
    if args.resume:
        state = service.get(args.owner, args.resume)
        if state["status"] in {"failed", "interrupted"}:
            service.retry(args.owner, args.resume)
        else:
            service.start(args.owner, args.resume)
    else:
        state = service.create(
            args.owner,
            WorkflowRequest(
                source_root=str(source),
                subjects=args.subjects,
                runs=args.runs,
                seed=args.seed,
                tmin=args.tmin,
                tmax=args.tmax,
            ),
        )
    print(f"Workflow: {state['id']}", flush=True)
    log = (root / "worker.log").open("a", encoding="utf-8")
    worker = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "app.preprocessing.worker",
            "--root",
            str(preprocessing.store.root),
            "--input-root",
            str(service.root),
        ],
        cwd=Path(__file__).resolve().parents[2],
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    task = service.tasks[state["id"]]
    last = None
    try:
        async with asyncio.timeout(args.timeout):
            while not task.done():
                if worker.poll() is not None:
                    raise RuntimeError(
                        f"Worker exited ({worker.returncode}); see {log.name}"
                    )
                current = service.get(args.owner, state["id"])
                progress = {
                    "stages": [(s["label"], s["status"]) for s in current["stages"]],
                    "activity": current["events"][-1]["message"]
                    if current["events"]
                    else None,
                }
                if progress != last:
                    print(json.dumps(progress, ensure_ascii=False), flush=True)
                    last = progress
                await asyncio.sleep(1)
            await task
        current = service.get(args.owner, state["id"])
        if current["status"] != "completed":
            raise RuntimeError(current["error"])
        print(
            json.dumps(
                {
                    "id": current["id"],
                    "status": current["status"],
                    "folder": str(service.folder(current["id"])),
                    "delivery": current["outputs"]["data_delivery"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return current
    finally:
        await service.close()
        worker.terminate()
        await asyncio.to_thread(worker.wait, 15)
        log.close()


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--root", default="workspace/training-cli")
    parser.add_argument("--owner", default="local-development-user")
    parser.add_argument("--subjects", nargs="*", default=[])
    parser.add_argument("--runs", nargs="+", type=int, default=[4, 8])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tmin", type=float, default=0)
    parser.add_argument("--tmax", type=float, default=2)
    parser.add_argument(
        "--resume", help="Resume a workflow ID under the same root and owner"
    )
    parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (ValueError, OSError, RuntimeError, TimeoutError) as exc:
        parser.exit(1, f"Workflow failed: {exc}\n")


if __name__ == "__main__":
    main()
