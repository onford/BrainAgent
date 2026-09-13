from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from app.preprocessing.schemas import Step, Postcondition, PlanRequest
from app.preprocessing.graph_runtime import Packet, GraphExecutor, PendingDecision, identity
from app.preprocessing.step_review import ShadowRequest, reviews, shadow_plan, verify_checkpoint
from app.preprocessing.storage import file_hash, digest
from app.preprocessing.service import PreprocessingService
from app.preprocessing.worker import Worker
from tests.preprocessing.test_graph_v2 import raw_fixture, method, step
from tests.preprocessing.conftest import make_dataset


def filter_step(lo=40.,hi=80.):
    return step('filter','EEG-FILTER','filter',dict(l_freq=lo,h_freq=hi,method='iir',phase='zero',picks='$eeg_channels'),
        input_channels='$eeg_channels',
        postconditions=[Postcondition(id='retained_amplitude',metric='rms',comparison='ge',threshold=5e-6,
            rationale='Synthetic integration prediction; not a neural preservation threshold')])


def test_empty_review_policy_preserves_legacy_step_serialization():
    s=step('ref','EEG-REREFERENCE','reference',dict(ref_channels='average'))
    assert 'postconditions' not in s.model_dump(mode='json')
    assert Step.model_validate(s.model_dump()).model_dump()==s.model_dump()
    with pytest.raises(ValueError):
        Step(id='bad',unit_id='EEG-FILTER',op='filter',evidence_indices=[0],postconditions=filter_step().postconditions)


def test_pause_writes_immutable_checkpoint_before_stopping_downstream(tmp_path):
    raw,events=raw_fixture()
    packet=Packet(raw,events,np.arange(4),['a','b','c','d'],'acquisition')
    source_hash=identity(packet)
    first=filter_step();first.params['picks']=raw.ch_names
    first.input_channels=raw.ch_names
    engine=GraphExecutor(None,[first],packet,tmp_path)
    with pytest.raises(PendingDecision,match='postcondition'):
        engine.execute(first)
    path=tmp_path/'filter/checkpoint.json'
    checkpoint=verify_checkpoint(path,file_hash(path))
    assert checkpoint['review_status']=='pause_required'
    assert checkpoint['postconditions'][0]['result']=='violated'
    assert checkpoint['observations']['rms']<5e-6
    assert checkpoint['trial_ids']==['a','b','c','d']
    assert checkpoint['output_hash']==identity(engine.nodes['filter']['packet'])
    assert identity(packet)==source_hash
    with pytest.raises(FileExistsError): engine.execute(first)
    artifact=checkpoint['files'][0]
    (path.parent/artifact['path']).write_bytes(b'changed')
    with pytest.raises(ValueError): verify_checkpoint(path,file_hash(path))


def prepare(tmp_path):
    data=make_dataset(tmp_path/'bids')
    svc=PreprocessingService(tmp_path/'store',[tmp_path/'bids'])
    inp=svc.register_input('owner',data)
    source=method([filter_step()])
    ref=svc.register_method('owner',source)
    pref,plan=svc.plan('owner',PlanRequest(input_ref=inp,methods=[ref],mode='validation'))
    assert len(plan.records)==2,plan.screening
    job=svc.submit('owner',pref)
    stopped=Worker(svc.store,svc.allowed_roots).run_once()
    assert stopped.status=='waiting_decision',stopped.model_dump()
    review=reviews(svc,'owner',job.job_id)
    assert len(review['checkpoints'])==2
    target=review['checkpoints'][0]
    request=ShadowRequest(record_key=target['record_key'],checkpoint_step='filter',
        checkpoint_sha256=target['checkpoint_sha256'],replacement=filter_step(1.,30.),
        reason='The synthetic source tones lie below the original filter; explicitly test the broader shared filter')
    return svc,data,job,stopped,request


