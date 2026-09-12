"""Cancellable native calls owned by a process tree, with durable run receipts."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import subprocess
import shutil
import tempfile
import time
from uuid import uuid4

from app.search.processes import ProcessTree
from .storage import write_json
from .storage import file_hash

_CONTEXT = ContextVar("native_execution", default=(lambda: False, None))


@contextmanager
def native_scope(cancelled, directory):
    token = _CONTEXT.set((cancelled, Path(directory)))
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def preserve_partial_files(work):
    """Keep failed native numeric/QC files inside this step's diagnostic tree."""
    _, directory = _CONTEXT.get()
    if directory is None:
        return
    root = Path(work).resolve()
    output = directory / ("native-partial-" + uuid4().hex)
    files = {}
    for source in root.rglob("*.mat"):
        if not source.is_file() or not source.resolve().is_relative_to(root):
            continue
        relative = source.relative_to(root)
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        files[relative.as_posix()] = file_hash(target)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "partial.json", dict(status="incomplete", completed=False, files=files))


def run(command, *, capture_output=True, text=True, timeout, env=None, cwd=None):
    """The closed numerical adapters use the capture-output subset of run()."""
    if not capture_output or not text or timeout <= 0:
        raise ValueError("native calls require captured text and a positive timeout")
    cancelled, directory = _CONTEXT.get()
    with tempfile.TemporaryDirectory(prefix="brainagent-native-") as scratch:
        output = (directory / ("native-" + uuid4().hex)) if directory else Path(scratch)
        output.mkdir(parents=True, exist_ok=True)
        receipt = dict(status="starting", started_at=time.time(), command=command,
            completed=False, wall_seconds=0., peak_process_tree_rss_bytes=0)
        started = time.monotonic()
        write_json(output / "execution.json", receipt)
        try:
            if cancelled():
                from .runner import Cancelled
                raise Cancelled("cancelled before native process creation")
            with (output / "stdout.log").open("wb") as stdout, (output / "stderr.log").open("wb") as stderr:
                with ProcessTree(command, stdout=stdout, stderr=stderr, env=env, cwd=cwd) as tree:
                    receipt.update(status="running", pid=tree.pid)
                    write_json(output / "execution.json", receipt)
                    while True:
                        if cancelled():
                            from .runner import Cancelled
                            raise Cancelled("cancelled during native algorithm")
                        elapsed = time.monotonic() - started
                        if elapsed >= timeout:
                            raise subprocess.TimeoutExpired(command, timeout)
                        receipt["peak_process_tree_rss_bytes"] = max(receipt["peak_process_tree_rss_bytes"], tree.memory_bytes())
                        try:
                            returncode = tree.wait(timeout=min(.1, timeout - elapsed))
                            break
                        except subprocess.TimeoutExpired:
                            pass
                    receipt.update(returncode=returncode, status="completed" if returncode == 0 else "failed", completed=returncode == 0)
            def tail(path):
                with path.open("rb") as stream:
                    stream.seek(max(0, path.stat().st_size - 1024 * 1024))
                    return stream.read().decode("utf-8", errors="replace")
            return subprocess.CompletedProcess(command, returncode, tail(output / "stdout.log"), tail(output / "stderr.log"))
        except BaseException as exc:
            from .runner import Cancelled
            receipt.update(status="cancelled" if isinstance(exc, Cancelled) else "timed_out" if isinstance(exc, subprocess.TimeoutExpired) else "failed", error=type(exc).__name__)
            raise
        finally:
            receipt["wall_seconds"] = time.monotonic() - started
            write_json(output / "execution.json", receipt)
