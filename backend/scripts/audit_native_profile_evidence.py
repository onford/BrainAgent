"""Re-read declared real-record native evidence without rerunning algorithms.

Requires a finished matrix, its independently chosen frozen validation script,
and explicit original input/record/bindings. Reports into a new directory only.
This is source/adapter evidence, not independent scientific validity or utility.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from app.preprocessing.artifact_codec import Codec, fingerprint
from app.preprocessing.assets import freeze_native, verify_native
from app.preprocessing.graph_runtime import Packet, identity, transition
from app.preprocessing.inputs import read_record, validate_record_files
from app.preprocessing.schemas import PreprocessInput, Step
from app.preprocessing.storage import file_hash, write_json
from app.preprocessing.units import engine_hash, environment
from app.preprocessing.units.contracts_v2 import validate_parameters
from app.preprocessing.units.operations_v2 import inventory
from scripts.audit_unit_matrix import audit as audit_matrix, require
from scripts import validate_native_profiles as native


def saved_outputs(directory, packet, step, row, receipt):
    """Reconstruct event lineage from decoded saved values and compare receipts."""
    loaded = []
    for folder in (directory / 'direct-source', directory / 'graph' / step.id):
        descriptor = folder / 'artifacts.json'
        require(descriptor.is_file(), 'Missing saved native descriptor; cannot reconstruct evidence')
        loaded.append(Codec(folder).load(json.loads(descriptor.read_text(encoding='utf8'))))
    expected, actual = loaded
    require(fingerprint(expected['data']) == fingerprint(actual['data']), 'Saved native data/MNE state differs')
    require(fingerprint(expected.get('model')) == fingerprint(actual.get('model')), 'Saved native model differs')
    expected_diagnostics = fingerprint(native.comparable(expected['artifacts']))
    require(expected_diagnostics == fingerprint(native.comparable(actual['artifacts'])),
            'Saved decoded native diagnostics differ')
    before = identity(packet)
    out = transition(packet, actual['data'], actual['artifacts'], row, step.params, node_id=step.id)
    require(identity(packet) == before == receipt['input_sha256'], 'Saved native input identity differs')
    require(identity(out) == receipt['output_sha256'], 'Saved native output identity differs')
    require(out.event_indices.tolist() == receipt['event_indices'] and out.trial_ids == receipt['trial_ids'],
            'Saved native event/trial lineage differs')
    require(list(out.data.get_data().shape) == receipt['shape'], 'Saved native output shape differs')
    require(fingerprint(actual.get('model')) == receipt['model_sha256'] and
            expected_diagnostics == receipt['diagnostics_sha256'], 'Saved native scientific hashes differ')
    maximum = float(np.max(np.abs(actual['data'].get_data() - expected['data'].get_data())))
    require(maximum == receipt['max_abs_error'], 'Saved native numerical difference differs')
    execution = json.loads((directory / 'graph' / step.id / 'execution.json').read_text(encoding='utf8'))
    require(execution['step_contract'] == step.model_dump(mode='json'), 'Saved native step differs')
    for log_key, receipt_key in [('input_hash', 'input_sha256'), ('output_hash', 'output_sha256'),
                                  ('event_indices', 'event_indices'), ('trial_ids', 'trial_ids')]:
        require(execution[log_key] == receipt[receipt_key], 'Native execution log differs from receipt')
    return dict(max_abs_error=maximum, output_sha256=identity(out), shape=receipt['shape'],
                retained_event_indices=out.event_indices.tolist(), retained_trial_ids=out.trial_ids)


def audit(profiles, validation_script, output, input_path, record_id, bindings_path):
    profiles, validation_script, input_path, bindings_path = [Path(p).resolve(strict=True)
        for p in (profiles, validation_script, input_path, bindings_path)]
    output = Path(output).resolve()
    require(not output.exists(), 'Native audit output must be a new directory')
    source = PreprocessInput.model_validate_json(input_path.read_text(encoding='utf8'))
    data_root = Path(source.collection.root).resolve(strict=True)
    require(not output.is_relative_to(data_root) and not data_root.is_relative_to(output),
            'Native audit output must be disjoint from real source data')
    require(record_id in source.collection.selected_record_ids, 'Record is outside selected real input')
    records = [r for r in source.collection.records if r.id == record_id]
    require(len(records) == 1, 'Real record identity is missing or ambiguous')
    record = records[0]
    files = {str(p): file_hash(p) for p in (input_path, bindings_path)}
    helper = validation_script.with_name('validate_native_profiles.py')
    require(file_hash(Path(native.__file__)) == file_hash(helper), 'Loaded native helper differs from frozen validator')
    tracked = {Path(p): sha for p, sha in files.items()}
    tracked.update({helper: file_hash(helper), profiles / 'results.json': file_hash(profiles / 'results.json')})
    matrix = audit_matrix(profiles, validation_script, output / 'matrix')
    bindings = json.loads(bindings_path.read_text(encoding='utf8'))
    indexed = json.loads((profiles / 'results.json').read_text(encoding='utf8'))['results']
    indexed = {r['identity']: r for r in indexed}
    paths = {json.loads(p.read_text(encoding='utf8'))['identity']: p for p in profiles.glob('*/receipt.json')}
    native_rows = [r for r in inventory() if r['op'] in native.OPERATIONS]
    results, asset_sets = [], []
    for row in native_rows:
        receipt = indexed.get(row['identity'])
        item = dict(identity=row['identity'], real_data_passed=False,
                    status=receipt['status'] if receipt else 'not_executed')
        if not receipt or receipt['status'] != 'passed':
            item['failure'] = receipt.get('error') if receipt else 'No current receipt'
            results.append(item)
            continue
        require(receipt.get('real_verified') is True and receipt.get('real_record_id') == record_id,
                'Passed native receipt lacks the declared real record')
        directory = paths[row['identity']].parent
        tracked[paths[row['identity']]] = file_hash(paths[row['identity']])
        declared = {(profiles / f['path']).resolve(strict=True): f['sha256'] for f in receipt['files']}
        present = {p.resolve() for p in directory.rglob('*') if p.is_file() and p.name != 'receipt.json'}
        require(set(declared) == present, 'Native file manifest does not cover exactly its case')
        tracked.update(declared)
        snapshot = json.loads((directory / 'native-inputs.json').read_text(encoding='utf8'))
        require(snapshot['files'] == files and snapshot['record_id'] == record_id,
                'Native source input or bindings differ from declared fixture')
        step = Step.model_validate(snapshot['recipe'])
        params = validate_parameters(row['unit_id'], row['op'],
            {**bindings[row['op']], **row['profile_parameters']}, profile=row['profile'])
        require(step.unit_id == row['unit_id'] and step.op == row['op'] and step.profile == row['profile']
                and step.params == params and step.adaptation_scope == 'record_unlabeled',
                'Native recipe differs from declared profile and asset bindings')
        assets = freeze_native([step])
        require(assets == snapshot['native_files'], 'Native assets differ from saved execution dependencies')
        require(all(not output.is_relative_to(Path(p).parent) for p in assets), 'Audit output overlaps native assets')
        asset_sets.append(assets)
        validate_record_files(data_root, record)
        raw, events, mapping = read_record(data_root, record, source.survey.event_id, source.survey.context_event_id)
        packet = Packet(raw, events, np.arange(len(events)), [m['trial_id'] for m in mapping], record.reference)
        require(identity(packet) == snapshot['input_sha256'], 'Native input differs from original real-record arrays')
        item.update(saved_outputs(directory, packet, step, row, receipt), real_data_passed=True,
                    record_id=record_id, receipt_sha256=file_hash(paths[row['identity']]))
        results.append(item)
    validate_record_files(data_root, record)
    for assets in asset_sets:
        verify_native(assets)
    require(engine_hash() == matrix['engine_sha256'] and environment() == matrix['environment'],
            'Native audit engine or runtime changed')
    for path, expected in tracked.items():
        require(file_hash(path) == expected, 'Native evidence changed during audit')
    passed = sum(r['real_data_passed'] for r in results)
    report = dict(status='passed' if passed == len(native_rows) else 'partial',
        native_profiles=len(native_rows), real_data_verified=passed, record_id=record_id,
        full_inventory_profiles=matrix['counts']['profiles'], profiles=results,
        engine_sha256=matrix['engine_sha256'], environment=matrix['environment'],
        read_files_unchanged=True, read_file_count=len(tracked), native_dependencies_unchanged=True,
        source_data_unchanged=True, service_registry_updated=False,
        scope='One declared real record. Decoded saved source/graph equivalence and event lineage only; '
              'no independent algorithm validity, fixed-panel utility or broader real-data coverage.')
    write_json(output / 'native-audit.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('profiles', 'validation-script', 'output', 'input', 'bindings'):
        parser.add_argument('--' + option, type=Path, required=True)
    parser.add_argument('--record', required=True)
    args = parser.parse_args()
    result = audit(args.profiles, args.validation_script, args.output, args.input, args.record, args.bindings)
    print(json.dumps({k: result[k] for k in ('status', 'native_profiles', 'real_data_verified', 'record_id')}))
