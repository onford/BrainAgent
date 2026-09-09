"""Real Windows venv launchers, Job RSS, cancellation and supervisor death."""

import asyncio
from contextlib import contextmanager
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import venv

import pytest

from app.search import processes
from app.search.processes import ProcessTree
from app.search.service import BudgetStop, SearchService

pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="Windows Job/venv launcher regression"
)
MIB = 1024**2
BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def venv_python(tmp_path):
    path = Path(sys.prefix) / "Scripts" / "python.exe"
    if sys.prefix != sys.base_prefix and path.is_file():
        return str(path)
    target = tmp_path / "real-venv"
    venv.create(target, with_pip=False)
    return str(target / "Scripts" / "python.exe")


def workload(python, root):
    # Both the venv interpreter and a further venv subprocess touch physical
    # pages. No cooperative parent guard is used: Job ownership must suffice.
    leaf = (
        "import os,time; from pathlib import Path; "
        "data=bytearray(80*1024*1024); data[::4096]=b'x'*(len(data)//4096); "
        f"Path({str(root / 'leaf-ready')!r}).write_text(str(os.getpid())); time.sleep(120)"
    )
    code = (
        "import os,sys,time,subprocess; from pathlib import Path; "
        f"child=subprocess.Popen([sys.executable,'-X','utf8','-c',{leaf!r}]); "
        "data=bytearray(96*1024*1024); data[::4096]=b'x'*(len(data)//4096); "
        f"Path({str(root / 'root-ready')!r}).write_text(str(os.getpid())); time.sleep(120)"
    )
    return [python, "-X", "utf8", "-c", code]


