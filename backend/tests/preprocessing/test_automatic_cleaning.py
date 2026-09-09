"""Numerical and permission checks for new, explicitly engineered adapters."""
import hashlib
from pathlib import Path
from types import SimpleNamespace

import mne
import numpy as np
import pytest

from app.preprocessing.units import invoke, validate_params, catalog
from app.preprocessing.units.source.automatic_cleaning import CleaningError
from app.preprocessing.runner import data_hash, state
from app.preprocessing.planner import compile_steps
from app.preprocessing.schemas import Step


def signal(seconds=65, channels=16, seed=73):
    sf = 160
    rng = np.random.default_rng(seed)
    names = ['Fp1', 'Fp2', 'F3', 'F4', 'F7', 'F8', 'C3', 'C4',
             'T7', 'T8', 'P3', 'P4', 'P7', 'P8', 'O1', 'O2'][:channels]
    n = int(seconds * sf)
    t = np.arange(n) / sf
    common = 10e-6 * np.sin(2 * np.pi * 10 * t) + rng.normal(0, 5e-6, n)
    data = common[None] + rng.normal(0, 3e-6, (channels, n))
    data = np.vstack([data, rng.normal(0, 1e-6, n)])
    raw = mne.io.RawArray(data, mne.create_info(names + ['AUX'], sf, ['eeg'] * channels + ['misc']),
                          first_samp=37, verbose='ERROR')
    raw.set_montage('standard_1020')
    raw.set_annotations(mne.Annotations([3, 10, 30], [0, 0, 0], ['left', 'right', 'left']))
    raw.filter(1, None, method='iir', verbose='ERROR')
    return raw


def call(op, raw, **params):
    unit = 'EEG-ASR-AUTO' if op == 'asr_clean' else 'EEG-AUTO-BAD-CHANNEL'
    return invoke(unit, op, raw, **validate_params(unit, op, params))


def unchanged_grid(a, b):
    assert a.get_data().shape == b.get_data().shape
    assert a.ch_names == b.ch_names and a.first_samp == b.first_samp
    assert a.info['sfreq'] == b.info['sfreq']
    assert a.annotations == b.annotations
    assert np.array_equal(mne.events_from_annotations(a, verbose='ERROR')[0],
                          mne.events_from_annotations(b, verbose='ERROR')[0])


def test_detection_and_official_interpolation_preserve_all_events_and_aux():
    raw = signal()
    raw._data[0] = 0
    raw._data[1] = np.random.default_rng(5).normal(0, 200e-6, raw.n_times)
    original = data_hash(raw)
    result = call('detect_bad_channels', raw, adaptation_scope='record_unlabeled')
    assert set(result['artifacts']['candidates']) == {'Fp1', 'Fp2'}
    assert data_hash(result['data']) == original == data_hash(raw)
    assert result['artifacts']['labels_used'] is False
    marked = invoke('EEG-BAD-CHANNEL-MARK', 'mark_channels', raw,
                    bads=result['artifacts']['candidates'], max_fraction=.2)['data']
    marked.info['bads'].append('AUX')
    repaired = call('interpolate_bad_channels', marked, max_fraction=.2)['data']
    expected = marked.copy()
    expected.info['bads'] = ['Fp1', 'Fp2']
    expected.interpolate_bads(reset_bads=False, method={'eeg': 'spline'}, verbose='ERROR')
    np.testing.assert_allclose(repaired.get_data(), expected.get_data(), rtol=1e-10, atol=1e-16)
    assert repaired.info['bads'] == ['AUX']
    assert np.array_equal(repaired.get_data()[2:], raw.get_data()[2:])
    unchanged_grid(raw, repaired)
    assert data_hash(raw) == original


def test_caps_geometry_and_explicit_permissions():
    raw = signal()
    with pytest.raises(ValueError):
        call('detect_bad_channels', raw)
    with pytest.raises(ValueError):
        call('asr_clean', raw, adaptation_scope='train')
    raw.info['bads'] = ['Fp1', 'Fp2']
    with pytest.raises(CleaningError, match='BAD_FRACTION_EXCEEDED'):
        call('interpolate_bad_channels', raw)
    raw.info['bads'] = ['Fp1']
    raw.info['chs'][0]['loc'][:3] = np.nan
    with pytest.raises(CleaningError, match='MISSING_GEOMETRY'):
        call('interpolate_bad_channels', raw)


