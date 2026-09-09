"""Scientific decision boundaries and upstream covariance endpoint regression."""
import numpy as np
import pytest

from app.preprocessing.units import validate_params
from app.preprocessing.units.source.automatic_cleaning import (
    _calibration_kernel, _complete_block_covariance,
)
from .test_automatic_cleaning import call, signal, unchanged_grid


def test_coherent_amplitude_is_reported_without_automatic_interpolation():
    raw = signal()
    raw._data[0] *= 30
    result = call('detect_bad_channels', raw, adaptation_scope='record_unlabeled')
    info = result['artifacts']
    assert 'Fp1' not in info['candidates']
    assert info['diagnostic_flags']['Fp1'] == ['amplitude_deviation']
    assert info['channel_diagnostics']['Fp1']['classes'] == ['suspected_correlated_artifact']
    assert info['channel_diagnostics']['Fp1']['recommended_action'] == 'asr_and_quality_review'
    assert info['selection_policy'] == 'consensus_v2'
    assert info['algorithm_version'] == 'brainagent-channel-consensus-2'
    assert info['labels_used'] is False
    np.testing.assert_array_equal(result['data'].get_data(), raw.get_data())
    unchanged_grid(raw, result['data'])


def test_independent_high_amplitude_has_joint_evidence():
    raw = signal()
    raw._data[0] = np.random.default_rng(5).normal(0, 200e-6, raw.n_times)
    info = call('detect_bad_channels', raw, adaptation_scope='record_unlabeled')['artifacts']
    assert 'Fp1' in info['candidates']
    assert 'joint_amplitude_low_correlation' in info['reasons']['Fp1']
    assert 'persistent_low_correlation' in info['reasons']['Fp1']


def test_persistent_low_correlation_requires_duration_and_fraction():
    raw = signal()
    independent = np.random.default_rng(7).normal(0, raw._data[0].std(), raw.n_times)
    persistent = raw.copy()
    persistent._data[0] = independent
    info = call('detect_bad_channels', persistent, adaptation_scope='record_unlabeled')['artifacts']
    assert info['reasons']['Fp1'] == ['persistent_low_correlation']
    intermittent = raw.copy()
    for start in range(5, 60, 10):
        segment = slice(start * 160, (start + 2) * 160)
        intermittent._data[0, segment] = independent[segment]
    info = call('detect_bad_channels', intermittent, adaptation_scope='record_unlabeled')['artifacts']
    assert 'Fp1' not in info['candidates']
    assert info['channel_diagnostics']['Fp1']['classes'] == ['intermittent_low_correlation']
    assert info['channel_diagnostics']['Fp1']['longest_low_correlation_seconds'] == 2


def test_flatness_detects_unaligned_complete_interval():
    raw = signal()
    start, count = 513, 800
    raw._data[0, start:start + count] = 3e-6
    info = call('detect_bad_channels', raw, adaptation_scope='record_unlabeled')['artifacts']
    assert 'flat' in info['reasons']['Fp1']
    assert info['channel_diagnostics']['Fp1']['first_flat_sample_interval'] == [start, start + count]
    assert 'Fp1' not in info['correlation_donors']


def test_consensus_parameter_relations_and_no_legacy_execution():
    for params in ({'selection_policy': 'legacy_union_v1'},
                   {'shared_correlation_threshold': .3},
                   {'bad_window_fraction': .8, 'persistent_low_corr_fraction': .5}):
        with pytest.raises(ValueError):
            validate_params('EEG-AUTO-BAD-CHANNEL', 'detect_bad_channels',
                            {'adaptation_scope': 'record_unlabeled', **params})


@pytest.mark.parametrize('samples', [99, 100, 101, 102, 103, 199, 200, 201, 202, 203])
def test_complete_covariance_matches_sample_outer_products(samples):
    data = np.random.default_rng(12).normal(size=(4, samples))
    actual = _complete_block_covariance(data, window=100).reshape(-1, 4, 4)
    expected = []
    for start in range(0, samples, 100):
        block = data[:, start:start + 100]
        block = np.pad(block, ((0, 0), (0, 100 - block.shape[1])), mode='edge')
        expected.append(block @ block.T)
    np.testing.assert_allclose(actual, expected, rtol=1e-14, atol=1e-13)


def test_upstream_endpoint_failure_and_local_dependency_binding():
    pytest.importorskip('asrpy')
    from asrpy import asr as source
    original = source.block_covariance
    data = np.random.default_rng(1).normal(size=(4, 14002))
    with pytest.raises(ValueError, match='reshape'):
        original(data, window=100)
    assert _complete_block_covariance(data, 100).shape == (141, 16)
    # Other upstream lengths retain its exact arithmetic; no upstream global mutation.
    np.testing.assert_array_equal(original(data[:, :14000], 100),
                                  _complete_block_covariance(data[:, :14000], 100))
    kernel = _calibration_kernel(source)
    assert kernel.__globals__['block_covariance'] is _complete_block_covariance
    assert source.block_covariance is original
    assert source.asr_calibrate.__globals__['block_covariance'] is original
