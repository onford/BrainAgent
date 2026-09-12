"""Stage timing without changing numerical settings or resource limits."""
from contextlib import contextmanager
import os
from pathlib import Path
import time

from app.preprocessing.storage import write_json


@contextmanager
def observe_stage(output, stage):
    started_at, started, cpu = time.time(), time.perf_counter(), time.process_time()
    outcome = 'raised'
    try:
        yield
        outcome = 'returned'
    finally:
        # Every stage owns its file; an interrupted process leaves no completed
        # observation. No missing child/native CPU is filled with a guessed zero.
        write_json(Path(output) / '_assessment' / 'stage-resources' / f'{stage}.json', {
            'schema_version': 'assessment-stage-cost-1', 'stage': stage,
            'pid': os.getpid(), 'outcome': outcome,
            'started_at_unix_seconds': started_at,
            'ended_at_unix_seconds': time.time(),
            'wall_seconds': time.perf_counter() - started,
            'supervisor_cpu_seconds': time.process_time() - cpu,
            'cpu_scope': 'This assessment process only; excludes utility and native descendant processes. Use their execution receipts or external process-tree telemetry.',
            'io_wait_seconds': None,
            'io_wait_status': 'not_measured; wall minus CPU is not IO wait',
        })
