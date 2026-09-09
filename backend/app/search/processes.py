"""Own a subprocess tree, measure aggregate RSS, and terminate all descendants.

Windows uses creation-time Job assignment (Windows 10+) and KILL_ON_JOB_CLOSE.
The Job handle is never inherited, so abrupt supervisor death also kills the
tree. Linux uses a dedicated session/process group; the numerical worker's
parent guard supplies parent-death protection there.
"""

from __future__ import annotations

from contextlib import ExitStack
import ctypes
import os
from pathlib import Path
import signal
import subprocess
import time


if os.name == "nt":
    from ctypes import wintypes as w
    import msvcrt

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_longlong),
            ("job_time", ctypes.c_longlong),
            ("flags", w.DWORD),
            ("min_ws", ctypes.c_size_t),
            ("max_ws", ctypes.c_size_t),
            ("active_limit", w.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", w.DWORD),
            ("scheduling", w.DWORD),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("basic", _BasicLimits),
            ("io", ctypes.c_ulonglong * 6),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process_memory", ctypes.c_size_t),
            ("peak_job_memory", ctypes.c_size_t),
        ]

    class _StartupInfo(ctypes.Structure):
        _fields_ = [
            ("cb", w.DWORD),
            ("reserved", w.LPWSTR),
            ("desktop", w.LPWSTR),
            ("title", w.LPWSTR),
            ("x", w.DWORD),
            ("y", w.DWORD),
            ("xsize", w.DWORD),
            ("ysize", w.DWORD),
            ("xchars", w.DWORD),
            ("ychars", w.DWORD),
            ("fill", w.DWORD),
            ("flags", w.DWORD),
            ("show", w.WORD),
            ("reserved_size", w.WORD),
            ("reserved_bytes", ctypes.c_void_p),
            ("stdin", w.HANDLE),
            ("stdout", w.HANDLE),
            ("stderr", w.HANDLE),
        ]

    class _StartupInfoEx(ctypes.Structure):
        _fields_ = [("startup", _StartupInfo), ("attributes", ctypes.c_void_p)]

    class _ProcessInfo(ctypes.Structure):
        _fields_ = [
            ("process", w.HANDLE),
            ("thread", w.HANDLE),
            ("pid", w.DWORD),
            ("tid", w.DWORD),
        ]

    class _MemoryCounters(ctypes.Structure):
        _fields_ = [("cb", w.DWORD), ("faults", w.DWORD)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak_ws",
                "working_set",
                "peak_paged",
                "paged",
                "peak_nonpaged",
                "nonpaged",
                "pagefile",
                "peak_pagefile",
            )
        ]

    def _kernel():
        dll = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": (
                [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD],
                w.BOOL,
            ),
            "QueryInformationJobObject": (
                [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p],
                w.BOOL,
            ),
            "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
            "IsProcessInJob": ([w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)], w.BOOL),
            "InitializeProcThreadAttributeList": (
                [ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.c_size_t)],
                w.BOOL,
            ),
            "UpdateProcThreadAttribute": (
                [
                    ctypes.c_void_p,
                    w.DWORD,
                    ctypes.c_size_t,
                    ctypes.c_void_p,
                    ctypes.c_size_t,
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                ],
                w.BOOL,
            ),
            "DeleteProcThreadAttributeList": ([ctypes.c_void_p], None),
            "CreateProcessW": (
                [
                    w.LPCWSTR,
                    w.LPWSTR,
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    w.BOOL,
                    w.DWORD,
                    ctypes.c_void_p,
                    w.LPCWSTR,
                    ctypes.POINTER(_StartupInfoEx),
                    ctypes.POINTER(_ProcessInfo),
                ],
                w.BOOL,
            ),
            "GetCurrentProcess": ([], w.HANDLE),
            "DuplicateHandle": (
                [
                    w.HANDLE,
                    w.HANDLE,
                    w.HANDLE,
                    ctypes.POINTER(w.HANDLE),
                    w.DWORD,
                    w.BOOL,
                    w.DWORD,
                ],
                w.BOOL,
            ),
            "OpenProcess": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "CloseHandle": ([w.HANDLE], w.BOOL),
            "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
            "GetExitCodeProcess": ([w.HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL),
            "K32GetProcessMemoryInfo": (
                [w.HANDLE, ctypes.POINTER(_MemoryCounters), w.DWORD],
                w.BOOL,
            ),
        }
        for name, (args, result) in signatures.items():
            function = getattr(dll, name)
            function.argtypes, function.restype = args, result
        return dll

    def _check(ok):
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())


