from copy import deepcopy

import numpy as np
import pytest

from app.search.source_simulation import simulate_sources, evaluate_known_sources, save_probe
from app.search.reconstruction import generate_contamination


@pytest.fixture(scope='module')
def probe():
    return simulate_sources()


def test_forward_projection_and_source_power_changes_match_known_design(probe):
    probe.verify()
    assert np.max(np.abs(probe.sensor_V.mean(axis=1))) < 1e-18
    assert np.linalg.matrix_rank(probe.leadfield_V_per_Am) == 3
    sfreq = probe.manifest['sfreq']
    baseline = probe.sources_Am[..., int(.5 * sfreq):int(1.5 * sfreq)]
    task = probe.sources_Am[..., int(3 * sfreq):int(5 * sfreq)]
    observed = 100 * ((task**2).mean(-1) / (baseline**2).mean(-1) - 1)
    np.testing.assert_allclose(observed, probe.manifest['expected_source_power_change_percent'], atol=1e-10)
    assert probe.sensor_V.shape == (4, 12, 960)


def test_simulation_repeats_without_modifying_global_rng(probe):
    before = np.random.get_state()
    other = simulate_sources()
    assert probe.manifest == other.manifest
    assert np.array_equal(probe.sensor_V, other.sensor_V)
    after = np.random.get_state()
    assert before[0] == after[0] and np.array_equal(before[1], after[1]) and before[2:] == after[2:]


def test_truth_cannot_be_relabelled_or_modified(probe):
    changed = deepcopy(probe)
    changed.sensor_V[0, 0, 0] += 1e-6
    with pytest.raises(ValueError, match='array hash'): changed.verify()
    changed = deepcopy(probe)
    changed.manifest['source_frequencies_hz'][0] = 12
    with pytest.raises(ValueError, match='manifest hash'): changed.verify()


def test_known_truth_separates_oracle_identity_zero_scaling_and_time_shift(probe):
    x = probe.sensor_V
    y, a, _ = generate_contamination(x, 160, kind='line', seed=14, rms_ratio=.5, window_keys=probe.manifest['cases'])
    def measure(q, z, identity):
        return evaluate_known_sources(probe, a, q, z, processor={'id': identity, 'provenance': 'analytic numerical control'})['summary']
    oracle = measure(x, x, 'oracle')
    identity = measure(x, y, 'identity')
    zero = measure(np.zeros_like(x), np.zeros_like(x), 'zero')
    scaled = measure(.1 * x, .1 * y, 'scale')
    shifted = measure(np.roll(x, 4, axis=-1), np.roll(y, 4, axis=-1), 'circular_shift_negative_control')
    assert oracle['reconstruction_nrmse']['value'] == 0
    assert identity['artifact_residual_rms_ratio']['value'] == pytest.approx(1)
    assert zero['clean_retention_nrmse']['value'] == pytest.approx(1)
    assert scaled['clean_retention_gain']['value'] == pytest.approx(.1)
    assert scaled['clean_retention_nrmse']['value'] == pytest.approx(.9)
    assert shifted['clean_retention_nrmse']['value'] > .5
    with pytest.raises(ValueError, match='all cases'):
        evaluate_known_sources(probe, a, x[:1], x, processor={'id': 'bad', 'provenance': 'wrong coverage'})


def test_saved_truth_manifest_is_independent_and_cannot_overwrite(probe, tmp_path):
    artifacts = save_probe(probe, tmp_path / 'probe')
    assert len(artifacts) == 3
    with pytest.raises(FileExistsError): save_probe(probe, tmp_path / 'probe')


def test_recorded_template_requires_frozen_source_and_uses_fixed_unlabelled_windows(tmp_path):
    from scipy.io import savemat
    from app.preprocessing.storage import file_hash
    from app.search.recorded_templates import bnci_eog_template
    values = np.zeros((8500, 25))
    values[:, 22] = np.arange(8500) * .1
    records = np.empty(3, dtype=object)
    for i in range(3): records[i] = {'X': values, 'fs': 250., 'trial': np.array([])}
    source = tmp_path / 'A01T.mat'
    savemat(source, {'data': records})
    target = tmp_path / 'template.npy'
    evidence = {'source_url': 'fixture:template', 'unit_and_channel_evidence': 'Test fixture only'}
    with pytest.raises(ValueError, match='hash'):
        bnci_eog_template(source, target, expected_source_sha256='0' * 64, source_evidence=evidence)
    manifest = bnci_eog_template(source, target, expected_source_sha256=file_hash(source), source_evidence=evidence)
    assert manifest['labels_used'] is False and manifest['sample_selection']['starts_zero_based'] == [2500, 4000, 5500, 7000]
    result = np.load(target, allow_pickle=False)
    assert result.shape == (4, 12, 1500)
    assert result[0, 0, 0] == pytest.approx(values[2500, 22] * 1e-6 * manifest['spatial_coupling'][0])
    assert np.max(np.abs(result.mean(axis=1))) < 1e-18
    with pytest.raises(FileExistsError):
        bnci_eog_template(source, target, expected_source_sha256=file_hash(source), source_evidence=evidence)


def test_template_grid_units_and_channels_cannot_be_guessed(probe, tmp_path):
    from app.search.source_validation import load_template
    from app.search.io import write
    from app.preprocessing.storage import file_hash
    path = tmp_path / 'template.npy'
    np.save(path, probe.sensor_V, allow_pickle=False)
    meta = dict(sha256=file_hash(path), sfreq=160., unit='V', channels=probe.manifest['channels'],
        source_url='fixture', source_file_sha256='a' * 64, sample_selection={'start': 0})
    write(path.with_suffix('.json'), meta)
    assert load_template(path, probe)[0].shape == probe.sensor_V.shape
    for key, wrong in [('sfreq', 250), ('unit', 'uV'), ('channels', list(reversed(meta['channels']))), ('sha256', '0' * 64)]:
        write(path.with_suffix('.json'), {**meta, key: wrong})
        with pytest.raises(ValueError): load_template(path, probe)
