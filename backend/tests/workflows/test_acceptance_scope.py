import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def source_scope():
    script = Path(__file__).resolve().parents[2] / 'scripts/release_workflow_acceptance.py'
    spec = importlib.util.spec_from_file_location('acceptance_scope_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.source_scope


def test_all_local_directories_are_not_automatically_full_dataset(tmp_path, source_scope):
    source = tmp_path / 'source'
    (source / 'S001').mkdir(parents=True)
    (source / 'S001/record.edf').write_bytes(b'original')
    (source / 'RECORDS').write_text('S001/record')
    before, scope = source_scope(source, tmp_path / 'output', ['S001'])
    assert scope['covers_all_local_participant_directories']
    assert not scope['full_eegmmidb_participant_scope']
    assert 'RECORDS' in before
    (source / 'S001/added.txt').write_text('new')
    after, _ = source_scope(source, tmp_path / 'output', ['S001'])
    assert before != after
    for i in range(2, 110):
        (source / f'S{i:03d}').mkdir()
    _, full = source_scope(source, tmp_path / 'output', [f'S{i:03d}' for i in range(1, 110)])
    assert full['full_eegmmidb_participant_scope']
    assert 'not independent validation' in full['scope_limitation']


def test_scope_rejects_overlapping_output_and_unknown_or_duplicate_ids(tmp_path, source_scope):
    source = tmp_path / 'source'
    (source / 'S001').mkdir(parents=True)
    for output in [source / 'output', tmp_path]:
        with pytest.raises(ValueError, match='disjoint'):
            source_scope(source, output, ['S001'])
    for subjects in [[], ['S002'], ['S001', 'S001'], ['../source']]:
        with pytest.raises(ValueError, match='unique, existing'):
            source_scope(source, tmp_path / 'output', subjects)
    assert not (tmp_path / 'output').exists()
