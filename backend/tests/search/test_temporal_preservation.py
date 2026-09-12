import numpy as np
import pytest

from app.search.temporal_preservation import measure_pair


def measure(x, y, sfreq=200):
    return measure_pair(x[None, None], y[None, None], sfreq=sfreq, channels=['C3'], trial_ids=['t'])


def test_known_delay_is_reported_without_realigning_preservation_error():
    t = np.arange(400) / 200
    x = np.exp(-((t-.8)/.05)**2) * 1e-5
    y = np.zeros_like(x); y[8:] = x[:-8]
    result = measure(x, y)
    assert result['summary']['lag_ms']['value'] == 40
    assert result['summary']['energy_centroid_shift_ms']['value'] == pytest.approx(40)
    assert result['summary']['normalized_change']['value'] > .5
    assert result['parameters']['time_alignment'] == 'none'


def test_periodic_delay_ambiguity_and_search_boundary_are_not_point_estimates():
    t = np.arange(400) / 200
    x = np.sin(2*np.pi*10*t)
    periodic = measure(x, x)
    assert periodic['summary']['lag_ms']['value'] is None
    assert periodic['measurements'][0]['metrics']['lag_ms']['reason'] == 'ambiguous_equal_maxima'
    pulse = np.exp(-((t-.8)/.05)**2)
    delayed = np.zeros_like(pulse); delayed[20:] = pulse[:-20]
    boundary = measure(pulse, delayed)
    assert boundary['measurements'][0]['metrics']['lag_ms']['reason'] == 'maximum_at_search_boundary'


def test_zero_scaling_and_nonfinite_cannot_claim_preservation():
    x = np.random.default_rng(4).normal(size=400) * 1e-5
    zero = measure(x, np.zeros_like(x))
    assert zero['summary']['normalized_change']['value'] == 1
    assert zero['summary']['lag_ms']['value'] is None
    scaled = measure(x, .1*x)
    assert scaled['summary']['gain']['value'] == pytest.approx(.1)
    assert scaled['summary']['normalized_change']['value'] == pytest.approx(.9)
    assert scaled['summary']['zero_lag_correlation']['value'] == pytest.approx(1)
    assert measure(x, x)['summary']['lag_ms']['value'] == 0
    x[3] = np.nan
    with pytest.raises(ValueError, match='finite'): measure(x, x)


def test_missing_channel_stays_in_denominator():
    x = np.stack([np.arange(400), np.zeros(400)])[None]
    result = measure_pair(x, x, sfreq=200, channels=['C3','C4'], trial_ids=['t'])
    assert result['summary']['normalized_change']['value'] is None
    assert result['summary']['normalized_change']['expected'] == 2
    assert result['summary']['normalized_change']['available'] == 1
