from copy import deepcopy
from types import SimpleNamespace
import time

import pytest

from app.preprocessing.storage import digest, file_hash
from app.search.contracts import RequestDiagnostic, Decision, ActionRecord, Usage
from app.search.diagnostic_registry import (catalog, validate_request, DiagnosticInputBudget,
    branch_result, pending_response, validate_response, DiagnosticDefinition, register)
from app.search.io import write, read
from app.search.neural_diagnostics import run_diagnostic
from app.search.service import SearchService
from tests.search.test_neural_priors import bundle  # noqa: F401


def experiment():
    return dict(hypothesis='Saved PSD maximum lies above 9 Hz', competing_explanation='A lower-frequency maximum',
        metric='spectral_distribution.maximum_bin_hz', comparison='gt', threshold=9,
        threshold_rationale='Synthetic test prediction; not a physiological cutoff',
        branches={key: {'next_action': action, 'reason': 'Distinguish remaining explanations'}
            for key, action in [('condition_met', 'propose_candidate'),
                ('condition_not_met', 'request_evidence'), ('unavailable', 'request_diagnostic')]})


@pytest.fixture
def diagnostic(tmp_path, bundle):
    recipe = {'nodes': []}
    q = dict(candidate_id='c', input_hash='input', panel_hash='panel', candidate_recipe_hash=digest(recipe),
        stages={'source_raw': {'psd': {'status': 'ok', 'value': [1, 3, 1],
            'unit': 'uV^2/Hz', 'axes': {'frequencies_hz': [5, 10, 15]}}}})
    path = tmp_path / 'candidates/c/assessment/quality/data-quality.json'
    write(path, q)
    ref = {'path': 'quality/data-quality.json', 'sha256': file_hash(path)}
    state = {'id': 'test', 'candidates': [{'id': 'c', 'status': 'evaluated', 'receipt': {
        'assessment_path': 'assessment', 'assessment': {'quality': {'receipt_artifact': ref}}}}],
        'registry': [{'id': 'c', 'recipe': recipe}], 'panel': {'panel_hash': 'panel'},
        'protocol': {'input_hash': 'input', 'neural_priors': bundle,
            'diagnostic_registry': catalog(), 'diagnostic_registry_hash': digest(catalog())},
        'actions': [], 'diagnostics': [], 'usage': {}, 'deadline': time.time() + 600,
        'budget': {'max_diagnostics': 3, 'max_diagnostic_input_bytes': 128 * 1024**2}}
    request = RequestDiagnostic(action='request_diagnostic', kind='spectral_distribution',
        candidate_id='c', question='Locate the saved PSD maximum', reason='Test a frequency hypothesis',
        experiment=experiment()).model_dump(mode='json')
    return tmp_path, state, request, path, ref


def test_new_registered_kernel_and_branch_are_bound_to_frozen_inputs(diagnostic):
    root, state, request, path, ref = diagnostic
    result = run_diagnostic(root, state, request)
    assert result['spectral_distribution']['maximum_bin_hz'] == 10
    assert result['spectral_distribution']['integral_on_saved_grid'] == 20
    assert result['decision_effect']['outcome'] == 'condition_met'
    assert result['decision_effect']['selected_branch']['next_action'] == 'propose_candidate'
    assert result['spectral_reference']['sha256'] == file_hash(path)
    changed = deepcopy(request)
    changed['experiment']['threshold'] = 11
    other = run_diagnostic(root, state, changed)
    assert other['decision_effect']['outcome'] == 'condition_not_met'
    assert other['id'] == result['id']  # New wording/threshold does not create new evidence.
    state['panel']['labels'] = ['different', 'held_out_labels']
    assert run_diagnostic(root, state, request) == result


@pytest.mark.parametrize('change', ['missing_registry', 'tampered_registry', 'unknown_kind', 'missing_experiment', 'wrong_metric'])
def test_unfrozen_or_unsupported_contract_cannot_execute(diagnostic, change):
    root, state, request, path, ref = diagnostic
    if change == 'missing_registry': state['protocol'].pop('diagnostic_registry')
    if change == 'tampered_registry': state['protocol']['diagnostic_registry']['label_permission'] = 'all'
    if change == 'unknown_kind': request['kind'] = 'execute_code'
    if change == 'missing_experiment': request['experiment'] = None
    if change == 'wrong_metric': request['experiment']['metric'] = 'macro_ba'
    with pytest.raises(ValueError): run_diagnostic(root, state, request)


@pytest.mark.parametrize('status,value', [('partial', 10), ('ok', None), ('ok', float('nan')), ('ok', True)])
def test_unavailable_is_not_a_negative_prediction(status, value):
    result = branch_result({'status': 'evaluated', 'spectral_distribution': {
        'status': status, 'maximum_bin_hz': value}}, experiment())
    assert result['outcome'] == 'unavailable' and result['value'] is None


def test_input_budget_precedes_parsing_and_hash_binds_actual_bytes(diagnostic):
    root, state, request, path, ref = diagnostic
    with pytest.raises(ValueError, match='输入预算'): run_diagnostic(root, state, request, DiagnosticInputBudget(1))
    budget = DiagnosticInputBudget(100000, -1)
    with pytest.raises(ValueError, match='时间预算'): budget.read(path, ref['sha256'])
    path.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='哈希'): run_diagnostic(root, state, request)


