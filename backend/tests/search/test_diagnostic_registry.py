from copy import deepcopy
from types import SimpleNamespace
import time

import pytest

from app.preprocessing.storage import digest, file_hash
from app.search.diagnostic_registry import (catalog, validate_request, DiagnosticInputBudget,
    DiagnosticDefinition, register)
from app.search.io import write, read
from app.search.neural_diagnostics import run_diagnostic
from app.search.service import SearchService
from tests.search.test_neural_priors import bundle  # noqa: F401




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
    request = dict(kind='spectral_distribution', candidate_id='c', stage='source_raw', question='Locate saved PSD maximum', reason='Read-only measurement')
    return tmp_path, state, request, path, ref




@pytest.mark.parametrize('change', ['missing_registry', 'tampered_registry', 'unknown_kind'])
def test_unfrozen_or_unsupported_contract_cannot_execute(diagnostic, change):
    root, state, request, path, ref = diagnostic
    if change == 'missing_registry': state['protocol'].pop('diagnostic_registry')
    if change == 'tampered_registry': state['protocol']['diagnostic_registry']['label_permission'] = 'all'
    if change == 'unknown_kind': request['kind'] = 'execute_code'
    with pytest.raises(ValueError): run_diagnostic(root, state, request)




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
    result = run_diagnostic(root, state, request, DiagnosticInputBudget(path.stat().st_size))
    detail = result['observations']['line_ratio_50hz']['missing_detail']
    assert detail['records_from_frozen_missing_index'] == 1
    assert detail['record_reason_counts'] == {'unknown_acquisition_history': 1}
    assert detail['examples'][0]['reference']['json_pointer'] == '/stages/source_raw/metrics/3'








def test_registration_rejects_duplicate_and_noncallable_code():
    with pytest.raises(ValueError): register(DiagnosticDefinition('signal_profile', '9', 'x', 'x', (), lambda *args: {}))
    with pytest.raises(ValueError): register(DiagnosticDefinition('untrusted', '1', 'x', 'x', (), 'print(labels)'))


def common_fixture(diagnostic):
    import numpy as np
    from app.search.physical_contrast import contrast_epochs
    root, state, request, path, ref = diagnostic
    source = np.random.default_rng(8).normal(size=(2, 2, 401)) * 1e-5
    arrays, contrast = contrast_epochs(source, source * .9, sfreq=200, channels=['C3', 'C4'],
        source_trial_ids=['a', 'b'], processed_trial_ids=['a', 'b'], source_history={'nominal_band_hz': [1, 45]},
        processed_history={'nominal_band_hz': [1, 45]}, time_window=[0, 2])
    artifacts = []
    for name, array in arrays.items():
        target = path.parent / (name + '.npy')
        np.save(target, array, allow_pickle=False)
        artifacts.append(dict(view=name, path=target.name, sha256=file_hash(target), unit='V', shape=list(array.shape), record_id='r'))
    contrast['artifacts'] = artifacts
    q = read(path)
    q['bysubject'] = {'group': {'records': [{'record_id': 'r', 'coverage': {'eligible_trials': 2}, 'physical_contrast': contrast}]}}
    q['coverage'] = {'records_expected': 1, 'records_visited': 1}
    write(path, q); ref['sha256'] = file_hash(path)
    request.update(kind='common_view_change', stage='processed_task')
    return root, state, request, path, ref


def test_registered_common_view_diagnostic_reads_verified_arrays_and_preserves_error(diagnostic):
    root, state, request, path, ref = common_fixture(diagnostic)
    result = run_diagnostic(root, state, request)
    assert result['common_view_change']['summary']['normalized_change']['value'] == pytest.approx(.1)
    assert len(result['input_artifacts']) == 3
    assert result['common_view_change']['neural_preservation'] == 'not_established'
    path.parent.joinpath('source.npy').write_bytes(b'changed')
    with pytest.raises(ValueError, match='哈希'): run_diagnostic(root, state, request)


def test_unvisited_record_inventory_cannot_be_reported_as_complete(diagnostic):
    root, state, request, path, ref = common_fixture(diagnostic)
    q = read(path)
    q['coverage']['records_expected'] = 2
    write(path, q); ref['sha256'] = file_hash(path)
    result = run_diagnostic(root, state, request)
    assert result['common_view_change']['summary']['normalized_change']['expected_records'] == 2
    assert result['common_view_change']['summary']['normalized_change']['value'] is None


@pytest.mark.parametrize('change', ['missing_contract', 'hash', 'time_window', 'geometry', 'unit', 'duplicate'])
def test_common_view_rejects_unverified_geometry_and_arrays(diagnostic, change):
    root, state, request, path, ref = common_fixture(diagnostic)
    q = read(path)
    contrast = q['bysubject']['group']['records'][0]['physical_contrast']
    if change == 'missing_contract': contrast.pop('contract')
    if change == 'hash': contrast['contract_sha256'] = '0' * 64
    if change == 'time_window': contrast['contract']['time_window'] = [0, 3]
    if change == 'geometry': contrast['contract']['geometry'] = 'warped'
    if change == 'unit': contrast['artifacts'][0]['unit'] = 'dimensionless'
    if change == 'duplicate': contrast['artifacts'].append(contrast['artifacts'][0])
    if change in {'time_window', 'geometry'}: contrast['contract_sha256'] = digest(contrast['contract'])
    write(path, q); ref['sha256'] = file_hash(path)
    if change == 'missing_contract':
        result = run_diagnostic(root, state, request)
        assert result['common_view_change']['summary']['normalized_change']['value'] is None
    else:
        with pytest.raises(ValueError): run_diagnostic(root, state, request)
