"""Bounded atomic publication while Windows readers briefly hold a file open."""

from pathlib import Path
import time


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
