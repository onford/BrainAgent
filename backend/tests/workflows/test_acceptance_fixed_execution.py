import importlib.util
from pathlib import Path

import pytest

from app.preprocessing.storage import digest
from app.search.catalog import BASELINE_ID


@pytest.fixture
def audit():
    path = Path(__file__).resolve().parents[2] / 'scripts/release_workflow_acceptance.py'
    spec = importlib.util.spec_from_file_location('fixed_acceptance_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.fixed_execution_audit


@pytest.fixture
def state():
    registry = [{'id': BASELINE_ID}, {'id': 'source-filter'}]
    return {'protocol': {'version': '4', 'registry_hash': digest(registry)},
            'status': 'completed', 'registry': registry, 'schedule': ['source-filter'],
            'recommendation': {'candidate_ids': ['source-filter'], 'registry_hash': digest(registry)},
            'actions': [{'action': 'initial_recommendation', 'status': 'completed',
                         'result': {'candidate_ids': ['source-filter']}}],
            'candidates': [{'id': BASELINE_ID}, {'id': 'source-filter'}]}


def test_accepts_initial_retry_then_fixed_execution(audit, state):
    state['actions'].insert(0, {'action': 'initial_recommendation', 'status': 'failed'})
    assert audit(state, state['recommendation'])['passed']


@pytest.mark.parametrize('damage', ['feedback', 'extra_candidate', 'reorder', 'registry', 'file', 'incomplete', 'legacy', 'second_recommendation'])
def test_completed_workflow_does_not_hide_contract_failures(audit, state, damage):
    saved = dict(state['recommendation'])
    if damage == 'feedback': state['actions'].append({'action': 'edit_candidate', 'status': 'failed'})
    elif damage == 'extra_candidate': state['candidates'].append({'id': 'after-feedback'})
    elif damage == 'reorder': state['candidates'].reverse()
    elif damage == 'registry': state['registry'][1]['id'] = 'changed'
    elif damage == 'file': saved['reason'] = 'changed'
    elif damage == 'incomplete': state['status'] = 'stopped'
    elif damage == 'legacy': state['protocol']['version'] = '3'
    else: state['actions'].append(state['actions'][0])
    assert not audit(state, saved)['passed']
