import pytest

from app.preprocessing.methods import baseline_methods
from app.preprocessing.schemas import Evidence, PlanRequest
from app.preprocessing.service import PreprocessingService
from app.search.knowledge_registry import KnowledgeRegistry
from app.search.scientific_space import knowledge
from .conftest import OWNER, PARAMETERS
from tests.search.test_knowledge_registry import edit


def test_current_knowledge_blocks_submission_retry_and_publication_but_frozen_search_survives(service,dataset):
    method=baseline_methods()[0].model_copy(deep=True)
    book=knowledge().model_dump(mode='json')
    method.evidence.append(Evidence(source_url=next(s['url'] for s in book['sources'] if s['id']=='S08'),
        source_version='fixture',locator='synthetic source link',text='Synthetic lifecycle fixture.'))
    method_ref=service.register_method(OWNER,method)
    inp=service.register_input(OWNER,dataset)
    request=PlanRequest(input_ref=inp,methods=[method_ref],mode='validation',parameters=PARAMETERS)
    plan_ref,plan=service.plan(OWNER,request)
    job=service.submit(OWNER,plan_ref)
    snapshot=plan.knowledge_revision
    assert snapshot
    service.knowledge_registry.update(OWNER,edit(snapshot['sha256']))
    for call in (lambda:service.submit(OWNER,plan_ref),lambda:service.control(OWNER,job.job_id,'retry'),
                 lambda:service.publish(OWNER,method_ref,[job.job_id])):
        with pytest.raises(ValueError,match='S08'):call()
    _,blocked=service.plan(OWNER,request)
    assert not blocked.records
    assert any('S08' in reason for s in blocked.screening for reason in s.reasons)
    frozen=PreprocessingService(service.store.root,service.allowed_roots,knowledge_snapshot=snapshot)
    assert frozen.submit(OWNER,plan_ref).job_id==job.job_id
    assert service.store.get(OWNER,plan_ref,'plan')['knowledge_revision']==snapshot
    service.control(OWNER,job.job_id,'cancel')


def test_search_plan_must_match_frozen_revision(tmp_path):
    from types import SimpleNamespace
    from app.search.worker import _check_plan
    from app.preprocessing.storage import digest,write_json
    registry=KnowledgeRegistry(tmp_path/'registry',knowledge())
    first=registry.get('a')
    second=registry.update('a',edit(first['sha256']))
    write_json(tmp_path/'protocol.json',dict(knowledge_revision_hash=digest(first)))
    plan=SimpleNamespace(knowledge_revision=second)
    with pytest.raises(RuntimeError,match='knowledge differs'):
        _check_plan(plan,None,None,tmp_path)
