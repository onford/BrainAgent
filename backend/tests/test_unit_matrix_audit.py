import json
from pathlib import Path

import pytest

from scripts import audit_unit_matrix as subject


def fixture(tmp_path, monkeypatch, *, status='passed'):
    monkeypatch.setattr(subject, 'engine_hash', lambda: 'engine-current')
    monkeypatch.setattr(subject, 'environment', lambda: {'numpy': 'pinned'})
    monkeypatch.setattr(subject, 'inventory', lambda: [
        dict(identity=name, source={'source': {'code_sha256': 'source-' + name}})
        for name in ('a', 'b')])
    profiles = tmp_path / 'profiles'
    case = profiles / '000-a'
    case.mkdir(parents=True)
    artifact = case / 'runtime.log'
    artifact.write_text('actual runtime output', encoding='utf-8')
    script = tmp_path / 'trusted-validation.py'
    script.write_text('# frozen driver', encoding='utf-8')
    receipt = dict(identity='a', engine_sha256='engine-current', source_sha256='source-a',
        environment={'numpy': 'pinned'}, validation_script_sha256=subject.file_hash(script),
        status=status, compiled_graph=True, executed=True, numerical_verified=True,
        boundary_passed=True, error='native step failed' if status == 'failed' else None,
        files=[dict(path='000-a/runtime.log', sha256=subject.file_hash(artifact),
                    bytes=artifact.stat().st_size)])

    def save():
        (case / 'receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
        (profiles / 'results.json').write_text(json.dumps(dict(total_inventory=2,
            attempted=1, passed=int(receipt['status'] == 'passed'), results=[receipt])), encoding='utf-8')
    save()
    return profiles, script, receipt, artifact, save


def test_partial_matrix_keeps_missing_identity_and_does_not_claim_real_data(tmp_path, monkeypatch):
    profiles, script, _, artifact, _ = fixture(tmp_path, monkeypatch)
    original = artifact.read_bytes()
    output = tmp_path / 'review'
    result = subject.audit(profiles, script, output)
    assert result['counts'] == dict(profiles=2, attempted=1, passed=1, failed=0,
                                   not_executed=1, real_data_verified=0)
    assert result['status'] == 'partial'
    evidence = json.loads((output / 'verification_v2.json').read_text())
    assert set(evidence) == {'a', 'b'}
    assert evidence['a']['numerical_passed'] is True
    assert evidence['b']['status'] == 'not_executed'
    assert all(item['real_data_passed'] is False for item in evidence.values())
    assert artifact.read_bytes() == original


def test_failure_cannot_publish_leftover_pass_flags(tmp_path, monkeypatch):
    profiles, script, _, _, _ = fixture(tmp_path, monkeypatch, status='failed')
    output = tmp_path / 'review'
    result = subject.audit(profiles, script, output)
    evidence = json.loads((output / 'verification_v2.json').read_text())
    assert result['counts']['failed'] == 1
    assert not any(evidence['a'][key] for key in
                   ('compiled_passed', 'execution_passed', 'numerical_passed', 'boundary_passed'))


@pytest.mark.parametrize('change, message', [
    ('artifact', 'checksum'), ('engine', 'Stale engine'), ('script', 'Validation script'),
    ('runtime', 'Runtime differs'), ('duplicate', 'Duplicate profile'),
    ('index', 'index and individual'), ('outside', 'outside profile'),
    ('flags', 'lacks required'),
])
def test_inconsistent_evidence_rejected_before_output(tmp_path, monkeypatch, change, message):
    profiles, script, receipt, artifact, save = fixture(tmp_path, monkeypatch)
    if change == 'artifact':
        artifact.write_text('tampered', encoding='utf-8')
    elif change == 'engine':
        receipt['engine_sha256'] = 'old'
    elif change == 'script':
        script.write_text('# changed driver', encoding='utf-8')
    elif change == 'runtime':
        receipt['environment'] = {'numpy': 'different'}
    elif change == 'outside':
        receipt['files'][0]['path'] = '../trusted-validation.py'
    elif change == 'flags':
        receipt['numerical_verified'] = False
    save()
    if change == 'duplicate':
        extra = profiles / '001-duplicate'
        extra.mkdir()
        (extra / 'receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
    elif change == 'index':
        receipt['error'] = 'only changed one copy'
        (profiles / '000-a/receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
    output = tmp_path / 'review'
    with pytest.raises(ValueError, match=message):
        subject.audit(profiles, script, output)
    assert not output.exists()


def test_output_must_not_overlap_evidence(tmp_path, monkeypatch):
    profiles, script, _, _, _ = fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='disjoint'):
        subject.audit(profiles, script, profiles / 'nested-audit')


def test_native_helper_version_is_bound_to_receipts(tmp_path, monkeypatch):
    profiles, script, receipt, _, save = fixture(tmp_path, monkeypatch)
    helper = script.with_name('validate_native_profiles.py')
    helper.write_text('# pinned helper', encoding='utf8')
    receipt['validation_helpers'] = {helper.name: subject.file_hash(helper)}
    save()
    helper.write_text('# changed helper', encoding='utf8')
    with pytest.raises(ValueError, match='Validation helper differs'):
        subject.audit(profiles, script, tmp_path / 'review')