def test_asr_actual_burst_correction_and_no_trial_deletion():
    pytest.importorskip('asrpy')
    raw = signal(channels=8)
    clean = raw.get_data().copy()
    burst = slice(45 * 160, 47 * 160)
    raw._data[0, burst] += np.random.default_rng(9).normal(0, 2e-3, 320)
    before = data_hash(raw)
    result = call('asr_clean', raw, adaptation_scope='record_unlabeled')
    out, info = result['data'], result['artifacts']
    unchanged_grid(raw, out)
    assert data_hash(raw) == before
    assert np.array_equal(raw.get_data()[-1], out.get_data()[-1])
    assert np.std(out.get_data()[0, burst] - clean[0, burst]) < .5 * np.std(raw.get_data()[0, burst] - clean[0, burst])
    # Quiet interior is substantially preserved in physical V (not normalized).
    assert np.sqrt(np.mean((out.get_data()[:8, 1600:4800] - clean[:8, 1600:4800]) ** 2)) < 3e-6
    assert info['clean_seconds'] >= 30 and info['labels_used'] is False
    assert info['calibration_sample_mask'].size == raw.n_times
    assert info['mixing_matrix'].shape == (8, 8)
    assert info['source_version'] == '0.0.8'


def test_asr_rank_short_calibration_and_sampling_guards():
    raw = signal(channels=8)
    car = raw.copy().set_eeg_reference('average', verbose='ERROR')
    with pytest.raises(CleaningError) as exc:
        call('asr_clean', car, adaptation_scope='record_unlabeled')
    assert exc.value.code == 'ASR_FULL_RANK_REQUIRED'
    assert exc.value.details['rank'] == 7
    # Excluding one bad channel can make a CAR subset full rank; CAR is still forbidden.
    car.info['bads'] = ['Fp1']
    with pytest.raises(CleaningError, match='ASR_FULL_RANK_REQUIRED'):
        call('asr_clean', car, adaptation_scope='record_unlabeled')
    with pytest.raises(CleaningError, match='ASR_CALIBRATION_TOO_SHORT'):
        call('asr_clean', raw.copy().crop(tmax=15), adaptation_scope='record_unlabeled')
    with pytest.raises(CleaningError, match='ASR_LOOKAHEAD_GRID'):
        call('asr_clean', raw, adaptation_scope='record_unlabeled', lookahead=.249)
    with pytest.raises(CleaningError, match='ASR_SFREQ_UNSUPPORTED'):
        call('asr_clean', raw.copy().resample(80), adaptation_scope='record_unlabeled')


def test_asr_excludes_marked_flat_channel():
    pytest.importorskip('asrpy')
    raw = signal(channels=8)
    raw._data[0] = 0
    raw.info['bads'] = ['Fp1']
    result = call('asr_clean', raw, adaptation_scope='record_unlabeled')
    assert result['artifacts']['input_rank'] == 7
    assert result['data'].info['bads'] == ['Fp1']
    assert np.array_equal(raw.get_data()[0], result['data'].get_data()[0])


def test_asr_matches_unmodified_official_fit_transform():
    asrpy = pytest.importorskip('asrpy')
    from threadpoolctl import threadpool_limits
    raw = signal(channels=8)
    with threadpool_limits(limits=1, user_api='blas'):
        estimator = asrpy.ASR(sfreq=160, cutoff=20)
        estimator.fit(raw)
        expected = estimator.transform(raw)
    actual = call('asr_clean', raw, adaptation_scope='record_unlabeled')['data']
    np.testing.assert_array_equal(expected.get_data(), actual.get_data())


