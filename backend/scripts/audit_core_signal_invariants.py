"""Analytic signal checks for the filter/reference/grid operators used by core delivery.

The oracle uses known tones and direct sample indexing, never a second call to
the filtering/resampling/epoch implementation. This is a bounded correctness
check, not a neural preservation or scientific effectiveness experiment.
"""
import argparse
import json
from pathlib import Path

import mne
import numpy as np

from app.build_info import execution_identity, runtime_snapshot
from app.preprocessing.storage import file_hash
from app.preprocessing.units.contracts_v2 import invoke_source


def audit():
    rows = []
    for sfreq in (128., 160.):
        times = np.arange(int(60 * sfreq)) / sfreq
        amplitude = 1e-5
        frequencies = (1., 15., 55.)
        values = np.array([amplitude * np.sin(2 * np.pi * f * times) for f in frequencies])
        names = ['C3', 'C4', 'Cz']
        raw = mne.io.RawArray(values, mne.create_info(names, sfreq, 'eeg'), verbose='ERROR')
        filtered = invoke_source('EEG-FILTER', 'filter', raw, l_freq=7., h_freq=30.,
                                 method='fir', phase='zero', picks=names)['data']
        central = slice(int(10 * sfreq), int(50 * sfreq))
        signal = filtered.get_data()[:, central]
        # An integer number of cycles excludes spectral leakage. The interior
        # excludes padding transients; this does not validate boundary behavior.
        gains, phases = [], []
        for row, frequency in zip(signal, frequencies, strict=True):
            angle = 2 * np.pi * frequency * times[central]
            sine = 2 * np.mean(row * np.sin(angle)) / amplitude
            cosine = 2 * np.mean(row * np.cos(angle)) / amplitude
            gains.append(float(np.hypot(sine, cosine)))
            phases.append(float(np.arctan2(cosine, sine)))
        assert gains[0] < .01 and gains[2] < .01, 'Out-of-band tone was not attenuated by 40 dB'
        assert abs(gains[1] - 1) < .01, 'Pass-band amplitude changed by more than 1 percent'
        assert abs(phases[1]) < .001, 'Pass-band zero-phase contract failed'
        np.testing.assert_array_equal(raw.get_data(), values)
        assert filtered.ch_names == names and filtered.n_times == raw.n_times
        # Fourth-order Butterworth band-pass after the bilinear transform.
        # Squared single-pass magnitude gives the forward/backward result.
        # This oracle does not call SciPy/MNE filter-design or response helpers.
        iir_checks = []
        for low, high in [(8., 30.), (1., 40.)]:
            iir = invoke_source('EEG-FILTER', 'filter', raw, l_freq=low, h_freq=high,
                                method='iir', phase='zero', picks=names)['data'].get_data()[:, central]
            lower, upper = np.tan(np.pi * np.array([low, high]) / sfreq)
            measured, expected = [], []
            for row, frequency in zip(iir, frequencies, strict=True):
                omega = np.tan(np.pi * frequency / sfreq)
                ratio = (omega ** 2 - lower * upper) / ((upper - lower) * omega)
                expected.append(float(1 / (1 + ratio ** 8)))
                angle = 2 * np.pi * frequency * times[central]
                measured.append(float(np.hypot(2 * np.mean(row * np.sin(angle)),
                                                2 * np.mean(row * np.cos(angle))) / amplitude))
            np.testing.assert_allclose(measured, expected, rtol=0, atol=2e-5)
            iir_checks.append({'band': [low, high], 'measured_gains': measured, 'analytic_gains': expected})
        referenced = invoke_source('EEG-REREFERENCE', 'reference', raw, ref_channels='average')['data']
        projection = np.eye(3) - np.ones((3, 3)) / 3
        np.testing.assert_allclose(referenced.get_data(), projection @ values, rtol=0, atol=1e-19)
        np.testing.assert_allclose(referenced.get_data().mean(axis=0), 0, rtol=0, atol=1e-19)
        np.testing.assert_array_equal(raw.get_data(), values)
        events = np.array([[int(20 * sfreq), 0, 1], [int(40 * sfreq), 0, 2]])
        # Test the grid operator directly on a known in-band signal, not on an
        # implementation-generated expected output.
        pure = mne.io.RawArray(values[1:2], mne.create_info(['C4'], sfreq, 'eeg'), verbose='ERROR')
        sampled = invoke_source('EEG-RESAMPLE', 'resample', pure, sfreq=160., events=events)
        resampled, synchronized = sampled['data'], sampled['artifacts']['events']
        expected_events = events.copy()
        expected_events[:, 0] = np.rint(events[:, 0] * 160. / sfreq).astype(int)
        np.testing.assert_array_equal(synchronized, expected_events)
        target_times = np.arange(resampled.n_times) / 160.
        expected_tone = amplitude * np.sin(2 * np.pi * 15. * target_times)
        relative_error = float(np.max(np.abs(resampled.get_data()[0, 1600:8000] - expected_tone[1600:8000])) / amplitude)
        assert relative_error < .01, 'Grid conversion failed analytic tone amplitude/time check'
        epoch = invoke_source('EEG-EPOCH', 'epoch', resampled, events=synchronized,
                              event_id={'left_hand': 1, 'right_hand': 2}, tmin=0., tmax=2., picks=['C4'])['data']
        assert epoch.get_data().shape == (2, 1, 321)
        for i, event in enumerate(expected_events):
            np.testing.assert_array_equal(epoch.get_data()[i], resampled.get_data()[:, event[0]:event[0] + 321])
        np.testing.assert_array_equal(epoch.events, expected_events)
        rows.append({'input_sfreq': sfreq, 'tone_frequencies': frequencies, 'fir_amplitude_gains': gains,
                     'iir_analytic_checks': iir_checks, 'average_reference_projection_verified': True,
                     'passband_phase_radians': phases[1], 'resample_relative_max_error': relative_error,
                     'epoch_samples': 321, 'events_and_input_unchanged': True})
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Use a new audit output; historical evidence is immutable')
    before = execution_identity(runtime_snapshot())
    result = {'status': 'failed', 'execution_build': before, 'scientific_effectiveness_validated': False,
              'scope': 'Registered 7–30 Hz FIR, 8–30/1–40 Hz IIR, average reference, 128/160→160 Hz synchronized resampling, and 0–2 s epoch; interior analytic signals only.'}
    try:
        result.update(status='passed', cases=audit())
    except Exception as exc:
        result.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    result['runtime_unchanged'] = execution_identity(runtime_snapshot()) == before
    if not result['runtime_unchanged']:
        result['status'] = 'failed'
    result['driver_sha256'] = file_hash(Path(__file__))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(result['status'], result.get('error', ''))
    raise SystemExit(0 if result['status'] == 'passed' else 1)
