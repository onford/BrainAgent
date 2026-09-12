import json
from pathlib import Path

import pytest

from app.workflows import bids_validation as validator


def dataset(tmp_path):
    root = tmp_path / 'bids'
    root.mkdir()
    (root / 'dataset_description.json').write_text('{"BIDSVersion":"1.7.0"}', encoding='utf-8')
    return root


def result(*issues, count=1):
    return {'summary': {'schemaVersion': '1.2.7', 'totalFiles': count},
            'issues': {'issues': list(issues), 'codeMessages': {}}}


def fake_runtime(monkeypatch, tmp_path, payload, *, code=0, during=None):
    binary = tmp_path / 'binary'
    bundle = tmp_path / 'bundle'
    binary.write_bytes(b'fixture binary'); bundle.write_bytes(b'fixture bundle')
    monkeypatch.setattr(validator, '_runtime', lambda: (binary, bundle))
    calls = []
    class Tree:
        def __init__(self, command, **kwargs):
            calls.append((command, kwargs))
            self.command = command
        def __enter__(self): return self
        def __exit__(self, *exc): calls.append('closed')
        def memory_bytes(self): return 10
        def wait(self, timeout):
            if during: during()
            Path(self.command[-1]).write_text(json.dumps(payload), encoding='utf-8')
            return code
    monkeypatch.setattr(validator, 'ProcessTree', Tree)
    return calls


def test_complete_warnings_retained_offline_and_original_version_separate(tmp_path, monkeypatch):
    root = dataset(tmp_path)
    issue = {'code': 'JSON_KEY_RECOMMENDED', 'subCode': 'HEDVersion', 'severity': 'warning', 'location': '/dataset_description.json'}
    calls = fake_runtime(monkeypatch, tmp_path, result(issue))
    monkeypatch.setenv('BIDS_SCHEMA', 'https://invalid.example/schema')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fixture-secret')
    value = validator.validate_bids(root, tmp_path / 'validation')
    assert value.status == 'passed_with_warnings' and value.errors == 0 and value.warnings == 1
    assert value.declared_bids_version == '1.7.0' and value.bids_version == '1.11.1'
    command, kwargs = calls[0]
    assert command[command.index('--max-rows') + 1] == '-1'
    assert '--allow-net' not in command and '--schema' not in command
    assert 'BIDS_SCHEMA' not in kwargs['env'] and 'DEEPSEEK_API_KEY' not in kwargs['env']
    assert calls[-1] == 'closed'
    receipt = tmp_path / value.receipt_path
    assert validator.file_hash(receipt) == value.receipt_sha256
    assert json.loads((receipt.parent / 'result.json').read_text())['issues']['issues'] == [issue]
    assert value.input_unchanged


@pytest.mark.parametrize('payload,code,status', [
    (result({'code': 'JSON_KEY_REQUIRED', 'severity': 'error'}), 16, 'failed'),
    (result({'code': 'JSON_KEY_REQUIRED', 'severity': 'error'}), 1, 'invalid_result'),
    (result({'code': 'JSON_KEY_REQUIRED', 'severity': 'error'}), 0, 'invalid_result'),
    (result(count=0), 0, 'invalid_result'),
    (result({'code': 'X', 'severity': 'ignore'}), 0, 'invalid_result'),
    (result({'code': 'NEW_WARNING', 'severity': 'warning'}), 0, 'review_required'),
    ({'summary': {'schemaVersion': 'future', 'totalFiles': 1}, 'issues': {'issues': []}}, 0, 'invalid_result'),
])
def test_no_success_for_errors_contradictions_missing_files_or_suppression(tmp_path, monkeypatch, payload, code, status):
    root = dataset(tmp_path)
    fake_runtime(monkeypatch, tmp_path, payload, code=code)
    value = validator.validate_bids(root, tmp_path / 'validation')
    assert value.status == status
    assert (tmp_path / value.receipt_path).exists()


def test_input_mutation_invalidates_even_zero_error_result(tmp_path, monkeypatch):
    root = dataset(tmp_path)
    fake_runtime(monkeypatch, tmp_path, result(), during=lambda: (root / 'README').write_text('changed'))
    value = validator.validate_bids(root, tmp_path / 'validation')
    assert value.status == 'input_changed' and not value.input_unchanged


def test_unavailable_and_cancelled_and_timeout_have_durable_receipts(tmp_path, monkeypatch):
    root = dataset(tmp_path)
    def absent(): raise ImportError('inspection extra missing')
    monkeypatch.setattr(validator, '_runtime', absent)
    value = validator.validate_bids(root, tmp_path / 'validation')
    assert value.status == 'unavailable'
    calls = fake_runtime(monkeypatch, tmp_path, result())
    value = validator.validate_bids(root, tmp_path / 'validation', cancelled=lambda: True)
    assert value.status == 'cancelled' and not calls
    value = validator.validate_bids(root, tmp_path / 'validation', timeout_s=0)
    assert value.status == 'timed_out' and calls[-1] == 'closed'


def test_ignore_file_rejected_without_launch(tmp_path, monkeypatch):
    root = dataset(tmp_path)
    (root / '.bidsignore').write_text('*.tsv')
    calls = fake_runtime(monkeypatch, tmp_path, result())
    value = validator.validate_bids(root, tmp_path / 'validation')
    assert value.status == 'unavailable' and not calls


def test_collection_does_not_register_on_official_failure(tmp_path, source, monkeypatch):
    from app.workflows import dataset as adapter
    from app.workflows.schemas import WorkflowRequest
    root = tmp_path / 'collection'
    survey = adapter.inspect(source, WorkflowRequest(source_root=str(source)), tmp_path / 'survey')
    class Service:
        def register_input(self, *args): pytest.fail('failed collection registered an input')
    fake_runtime(monkeypatch, tmp_path, result(count=0))
    with pytest.raises(ValueError, match='未注册输入'):
        adapter.collect(survey, root, 'test', Service(), 'owner')
    standard = json.loads((root / 'standardization.json').read_text(encoding='utf-8'))
    assert standard['official_validator'] == 'invalid_result'
    assert not (root / 'input.json').exists()


from tests.workflows.test_workflow import source


def test_real_official_validator_checks_tsv_rows_beyond_1000(tmp_path):
    pytest.importorskip('bids_validator_deno')
    pytest.importorskip('deno')
    root = dataset(tmp_path)
    (root / 'participants.tsv').write_text('participant_id\tage\n'
        + ''.join(f'sub-{i:04d}\t25\n' for i in range(1001))
        + 'sub-1001\t25\textra\n', encoding='utf-8')
    value = validator.validate_bids(root, tmp_path / 'validation')
    assert value.status == 'failed' and value.errors > 0 and value.input_unchanged
    receipt = tmp_path / value.receipt_path
    raw = json.loads((receipt.parent / 'result.json').read_text(encoding='utf-8'))
    assert any(i['code'] == 'TSV_EQUAL_ROWS' and i.get('line') == 1003
               for i in raw['issues']['issues'])
