"""Live resource scans tolerate publication races, not storage failures."""

import os
from pathlib import Path
import threading

import pytest

from app.search import io, worker
from app.preprocessing.resources import MIB, ResourceError


def test_disappearing_file_is_not_a_search_failure(tmp_path, monkeypatch):
    stable = tmp_path / "signal.npy"
    stable.write_bytes(b"signal")
    temporary = tmp_path / ".publish.tmp"
    temporary.write_bytes(b"transient")
    scan = os.scandir

    class Entry:
        def __init__(self, entry):
            self.entry, self.path = entry, entry.path

        def stat(self, **kwargs):
            if Path(self.path) == temporary:
                temporary.unlink()
            # DirEntry caches stat data on Windows; force the POSIX-style race.
            return Path(self.path).stat(**kwargs)

    class Scan:
        def __enter__(self):
            self.context = scan(tmp_path)
            return iter([Entry(e) for e in self.context])

        def __exit__(self, *args):
            return self.context.__exit__(*args)

    monkeypatch.setattr(io.os, "scandir", lambda path: Scan())
    assert io.directory_bytes(tmp_path) == len(b"signal")


def test_disappearing_directory_is_not_a_search_failure(tmp_path, monkeypatch):
    child = tmp_path / "temporary"
    child.mkdir()
    (tmp_path / "stable").write_bytes(b"abc")
    scan = os.scandir

    def race(path):
        if Path(path) == child:
            child.rmdir()
        return scan(path)

    monkeypatch.setattr(io.os, "scandir", race)
    assert io.directory_bytes(tmp_path) == 3
    with pytest.raises(FileNotFoundError):
        io.directory_bytes(tmp_path / "missing-root")


def test_inaccessible_storage_is_not_zero_usage(tmp_path, monkeypatch):
    def denied(path):
        raise PermissionError("storage unavailable")

    monkeypatch.setattr(io.os, "scandir", denied)
    with pytest.raises(PermissionError, match="storage unavailable"):
        io.directory_bytes(tmp_path)
    with pytest.raises(PermissionError, match="storage unavailable"):
        worker._limits(tmp_path, {"memory_limit_bytes": 128*MIB, "disk_limit_bytes": 128*MIB})


def test_atomic_publisher_and_capacity_check(tmp_path):
    (tmp_path / "stable").write_bytes(b"baseline")
    started, done = threading.Event(), threading.Event()
    errors = []

    def publish():
        try:
            started.set()
            for i in range(150):
                io.write(tmp_path / "status.json", {"iteration": i})
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    thread = threading.Thread(target=publish)
    thread.start()
    started.wait()
    try:
        while not done.is_set():
            assert io.directory_bytes(tmp_path) >= len(b"baseline")
    finally:
        thread.join(timeout=10)
    assert not thread.is_alive() and not errors
    assert io.read(tmp_path / "status.json") == {"iteration": 149}
    assert io.directory_bytes(tmp_path) == sum(p.stat().st_size for p in tmp_path.iterdir())
    # A real disk shortage remains a resource error after the race fix.
    with pytest.raises(ResourceError, match="磁盘资源不足"):
        worker._limits(tmp_path, {"memory_limit_bytes": 128*MIB, "disk_limit_bytes": 64*MIB})