def test_stopped_graph_compiles_shared_shadow_and_keeps_original_failure(tmp_path):
    svc,data,job,stopped,request=prepare(tmp_path)
    before={str(p):file_hash(p) for p in (svc.store.root/'runs'/job.job_id).rglob('*') if p.is_file()}
    original_inputs={str(p):file_hash(p) for p in Path(data.collection.root).rglob('*') if p.is_file()}
    response=shadow_plan(svc,'owner',job.job_id,request)
    assert response['execution_status']=='not_submitted'
    assert {r.record_id for r in response['plan'].records}==set(data.collection.selected_record_ids)
    assert len({r.method_ref.id for r in response['plan'].records})==1
    method_ref=response['plan'].request.methods[0]
    derived=svc.store.get('owner',method_ref,'method')
    assert derived['source']=='classic'
    assert derived['recipe'][0]['parameter_sources']['l_freq']['origin']=='engineering'
    assert derived['lineage']['branch_kind']=='engineering_step_replacement'
    child=svc.submit('owner',response['plan_ref'])
    done=Worker(svc.store,svc.allowed_roots).run_once()
    assert done.job_id==child.job_id and done.status=='completed',done.model_dump()
    assert svc.store.status('owner',job.job_id)==stopped
    assert all(file_hash(Path(p))==h for p,h in before.items())
    assert all(file_hash(Path(p))==h for p,h in original_inputs.items())
    assert all(r['review_status']=='observed' for r in reviews(svc,'owner',child.job_id)['checkpoints'])


@pytest.mark.parametrize('change',['owner','checkpoint_hash','node_id','relaxed_guard','invalid_band','record_override','tampered_checkpoint'])
def test_shadow_cannot_bypass_identity_guards_or_applicability(tmp_path,change):
    svc,data,job,stopped,request=prepare(tmp_path)
    owner='owner'
    if change=='owner': owner='other'
    if change=='checkpoint_hash': request.checkpoint_sha256='a'*64
    if change=='node_id': request.replacement.id='new_node'
    if change=='relaxed_guard': request.replacement.postconditions=[]
    if change=='invalid_band': request.replacement.params['h_freq']=500.
    if change=='record_override':
        from app.preprocessing.schemas import DecisionPolicy
        request.replacement.record_decisions={'sub-01':DecisionPolicy(mode='manual',reason='individual override')}
    if change=='tampered_checkpoint':
        from app.preprocessing.step_review import _job_checkpoint
        _,_,_,path=_job_checkpoint(svc,'owner',job.job_id,request.record_key,'filter')
        content=json.loads(path.read_text(encoding='utf-8'));content['observations']['rms']=50.
        path.write_text(json.dumps(content),encoding='utf-8')
        request.checkpoint_sha256=file_hash(path)
    with pytest.raises((KeyError,ValueError)):
        shadow_plan(svc,owner,job.job_id,request)
    assert svc.store.status('owner',job.job_id)==stopped


@pytest.mark.asyncio
async def test_agent_reviews_but_cannot_compile_a_shadow_plan(tmp_path):
    from app.agents.data_preprocessing.agent import DataPreprocessingAgent
    from app.runtime.context import AgentContext,AgentTask
    svc,data,job,stopped,request=prepare(tmp_path)
    agent=DataPreprocessingAgent(svc)
    context=AgentContext(session_id='review',owner_id='owner',user_message='Review stopped step and compile a shared replacement')
    result=await agent.run(AgentTask(instruction='review',inputs={'action':'step_reviews','job_id':job.job_id}),context)
    assert result.output['execution_status']=='reviewed' and len(result.output['checkpoints'])==2
    result=await agent.run(AgentTask(instruction='compile',inputs={'action':'shadow_plan','job_id':job.job_id,
        'request':request.model_dump(mode='json')}),context)
    assert result.output['execution_status']=='needs_input'
    assert 'job_id' not in result.output and svc.store.status('owner',job.job_id)==stopped


def test_review_routes_use_owner_scope_and_do_not_submit_shadow(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from app.api.routes.preprocessing import router,service
    from app.api.deps import get_current_user
    svc,data,job,stopped,request=prepare(tmp_path)
    app=FastAPI();app.include_router(router,prefix='/api')
    app.dependency_overrides[service]=lambda:svc
    app.dependency_overrides[get_current_user]=lambda:SimpleNamespace(owner_id='owner')
    with TestClient(app) as client:
        response=client.get(f'/api/preprocessing/jobs/{job.job_id}/step-reviews')
        assert response.status_code==200 and len(response.json()['checkpoints'])==2
        response=client.post(f'/api/preprocessing/jobs/{job.job_id}/shadow-plans',json=request.model_dump(mode='json'))
        assert response.status_code==201 and response.json()['execution_status']=='not_submitted'
        app.dependency_overrides[get_current_user]=lambda:SimpleNamespace(owner_id='other')
        assert client.get(f'/api/preprocessing/jobs/{job.job_id}/step-reviews').status_code==404