class ProcessTree:
    """Synchronous process owner; use asyncio.to_thread(tree.wait) when awaiting.

    stdout/stderr accept binary files or DEVNULL; stderr also accepts STDOUT.
    close() is mandatory, including after a successful root-process exit.
    """

    def __init__(self, command, *, stdout=None, stderr=None, env=None, cwd=None):
        self.command = [os.fspath(arg) for arg in command]
        self._closed = False
        self._returncode = None
        if os.name == "nt":
            self._job = self._handle = None
            self._api = _kernel()
            try:
                self._start_windows(stdout, stderr, env, cwd)
            except BaseException:
                self.close()
                raise
        else:
            if not Path("/proc/self/statm").is_file():
                raise RuntimeError(
                    "process-tree RSS requires Windows Jobs or Linux /proc"
                )
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.DEVNULL,
                stdout=stdout if stdout is not None else subprocess.DEVNULL,
                stderr=stderr if stderr is not None else subprocess.DEVNULL,
                env=env,
                cwd=cwd,
                start_new_session=True,
            )
            self.pid = self._process.pid

    def _start_windows(self, stdout, stderr, env, cwd):
        api = self._api
        self._job = api.CreateJobObjectW(None, None)
        _check(self._job)
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        _check(
            api.SetInformationJobObject(
                self._job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            )
        )
        # Explicit handle and Job lists prevent both accidental Job inheritance
        # and the create-then-assign race, including supervisor death at startup.
        with ExitStack() as stack:
            current = api.GetCurrentProcess()

            def inherited(stream, mode):
                if stream is None or stream == subprocess.DEVNULL:
                    stream = stack.enter_context(open(os.devnull, mode))
                handle = w.HANDLE()
                _check(
                    api.DuplicateHandle(
                        current,
                        msvcrt.get_osfhandle(stream.fileno()),
                        current,
                        ctypes.byref(handle),
                        0,
                        True,
                        2,
                    )
                )
                stack.callback(api.CloseHandle, handle)
                return handle.value

            stdin_handle = inherited(None, "rb")
            stdout_handle = inherited(stdout, "wb")
            stderr_handle = (
                stdout_handle
                if stderr == subprocess.STDOUT
                else inherited(stderr, "wb")
            )
            handles = (
                w.HANDLE * len(set((stdin_handle, stdout_handle, stderr_handle)))
            )(*dict.fromkeys((stdin_handle, stdout_handle, stderr_handle)))
            jobs = (w.HANDLE * 1)(self._job)
            size = ctypes.c_size_t()
            api.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
            if not size.value:
                _check(False)
            attributes = ctypes.create_string_buffer(size.value)
            _check(
                api.InitializeProcThreadAttributeList(
                    attributes, 2, 0, ctypes.byref(size)
                )
            )
            stack.callback(api.DeleteProcThreadAttributeList, attributes)
            for attribute, value in ((0x00020002, handles), (0x0002000D, jobs)):
                _check(
                    api.UpdateProcThreadAttribute(
                        attributes,
                        0,
                        attribute,
                        value,
                        ctypes.sizeof(value),
                        None,
                        None,
                    )
                )
            startup = _StartupInfoEx()
            startup.startup.cb = ctypes.sizeof(startup)
            startup.startup.flags = 0x00000100  # STARTF_USESTDHANDLES
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = (
                stdin_handle,
                stdout_handle,
                stderr_handle,
            )
            startup.attributes = ctypes.cast(attributes, ctypes.c_void_p)
            block = None
            if env is not None:
                block = ctypes.create_unicode_buffer(
                    "\0".join(
                        f"{key}={value}"
                        for key, value in sorted(
                            env.items(), key=lambda item: item[0].upper()
                        )
                    )
                    + "\0\0"
                )
            info = _ProcessInfo()
            _check(
                api.CreateProcessW(
                    self.command[0],
                    ctypes.create_unicode_buffer(subprocess.list2cmdline(self.command)),
                    None,
                    None,
                    True,
                    0x00080000
                    | 0x00000400
                    | 0x08000000,  # EXTENDED, UNICODE_ENV, NO_WINDOW
                    block,
                    os.fspath(cwd) if cwd is not None else None,
                    ctypes.byref(startup),
                    ctypes.byref(info),
                )
            )
            self._handle, self.pid = info.process, info.pid
            api.CloseHandle(info.thread)

    @property
    def returncode(self):
        if self._returncode is not None:
            return self._returncode
        if self._closed:
            return None
        if os.name != "nt":
            self._returncode = self._process.poll()
        else:
            state = self._api.WaitForSingleObject(self._handle, 0)
            if state == 0:  # Handles bind exit checks to this process identity.
                code = w.DWORD()
                _check(self._api.GetExitCodeProcess(self._handle, ctypes.byref(code)))
                self._returncode = code.value
            elif state != 0x102:
                _check(False)
        return self._returncode

    def wait(self, timeout=None):
        started = time.monotonic()
        if os.name != "nt":
            self._returncode = self._process.wait(timeout=timeout)
        else:
            milliseconds = (
                0xFFFFFFFF
                if timeout is None
                else min(0xFFFFFFFE, max(0, int(timeout * 1000)))
            )
            state = self._api.WaitForSingleObject(self._handle, milliseconds)
            if state == 0x102:
                raise subprocess.TimeoutExpired(self.command, timeout)
            if state != 0:
                _check(False)
        # A launcher may exit before its descendants. Keep monitoring the Job
        # until all members have exited, including during cancellation cleanup.
        while self.pids():
            if timeout is not None and time.monotonic() - started >= timeout:
                raise subprocess.TimeoutExpired(self.command, timeout)
            time.sleep(0.025)
        return self.returncode

    def pids(self):
        if self._closed:
            return []
        if os.name != "nt":
            members = []
            for path in Path("/proc").glob("[0-9]*/stat"):
                try:
                    # comm can contain spaces and parentheses; fields after it
                    # start with state, ppid, pgrp, session.
                    fields = path.read_text().rsplit(")", 1)[1].split()
                    if (
                        fields[0] != "Z"
                        and int(fields[2]) == self.pid
                        and int(fields[3]) == self.pid
                    ):
                        members.append(int(path.parent.name))
                except FileNotFoundError:
                    pass
            return members
        capacity = 16
        while True:

            class ProcessIds(ctypes.Structure):
                _fields_ = [
                    ("assigned", w.DWORD),
                    ("count", w.DWORD),
                    ("ids", ctypes.c_size_t * capacity),
                ]

            value = ProcessIds()
            if self._api.QueryInformationJobObject(
                self._job, 3, ctypes.byref(value), ctypes.sizeof(value), None
            ):
                return list(value.ids[: value.count])
            if ctypes.get_last_error() != 234:  # ERROR_MORE_DATA
                _check(False)
            capacity = max(capacity * 2, value.assigned)

    def memory_bytes(self):
        """Sum live Job members' working sets; never substitute launcher RSS."""
        total = 0
        for pid in self.pids():
            if os.name != "nt":
                try:
                    total += int(
                        Path(f"/proc/{pid}/statm").read_text().split()[1]
                    ) * os.sysconf("SC_PAGE_SIZE")
                except FileNotFoundError:
                    pass
                continue
            api = self._api
            handle = api.OpenProcess(0x1000 | 0x0010 | 0x00100000, False, pid)
            if not handle:
                if ctypes.get_last_error() == 87:  # Process exited between queries.
                    continue
                _check(False)
            try:
                member = w.BOOL()
                _check(api.IsProcessInJob(handle, self._job, ctypes.byref(member)))
                if not member.value:
                    continue  # PID was recycled: never inspect an unrelated process.
                counters = _MemoryCounters()
                counters.cb = ctypes.sizeof(counters)
                if not api.K32GetProcessMemoryInfo(
                    handle, ctypes.byref(counters), counters.cb
                ):
                    if api.WaitForSingleObject(handle, 0) == 0:
                        continue
                    _check(False)
                total += counters.working_set
            finally:
                api.CloseHandle(handle)
        return total

    def kill(self):
        if self._closed:
            return
        if os.name == "nt":
            if self._job:
                _check(self._api.TerminateJobObject(self._job, 1))
        else:
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def close(self):
        if self._closed:
            return
        if os.name == "nt":
            if self._job:
                self._api.CloseHandle(self._job)
                self._job = None
            if self._handle:
                self._api.CloseHandle(self._handle)
                self._handle = None
        else:
            self.kill()
            self._process.wait()
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            self.kill()
            self.wait()
        finally:
            self.close()
