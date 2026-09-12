import numpy as np
import pytest

from app.search.neural_spectra import irasa_components


def evaluate(x, band=(0.,100.)):
    return irasa_components(x[None,None], sfreq=200., nominal_band_hz=list(band), channels=['C3'], window_ids=['w'])


def test_known_tone_on_noise_is_separated_without_clipping_or_peak_fit():
    rng = np.random.default_rng(14)
    t = np.arange(12000)/200
    x = rng.normal(0, 3e-6, len(t)) + 15e-6*np.sin(2*np.pi*10*t)
    r = evaluate(x)
    assert r['status'] == 'evaluated'
    freq = np.array(r['frequencies_hz'])
    mixed, background, residual = [np.array(r[k]) for k in ['mixed_psd','aperiodic_psd','periodic_difference_psd']]
    np.testing.assert_allclose(mixed, background + residual, atol=1e-12)
    peak = np.argmax(residual)
    assert freq[peak] == 10
    assert background[peak] < mixed[peak] * .1
    assert (residual < 0).any()
    assert r['parameters']['fitting'].startswith('none')


def test_white_noise_background_and_amplitude_scaling_are_numerically_consistent():
    x = np.random.default_rng(5).normal(0, 1e-5, 16000)
    first, scaled = evaluate(x), evaluate(3*x)
    ratio = np.mean(first['aperiodic_psd']) / np.mean(first['mixed_psd'])
    assert .8 < ratio < 1.2
    np.testing.assert_allclose(scaled['aperiodic_psd'], np.array(first['aperiodic_psd'])*9, rtol=1e-12)


def test_narrow_band_short_windows_and_unknown_band_do_not_recover_missing_information():
    x = np.random.default_rng(3).normal(size=2400)*1e-5
    assert evaluate(x,(8.,30.))['reason'] == 'insufficient_supported_frequency_bins_after_resampling'
    assert evaluate(x[:400])['reason'] == 'insufficient_contiguous_resampled_welch_support'
    assert evaluate(x,(None,100.))['reason'] == 'declared_nominal_passband_required'
    x[4] = np.nan
    assert evaluate(x)['reason'] == 'nonfinite_input_windows'


def test_explicit_budget_check_interrupts_resampling():
    def check(): raise ValueError('time budget')
    with pytest.raises(ValueError, match='time budget'):
        irasa_components(np.random.default_rng(1).normal(size=(1,1,2400)),sfreq=200.,nominal_band_hz=[0.,100.],channels=['C3'],window_ids=['w'],check=check)


def test_constant_channels_and_nonreal_data_are_not_spectral_evidence():
    assert evaluate(np.ones(3200)*1e-5)['reason'] == 'constant_or_empty_window_channel'
    with pytest.raises(ValueError, match='real floating'):
        evaluate(np.ones(3200, dtype=complex))
