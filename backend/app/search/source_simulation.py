"""Known-source numerical probes, separate from real-EEG cleanproxy evidence."""
from dataclasses import dataclass
import hashlib
import math

import numpy as np

from app.preprocessing.storage import digest, file_hash
from pathlib import Path

VERSION = 'known-source-sphere-1'
CHANNELS = ('Fp1', 'Fp2', 'F3', 'F4', 'C3', 'Cz', 'C4', 'P3', 'Pz', 'P4', 'O1', 'O2')
LIMITATIONS = [
    'Known simulated sources and a fixed spherical conductor are numerical ground truth only for this simulation.',
    'Fixed standard electrode geometry is not an individual anatomy or a source estimate from observed EEG.',
    'Oscillation frequencies, amplitudes and task changes are declared test cases, not mandatory human EEG patterns.',
    'Injected artifact waveforms, even recorded EOG templates, are not pure physiological artifact ground truth.',
    'Numerical success does not establish preservation on real EEG, independent generalization or clinical utility.',
]


def array_hash(values):
    data = np.ascontiguousarray(values, dtype='<f8')
    h = hashlib.sha256(digest({'shape': list(data.shape), 'dtype': '<f8'}).encode('ascii'))
    h.update(data.tobytes())
    return h.hexdigest()


@dataclass
class KnownSourceProbe:
    sensor_V: np.ndarray
    sources_Am: np.ndarray
    leadfield_V_per_Am: np.ndarray
    manifest: dict

    def verify(self):
        m = self.manifest
        if digest({k: v for k, v in m.items() if k != 'sha256'}) != m.get('sha256'):
            raise ValueError('known-source manifest hash differs')
        for key, value in [('sensor_V', self.sensor_V), ('sources_Am', self.sources_Am),
                           ('leadfield_V_per_Am', self.leadfield_V_per_Am)]:
            if not np.isfinite(value).all() or array_hash(value) != m['array_hashes'][key]:
                raise ValueError('known-source array hash differs: ' + key)
        projected = np.einsum('cs,wst->wct', self.leadfield_V_per_Am, self.sources_Am)
        if not np.array_equal(projected, self.sensor_V):
            raise ValueError('sensor truth does not match the declared source projection')


def simulate_sources(*, sfreq=160., seed=42):
    """Four fixed scenarios, three dipoles, six seconds; no observed EEG or fit."""
    import mne
    if type(sfreq) not in (int, float) or not math.isfinite(sfreq) or not 80 <= sfreq <= 512 or sfreq != int(sfreq):
        raise ValueError('simulation requires an integer sampling rate between 80 and 512 Hz')
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError('simulation seed must be a nonnegative uint32')
    info = mne.create_info(list(CHANNELS), sfreq, 'eeg')
    info.set_montage('standard_1020')
    center = [0., 0., .04]
    positions = np.array([[-.03, 0., .085], [.03, 0., .085], [0., -.035, .06]])
    orientations = np.tile([0., 0., 1.], (3, 1))
    radii, conductivities = [.9, .92, .97, 1.], [.33, 1., .004, .33]
    sphere = mne.make_sphere_model(r0=center, head_radius=.09, relative_radii=radii,
                                   sigmas=conductivities, verbose=False)
    dipoles = mne.Dipole(np.arange(3) / sfreq, positions, np.ones(3) * 1e-9,
                        orientations, np.ones(3) * 100, verbose=False)
    forward, _ = mne.make_forward_dipole(dipoles, sphere, info, n_jobs=1, verbose=False)
    gain = np.asarray(forward['sol']['data'], dtype=float)
    if gain.shape != (len(CHANNELS), 3) or forward['sol']['row_names'] != list(CHANNELS):
        raise ValueError('unexpected forward source/channel ordering')
    if not np.allclose(forward['source_rr'], positions, rtol=0, atol=1e-8) or not np.allclose(forward['source_nn'], orientations, rtol=0, atol=1e-8):
        raise ValueError('forward dipole geometry or orientation differs from the declared sources')
    gain = gain - gain.mean(axis=0, keepdims=True)
    times = np.arange(int(6 * sfreq)) / sfreq
    frequencies = np.array([10., 10., 20.])
    phases = np.random.default_rng(seed).uniform(-np.pi, np.pi, size=3)
    oscillations = 10e-9 * np.sin(2 * np.pi * frequencies[:, None] * times + phases[:, None])
    # Numerical negative and positive changes, without left/right class labels.
    task_gains = np.array([[.5, 1., 1.], [1., .5, 1.], [1.5, 1.5, 1.], [1., 1., 1.]])
    sources = np.tile(oscillations, (4, 1, 1))
    sources[:, :, times >= 2.] *= task_gains[:, :, None]
    sensor = np.einsum('cs,wst->wct', gain, sources)
    manifest = dict(schema_version=VERSION, generator_source_sha256=file_hash(Path(__file__)), reference_kind='known_simulated_neural_signal', seed=seed,
        sfreq=float(sfreq), duration_seconds=6., channels=list(CHANNELS), reference='common_average',
        cases=['source_1_attenuated', 'source_2_attenuated', 'both_enhanced', 'unchanged'],
        source_positions_head_m=positions.tolist(), source_orientations=orientations.tolist(),
        source_frequencies_hz=frequencies.tolist(), source_phases_rad=phases.tolist(), amplitude_Am=10e-9,
        task_onset_seconds=2., baseline_window_seconds=[.5, 1.5], task_window_seconds=[3., 5.],
        task_amplitude_gain=task_gains.tolist(), expected_source_power_change_percent=(100 * (task_gains**2 - 1)).tolist(),
        conductor=dict(center_head_m=center, head_radius_m=.09, relative_radii=radii, conductivities_S_per_m=conductivities),
        electrode_positions_head_m=[ch['loc'][:3].tolist() for ch in info['chs']],
        software=dict(mne=mne.__version__, numpy=np.__version__),
        array_hashes={name: array_hash(value) for name, value in [('sensor_V', sensor), ('sources_Am', sources), ('leadfield_V_per_Am', gain)]},
        sources=['https://mne.tools/1.10/generated/mne.make_sphere_model.html',
                 'https://mne.tools/1.10/generated/mne.make_forward_dipole.html'],
        limitations=LIMITATIONS)
    manifest['sha256'] = digest(manifest)
    result = KnownSourceProbe(sensor, sources, gain, manifest)
    result.verify()
    return result


