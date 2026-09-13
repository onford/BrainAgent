"""Missing probe observations must never improve a reported aggregate."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def auditor():
    path = Path(__file__).resolve().parents[2] / 'scripts/audit_core_reconstruction_receipts.py'
    spec = importlib.util.spec_from_file_location('core_reconstruction_receipt_audit', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_value_keeps_full_denominator(auditor):
    rows = [{'error': {'value': .25}}, {'error': {'value': None}}]
    auditor.aggregate(rows, {'error': {'value': None, 'status': 'incomplete', 'n_total': 2, 'n_valid': 1}})
    with pytest.raises(ValueError):
        auditor.aggregate(rows, {'error': {'value': .25, 'status': 'ok', 'n_total': 1, 'n_valid': 1}})


def test_condition_mean_uses_equal_assigned_subjects(auditor):
    # Subject means remain equally weighted even when their trial counts differ.
    rows = [{'error': {'value': .1, 'n_total': 100}}, {'error': {'value': .9, 'n_total': 10}}]
    auditor.aggregate(rows, {'error': {'value': .5, 'status': 'ok', 'n_total': 2, 'n_valid': 2}})
    with pytest.raises(ValueError):
        auditor.aggregate(rows, {'error': {'value': 19 / 110, 'status': 'ok', 'n_total': 2, 'n_valid': 2}})


def test_duplicate_window_cannot_replace_missing_window(auditor):
    receipt = {'reference_kind': 'real_eeg_cleanproxy', 'status': 'evaluated', 'windows': [
        {'subject_id': 'S001', 'window_id': 'trial1'}, {'subject_id': 'S001', 'window_id': 'trial1'}]}
    with pytest.raises(ValueError, match='Frozen probe windows'):
        auditor.receipt_check(receipt, 'S001', ['trial1', 'trial2'])
