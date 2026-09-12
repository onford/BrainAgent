"""Measure the complete EEGMMIDB baseline with unchanged five-fold/three-seed training.

Engineering resource probe only. This driver supplies a Collection context and
never claims to exercise the upstream model research or final-agent acceptance.
"""
import argparse
import asyncio
import csv
import ctypes
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
from types import SimpleNamespace

CODE = Path(__file__).resolve().parents[1]
ROOT = None
sys.path.insert(0, str(CODE))
from app.preprocessing.storage import Storage, file_hash, write_json
from app.search import service as service_module
from app.search.contracts import SearchRequest, SearchBudget
from app.search.io import read
from app.search.processes import ProcessTree


class Accounting(ctypes.Structure):
    _fields_ = [(name, ctypes.c_longlong) for name in ('user', 'kernel', 'period_user', 'period_kernel')] + [
        (name, w.DWORD) for name in ('faults', 'processes', 'active', 'terminated')]


class IoAccounting(ctypes.Structure):
    _fields_ = [('basic', Accounting)] + [(name, ctypes.c_ulonglong) for name in (
        'read_operations', 'write_operations', 'other_operations', 'read_bytes', 'write_bytes', 'other_bytes')]


def snapshot_hashes(root):
    return {p.relative_to(root).as_posix(): file_hash(p) for p in root.rglob('*')
            if p.is_file() and '__pycache__' not in p.parts}


class ProfiledTree(ProcessTree):
    """Observe the actual inherited Job; do not replace numerical execution."""
    records = []
    def __init__(self, command, **kwargs):
        super().__init__(command, **kwargs)
        self.stage = command[command.index('--stage') + 1]
        self.sample_stop = threading.Event()
        self.started = time.perf_counter()
        self.peak_rss = 0
        self.sample_errors = []
        self.last = None
        self.trace_path = ROOT / f'resources-{self.stage}-{self.pid}.csv'
        self.trace = self.trace_path.open('w', newline='', encoding='utf-8', buffering=1)
        self.writer = csv.DictWriter(self.trace, fieldnames=['observed_at_unix_seconds', 'wall_seconds', 'cpu_user_seconds', 'cpu_kernel_seconds',
             'rss_bytes', 'read_bytes', 'write_bytes', 'other_bytes', 'read_operations', 'write_operations',
             'other_operations', 'total_processes', 'active_processes', 'page_faults'])
        self.writer.writeheader()
        self.sampler = threading.Thread(target=self.observe, daemon=True)
        self.sampler.start()

    def sample(self):
        value = IoAccounting()
        if not self._api.QueryInformationJobObject(self._job, 8, ctypes.byref(value), ctypes.sizeof(value), None):
            raise ctypes.WinError(ctypes.get_last_error())
        rss = self.memory_bytes()
        self.peak_rss = max(self.peak_rss, rss)
        row = dict(observed_at_unix_seconds=time.time(), wall_seconds=time.perf_counter()-self.started,
                   cpu_user_seconds=value.basic.user/1e7, cpu_kernel_seconds=value.basic.kernel/1e7,
                   rss_bytes=rss, total_processes=value.basic.processes, active_processes=value.basic.active,
                   page_faults=value.basic.faults)
        row.update({name:getattr(value,name) for name,_ in IoAccounting._fields_[1:]})
        self.writer.writerow(row)
        self.last = row

    def observe(self):
        while not self.sample_stop.is_set():
            try:
                self.sample()
            except Exception as exc:
                self.sample_errors.append(f'{type(exc).__name__}: {exc}')
            self.sample_stop.wait(.25)

    def close(self):
        if self._closed:
            return
        self.sample_stop.set()
        self.sampler.join()
        try:
            self.sample()
        except Exception as exc:
            self.sample_errors.append(f'{type(exc).__name__}: {exc}')
        row = dict(stage=self.stage, launcher_pid=self.pid, returncode=self.returncode,
                   wall_seconds=time.perf_counter()-self.started, sampled_peak_tree_rss_bytes=self.peak_rss,
                   sampling_period_seconds=.25, final_job_counters=self.last, sampling_errors=self.sample_errors,
                   trace_path=str(self.trace_path), trace_sha256=None,
                   io_wait_seconds=None, io_wait_status='not_measured; CPU idle/wall differences are not IO wait',
                   io_scope='Windows Job IO transfer counters include all current and exited members; not physical disk traffic')
        self.trace.close()
        row['trace_sha256'] = file_hash(self.trace_path)
        self.records.append(row)
        write_json(ROOT / 'resource-stages.json', self.records)
        super().close()


