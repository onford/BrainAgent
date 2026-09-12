"""Inventory of published workflow files and independent worker artifacts."""

import re

from app.preprocessing.storage import file_hash, within

STAGE_FOLDERS = {
    "data_survey": "survey",
    "data_collection": "collection",
    "data_preprocessing": "preprocessing",
    "data_evaluation": "evaluation",
    "data_report": "report",
    "data_delivery": "delivery",
}
LIVE_FILES = {"workflow.json", "process/index.json", "llm-budget.json"}
COGNITIVE_FILES = {
    "decisions.json",
    "sources.json",
    "research-plan.json",
    "research.json",
    "review.json",
    "narrative.json",
    "verification.json",
    "literature.json",
    "local-inspection.json",
    "directory-tree.txt",
}
COGNITIVE_FILES.update(
    {
        "audit.json",
        "literature-exclusions.json",
        "source-integrity.json",
        "pre-screen.json",
        "post-screen.json",
        "delta.tsv",
        "anomalies.tsv",
        "exclusions.tsv",
    }
)


def local_files(folder, state, previous=()):
    known = {a["name"]: a for a in previous}
    finished = {
        STAGE_FOLDERS[s["name"]]
        for s in state["stages"]
        if s["status"] in {"completed", "failed"}
    }
    delivery_completed = any(
        s["name"] == "data_delivery" and s["status"] == "completed"
        for s in state["stages"]
    )
    entries = []
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if (
            not path.is_file()
            or any(part.startswith(".") for part in relative.parts)
            or path.suffix in {".tmp", ".bak", ".orig", ".rej", ".swp", ".swo", ".lock", ".db"}
            or path.name.endswith("~")
        ):
            continue
        name = relative.as_posix()
        if not (
            relative.parts[0] in finished | {"process"}
            or path.name in COGNITIVE_FILES
            or name in LIVE_FILES | {"preprocessing/plan.json"}
            or name.startswith("preprocessing/literature-methods/")
            or (name == "training-data.zip" and delivery_completed)
        ):
            continue
        within(folder, name)  # Reject symlinks that escape the workflow directory.
        entries.append(
            {
                "name": name,
                "bytes": path.stat().st_size,
                "sha256": None
                if name in LIVE_FILES
                or (path.name in COGNITIVE_FILES and relative.parts[0] not in finished)
                else (known.get(name, {}).get("sha256") or file_hash(path)),
            }
        )
    return entries


def worker_files(store, owner, job_id, previous=()):
    """Expose committed outputs during execution, and finalized failed attempts."""
    if not job_id:
        return []
    job = store.status(owner, job_id)  # Always verify the job's owner.
    entries = {}
    for record in job.records:
        for artifact in (record.get("result") or {}).get("artifacts", []):
            name = "preprocessing/" + artifact["path"]
            within(store.root, artifact["path"])
            entries[name] = {
                "name": name,
                "bytes": artifact["bytes"],
                "sha256": artifact["sha256"],
            }
    # A failed/interrupted attempt may not have a RunResult. Keep its finalized
    # diagnostic files visible as well; never enumerate a worker's active directory.
    known = {a["name"]: a for a in previous}
    plan = store.get(owner, job.plan_ref, "plan")
    records = {(r["method_id"], r["record_id"]): r for r in job.records}
    for index, config in enumerate(plan["records"]):
        record = records[(config["method_ref"]["id"], config["record_id"])]
        root = within(store.root, f"runs/{job_id}/r{index:04}")
        for attempt in root.glob("a*"):
            if not re.fullmatch(r"a[1-9][0-9]*", attempt.name):
                continue
            number = int(attempt.name[1:])
            if number > record["attempt"] or (
                number == record["attempt"]
                and record["status"] not in {"completed", "failed", "cancelled"}
            ):
                continue
            for path in sorted(attempt.rglob("*")):
                if (
                    not path.is_file()
                    or path.is_relative_to(attempt / "input")
                    or path.suffix == ".tmp"
                ):
                    continue
                relative = path.relative_to(store.root).as_posix()
                within(store.root, relative)
                name = "preprocessing/" + relative
                if name not in entries:
                    entries[name] = {
                        "name": name,
                        "bytes": path.stat().st_size,
                        "sha256": known[name]["sha256"]
                        if name in known
                        else file_hash(path),
                    }
    return list(entries.values())
