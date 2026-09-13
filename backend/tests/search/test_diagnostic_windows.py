from copy import deepcopy

import numpy as np
import pytest

from app.preprocessing.storage import digest, file_hash
from app.search.diagnostic_windows import save_window, verified_windows
from app.search.neural_diagnostics import run_diagnostic
from app.search.io import read, write
from tests.search.test_diagnostic_registry import diagnostic  # noqa: F401
from tests.search.test_neural_priors import bundle  # noqa: F401


def setup_window(diagnostic):
    root, state, request, path, ref = diagnostic
    x = np.random.default_rng(15).normal(0, 1e-5, (1, 2, 4000))
    x += np.sin(np.arange(4000)[None, None] * 2*np.pi*10/200) * 1e-5
    w = save_window(x, output=path.parent, record_id='r', stage='source_raw', sfreq=200.,
        channels=['C3', 'C4'], history={'nominal_band_hz': [0., 100.]})
    w['measurement_frame_sha256'] = 'f'*64
    q = read(path)
    q['coverage'] = dict(records_expected=1, records_visited=1)
    q['bysubject'] = {'group': {'records': [dict(record_id='r', diagnostic_windows={'source_raw': w},
        measurement_frames={'source_raw': dict(status='verified', sha256='f'*64)})]}}
    write(path, q); ref['sha256'] = file_hash(path)
    request.update(kind='spectral_components', stage='source_raw')
    return root, state, request, path, ref, w


def test_fixed_window_registered_measurement_and_immutable_snapshot(diagnostic):
    root, state, request, path, ref, w = setup_window(diagnostic)
    assert w['contract']['stop_sample_exclusive'] == 3200
    assert w['contract']['stage_samples'] == 4000
    result = run_diagnostic(root, state, request)
    assert result['status'] == 'evaluated'
    assert len(result['input_artifacts']) == 2
    assert result['spectral_components']['signed_periodic_fraction']['available_records'] == 1
    # Label changes cannot alter the descriptive input selection or measurement.
    state['panel']['labels'] = ['held-out']
    assert run_diagnostic(root, state, request) == result


@pytest.mark.parametrize('change', ['tamper_array', 'geometry', 'frame', 'stage', 'duplicate', 'missing', 'unvisited', 'narrow'])
def test_changed_or_missing_support_cannot_be_complete_spectral_evidence(diagnostic, change):
    root, state, request, path, ref, w = setup_window(diagnostic)
    q = read(path)
    row = q['bysubject']['group']['records'][0]
    w = row['diagnostic_windows']['source_raw']
    if change == 'tamper_array':
        p = path.parent / w['contract']['artifact']['path']
        p.write_bytes(p.read_bytes() + b'changed')
    if change == 'geometry': w['contract']['stop_sample_exclusive'] -= 1
    if change == 'frame': w['measurement_frame_sha256'] = 'b'*64
    if change == 'stage': w['contract']['stage'] = 'processed_continuous'
    if change == 'duplicate': q['bysubject']['group']['records'].append(deepcopy(row))
    if change == 'missing': row.pop('diagnostic_windows')
    if change == 'unvisited': q['coverage']['records_expected'] = 2
    if change == 'narrow': w['contract']['history']['nominal_band_hz'] = [8., 30.]
    w['sha256'] = digest(w['contract'])
    write(path, q); ref['sha256'] = file_hash(path)
    if change in ('missing', 'unvisited', 'narrow'):
        r = run_diagnostic(root, state, request)
        assert r['spectral_components']['signed_periodic_fraction']['value'] is None
    else:
        with pytest.raises(ValueError): run_diagnostic(root, state, request)


def test_window_limit_applies_before_allocating_snapshot(tmp_path):
    # Broadcast view avoids allocating the deliberately oversized input.
    x = np.broadcast_to(np.array([1.]), (1, 512, 16000))
    w = save_window(x, output=tmp_path, record_id='r', stage='source_raw', sfreq=1000.,
        channels=[str(i) for i in range(512)], history={})
    assert w['reason'] == 'fixed_window_exceeds_4MiB_payload_limit'
    assert not list(tmp_path.iterdir())
