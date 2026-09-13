import ctypes
import importlib
import json
from pathlib import Path
import sys
import threading

import pytest

from app import file_publish


@pytest.mark.parametrize('code', [5, 32, 33])
def test_search_snapshot_read_retries_native_transient_lock(tmp_path, monkeypatch, code):
    from app.search.io import read
    target = tmp_path / 'search.json'
    target.write_text('{"status":"running"}', encoding='utf8')
    original = Path.read_text
    calls = []

    def locked(path, **kwargs):
        calls.append(path)
        if len(calls) < 3:
            error = PermissionError('atomic replacement in progress')
            error.winerror = code
            raise error
        return original(path, **kwargs)

    monkeypatch.setattr(Path, 'read_text', locked)
    monkeypatch.setattr(file_publish.time, 'sleep', lambda _: None)
    assert read(target) == {'status': 'running'}
    assert len(calls) == 3


@pytest.mark.parametrize('code, attempts', [(5, 9), (32, 9), (33, 9), (2, 1), (None, 1)])
def test_snapshot_read_does_not_hide_persistent_or_other_errors(tmp_path, monkeypatch, code, attempts):
    calls = []
    error = PermissionError('denied')
    if code is not None:
        error.winerror = code

    def fail(*args, **kwargs):
        calls.append(1)
        raise error

    monkeypatch.setattr(Path, 'read_text', fail)
    monkeypatch.setattr(file_publish.time, 'sleep', lambda _: None)
    with pytest.raises(PermissionError) as caught:
        file_publish.read_text(tmp_path / 'search.json')
    assert caught.value is error
    assert len(calls) == attempts


def test_snapshot_reader_preserves_json_integrity_errors(tmp_path):
    from app.search.io import read
    target = tmp_path / 'search.json'
    target.write_text('{incomplete', encoding='utf8')
    with pytest.raises(json.JSONDecodeError):
        read(target)


@pytest.mark.skipif(sys.platform != 'win32', reason='native Windows sharing semantics')
def test_actual_windows_exclusive_lock_can_release_during_read(tmp_path):
    from ctypes import wintypes
    from app.search.io import read
    target = tmp_path / 'search.json'
    target.write_text('{"status":"running"}', encoding='utf8')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(target), 0x80000000, 0, None, 3, 0x80, None)
    assert handle != wintypes.HANDLE(-1).value
    timer = threading.Timer(.12, lambda: kernel.CloseHandle(handle))
    timer.start()
    try:
        assert read(target) == {'status': 'running'}
    finally:
        timer.join()


@pytest.mark.parametrize("code", [5, 32, 33])
def test_transient_windows_lock_preserves_old_file_until_publish(
    tmp_path, monkeypatch, code
):
    source, target = tmp_path / "pending.tmp", tmp_path / "state.json"
    source.write_text("new")
    target.write_text("old")
    original = Path.replace
    calls = []

    def replace(path, destination):
        calls.append(path)
        assert target.read_text() == "old"
        if len(calls) < 3:
            error = PermissionError("reader holds destination")
            error.winerror = code
            raise error
        return original(path, destination)

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(file_publish.time, "sleep", lambda _: None)
    file_publish.replace_file(source, target)
    assert len(calls) == 3
    assert target.read_text() == "new"
    assert not source.exists()


@pytest.mark.parametrize("windows_lock", [False, True])
def test_permanent_error_is_bounded_and_preserves_both_files(
    tmp_path, monkeypatch, windows_lock
):
    source, target = tmp_path / "pending.tmp", tmp_path / "state.json"
    source.write_text("new")
    target.write_text("old")
    calls = []

    def fail(*_):
        calls.append(1)
        error = PermissionError("denied")
        if windows_lock:
            error.winerror = 5
        raise error

    monkeypatch.setattr(Path, "replace", fail)
    monkeypatch.setattr(file_publish.time, "sleep", lambda _: None)
    with pytest.raises(PermissionError):
        file_publish.replace_file(source, target)
    assert len(calls) == (9 if windows_lock else 1)
    assert target.read_text() == "old"
    assert source.read_text() == "new"


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows sharing semantics")
def test_actual_windows_reader_can_release_during_publication(tmp_path):
    from ctypes import wintypes

    source, target = tmp_path / "pending.tmp", tmp_path / "state.json"
    source.write_text("new")
    target.write_text("old")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(target), 0x80000000, 1, None, 3, 0x80, None)
    assert handle != wintypes.HANDLE(-1).value
    # The reader shares reads, but deliberately denies delete/rename sharing.
    timer = threading.Timer(0.12, lambda: kernel.CloseHandle(handle))
    timer.start()
    try:
        file_publish.replace_file(source, target)
    finally:
        timer.join()
    assert target.read_text() == "new"
    assert not source.exists()


@pytest.mark.parametrize(
    "module,function",
    [
        ("app.search.io", "write"),
        ("app.search.worker", "write_json"),
        ("app.preprocessing.storage", "write_json"),
        ("app.workflows.records", "write_readable"),
    ],
)
@pytest.mark.parametrize("persistent", [False, True])
def test_json_publishers_retry_and_clean_temporary_files(
    tmp_path, monkeypatch, module, function, persistent
):
    writer = getattr(importlib.import_module(module), function)
    target = tmp_path / "state.json"
    target.write_text('{"value":"old"}')
    original = Path.replace
    calls = []

    def replace(path, destination):
        calls.append(1)
        assert json.loads(target.read_text()) == {"value": "old"}
        if persistent or len(calls) == 1:
            error = PermissionError("Windows reader")
            error.winerror = 32
            raise error
        return original(path, destination)

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(file_publish.time, "sleep", lambda _: None)
    if persistent:
        with pytest.raises(PermissionError):
            writer(target, {"value": "new"})
    else:
        writer(target, {"value": "new"})
    assert len(calls) == (9 if persistent else 2)
    assert json.loads(target.read_text()) == {"value": "old" if persistent else "new"}
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize(
    "module,function",
    [
        ("app.search.catalog", "search_engine_hash"),
        ("app.preprocessing.units", "engine_hash"),
    ],
)
def test_frozen_engine_covers_shared_publisher(monkeypatch, module, function):
    engine = importlib.import_module(module)
    fingerprint = getattr(engine, function)
    before = fingerprint()
    original = engine.file_hash
    monkeypatch.setattr(
        engine,
        "file_hash",
        lambda path: "f" * 64
        if Path(path).name == "file_publish.py"
        else original(path),
    )
    assert fingerprint() != before
