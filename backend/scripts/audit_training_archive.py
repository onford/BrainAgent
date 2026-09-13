"""Verify a delivered ZIP against its manifest, physical arrays and frozen events.

Optionally run the packaged compatibility example in a new extraction directory,
only when its bytes match an explicitly supplied trusted template SHA256.
"""
import argparse
from collections import Counter
from contextlib import ExitStack, contextmanager
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import time
import zipfile

import numpy as np

from app.preprocessing.storage import digest, file_hash, write_json


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def safe_member(name):
    parts = PurePosixPath(name).parts
    require(bool(parts) and not name.startswith('/') and '\\' not in name and ':' not in name
        and all(part not in ('', '.', '..') for part in name.split('/')), 'Unsafe archive member name')
    return name


@contextmanager
def mapped(path):
    values = np.load(path, mmap_mode='r', allow_pickle=False)
    try:
        yield values
    finally:
        if getattr(values, '_mmap', None) is not None:
            values._mmap.close()


def audit(workflow, search, output, *, run_example=False, template_sha256=None):
    workflow, search = workflow.resolve(strict=True), search.resolve(strict=True)
    output = output.resolve()
    require(not output.exists() and all(not output.is_relative_to(root) and not root.is_relative_to(output)
        for root in (workflow, search)), 'Use a new audit directory disjoint from workflow and search')
    require(not run_example or (template_sha256 and len(template_sha256) == 64), 'Supply the trusted template SHA256 before executing the example')
    before = {}

    def checked(path, checksum=None):
        path = path.resolve(strict=True)
        require(any(path.is_relative_to(root) for root in (workflow, search)), 'Evidence escapes declared roots')
        actual = file_hash(path)
        require(checksum is None or actual == checksum, f'Artifact checksum differs: {path}')
        require(path not in before or before[path] == actual, 'Artifact changed during audit')
        before[path] = actual
        return path

    def read(path):
        return json.loads(checked(path).read_text(encoding='utf-8'))

    state = read(workflow / 'workflow.json')
    require(state['status'] == 'completed', 'Workflow delivery has not completed')
    delivery = state['outputs']['data_delivery']
    delivery = read(workflow / delivery) if isinstance(delivery, str) else delivery
    archive = checked(workflow / delivery['archive'], delivery['sha256'])
    manifest = read(workflow / delivery['manifest'])
    require(manifest['workflow_id'] == state['id'] and manifest['search_id'] == search.name, 'Workflow/search manifest binding differs')
    require(manifest['unit'] == 'V' and manifest['independent_confirmation'] is False, 'Expected development physical-voltage export')
    candidate = search / 'candidates' / manifest['selected_candidate_id']
    result = read(candidate / 'result.json')
    receipt = read(candidate / 'receipt.json')
    require(receipt['assessment']['bindings']['result_hash'] == digest(result), 'Selected result hash differs from assessment')
    panel = read(search / 'panel.json')
    require(panel['panel_hash'] == digest({k: v for k, v in panel.items() if k != 'panel_hash'}), 'Panel checksum differs')
    frozen = {t['event_id']: t for t in panel['trials'] if t['eligible']}
    output.mkdir()
    extracted = output / 'extracted'
    extracted.mkdir()
    started = time.perf_counter()
    report = {'status': 'failed', 'workflow_id': state['id'], 'search_id': search.name,
        'selected_candidate_id': manifest['selected_candidate_id'], 'final_agent_accepted': False,
        'scope': 'Delivery integrity and compatibility only; no independent test-set or scientific acceptance'}
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            names = [safe_member(info.filename) for info in infos]
            require(len(names) == len(set(names)), 'Duplicate archive members')
            require(all(not info.is_dir() and not stat.S_ISLNK(info.external_attr >> 16) for info in infos), 'Archive contains a directory or symbolic link')
            require(json.loads(bundle.read('manifest.json')) == manifest, 'Internal and published manifests differ')
            inventory = {row['name']: row for row in manifest['files']}
            require(len(inventory) == len(manifest['files']) and set(names) == set(inventory) | {'manifest.json'}, 'Manifest/member inventory differs')
            extract_names = {'X.npy', 'y.npy', 'subjects.npy', 'split.npy', 'train_example.py', 'trial-index.tsv', 'channels.json', 'labels.json'}
            require(extract_names <= set(inventory), 'Required training files are absent')
            require(sum(inventory[name]['bytes'] for name in extract_names) <= 4 * 1024**3, 'Training extraction exceeds 4 GiB audit cap')
            for name, ref in inventory.items():
                hasher, size = hashlib.sha256(), 0
                with bundle.open(name) as stream:
                    while block := stream.read(1024**2):
                        hasher.update(block)
                        size += len(block)
                require(size == ref['bytes'] and hasher.hexdigest() == ref['sha256'], f'ZIP member differs: {name}')
                if name in extract_names:
                    with bundle.open(name) as stream, (extracted / name).open('xb') as destination:
                        shutil.copyfileobj(stream, destination, 1024**2)
                    require(file_hash(extracted / name) == ref['sha256'], 'Extracted file differs')
            index = json.loads(bundle.read('evaluation/assessment-index.json'))
            require(index['path_base'] == 'archive_root', 'Unknown assessment path base')
            for ref in index['files']:
                require(safe_member(ref['path']) in inventory and inventory[ref['path']]['sha256'] == ref['sha256'], 'Portable assessment reference differs')

            def check_model_paths(value):
                if isinstance(value, dict):
                    if 'path' in value and 'sha256' in value:
                        require(safe_member(value['path']) in inventory and inventory[value['path']]['sha256'] == value['sha256'], 'Portable model reference differs')
                    for child in value.values():
                        check_model_paths(child)
                elif isinstance(value, list):
                    for child in value:
                        check_model_paths(child)

            check_model_paths(index['learners'])
            for key in ('summary', 'core_receipt', 'utility_receipt', 'operator_usage'):
                if index.get(key) is not None:
                    require(safe_member(index[key]) in inventory, 'Portable assessment entry point missing')
            array_map = json.loads(bundle.read('evaluation/artifact-map.json'))['arrays']
            rows = list(csv.DictReader(io.StringIO(bundle.read('trial-index.tsv').decode('utf-8')), delimiter='\t'))
        require([int(row['index']) for row in rows] == list(range(len(rows))), 'Non-contiguous exported trial rows')
        require(Counter(row['source_event'] for row in rows) == Counter({k: 1 for k in frozen}), 'Export omits or duplicates frozen trials')
        records = {r['record_id']: r for r in result['records']}
        require(len(records) == len(result['records']) and {row['record_id'] for row in rows} == set(records), 'Export/result records differ')
        with ExitStack() as stack:
            X, y, subjects, splits = [stack.enter_context(mapped(extracted / f'{name}.npy')) for name in ('X', 'y', 'subjects', 'split')]
            require(X.dtype == np.dtype('float32') and list(X.shape) == manifest['shape'] and len(rows) == len(X), 'Exported X shape/dtype differs')
            require(y.dtype == np.dtype('int64') and y.shape == subjects.shape == splits.shape == (len(X),), 'Label/split array contract differs')
            channels = json.loads((extracted / 'channels.json').read_text(encoding='utf-8'))
            require(channels['unit'] == 'V' and channels['names'] == panel['output_contract']['channels']
                and channels['sfreq'] == panel['output_contract']['sfreq'], 'Export channel/unit/rate contract differs')
            offset = 0
            require(len(array_map) == len(records), 'Array map record count differs')
            for entry in array_map:
                rid, start, stop = entry['record_id'], entry['row_start'], entry['row_stop']
                require(start == offset and stop > start and entry['archive_path'] == 'X.npy'
                    and entry['event_index'] == 'trial-index.tsv' and entry['conversion'] == 'float32', 'Invalid portable array range')
                refs = {ref['name']: ref for ref in records[rid]['result']['artifacts']}
                require(len(refs) == len(records[rid]['result']['artifacts']), 'Duplicate physical artifact names')
                signal_ref, event_ref = refs['signal_V.npy'], refs['events.json']
                require(entry['source_sha256'] == signal_ref['sha256'], 'Portable source array hash differs')
                signal = checked(search / 'engine' / signal_ref['path'], signal_ref['sha256'])
                events = json.loads(checked(search / 'engine' / event_ref['path'], event_ref['sha256']).read_text(encoding='utf-8'))
                events = {event['event_id']: event for event in events}
                with mapped(signal) as values:
                    require(stop - start == len(values), 'Record epoch count differs')
                    for i in range(start, stop):
                        row, truth = rows[i], frozen[rows[i]['source_event']]
                        event = events[row['source_event']]
                        require(row['record_id'] == rid and row['subject'] == truth['subject'] == str(subjects[i])
                            and row['label'] == truth['label'] == event['label'], 'Exported trial identity/label differs')
                        require(event['retained'] and int(row['epoch_index']) == event['epoch_index']
                            and float(row['source_sample']) == event['original_sample'] == truth['source_sample'], 'Exported event position differs')
                        require(int(y[i]) == (row['label'] == 'right_hand') and str(splits[i]) == row['split'] == manifest['subject_split'][row['subject']], 'Exported label/split differs')
                        require(np.array_equal(X[i], values[int(row['epoch_index'])].astype(np.float32)), 'Exported float32 values differ from selected physical output')
                offset = stop
            require(offset == len(X), 'Portable ranges do not cover X')
            require(manifest['classes'] == {str(k): int(np.sum(y == k)) for k in (0, 1)}, 'Class counts differ')
            require(manifest['split_counts'] == {k: int(np.sum(splits == k)) for k in ('train', 'validation', 'test')}, 'Split counts differ')
            report.update(trials=len(X), records=len(records), subjects=len(set(subjects)), verified_zip_members=len(inventory),
                exact_float32_physical_match=True, inference_files_portable=True)
        if run_example:
            example = extracted / 'train_example.py'
            require(file_hash(example) == template_sha256, 'Packaged example differs from trusted source template')
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            command = [sys.executable, '-u', '-X', 'utf8', str(example), '--data', str(extracted), '--output', str(output / 'training-smoke.json')]
            run = subprocess.run(command, cwd=extracted, capture_output=True, timeout=180, creationflags=flags)
            (output / 'training-smoke.log').write_bytes(run.stdout + run.stderr)
            require(run.returncode == 0, 'Packaged training example failed; see training-smoke.log')
            smoke = json.loads((output / 'training-smoke.json').read_text(encoding='utf-8'))
            require(smoke['prediction_count'] == report['trials'] and smoke['quality_evaluated'] is False, 'Unexpected training compatibility receipt')
            report.update(training_example_completed=True, training_smoke=smoke, trusted_template_sha256=template_sha256)
        else:
            report['training_example_completed'] = False
        report['status'] = 'passed'
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        report['read_files_unchanged'] = all(file_hash(path) == checksum for path, checksum in before.items())
        if not report['read_files_unchanged']:
            report['status'] = 'failed'
        report['read_files'] = {str(path): checksum for path, checksum in before.items()}
        report['driver_sha256'] = file_hash(Path(__file__))
        report['wall_seconds'] = time.perf_counter() - started
        write_json(output / 'audit.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workflow', type=Path, required=True)
    parser.add_argument('--search', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-example', action='store_true')
    parser.add_argument('--template-sha256')
    args = parser.parse_args()
    result = audit(args.workflow, args.search, args.output, run_example=args.run_example, template_sha256=args.template_sha256)
    print('AUDIT', result['status'], result.get('error'), flush=True)
    raise SystemExit(0 if result['status'] == 'passed' else 1)
