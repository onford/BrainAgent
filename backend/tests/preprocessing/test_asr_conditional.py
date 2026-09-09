"""Explicit insufficient-calibration identity must never imply ASR application."""
import numpy as np
import pytest

from app.preprocessing.runner import data_hash
from app.preprocessing.units import validate_params
from app.preprocessing.units.source.automatic_cleaning import CleaningError
from .test_automatic_cleaning import call, signal, unchanged_grid


def test_conditional_short_record_preserves_input_with_unattempted_selection():
    raw = signal(seconds=15, channels=8)
    before = data_hash(raw)
    result = call('asr_clean', raw, adaptation_scope='record_unlabeled',
                  on_insufficient_calibration='identity')
    info = result['artifacts']
    assert data_hash(raw) == data_hash(result['data']) == before
    unchanged_grid(raw, result['data'])
    assert info['status'] == 'not_applicable' and info['asr_applied'] is False
    assert info['not_applicable_code'] == 'ASR_CALIBRATION_TOO_SHORT'
    assert info['actual_calibration_seconds'] is None
    assert info['available_record_seconds'] == 15
    assert info['minimum_calibration_seconds'] == 30
    assert info['calibration_selection_performed'] is False
    assert info['calibration_sample_mask'] is None
    assert info['model_created'] is False and info['data_action'] == 'identity'
    assert 'mixing_matrix' not in info and 'threshold_matrix' not in info


def test_selected_shortage_is_identity_only_when_declared(monkeypatch):
    from asrpy import asr as source
    raw = signal(channels=8)
    mask = np.zeros((1, raw.n_times), dtype=bool)
    mask[:, :1600] = True
    def select_short(data, **kwargs):
        return data[:, :1600], mask
    monkeypatch.setattr(source, 'clean_windows', select_short)
    assert validate_params('EEG-ASR-AUTO', 'asr_clean',
                           {'adaptation_scope': 'record_unlabeled'})['on_insufficient_calibration'] == 'error'
    with pytest.raises(CleaningError) as exc:
        call('asr_clean', raw, adaptation_scope='record_unlabeled')
    assert exc.value.code == 'ASR_CALIBRATION_TOO_SHORT'
    assert exc.value.details['clean_seconds'] == 10
    result = call('asr_clean', raw, adaptation_scope='record_unlabeled',
                  on_insufficient_calibration='identity')
    info = result['artifacts']
    assert info['status'] == 'not_applicable' and info['asr_applied'] is False
    assert info['actual_calibration_seconds'] == info['clean_seconds'] == 10
    assert info['minimum_calibration_seconds'] == 30 and info['calibration_selection_performed']
    np.testing.assert_array_equal(info['calibration_sample_mask'], mask)
    np.testing.assert_array_equal(result['data'].get_data(), raw.get_data())


def test_identity_never_hides_numerical_or_rank_failure(monkeypatch):
    from asrpy import asr as source
    raw = signal(channels=8)
    def broken(*args, **kwargs):
        raise ValueError('calibration kernel failed')
    monkeypatch.setattr(source, 'clean_windows', broken)
    with pytest.raises(CleaningError) as exc:
        call('asr_clean', raw, adaptation_scope='record_unlabeled',
             on_insufficient_calibration='identity')
    assert exc.value.code == 'CLEANING_NUMERICAL_FAILURE'
    raw.set_eeg_reference('average', verbose='ERROR')
    with pytest.raises(CleaningError, match='ASR_FULL_RANK_REQUIRED'):
        call('asr_clean', raw, adaptation_scope='record_unlabeled',
             on_insufficient_calibration='identity')


def test_successful_asr_has_same_arrays_under_both_policies():
    raw = signal(channels=8)
    strict = call('asr_clean', raw, adaptation_scope='record_unlabeled')
    conditional = call('asr_clean', raw, adaptation_scope='record_unlabeled',
                       on_insufficient_calibration='identity')
    np.testing.assert_array_equal(strict['data'].get_data(), conditional['data'].get_data())
    info = conditional['artifacts']
    assert info['asr_applied'] is True and info['status'] == 'applied'
    assert info['not_applicable_code'] is None and info['not_applicable_reason'] is None
    assert info['actual_calibration_seconds'] >= info['minimum_calibration_seconds']
    assert info['calibration_selection_performed'] is True and info['model_created'] is True