def test_runner_new_cleaning_templates_keep_complete_trial_panel(service, dataset):
    pytest.importorskip('asrpy')
    import json
    from app.preprocessing.methods import automatic_cleaning_methods
    from app.preprocessing.worker import Worker
    from .test_execution import prepare
    from .conftest import OWNER
    from mne_bids import get_bids_path_from_fname, read_raw_bids, write_raw_bids
    from app.preprocessing.storage import file_hash
    # Use stationary full-rank calibration, not the EOG fixture's large drift.
    root = Path(dataset.collection.root)
    for record in dataset.collection.records:
        path = root / record.bids_path
        bids = get_bids_path_from_fname(path).update(root=root)
        raw = read_raw_bids(bids, extra_params={'preload': True}, verbose='ERROR')
        rng = np.random.default_rng(14)
        raw._data[:4] = (rng.normal(0, 6e-6, (1, raw.n_times))
                         + rng.normal(0, 3e-6, (4, raw.n_times)))
        write_raw_bids(raw, bids, format='BrainVision', allow_preload=True,
                       event_id={'left': 1, 'right': 2}, overwrite=True, verbose='ERROR')
        meta = json.loads(path.with_suffix('.json').read_text())
        meta['EEGReference'] = 'acquisition'
        path.with_suffix('.json').write_text(json.dumps(meta), encoding='utf-8')
    inventory = {p.relative_to(root).as_posix(): file_hash(p) for p in root.rglob('*') if p.is_file()}
    for record in dataset.collection.records:
        record.files = inventory.copy()
    methods = automatic_cleaning_methods()
    for method in methods:
        # Fixture has four independent physiological oscillations, not spatial EEG.
        method.recipe[1].params.update(correlation_threshold=0, deviation_z=10)
        method.recipe.append(Step(id='epochs', unit_id='EEG-EPOCH', op='epoch', input='car',
            params={'events': '$events', 'event_id': '$event_id', 'tmin': 0, 'tmax': .5,
                    'picks': '$all_channels'}, evidence_indices=[1]))
        method.output = 'epochs'
    job, _, _ = prepare(service, dataset, methods)
    result = Worker(service.store, service.allowed_roots).run_once()
    assert result.status == 'completed', result.model_dump()
    for row in result.records:
        report = row['result']['delta']
        assert report['events_retained'] == report['events_before'] == 8
        assert report['channels_removed'] == []
        assert report['after']['shape'] == [8, 5, 101]
        provenance = json.loads(service.store.artifact(OWNER, job.job_id, row['key'], 'provenance.json').read_text())
        assert any(s['op'] == 'detect_bad_channels' for s in provenance['steps'])
        assert row['result']['source_unchanged'] is True


def test_hash_never_svd_and_tracks_geometry_annotations(monkeypatch):
    raw = signal(channels=8)
    old = data_hash(raw)
    actual_rank = state(raw)['rank']
    assert actual_rank == 8
    def forbidden(*args, **kwargs):
        raise AssertionError('hash must not perform SVD')
    monkeypatch.setattr(np.linalg, 'matrix_rank', forbidden)
    monkeypatch.setattr(np.linalg, 'svd', forbidden)
    assert data_hash(raw) == old
    altered = raw.copy()
    altered.info['chs'][0]['loc'][0] += .001
    assert data_hash(altered) != old
    altered = raw.copy()
    altered.annotations.description[0] = 'other'
    assert data_hash(altered) != old


def test_new_catalog_hashes_constraints_and_planner(dataset):
    for spec in catalog():
        if spec.id not in {'EEG-ASR-AUTO', 'EEG-AUTO-BAD-CHANNEL'}:
            continue
        path = Path(__file__).parents[2] / 'app/preprocessing/units/source/automatic_cleaning.py'
        assert hashlib.sha256(path.read_bytes()).hexdigest() == spec.source['code_sha256']
        assert spec.implementation['constraints']['trial_rejection'] is False
    recipe = [Step(id='car', unit_id='EEG-REREFERENCE', op='reference',
                   params={'ref_channels': 'average'}, evidence_indices=[0]),
              Step(id='asr', unit_id='EEG-ASR-AUTO', op='asr_clean', input='car',
                   params={'adaptation_scope': 'record_unlabeled'}, evidence_indices=[0])]
    method = SimpleNamespace(recipe=recipe, evidence=[1], output='asr')
    with pytest.raises(CleaningError, match='ASR_FULL_RANK_REQUIRED'):
        compile_steps(method, dataset.collection.records[0], dataset, {})
