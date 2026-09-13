import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def importer():
    path = Path(__file__).resolve().parents[2] / 'scripts/import_completed_workflow.py'
    spec = importlib.util.spec_from_file_location('completed_import_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


@pytest.fixture
def inputs(tmp_path):
    run, destination = tmp_path / 'run', tmp_path / 'service'
    workflow_id, search_id = '1' * 32, '2' * 32
    workflow, search = run / 'workflows' / workflow_id, run / 'offline-search' / search_id
    build = {'source_sha256': 'bound-source'}
    write(run / 'result.json', dict(status='completed', mechanical_gate_passed=True,
          original_data_unchanged=True, code_unchanged_during_run=True, driver_unchanged_during_run=True,
          workflow_id=workflow_id, search_id=search_id))
    write(workflow / 'workflow.json', dict(id=workflow_id, search_id=search_id, owner='owner', status='completed', execution_build=build))
    write(search / 'search.json', dict(id=search_id, workflow_id=workflow_id, owner='owner', status='completed'))
    (workflow / 'training-data.zip').write_bytes(b'opaque archive bytes')
    (search / 'model.pt').write_bytes(b'opaque model bytes')
    for name in ('workflows', 'offline-search'):
        (destination / name).mkdir(parents=True)
    return dict(run=run, destination=destination, expected_build=build, owner='owner', output=tmp_path / 'receipt.json')


def test_import_preserves_bytes_and_never_overwrites(importer, inputs):
    before = importer.inventory(inputs['run'])
    result = importer.import_completed(**inputs)
    assert result['status'] == 'copied_and_verified' and not result['execution_started']
    assert importer.inventory(inputs['run']) == before
    for name, identity in [('workflows', '1' * 32), ('offline-search', '2' * 32)]:
        assert importer.inventory(inputs['run'] / name / identity) == importer.inventory(inputs['destination'] / name / identity)
    inputs['output'] = inputs['output'].with_name('second.json')
    with pytest.raises(ValueError, match='never overwrite'):
        importer.import_completed(**inputs)


@pytest.mark.parametrize('damage', ['running', 'wrong-owner', 'wrong-build', 'bad-id', 'sidecar', 'receipt-in-source'])
def test_invalid_sources_rejected_before_publication(importer, inputs, damage):
    source = inputs['run'] / 'workflows' / ('1' * 32)
    state = importer.read(source / 'workflow.json')
    if damage == 'running':
        state['status'] = 'running'
    elif damage == 'wrong-owner':
        inputs['owner'] = 'another-owner'
    elif damage == 'wrong-build':
        inputs['expected_build'] = {'source_sha256': 'other'}
    elif damage == 'bad-id':
        path = inputs['run'] / 'result.json'
        result = importer.read(path)
        result['search_id'] = '../escape'
        write(path, result)
    elif damage == 'sidecar':
        (source / 'state.db-wal').write_bytes(b'active SQLite writes')
    elif damage == 'receipt-in-source':
        inputs['output'] = source / 'new-receipt.json'
    write(source / 'workflow.json', state)
    with pytest.raises(ValueError):
        importer.import_completed(**inputs)
    assert not list((inputs['destination'] / 'workflows').iterdir())
    assert not list((inputs['destination'] / 'offline-search').iterdir())


def test_source_change_during_copy_preserves_staging_without_publishing(importer, inputs, monkeypatch):
    original = importer.shutil.copytree

    def changed(source, destination, *args, **kwargs):
        result = original(source, destination, *args, **kwargs)
        if source.name == '1' * 32:
            (source / 'training-data.zip').write_bytes(b'changed source')
        return result

    monkeypatch.setattr(importer.shutil, 'copytree', changed)
    with pytest.raises(ValueError, match='Source changed'):
        importer.import_completed(**inputs)
    assert not list((inputs['destination'] / 'workflows').iterdir())
    assert not list((inputs['destination'] / 'offline-search').iterdir())
    assert importer.read(inputs['output'])['status'] == 'failed'
    assert (inputs['destination'] / ('.completed-import-' + '1' * 32)).is_dir()


def test_explicit_owner_mapping_changes_only_access_state(importer, inputs):
    before = importer.inventory(inputs['run'])
    inputs['destination_owner'] = 'sites-public'
    result = importer.import_completed(**inputs)
    assert importer.inventory(inputs['run']) == before
    assert result['source_owner'] == 'owner' and result['destination_owner'] == 'sites-public'
    assert set(result['state_changes']) == {'workflow.json', 'search.json'}
    for name, identity, state_name in [('workflows', '1' * 32, 'workflow'), ('offline-search', '2' * 32, 'search')]:
        source = inputs['run'] / name / identity
        target = inputs['destination'] / name / identity
        assert importer.read(target / (state_name + '.json')) == {
            **importer.read(source / (state_name + '.json')), 'owner': 'sites-public'}
        original, copied = importer.inventory(source), importer.inventory(target)
        original.pop(state_name + '.json')
        copied.pop(state_name + '.json')
        assert original == copied
        assert result['state_changes'][state_name + '.json']['destination_sha256'] == importer.sha(target / (state_name + '.json'))


def test_explicit_historical_import_preserves_original_build(importer, inputs):
    original_build = inputs['expected_build']
    inputs.update(expected_build={'source_sha256': 'new-service'}, allow_historical_build=True)
    result = importer.import_completed(**inputs)
    assert result['historical_build'] is True and result['execution_started'] is False
    assert result['execution_build'] == original_build
    state = importer.read(inputs['destination'] / 'workflows' / ('1' * 32) / 'workflow.json')
    assert state['execution_build'] == original_build
    assert state['execution_build'] != result['destination_execution_build']


@pytest.mark.parametrize('owner', ['', ' ', ' padded ', 'x' * 192])
def test_invalid_destination_owner_rejected(importer, inputs, owner):
    with pytest.raises(ValueError, match='Invalid destination owner'):
        importer.import_completed(**inputs, destination_owner=owner)
    assert not list((inputs['destination'] / 'workflows').iterdir())


def test_historical_mode_still_rejects_active_source(importer, inputs):
    path = inputs['run'] / 'offline-search' / ('2' * 32) / 'search.json'
    write(path, {**importer.read(path), 'status': 'running'})
    with pytest.raises(ValueError, match='Source is still active'):
        importer.import_completed(**inputs, allow_historical_build=True)
    assert not list((inputs['destination'] / 'workflows').iterdir())