def evaluate_known_sources(probe, artifact_V, processed_clean_V, processed_contaminated_V, *, processor):
    """All declared cases count; no subject grouping, inverse fit or selection score."""
    from .reconstruction import _window_metrics, _aggregate
    probe.verify()
    x = probe.sensor_V
    arrays = [np.asarray(v, dtype=float) for v in (artifact_V, processed_clean_V, processed_contaminated_V)]
    if any(v.shape != x.shape or not np.isfinite(v).all() for v in arrays):
        raise ValueError('known-source evaluation requires all cases on the original finite physical grid')
    if not isinstance(processor, dict) or not processor.get('id') or not processor.get('provenance'):
        raise ValueError('processor identity and execution provenance are required')
    a, q, z = arrays
    rows = []
    for i, case in enumerate(probe.manifest['cases']):
        metrics, flags = _window_metrics(x[i], x[i] + a[i], z[i], a[i], q[i])
        metrics['paired_error_reference_ratio'] = metrics.pop('paired_error_cleanproxy_ratio')
        rows.append(dict(case=case, metrics=metrics, flags=flags))
    return dict(schema_version='known-source-evaluation-1', reference_kind='known_simulated_neural_signal',
        status='evaluated', probe_sha256=probe.manifest['sha256'], processor=processor,
        input_hashes={name: array_hash(value) for name, value in zip(
            ['artifact_V', 'processed_clean_V', 'processed_contaminated_V'], arrays)},
        cases=rows, summary=_aggregate([row['metrics'] for row in rows]),
        aggregation='equal_mean_of_all_declared_synthetic_cases; cases are not independent human subjects',
        limitations=LIMITATIONS, selection_role='validation_only')


def save_probe(probe, directory):
    from pathlib import Path
    from .io import write
    from app.preprocessing.storage import file_hash
    probe.verify()
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=False)
    artifacts = []
    for name, value in [('sensor_V', probe.sensor_V), ('sources_Am', probe.sources_Am),
                         ('leadfield_V_per_Am', probe.leadfield_V_per_Am)]:
        path = root / (name + '.npy')
        np.save(path, value, allow_pickle=False)
        artifacts.append(dict(path=path.name, sha256=file_hash(path), bytes=path.stat().st_size))
    write(root / 'manifest.json', dict(probe=probe.manifest, artifacts=artifacts))
    return artifacts
