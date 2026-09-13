"""Bounded atomic publication while Windows readers briefly hold a file open."""

from pathlib import Path
import errno
import sys
import time


def read_text(path: Path, *, encoding: str = 'utf-8') -> str:
    """Read an atomic snapshot despite a brief Windows replacement lock.

    Only native sharing/access errors are retried. Missing files, invalid text,
    invalid JSON (in callers), and persistent denial remain visible failures.
    """
    delays = (0.02, 0.04, 0.08, 0.16, 0.25, 0.25, 0.25, 0.25)
    for attempt in range(len(delays) + 1):
        try:
            return Path(path).read_text(encoding=encoding)
        except OSError as exc:
            # CRT-backed open() can discard winerror and retain only EACCES.
            native_lock = getattr(exc, 'winerror', None) in {5, 32, 33}
            crt_access = (sys.platform == 'win32' and getattr(exc, 'winerror', None) is None
                          and isinstance(exc, PermissionError) and exc.errno in {errno.EACCES, errno.EPERM})
            if not (native_lock or crt_access) or attempt == len(delays):
                raise
            time.sleep(delays[attempt])


def replace_file(source: Path, destination: Path) -> None:
    """Keep the old destination intact until replacement succeeds.

    Windows readers and antivirus scanners can temporarily deny delete sharing.
    Retry only the corresponding native errors; permanent failures still escape.
    The caller owns temporary-file cleanup and any content validation.
    """
    delays = (0.02, 0.04, 0.08, 0.16, 0.25, 0.25, 0.25, 0.25)
    for attempt in range(len(delays) + 1):
        try:
            Path(source).replace(destination)
            return
        except OSError as exc:
            transient_lock = getattr(exc, "winerror", None) in {5, 32, 33}
            if not transient_lock or attempt == len(delays):
                raise
            time.sleep(delays[attempt])
