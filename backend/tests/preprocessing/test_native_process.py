from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import sys
import threading

import pytest

from app.preprocessing.native_process import native_scope, preserve_partial_files, run
from app.preprocessing.runner import Cancelled


def test_native_success_retains_logs_and_resource_receipt(tmp_path):
    with native_scope(lambda: False, tmp_path):
        result = run([sys.executable, "-c", "print('native completed')"], timeout=10)
    assert result.returncode == 0 and "native completed" in result.stdout
    receipt = json.loads(next(tmp_path.glob("native-*/execution.json")).read_text())
    assert receipt["completed"] and receipt["status"] == "completed"
    assert receipt["wall_seconds"] > 0


def test_partial_numeric_files_remain_incomplete_and_verifiable(tmp_path):
    from app.preprocessing.storage import file_hash

    work = tmp_path / "working"
    work.mkdir()
    (work / "native-output.mat").write_bytes(b"partial native output")
    (work / "unrelated.txt").write_text("not a numeric artifact")
    with native_scope(lambda: False, tmp_path / "step"):
        preserve_partial_files(work)
    manifest = next((tmp_path / "step").glob("native-partial-*/partial.json"))
    saved = json.loads(manifest.read_text())
    assert saved["status"] == "incomplete" and not saved["completed"]
    assert saved["files"] == {"native-output.mat": file_hash(work / "native-output.mat")}
    assert file_hash(manifest.parent / "native-output.mat") == saved["files"]["native-output.mat"]


@pytest.mark.skipif(os.name != "nt", reason="verify native Windows descendant identities")
@pytest.mark.parametrize("cancel", [True, False])
def test_native_cancel_or_timeout_reaps_descendants(tmp_path, cancel):
    from tests.test_processes import workload, wait_ready, held_processes, assert_exited

    stop = threading.Event()

    def execute():
        with native_scope(stop.is_set, tmp_path / "receipts"):
            return run(workload(sys.executable, tmp_path), timeout=30 if cancel else 4)

    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(execute)
        identities = wait_ready(tmp_path)
        with held_processes(identities) as (api, handles):
            if cancel:
                stop.set()
            with pytest.raises(Cancelled if cancel else subprocess.TimeoutExpired):
                result.result(timeout=10)
            assert_exited(api, handles)
    receipt = json.loads(next((tmp_path / "receipts").glob("native-*/execution.json")).read_text())
    assert not receipt["completed"]
    assert receipt["status"] == ("cancelled" if cancel else "timed_out")