def test_spectral_kernel_does_not_read_unrelated_large_detail(diagnostic):
    root, state, request, path, ref = diagnostic
    quality = read(path)
    quality['detail_artifacts'] = [{'record_id': 'r', 'path': 'unread-waveform.json', 'sha256': '0' * 64}]
    write(path, quality)
    ref['sha256'] = file_hash(path)
    result = run_diagnostic(root, state, request, DiagnosticInputBudget(path.stat().st_size))
    assert result['status'] == 'evaluated'


def test_missing_index_is_bounded_and_preserves_original_metric_locator(diagnostic):
    root, state, request, path, ref = diagnostic
    quality = read(path)
    artifact = {'record_id': 'r', 'path': 'unread-waveform.json', 'sha256': '0' * 64}
    quality['detail_artifacts'] = [artifact]
    quality['bysubject'] = {'group': {'records': [{'record_id': 'r', 'detail_artifact': artifact,
        'diagnostic_missing_index': {'source_raw': [{'metricID': 'line_ratio_50hz', 'status': 'not_applicable',
            'reason': 'unknown_acquisition_history', 'metric_index': 3}]}}]}}
    write(path, quality); ref['sha256'] = file_hash(path)
    request['kind'] = 'signal_profile'
    request['experiment']['metric'] = 'observations.line_ratio_50hz.value'
    result = run_diagnostic(root, state, request, DiagnosticInputBudget(path.stat().st_size))
    detail = result['observations']['line_ratio_50hz']['missing_detail']
    assert detail['records_from_frozen_missing_index'] == 1
    assert detail['record_reason_counts'] == {'unknown_acquisition_history': 1}
    assert detail['examples'][0]['reference']['json_pointer'] == '/stages/source_raw/metrics/3'
    assert result['decision_effect']['outcome'] == 'unavailable'


def test_next_decision_must_follow_actual_branch_or_explicitly_revise(diagnostic):
    root, state, request, *_ = diagnostic
    result = run_diagnostic(root, state, request)
    state['diagnostics'].append(result)
    response = {'diagnostic_response': {'diagnostic_id': result['id'], 'disposition': 'follow', 'reason': 'Observed the registered condition'},
                'decision': {'action': 'request_evidence'}}
    with pytest.raises(ValueError, match='下一步'): validate_response(state, {'decision': {'action': 'finish'}})
    with pytest.raises(ValueError, match='修订理由'): validate_response(state, response)
    response['diagnostic_response']['disposition'] = 'revise'
    validate_response(state, response)
    state['actions'].append({'action': 'model_decision', 'status': 'completed', 'result': response})
    assert pending_response(state) is None
    with pytest.raises(ValueError, match='伪造'): validate_response(state, response)


class DiagnosticService(SearchService):
    def __init__(self, root): self.root = root
    def folder(self, identity): return self.root
    def guard(self, state): pass
    def verify_runtime(self, state): pass
    def save(self, state):
        # Check that ledger costs survive their actual schema round trip.
        for action in state['actions']: ActionRecord.model_validate(action)
        Usage.model_validate(state['usage'])
        write(self.root / 'ledger.json', state)


@pytest.mark.asyncio
async def test_budget_is_durable_and_failed_duplicate_is_not_new_evidence(diagnostic):
    root, state, request, *_ = diagnostic
    service = DiagnosticService(root)
    result = await service.diagnostic_action(state, request)
    assert result['cost']['input_bytes_observed'] > 0
    assert read(root / 'ledger.json')['usage']['diagnostic_input_bytes_reserved'] == 64 * 1024**2
    assert file_hash(root / result['artifact']['path']) == result['artifact']['sha256']
    with pytest.raises(ValueError, match='已经计算'): await service.diagnostic_action(state, request)
    assert len(state['diagnostics']) == 1
    assert read(root / 'ledger.json')['usage']['diagnostic_input_bytes_reserved'] == 128 * 1024**2
    with pytest.raises(ValueError, match='累计输入预算'): await service.diagnostic_action(state, request)
    assert state['usage']['diagnostics'] == 2


def test_registration_rejects_duplicate_and_noncallable_code():
    with pytest.raises(ValueError): register(DiagnosticDefinition('signal_profile', '9', 'x', 'x', (), lambda *args: {}))
    with pytest.raises(ValueError): register(DiagnosticDefinition('untrusted', '1', 'x', 'x', (), 'print(labels)'))


@pytest.mark.asyncio
async def test_model_decision_gate_records_rejection_then_explicit_revision(diagnostic, monkeypatch):
    root, state, request, *_ = diagnostic
    service = DiagnosticService(root)
    service.llm = object()
    service.workflows = SimpleNamespace(folder=lambda identity: root)
    state.update(workflow_id='workflow', usage=Usage().model_dump())
    result = await service.diagnostic_action(state, request)
    answer = {'decision': {'action': 'finish', 'reason': 'No remaining useful measurement', 'unresolved': []}}
    async def decide(*args, **kwargs): return Decision.model_validate(answer).model_dump(mode='json')
    monkeypatch.setattr('app.search.service.decide', decide)
    with pytest.raises(ValueError, match='下一步'): await service.model_action(state, [])
    assert state['actions'][-1]['status'] == 'failed'
    assert pending_response(state)['id'] == result['id']
    answer['diagnostic_response'] = {'diagnostic_id': result['id'], 'disposition': 'revise', 'reason': 'No remaining measurement budget'}
    accepted = await service.model_action(state, [])
    assert accepted['diagnostic_response']['disposition'] == 'revise'
    assert pending_response(state) is None