async def main(args):
    global ROOT
    ROOT = Path(args.output).resolve()
    source_input = Path(args.input_json).resolve()
    if os.name != 'nt':
        raise RuntimeError('This telemetry driver requires Windows Job accounting')
    if ROOT.exists():
        raise ValueError('Output must be a new directory; existing artifacts remain immutable')
    input_value = read(source_input)
    input_root = Path(input_value['collection']['root']).resolve(strict=True)
    if ROOT.is_relative_to(input_root) or input_root.is_relative_to(ROOT):
        raise ValueError('Input and output trees must be disjoint before creating output files')
    source_hash = file_hash(source_input)
    import re
    if any(not re.fullmatch(r'S[0-9]{3}R[0-9]{2}', r['id']) for r in input_value['collection']['records']):
        raise ValueError('EEGMMIDB record IDs required for exact participant grouping')
    subjects = {r['id']:r['id'][:4] for r in input_value['collection']['records']}
    selected = input_value['collection']['selected_record_ids']
    if len(selected) != 327 or len({subjects[r] for r in selected}) != 109:
        raise ValueError('This full-dataset probe requires all 109 participants and 327 selected MI recordings')
    ROOT.mkdir(parents=True)
    source_folder = ROOT / 'source-workflow'
    (source_folder / 'collection').mkdir(parents=True)
    shutil.copyfile(source_input, source_folder / 'collection/input.json')
    if file_hash(source_folder / 'collection/input.json') != source_hash:
        raise ValueError('Collection input changed during copying')
    code_before = snapshot_hashes(CODE / 'app')
    input_before = snapshot_hashes(input_root)
    source_state = {'outputs': {'data_collection': {}, 'data_survey': {'records': [
        {'id': k, 'subject': v} for k,v in subjects.items()]}}, 'request': {'tmin': 0., 'tmax': 2.}}
    preprocessing = SimpleNamespace(allowed_roots=[input_root], store=Storage(ROOT / 'evidence-store'))
    workflows = SimpleNamespace(get=lambda *args: source_state, folder=lambda *args: source_folder,
                                preprocessing=preprocessing, llm=None)
    service_module.ProcessTree = ProfiledTree
    service = service_module.SearchService(ROOT / 'searches', workflows)
    state = service.create('resource-probe', SearchRequest(workflow_id='f'*32, strategy='exhaustive',
        budget=SearchBudget(max_candidates=1, max_proposals=0, max_evidence_reads=0,
                            max_seconds=args.seconds, max_memory_mb=args.memory_mb, max_disk_mb=args.disk_mb, max_retries=0)), start=False)
    root = service.folder(state['id'])
    write_json(ROOT / 'probe-request.json', dict(scope='Engineering cost only; no literature search or final-agent acceptance',
        search_id=state['id'], selected_records=327, participants=109, source_input_sha256=source_hash,
        frozen_code=code_before, driver_sha256=file_hash(Path(__file__)), frozen_input_files=input_before,
        protocol=state['protocol'], windows_io_wait_available=False))
    started = time.perf_counter()
    try:
        await service.run('resource-probe', state['id'])
    finally:
        await service.close()
    result = service.get('resource-probe', state['id'])
    output_bytes = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    panel = result.get('panel') or {}
    candidates = result['candidates']
    summary = dict(search_id=state['id'], status=result['status'], stop_reason=result.get('stop_reason'),
        error=result.get('error'), wall_seconds=time.perf_counter()-started,
        output_bytes=output_bytes, usage=result['usage'], candidates=[
            {'id':c['id'],'status':c['status'],'error':c.get('error'),'receipt':c.get('receipt')} for c in candidates],
        panel_counts={'participants':len(panel.get('development_subjects',[])), 'records':len(panel.get('records',{})),
                      'trials':len(panel.get('trials',[])), 'folds':len(panel.get('folds',[]))},
        resource_stages=ProfiledTree.records,
        frozen_code_unchanged=snapshot_hashes(CODE / 'app')==code_before,
        frozen_input_unchanged=snapshot_hashes(input_root)==input_before,
        source_input_unchanged=file_hash(source_input)==source_hash,
        final_agent_acceptance=False, interpretation='Complete baseline cost probe; no substantive-paper or independent-test claim')
    summary['measurement_complete'] = bool(candidates and result['status'] == 'stopped'
        and all(c['status'] == 'evaluated' and (c.get('receipt') or {}).get('assessment', {}).get('status') == 'complete' for c in candidates)
        and summary['frozen_code_unchanged'] and summary['frozen_input_unchanged'] and summary['source_input_unchanged'])
    write_json(ROOT / 'audit.json', summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in {'candidates','resource_stages'}},ensure_ascii=False))
    return 0 if summary['measurement_complete'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-json', required=True, help='Verified full EEGMMIDB Collection input.json')
    parser.add_argument('--output', required=True, help='New measurement directory')
    parser.add_argument('--seconds', type=float, default=7200.)
    parser.add_argument('--memory-mb', type=int, default=16384)
    parser.add_argument('--disk-mb', type=int, default=65536)
    sys.exit(asyncio.run(main(parser.parse_args())))
