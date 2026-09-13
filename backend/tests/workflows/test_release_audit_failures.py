import importlib.util
from pathlib import Path

import pytest

from app.preprocessing.storage import file_hash, write_json


@pytest.fixture
def unassessed():
    script = Path(__file__).resolve().parents[2] / 'scripts/audit_release_evidence.py'
    spec = importlib.util.spec_from_file_location('release_failure_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.unassessed_candidate


def test_failed_before_assessment_is_retained_and_read_only(tmp_path, unassessed):
    receipt = {'status': 'failed', 'error': 'Native runtime unavailable'}
    path = tmp_path / 'receipt.json'
    write_json(path, receipt)
    before = file_hash(path)
    row = unassessed({'id': 'failed-method', 'status': 'failed', 'receipt': receipt}, tmp_path)
    assert row['assessment_status'] == 'not_produced' and row['score'] is None
    assert row['error'] == receipt['error']
    assert row['available_stage_files']['receipt.json']['sha256'] == before == file_hash(path)
    assert set(p.name for p in tmp_path.iterdir()) == {'receipt.json'}
    assert unassessed({'id': 'queued', 'status': 'pending', 'receipt': None}, tmp_path / 'absent')['available_stage_files'] == {}


def test_missing_assessment_does_not_hide_evaluated_or_tampered_receipt(tmp_path, unassessed):
    candidate = {'id': 'bad', 'status': 'evaluated', 'receipt': None}
    with pytest.raises(ValueError, match='must have its assessment'):
        unassessed(candidate, tmp_path)
    candidate.update(status='failed', receipt={'status': 'evaluated'})
    with pytest.raises(ValueError, match='must have its assessment'):
        unassessed(candidate, tmp_path)
    candidate['receipt'] = {'status': 'failed', 'error': 'original'}
    write_json(tmp_path / 'receipt.json', {'status': 'failed', 'error': 'changed'})
    with pytest.raises(AssertionError, match='differs'):
        unassessed(candidate, tmp_path)
    candidate['receipt'] = None
    with pytest.raises(AssertionError, match='Unbound'):
        unassessed(candidate, tmp_path)
