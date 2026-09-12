from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from app.search.knowledge_registry import KnowledgeRegistry, inactive
from app.search.scientific_space import knowledge
from tests.search.test_controller import factory  # noqa: F401


EVIDENCE = dict(source_url='fixture://review-notice',source_version='1',locator='Synthetic review',
    text='A test of revision handling, not an actual retraction or correction.')


def edit(head, status='suspended', identity='S08'):
    return dict(expected_sha256=head,changes=[dict(kind='source',id=identity,status=status,
        reason='Synthetic lifecycle change',evidence=EVIDENCE,observed_at='2026-09-12T00:00:00+00:00')])


def test_revisions_propagate_source_state_and_preserve_owned_history(tmp_path):
    registry=KnowledgeRegistry(tmp_path,knowledge())
    first=registry.get('a')
    second=registry.update('a',edit(first['sha256']))
    assert 'S08' in inactive(second['catalog'])[0]
    assert second['impact']['newly_inactive_rule_ids']
    assert registry.get('a',first['sha256']) == first
    assert registry.get('b') == first
    with pytest.raises(KeyError):registry.get('b',second['sha256'])
    restored=registry.update('a',edit(second['sha256'],'active'))
    assert 'S08' not in inactive(restored['catalog'])[0]
    assert restored['impact']['reactivated_rule_ids']
    assert registry.get('a',second['sha256']) == second
    assert KnowledgeRegistry(tmp_path,knowledge()).get('a') == restored


def test_concurrent_updates_cannot_lose_an_accepted_revision(tmp_path):
    registry=KnowledgeRegistry(tmp_path,knowledge())
    head=registry.get('a')['sha256']
    def update(identity):
        try:return registry.update('a',edit(head,identity=identity))
        except ValueError as exc:return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(update,['S08','S20']))
    assert sum(isinstance(o,dict) for o in outcomes)==1
    assert any(isinstance(o,str) and 'head changed' in o for o in outcomes)
    assert registry.get('a')['revision']==1


def test_catalog_rebase_is_explicit_and_old_records_remain_readable(tmp_path):
    original=knowledge().model_dump(mode='json')
    registry=KnowledgeRegistry(tmp_path,original)
    initial=registry.get('a')
    prior=registry.update('a',edit(initial['sha256']))
    changed=deepcopy(original)
    changed['sources'][0]['version']='fixture-new-source-version'
    current=KnowledgeRegistry(tmp_path,changed)
    with pytest.raises(ValueError,match='rebase'):current.get('a',require_current=True)
    # Explicitly carry the reviewed suspension into the new bundled catalog.
    next(s for s in changed['sources'] if s['id']=='S08').update(
        next(s for s in prior['catalog']['sources'] if s['id']=='S08'))
    rebased=current.rebase('a',dict(expected_sha256=prior['sha256'],catalog=changed,
        reason='Synthetic reviewed catalog merge',evidence=EVIDENCE,observed_at='2026-09-13T00:00:00+00:00'))
    assert 'S08' in inactive(rebased['catalog'])[0]
    assert current.get('a',require_current=True)==rebased
    assert current.get('a',prior['sha256'])==prior


def test_initial_revision_is_persisted_before_catalog_upgrade(tmp_path):
    registry=KnowledgeRegistry(tmp_path,knowledge())
    first=registry.get('a')
    changed=deepcopy(first['catalog'])
    changed['sources'][0]['version']='fixture-upgrade'
    newer=KnowledgeRegistry(tmp_path,changed)
    assert newer.get('a',first['sha256'])==first
    with pytest.raises(ValueError,match='rebase'):newer.get('a',require_current=True)


def test_invalid_replacement_and_corrupt_revision_fail_closed(tmp_path):
    registry=KnowledgeRegistry(tmp_path,knowledge())
    initial=registry.get('a')
    invalid=edit(initial['sha256'])
    invalid['changes'][0]['replacement']={'id':'different'}
    with pytest.raises(ValueError,match='identity'):registry.update('a',invalid)
    assert registry.get('a')==initial
    current=registry.update('a',edit(initial['sha256']))
    with registry.connect() as db:
        body={k:v for k,v in current.items() if k!='sha256'}
        body['revision']=99
        db.execute('UPDATE snapshots SET body=? WHERE owner=? AND sha256=?',(json.dumps(body),'a',current['sha256']))
    with pytest.raises(ValueError,match='checksum'):registry.get('a')


