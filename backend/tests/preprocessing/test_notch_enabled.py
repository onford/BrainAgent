"""Existing FIR notch execution and bounded integration contracts."""
from types import SimpleNamespace

import mne
import numpy as np
import pytest

from app.preprocessing.planner import compile_steps
from app.preprocessing.schemas import Step
from app.preprocessing.units import invoke, validate_params
from .test_automatic_cleaning import signal, unchanged_grid


def notch(raw, freqs, picks):
    params = validate_params('EEG-FILTER', 'notch', {'freqs': freqs, 'picks': picks})
    return invoke('EEG-FILTER', 'notch', raw, **params)['data']


@pytest.mark.parametrize('frequency', [50., 60.])
def test_notch_attenuates_line_and_preserves_neural_tone_grid_events(frequency):
    raw = signal(seconds=35, channels=8)
    time = np.arange(raw.n_times) / raw.info['sfreq']
    neural = 10e-6 * np.sin(2 * np.pi * 10 * time)
    line = 100e-6 * np.sin(2 * np.pi * frequency * time)
    raw._data[:8] = neural + line
    before = raw.get_data().copy()
    out = notch(raw, [frequency], raw.ch_names[:8])
    unchanged_grid(raw, out)
    np.testing.assert_array_equal(raw.get_data(), before)
    np.testing.assert_array_equal(out.get_data()[8:], before[8:])
    interior = slice(5 * 160, 30 * 160)
    def amplitude(values, hz):
        return 2 * abs(np.mean(values[interior] * np.exp(-2j * np.pi * hz * time[interior])))
    assert amplitude(out.get_data()[0], frequency) < .01 * amplitude(before[0], frequency)
    assert amplitude(out.get_data()[0], 10) == pytest.approx(10e-6, rel=.002)
    expected = raw.copy().notch_filter([frequency], picks=raw.ch_names[:8], method='fir',
        phase='zero', fir_design='firwin', notch_widths=None, trans_bandwidth=1., verbose='ERROR')
    np.testing.assert_array_equal(out.get_data(), expected.get_data())


def test_notch_requires_explicit_nonempty_distinct_supported_parameters():
    for params in ({'freqs': [], 'picks': ['C3']}, {'freqs': [55], 'picks': ['C3']},
                   {'freqs': [50, 50], 'picks': ['C3']}, {'freqs': [60, 50], 'picks': ['C3']},
                   {'freqs': [50], 'picks': []}, {'freqs': [50], 'picks': ['C3', 'C3']},
                   {'freqs': [50]}):
        with pytest.raises(ValueError):
            validate_params('EEG-FILTER', 'notch', params)


def test_notch_kernel_rejects_epochs_nyquist_and_acquisition_joins():
    raw = signal(seconds=15, channels=8)
    epochs = mne.EpochsArray(raw.get_data()[None], raw.info, verbose='ERROR')
    with pytest.raises(TypeError):
        notch(epochs, [50], raw.ch_names[:8])
    with pytest.raises(ValueError):
        notch(raw.copy().resample(100), [50], raw.ch_names[:8])
    raw.annotations.append(8, 0, 'EDGE boundary')
    with pytest.raises(ValueError, match='断点'):
        notch(raw, [50], raw.ch_names[:8])


def test_notch_planner_checks_transition_margin_and_continuous_stage(dataset):
    record = dataset.collection.records[0]
    def compile(recipe):
        return compile_steps(SimpleNamespace(recipe=recipe, evidence=[1], output=recipe[-1].id),
                             record, dataset, {})
    def step(input='raw', freqs=None):
        return Step(id='notch', unit_id='EEG-FILTER', op='notch', input=input,
                    params={'freqs': freqs or [50], 'picks': '$eeg_channels'}, evidence_indices=[0])
    assert compile([step()])[0].op == 'notch'
    resample = Step(id='rate', unit_id='EEG-RESAMPLE', op='resample',
                    params={'sfreq': 101}, evidence_indices=[0])
    with pytest.raises(ValueError, match='Nyquist'):
        compile([resample, step('rate')])
    epoch = Step(id='epoch', unit_id='EEG-EPOCH', op='epoch', params={
        'events': '$events', 'event_id': '$event_id', 'tmin': 0, 'tmax': .5,
        'picks': '$all_channels'}, evidence_indices=[0])
    with pytest.raises(ValueError, match='continuous'):
        compile([epoch, step('epoch')])