def wait_ready(root, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return [
                int((root / name).read_text()) for name in ("root-ready", "leaf-ready")
            ]
        except (FileNotFoundError, ValueError):
            time.sleep(0.025)
    pytest.fail("real venv processes did not initialize")


@contextmanager
def held_processes(pids):
    # Retain kernel process identities so recycled PIDs cannot make the cleanup
    # assertion pass/fail for a different process.
    from ctypes import wintypes as w

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    api.OpenProcess.restype = w.HANDLE
    api.CloseHandle.argtypes = [w.HANDLE]
    api.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    api.WaitForSingleObject.restype = w.DWORD
    api.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
    api.TerminateProcess.restype = w.BOOL
    handles = []
    try:
        for pid in pids:
            handle = api.OpenProcess(0x00100000 | 0x0001, False, pid)
            assert handle, (pid, ctypes.get_last_error())
            handles.append(handle)
        yield api, handles
    finally:
        for handle in handles:
            # All callers own only test processes. Cleanup also runs on failed assertions.
            if api.WaitForSingleObject(handle, 0) == 0x102:
                api.TerminateProcess(handle, 1)
                api.WaitForSingleObject(handle, 5000)
            api.CloseHandle(handle)


def assert_exited(api, handles):
    assert all(api.WaitForSingleObject(handle, 5000) == 0 for handle in handles)


def test_real_venv_rss_covers_launcher_interpreter_and_descendants(
    venv_python, tmp_path
):
    with ProcessTree(workload(venv_python, tmp_path)) as tree:
        actual_pids = wait_ready(tmp_path)
        assert tree.pid not in actual_pids  # The launcher is not the interpreter.
        assert set(actual_pids) <= set(tree.pids())
        counters = processes._MemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        assert tree._api.K32GetProcessMemoryInfo(
            tree._handle, ctypes.byref(counters), counters.cb
        )
        tree_memory = tree.memory_bytes()
        print(
            f"venv={venv_python}; launcher_rss_bytes={counters.working_set}; "
            f"tree_rss_bytes={tree_memory}; members={tree.pids()}"
        )
        assert counters.working_set < 64 * MIB
        assert tree_memory > 160 * MIB
        with held_processes(tree.pids()) as (api, handles):
            tree.kill()
            assert tree.wait(timeout=10) != 0
            assert tree.pids() == []
            assert_exited(api, handles)


def test_close_job_kills_every_descendant(venv_python, tmp_path):
    tree = ProcessTree(workload(venv_python, tmp_path))
    try:
        wait_ready(tmp_path)
        with held_processes(tree.pids()) as (api, handles):
            tree.close()
            tree.close()  # Idempotent cleanup must not close a recycled handle.
            assert_exited(api, handles)
    finally:
        tree.close()


def test_abrupt_supervisor_death_closes_job_without_cooperative_guard(
    venv_python, tmp_path
):
    command = workload(venv_python, tmp_path)
    ready = tmp_path / "supervisor-ready.json"
    code = (
        "import os,json,time; from pathlib import Path; "
        "from app.search.processes import ProcessTree; "
        f"tree=ProcessTree({command!r}); "
        f"root=Path({str(tmp_path)!r}); "
        "\nwhile not (root/'leaf-ready').exists(): time.sleep(0.025)\n"
        f"Path({str(ready)!r}).write_text(json.dumps(dict(pid=os.getpid(),members=tree.pids()))); "
        "time.sleep(120)"
    )
    env = dict(os.environ, PYTHONUTF8="1", PYTHONPATH=str(BACKEND))
    # Use the base interpreter for the supervisor, then terminate its actual PID.
    with (tmp_path / "supervisor.log").open("wb") as log:
        supervisor = subprocess.Popen(
            [sys._base_executable, "-X", "utf8", "-c", code],
            env=env,
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            deadline = time.monotonic() + 15
            value = None
            while time.monotonic() < deadline:
                try:
                    value = json.loads(ready.read_text())
                    break
                except (FileNotFoundError, json.JSONDecodeError):
                    assert supervisor.poll() is None, (
                        tmp_path / "supervisor.log"
                    ).read_text()
                    time.sleep(0.025)
            assert value is not None
            with held_processes([value["pid"], *value["members"]]) as (api, handles):
                assert api.TerminateProcess(handles[0], 1)
                assert_exited(api, handles)
            supervisor.wait(timeout=10)
        finally:
            if supervisor.poll() is None:
                supervisor.kill()
                supervisor.wait(timeout=10)


def test_failed_job_binding_never_launches_uncontained_work(
    venv_python, tmp_path, monkeypatch
):
    api = processes._kernel()

    class RejectedJob:
        def __getattr__(self, name):
            return getattr(api, name)

        def UpdateProcThreadAttribute(self, attributes, flags, key, *args):
            if key == 0x0002000D:
                ctypes.set_last_error(5)
                return False
            return api.UpdateProcThreadAttribute(attributes, flags, key, *args)

        def CreateProcessW(self, *args):
            pytest.fail("job binding failed: must not launch an uncontained fallback")

    monkeypatch.setattr(processes, "_kernel", RejectedJob)
    with pytest.raises(OSError):
        ProcessTree(workload(venv_python, tmp_path))
    assert not (tmp_path / "root-ready").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["memory", "cancel"])
async def test_service_child_monitors_tree_rss_and_cleans_all_members(
    venv_python, tmp_path, monkeypatch, stop
):
    from app.search import service as service_module

    root = tmp_path / ("a" * 32)
    root.mkdir()
    instance = SearchService(tmp_path, SimpleNamespace(llm=None))
    state = {
        "id": root.name,
        "deadline": time.time() + 30,
        "usage": {"peak_worker_memory_bytes": 0, "disk_bytes": 0},
        "protocol": {
            "limits": {
                "memory_limit_bytes": (64 if stop == "memory" else 1024) * MIB,
                "disk_limit_bytes": 128 * MIB,
            }
        },
    }
    launched = []

    def launch(command, **kwargs):
        assert command[1:3] == ["-m", "app.search.worker"]
        assert command[-2:] == ["--parent-pid", str(os.getpid())]
        tree = ProcessTree(workload(venv_python, root), **kwargs)
        launched.append(tree)
        return tree

    monkeypatch.setattr(service_module, "ProcessTree", launch)
    monkeypatch.setattr(instance, "save", lambda state: None)
    task = asyncio.create_task(instance.child(state, "prepare"))
    try:
        await asyncio.to_thread(wait_ready, root)
        tree = launched[0]
        with held_processes(tree.pids()) as (api, handles):
            if stop == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                with pytest.raises(BudgetStop, match="memory_budget_exhausted"):
                    await asyncio.wait_for(task, timeout=10)
                print(
                    f"service_memory_limit_bytes={64 * MIB}; "
                    f"observed_tree_peak_bytes={state['usage']['peak_worker_memory_bytes']}; "
                    "stop=memory_budget_exhausted"
                )
                assert state["usage"]["peak_worker_memory_bytes"] > 64 * MIB
            assert instance.children == {}
            assert_exited(api, handles)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_stdio_and_environment_preserve_utf8(venv_python, tmp_path):
    logpath = tmp_path / "utf8.log"
    with logpath.open("wb") as log:
        with ProcessTree(
            [venv_python, "-c", "import os; print(os.environ['TREE_TEST'])"],
            stdout=log,
            stderr=log,
            env=dict(os.environ, PYTHONUTF8="1", TREE_TEST="树形进程±"),
        ) as tree:
            assert tree.wait(timeout=10) == 0
    assert logpath.read_text(encoding="utf-8").strip() == "树形进程±"
