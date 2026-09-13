import importlib.util
from pathlib import Path

import pytest

from app.preprocessing.storage import file_hash


@pytest.fixture
def evidence_type():
    script = Path(__file__).resolve().parents[2] / 'scripts/audit_eegnet_checkpoints.py'
    spec = importlib.util.spec_from_file_location('checkpoint_audit_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Evidence


def test_verified_artifact_change_is_detected_at_audit_end(tmp_path, evidence_type):
    path = tmp_path / 'model.pt'
    path.write_bytes(b'original checkpoint bytes')
    evidence = evidence_type(tmp_path)
    expected = file_hash(path)
    assert evidence.ref({'path': 'model.pt', 'sha256': expected, 'bytes': path.stat().st_size}) == path
    path.write_bytes(b'changed checkpoint bytes')
    with pytest.raises(ValueError, match='changed'):
        evidence.finish()
    with pytest.raises(ValueError, match='changed during audit'):
        evidence.path(path)


def test_wrong_hash_size_and_escaping_artifact_are_rejected(tmp_path, evidence_type):
    root = tmp_path / 'search'
    root.mkdir()
    path = root / 'predictions.json'
    path.write_bytes(b'[]')
    outside = tmp_path / 'unrelated.json'
    outside.write_bytes(b'{}')
    evidence = evidence_type(root)
    with pytest.raises(ValueError, match='Checksum mismatch'):
        evidence.ref({'path': str(path), 'sha256': '0' * 64})
    with pytest.raises(ValueError, match='size mismatch'):
        evidence.ref({'path': str(path), 'sha256': file_hash(path), 'bytes': 999})
    with pytest.raises(ValueError, match='outside'):
        evidence.path(outside)
    assert outside not in evidence.files
