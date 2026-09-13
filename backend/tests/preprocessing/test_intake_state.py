import asyncio
import json

import pytest

from app.preprocessing import intake_state
from app.preprocessing.methods import MethodLibrary
from app.preprocessing.schemas import SurveyLiteratureBundle
from app.preprocessing.storage import Storage, digest


@pytest.fixture
def intake(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_state, 'build_identity', lambda: {'source_sha256': 'fixed-engine'})
    store = Storage(tmp_path)
    library = MethodLibrary(store)
    bundle = SurveyLiteratureBundle(survey_run_id='same-survey', dataset_id='fixture',
                                    dataset_version='1', papers=[])
    root = store.root / 'intake' / digest(['owner', bundle.model_dump(mode='json')])
    ref = store.put('owner', 'method', {'title': 'Immutable method'})
    return library, bundle, root, dict(methods=[ref], supplement_requests=[])


@pytest.mark.asyncio
async def test_concurrent_instances_only_extract_once_and_reuse_after_restart(intake, monkeypatch):
    library, bundle, root, result = intake
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def extract(self, owner, value):
        calls.append(owner)
        entered.set()
        await release.wait()
        return result
    monkeypatch.setattr(MethodLibrary, '_intake', extract)
    first = asyncio.create_task(library.intake('owner', bundle))
    await entered.wait()
    second = asyncio.create_task(MethodLibrary(library.store).intake('owner', bundle))
    await asyncio.sleep(.1)
    assert calls == ['owner'] and not second.done()
    release.set()
    assert await first == await second == result
    assert await MethodLibrary(library.store).intake('owner', bundle) == result
    assert calls == ['owner']


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_release_the_active_intake(intake):
    _, _, root, _ = intake
    async with intake_state.intake_lock(root):
        async def wait():
            async with intake_state.intake_lock(root):
                pytest.fail('waiter entered an owned lock')
        task = asyncio.create_task(wait())
        await asyncio.sleep(.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ValueError, match='still running'):
            async with intake_state.intake_lock(root, timeout=.1):
                pytest.fail('active lock was released')
    async with intake_state.intake_lock(root, timeout=.1):
        pass


@pytest.mark.asyncio
async def test_failed_intake_releases_lock_and_keeps_existing_budget(intake, monkeypatch):
    library, bundle, root, result = intake
    calls = []
    async def extract(self, owner, value):
        calls.append(owner)
        if len(calls) == 1:
            (root / 'budget.json').write_text('{"used":6,"expires_at":1}')
            raise asyncio.CancelledError()
        assert json.loads((root / 'budget.json').read_text()) == {'used': 6, 'expires_at': 1}
        return result
    monkeypatch.setattr(MethodLibrary, '_intake', extract)
    with pytest.raises(asyncio.CancelledError):
        await library.intake('owner', bundle)
    assert not (root / 'completed-intake.json').exists()
    assert await library.intake('owner', bundle) == result


@pytest.mark.asyncio
async def test_missing_inputs_are_not_frozen_as_success(intake, monkeypatch):
    library, bundle, root, result = intake
    replies = [dict(methods=[], supplement_requests=[{'missing_fields': ['model']}]), result]
    async def extract(self, owner, value):
        return replies.pop(0)
    monkeypatch.setattr(MethodLibrary, '_intake', extract)
    assert (await library.intake('owner', bundle))['supplement_requests']
    assert not (root / 'completed-intake.json').exists()
    assert await library.intake('owner', bundle) == result


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['engine', 'method', 'receipt'])
async def test_completed_results_reject_changed_build_or_objects(intake, monkeypatch, change):
    library, bundle, root, result = intake
    async def extract(self, owner, value):
        return result
    monkeypatch.setattr(MethodLibrary, '_intake', extract)
    await library.intake('owner', bundle)
    if change == 'engine':
        monkeypatch.setattr(intake_state, 'build_identity', lambda: {'source_sha256': 'changed-engine'})
    elif change == 'method':
        with library.store.db() as db:
            db.execute("UPDATE objects SET body='{}' WHERE kind='method'")
    else:
        path = root / 'completed-intake.json'
        saved = json.loads(path.read_text())
        saved['identity']['bundle_sha256'] = 'changed'
        path.write_text(json.dumps(saved))
    with pytest.raises(ValueError):
        await library.intake('owner', bundle)


@pytest.mark.asyncio
async def test_crash_after_result_storage_reuses_content_addressed_result(intake, monkeypatch):
    library, bundle, root, result = intake
    async def extract(self, owner, value):
        return result
    monkeypatch.setattr(MethodLibrary, '_intake', extract)
    original = intake_state.write_json
    def crash(path, value):
        if path.name == 'completed-intake.json':
            raise OSError('injected completion failure')
        original(path, value)
    monkeypatch.setattr(intake_state, 'write_json', crash)
    with pytest.raises(OSError, match='injected'):
        await library.intake('owner', bundle)
    assert len(library.store.list_objects('owner', 'literature_intake_result')) == 1
    monkeypatch.setattr(intake_state, 'write_json', original)
    assert await library.intake('owner', bundle) == result
    assert len(library.store.list_objects('owner', 'literature_intake_result')) == 1


@pytest.mark.asyncio
async def test_legacy_unbound_extraction_is_not_stamped_as_current(intake):
    library, bundle, root, _ = intake
    root.mkdir(parents=True)
    old = b'{"used":4,"expires_at":1}'
    (root / 'budget.json').write_bytes(old)
    with pytest.raises(ValueError, match='Legacy'):
        await library.intake('owner', bundle)
    assert (root / 'budget.json').read_bytes() == old
    assert not (root / 'intake-identity.json').exists()


@pytest.mark.asyncio
async def test_another_valid_result_cannot_be_substituted(intake, monkeypatch):
    library, bundle, root, result = intake
    async def extract(self, owner, value):
        return result
    monkeypatch.setattr(MethodLibrary, '_intake', extract)
    await library.intake('owner', bundle)
    other = bundle.model_copy(update={'survey_run_id': 'different-survey'})
    await library.intake('owner', other)
    other_root = library.store.root / 'intake' / digest(['owner', other.model_dump(mode='json')])
    original = json.loads((root / 'completed-intake.json').read_text())
    original['result_ref'] = json.loads((other_root / 'completed-intake.json').read_text())['result_ref']
    (root / 'completed-intake.json').write_text(json.dumps(original))
    with pytest.raises(ValueError, match='another intake'):
        await library.intake('owner', bundle)