def test_new_search_uses_revision_and_impact_preserves_old_files(factory):
    from app.search.contracts import SearchRequest
    from app.search.io import read
    from app.preprocessing.storage import file_hash
    service, _, first = factory()
    root=service.folder(first['id'])
    hashes={p.name:file_hash(p) for p in root.glob('*.json')}
    prior=read(root/'knowledge-revision.json')
    updated=service.knowledge_registry.update('owner',edit(prior['sha256']))
    second=service.create('owner',SearchRequest(workflow_id='a'*32),start=False)
    current=read(service.folder(second['id'])/'knowledge-revision.json')
    assert current==updated
    space=read(service.folder(second['id'])/'space.json')
    assert 'S08' in space['knowledge_effects']['inactive_source_ids']
    assert space['knowledge_effects']['blocked_operator_ids']
    report=service.knowledge_impact('owner')
    old=next(r for r in report['runs'] if r['search_id']==first['id'])
    assert old['review_status']=='compared'
    assert 'S08' in old['impact']['newly_inactive_source_ids']
    assert service.knowledge_impact('other')['runs']==[]
    assert {p.name:file_hash(p) for p in root.glob('*.json')}==hashes


def test_inactive_rule_disables_advice_but_keeps_independent_contract(tmp_path):
    from types import SimpleNamespace
    from app.search.scientific_space import build_space
    from app.search.neural_priors import freeze_bundle
    from app.search.interpretation import interpretation_guide
    registry=KnowledgeRegistry(tmp_path,knowledge())
    request=edit(registry.get('a')['sha256'])
    request['changes'][0].update(kind='rule',id='R69')
    book=registry.update('a',request)['catalog']
    space=build_space({},book)
    assert 'asr-before-car' in space.knowledge_effects['independent_contracts_retained']
    assert next(p for p in space.priors if p.id=='asr-before-car').status=='active'
    guide=interpretation_guide()
    # Exact URL match also covers advice with no research-rule binding.
    suspended=deepcopy(book['sources'][0])
    suspended.update(status='suspended',status_reason='fixture',status_evidence=EVIDENCE,
        status_observed_at='2026-09-13T00:00:00+00:00',url=guide['sources'][0]['url'])
    book['sources'][0]=suspended
    linked={c['id'] for c in guide['cards'] if guide['sources'][0]['id'] in c['source_ids']}
    assert linked
    data=SimpleNamespace(collection=SimpleNamespace(records=[],selected_record_ids=[]),
        survey=SimpleNamespace(dataset_id='fixture',task='motor_imagery'))
    bundle=freeze_bundle(data,space,book,guide)
    assert bundle['inactive_rules']
    assert all('guide:'+guide['sources'][0]['id'] not in r['source_ids'] for r in bundle['rules'])


def test_revision_api_is_owner_scoped_and_detects_stale_updates(factory):
    from types import SimpleNamespace
    from fastapi import FastAPI, Header
    from fastapi.testclient import TestClient
    from app.api.deps import get_current_user
    from app.api.routes.searches import router
    service, _, _=factory()
    app=FastAPI()
    app.state.searches=service
    app.include_router(router)
    def principal(x_fixture_owner: str = Header()):
        return SimpleNamespace(owner_id=x_fixture_owner)
    app.dependency_overrides[get_current_user]=principal
    with TestClient(app) as client:
        headers={'X-Fixture-Owner':'owner'}
        first=client.get('/searches/knowledge',headers=headers).json()
        reply=client.post('/searches/knowledge',headers=headers,json=edit(first['sha256']))
        assert reply.status_code==201,reply.text
        updated=reply.json()
        assert client.post('/searches/knowledge',headers=headers,json=edit(first['sha256'])).status_code==422
        path='/searches/knowledge/revisions/'+updated['sha256']
        assert client.get(path,headers=headers).json()==updated
        assert client.get(path,headers={'X-Fixture-Owner':'other'}).status_code==404
        report=client.get('/searches/knowledge/impact',headers=headers)
        assert report.status_code==200 and report.json()['runs']


def test_correction_cannot_reactivate_obsolete_bindings_or_lose_original_url(tmp_path):
    from app.preprocessing.methods import baseline_methods
    from app.preprocessing.schemas import Evidence
    from app.search.knowledge_registry import method_issues
    registry=KnowledgeRegistry(tmp_path,knowledge())
    first=registry.get('a')
    original=next(s for s in first['catalog']['sources'] if s['id']=='S08')
    replacement={**original,'url':'https://example.org/fixture-corrected-source'}
    request=edit(first['sha256'],'active')
    request['changes'][0]['replacement']=replacement
    updated=registry.update('a',request)
    corrected=next(s for s in updated['catalog']['sources'] if s['id']=='S08')
    assert corrected['binding_review_required']
    assert corrected['binding_original_url']==original['url']
    assert 'S08' in inactive(updated['catalog'])[0]
    method=baseline_methods()[0].model_copy(deep=True)
    method.evidence=[Evidence(**{**EVIDENCE,'source_url':original['url']})]
    assert method_issues(method,updated['catalog'])
    again=registry.update('a',edit(updated['sha256'],'active'))
    assert 'S08' in inactive(again['catalog'])[0]
