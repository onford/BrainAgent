"""Identify the source and dependency snapshot loaded by a service process."""
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import subprocess
from functools import lru_cache
import platform

SOURCE_SUFFIXES = {".py", ".json", ".html", ".txt", ".css", ".js", ".m", ".yaml", ".yml"}
DEPENDENCIES = (
    "fastapi", "pydantic", "numpy", "scipy", "mne", "mne-bids", "torch",
    "scikit-learn", "asrpy", "pandas", "h5io", "h5py", "pybv", "httpx",
    "sqlalchemy", "aiosqlite", "portalocker", "psutil", "jinja2",
)

from app.preprocessing.storage import digest, file_hash


def runtime_snapshot():
    """Read current files and installed versions without a Git or time identity."""
    app_root = Path(__file__).parent
    source_files = {
        p.relative_to(app_root).as_posix(): file_hash(p)
        for p in sorted(app_root.rglob("*"))
        if p.is_file() and p.suffix in SOURCE_SUFFIXES
    }
    dependencies = {}
    for name in DEPENDENCIES:
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = None
    return {
        "source_sha256": digest(source_files),
        "dependencies": dependencies,
        "dependencies_sha256": digest(dependencies),
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
    }


def execution_identity(runtime):
    return {"schema_version": "1", **{key: runtime[key] for key in (
        "source_sha256", "dependencies_sha256", "python", "system", "machine")}}


@lru_cache(maxsize=1)
def snapshot():
    from app.llm.budget import DEFAULT_LIMITS
    app_root = Path(__file__).parent
    runtime = runtime_snapshot()
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=app_root,
            stderr=subprocess.DEVNULL, text=True, timeout=5,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
    return {
        "schema_version": "1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "commit": commit,
        **runtime,
        "execution_build": execution_identity(runtime),
        "preprocessing_scope": "shared_recipe_all_records",
        "core_evaluator_version": 4,
        "selection": "eegnet_three_seed_subject_macro_ba",
        "llm_operational_limits": DEFAULT_LIMITS,
    }
