"""Read-only audit of an active or completed fixed EEGMMIDB delivery.

Checks the saved first model request, execution timestamps and identical shared
plans across the target records. An active-run pass is not final acceptance.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def audit(search, output):
    search = search.resolve(strict=True)
    output = output.resolve()
    require(not output.exists() and not output.is_relative_to(search.parent.parent), 'Use a new external receipt path')
    checked = {}

    def read(path, stable=True):
        raw = path.read_bytes()
        if stable:
            checked[str(path)] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    state = read(search / 'search.json', False)
    protocol = read(search / 'protocol.json')
    recommendation = read(search / 'initial-recommendation.json')
    registry = read(search / 'registry.json')
    require(protocol == state['protocol'], 'Persisted protocol differs')
    require(protocol['version'] == '4' and protocol['preprocessing_scope'] == 'shared_recipe_all_records',
            'Expected fixed, shared preprocessing protocol')
    require(registry == state['registry'] and digest(registry) == recommendation['registry_hash'] == protocol['registry_hash'],
            'Frozen registry binding differs')
    require(recommendation == state['recommendation'] and state['schedule'] == recommendation['candidate_ids'],
            'Saved first recommendation differs')
    expected = [protocol['baseline_id'], *recommendation['candidate_ids']]
    require(len(expected) == len(set(expected)) and len(expected) <= state['budget']['max_candidates'],
            'Duplicate or over-budget recommendation')
    executed = [row['id'] for row in state['candidates']]
    require(executed == expected[:len(executed)], 'Execution departed from the frozen order')
    require(len(state['actions']) == 1 and state['actions'][0]['action'] == 'initial_recommendation'
            and state['actions'][0]['status'] == 'completed', 'Unexpected later controller action')
    calls = read(search / 'llm-calls.json')['calls']
    require(len(calls) == 1 and calls[0]['operation'] == 'initial_recommendation'
            and calls[0]['status'] == 'completed', 'Unexpected recommendation model call')
    requests = list((search / 'decisions').glob('*/request.json'))
    require(len(requests) == 1, 'Unexpected decision request count')
    context = json.loads(read(requests[0])['messages'][1]['content'])
    require(not {'results', 'diagnostics', 'feedback', 'actions', 'history'} & context.keys(), 'Measured feedback entered initial request')
    require({m['id']: m['recipe_hash'] for m in context['methods']} == {m['id']: m['recipe_hash'] for m in registry},
            'Initial model request did not receive the complete frozen catalog')
    recommended_at = datetime.fromisoformat(recommendation['recommended_at']).timestamp()
    require(calls[0]['completed_at'] <= recommended_at, 'Recommendation preceded its model response')
    with sqlite3.connect((search / 'engine/preprocessing.db').as_uri() + '?mode=ro', uri=True) as db:
        created = dict(db.execute('SELECT id,created FROM jobs'))
    require(bool(created) and all(value > recommended_at for value in created.values()),
            'Numerical job exists before recommendation freeze')
    panel = read(search / 'panel.json')
    target_records = {trial['record_id'] for trial in panel['trials'] if trial['eligible']}
    require(len(target_records) == 327 and sum(bool(trial['eligible']) for trial in panel['trials']) == 4918,
            'Unexpected core data scope')
    plan_rows = []
    for candidate in state['candidates']:
        plan_path = search / 'candidates' / candidate['id'] / 'plan.json'
        if not plan_path.exists():
            require(candidate['status'] in {'reserved', 'running'}, 'Completed candidate has no plan')
            continue
        plan = read(plan_path)
        records = plan['records']
        require(len(records) == len(target_records) and {row['record_id'] for row in records} == target_records,
                'Plan omitted or duplicated target records')
        # Per-record byte estimates describe output size, not a processing
        # policy; all scientific and execution configuration remains compared.
        shared = [{key: value for key, value in row.items()
                   if key not in {'record_id', 'estimated_disk_bytes', 'estimated_memory_bytes'}}
                  for row in records]
        require(all(row == shared[0] for row in shared), 'Record-specific preprocessing configuration found')
        for step in shared[0]['steps']:
            require(step['unit_id'] in {'EEG-FILTER', 'EEG-RESAMPLE', 'EEG-REREFERENCE', 'EEG-EPOCH'},
                    'A used operation needs a separate fitting-scope review')
            require(step.get('fit_scope') is None and step.get('model_from') is None
                    and step.get('decision_from') is None and not step.get('record_decisions')
                    and step.get('adaptation_scope', 'none') == 'none', 'Unexpected fit or individual adaptation')
        plan_rows.append({'candidate_id': candidate['id'], 'records': len(records),
                          'shared_configuration_sha256': digest(shared[0]), 'fitted_preprocessing_nodes': 0,
                          'excluded_comparison_fields': ['record_id', 'estimated_disk_bytes', 'estimated_memory_bytes']})
    end = read(search / 'search.json', False)
    require(all(end[key] == state[key] for key in ('protocol', 'registry', 'recommendation', 'schedule', 'actions')),
            'Frozen execution state changed during audit')
    require(all(sha(Path(path)) == checksum for path, checksum in checked.items()), 'Read evidence changed')
    report = {'status': 'passed', 'search_id': state['id'], 'search_status_observed': state['status'],
              'final_core_acceptance': False, 'expected_order': expected, 'executed_prefix': executed,
              'one_initial_call_before_all_numerical_jobs': True, 'complete_catalog_presented': True,
              'plans': plan_rows, 'evidence_sha256': checked,
              'limits': 'Checks this fixed four-operation family and saved execution prefix; classification training remains grouped across subjects. Final numeric completion and all other methods require separate verification.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--search', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.search, args.output)
    print(result['status'], len(result['plans']), 'shared plans audited')
