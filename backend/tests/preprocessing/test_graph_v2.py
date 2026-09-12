from copy import deepcopy
from pathlib import Path
import numpy as np
import mne
import pytest

from app.preprocessing.schemas import Step, MethodSpec, PlanRequest, ArtifactPort, DecisionPolicy, Scope
from app.preprocessing.methods import baseline_methods
from app.preprocessing.graph_runtime import Packet, GraphExecutor, PendingDecision, identity
from app.preprocessing.artifact_codec import Codec, fingerprint
from app.preprocessing.planner import compile_steps
from app.preprocessing.service import PreprocessingService
from app.preprocessing.worker import Worker
from app.preprocessing.runner import verify_result
from app.preprocessing.units.contracts_v2 import validate_parameters, parameter_schema
from app.preprocessing.units.operations_v2 import DEFINITIONS, inventory
from tests.preprocessing.conftest import make_dataset


def step(identity,unit,op,params=None,**kwargs):
    return Step(id=identity,unit_id=unit,op=op,params=params or {},implementation_version='2',evidence_indices=[0],**kwargs)


def method(steps,output=None):
    return MethodSpec(id='graph-test',version='2',title='graph',source='classic',mechanism='test',recipe=steps,output=output or steps[-1].id,evidence=baseline_methods()[0].evidence)


def raw_fixture():
    sf=200.;t=np.arange(4000)/sf;rng=np.random.default_rng(42)
    a=np.stack([np.sin(2*np.pi*f*t)*10e-6+rng.normal(0,1e-6,len(t)) for f in [9,11,13,15]])
    raw=mne.io.RawArray(a,mne.create_info(['C3','C4','Cz','Pz'],sf,'eeg'),first_samp=37,verbose='ERROR')
    raw.set_montage('standard_1020')
    events=np.array([[237,0,1],[1237,0,2],[2237,0,1],[3237,0,2]])
    return raw,events


def test_complete_closed_registry():
    assert len(DEFINITIONS)==90
    assert len({r['identity'] for r in inventory()})==len(inventory())
    for spec in DEFINITIONS.values():assert parameter_schema(spec)['additionalProperties'] is False
    with pytest.raises(ValueError):validate_parameters('EEG-CROP','crop',{'tmin':0,'tmax':1,'events':'$events','arbitrary':1})
    with pytest.raises(ValueError):validate_parameters('EEG-RESAMPLE','resample',{'sfreq':True,'events':'$events'})
    assert validate_parameters('EEG-ASR','asr_fit',dict(scope='$scope',reference_id='$reference_id',start=0,stop='$n_samples'))['stop']=='$n_samples'
    from app.preprocessing.methods import extraction_contracts
    extracted=extraction_contracts('2')
    assert len(extracted)==90 and sum(len(op['profiles']) for op in extracted)==len(inventory())
    assert {(op['unit_id'],op['op'],p['profile']) for op in extracted for p in op['profiles']}=={(r['unit_id'],r['op'],r['profile']) for r in inventory()}


def test_native_ica_randomness_is_an_explicit_profile():
    profiles = [r for r in inventory() if r['op'] == 'automagic_native']
    assert {r['profile_parameters']['ica_random_policy'] for r in profiles} == {'author_clock','fixed_loop_seed_zero'}
    params = dict(source_root='author-source', eeglab_root='eeglab', prep_root='prep',
        matlab_path='matlab', line_freq=60, seed=321, timeout_seconds=600,
        adaptation_scope='record_unlabeled', ica_random_policy='fixed_loop_seed_zero')
    with pytest.raises(ValueError, match='contradict'):
        validate_parameters('EEG-CLASSIC-NATIVE','automagic_native',params,profile='ica_random_policy=author_clock')
    with pytest.raises(ValueError):
        validate_parameters('EEG-CLASSIC-NATIVE','automagic_native',{**params,'ica_random_policy':'implicit'})


def test_codec_exact_signal_arrays_annotations_and_tuple(tmp_path):
    raw,events=raw_fixture();raw.set_annotations(mne.Annotations([1],[.3],['BAD_noise']))
    payload={'raw':raw,'array':np.array([np.nan,1.]),'signature':('C3',('foo',2)),'ann':raw.annotations}
    codec=Codec(tmp_path)
    encoded=codec.verified_dump(payload)
    assert fingerprint(payload)==fingerprint(codec.load(encoded))
    next(tmp_path.glob('*.npy')).write_bytes(b'corrupt')
    with pytest.raises((ValueError,OSError)):codec.load(encoded)


def test_crop_join_epoch_reject_maps_and_original_readonly(tmp_path):
    raw,events=raw_fixture();before=fingerprint(raw)
    packet=Packet(raw,events,np.arange(4),['a','b','c','d'],'acquisition')
    decision=DecisionPolicy(mode='manual',status='confirmed',reason='test retained intervals',input_sha256=identity(packet))
    steps=[step('join','EEG-CROP','crop_join',{'keep_intervals':[[0,1600],[2000,4000]],'events':'$events','decision_id':'verified-join'},decision=decision),
        step('epoch','EEG-EPOCH','epoch',{'events':'$events','event_id':{'a':1,'b':2},'tmin':0,'tmax':.5,'picks':raw.ch_names},input='join')]
    engine=GraphExecutor(None,steps,packet,tmp_path)
    engine.execute(steps[0]);result=engine.execute(steps[1])
    assert result.event_indices.tolist()==[0,1,2,3]
    assert result.events[:,0].tolist()==[237,1237,1837,2837]
    assert result.trial_ids==['a','b','c','d']
    assert fingerprint(raw)==before
    policy=DecisionPolicy(mode='manual',status='confirmed',reason='reject one trial',input_sha256=identity(result))
    drop=step('drop','EEG-TRIAL-REJECT','drop_mask',{'reject_mask':[False,True,False,False],'trial_ids':'$trial_ids','decision_id':'drop-b'},input='epoch',decision=policy)
    out=engine.execute(drop)
    assert out.trial_ids==['a','c','d']
    np.testing.assert_array_equal(out.data.get_data(),result.data.get_data()[[0,2,3]])


def test_pending_manual_decision_does_not_apply(tmp_path):
    raw,events=raw_fixture();packet=Packet(raw,events,np.arange(4),['a','b','c','d'],'acquisition')
    s=step('join','EEG-CROP','crop_join',{'keep_intervals':[[0,1000]],'events':'$events','decision_id':'unconfirmed'},decision=DecisionPolicy(mode='manual',reason='needs review'))
    engine=GraphExecutor(None,[s],packet,tmp_path)
    with pytest.raises(PendingDecision):engine.execute(s)
    assert (tmp_path/'join/pending-decision.json').exists()
    assert 'join' not in engine.nodes


def test_csd_unit_is_persisted_and_matches_reference(tmp_path):
    raw,events=raw_fixture();packet=Packet(raw,events,np.arange(4),['a','b','c','d'],'acquisition')
    p=dict(sphere=[0.,0.,0.,.09],lambda2=1e-5,stiffness=4.,n_legendre_terms=50)
    s=step('csd','EEG-CSD','csd',p)
    out=GraphExecutor(None,[s],packet,tmp_path).execute(s)
    expected=mne.preprocessing.compute_current_source_density(raw.copy(),**p)
    np.testing.assert_allclose(out.data.get_data(),expected.get_data(),rtol=1e-12,atol=1e-16)
    assert out.unit=='V/m^2' and out.data.get_channel_types()==['csd']*4


def test_v2_planner_worker_and_validation_publication(tmp_path):
    data=make_dataset(tmp_path/'bids')
    svc=PreprocessingService(tmp_path/'output',[tmp_path/'bids'])
    inp=svc.register_input('test',data)
    recipe=[step('crop','EEG-CROP','crop',dict(tmin=1.,tmax=39.,events='$events')),
        step('reference','EEG-REREFERENCE','reference',dict(ref_channels='average'),input='crop'),
        step('epoch','EEG-EPOCH','epoch',dict(events='$events',event_id='$event_id',tmin=0.,tmax=.5,picks='$all_channels'),input='reference'),
        step('baseline','EEG-BASELINE','baseline',dict(baseline=[0.,.1]),input='epoch')]
    ref=svc.register_method('test',method(recipe))
    plan_ref,plan=svc.plan('test',PlanRequest(input_ref=inp,methods=[ref],mode='validation'))
    assert len(plan.records)==2
    job=svc.submit('test',plan_ref);result=Worker(svc.store,svc.allowed_roots).run_once()
    assert result.status=='completed',result.model_dump()
    for r in result.records:
        assert r['result']['schema_version']=='2'
        assert r['result']['delta']['events_retained']==7
        assert verify_result(svc.store.root,r['result'])
    published=svc.publish('test',ref,[job.job_id])
    assert svc.store.get('test',published,'method')['status']=='validated'


def test_model_binding_rejects_test_scope_and_missing_model(tmp_path):
    data=make_dataset(tmp_path/'bids');r=data.collection.records[0]
    s=step('fit','EEG-EOG-REGRESSION','eog_fit',dict(picks='$eeg_channels',picks_artifact='$eog_channels',scope='$scope',reference_id='$reference_id'),fit_scope=Scope(role='calibration',ids=['heldout']))
    with pytest.raises(ValueError,match='test'):compile_steps(method([s]),r,data,{})
    s=step('apply','EEG-ICA','ica_apply',dict(exclude=[],reference_id='$reference_id'),model_from='missing',decision=DecisionPolicy(mode='manual',reason='review'))
    with pytest.raises(ValueError,match='model'):compile_steps(method([s]),r,data,{})


def test_confirmed_decisions_create_new_plan_and_keep_original(tmp_path):
    from app.preprocessing.decisions import pending,confirm,Confirmations
    data=make_dataset(tmp_path/'bids');svc=PreprocessingService(tmp_path/'out',[tmp_path/'bids'])
    inp=svc.register_input('owner',data)
    s=step('join','EEG-CROP','crop_join',dict(keep_intervals=[[0,2000]],events='$events',decision_id='human-reviewed'),decision=DecisionPolicy(mode='manual',reason='review retained data'))
    ref=svc.register_method('owner',method([s]));pref,plan=svc.plan('owner',PlanRequest(input_ref=inp,methods=[ref],mode='validation'))
    job=svc.submit('owner',pref);waiting=Worker(svc.store,svc.allowed_roots).run_once()
    assert waiting.status=='waiting_decision'
    observed=pending(svc,'owner',job.job_id);assert len(observed)==2
    confirmations=[{k:p[k] for k in ('record_key','step_id','input_sha256','model_sha256')}|{'reason':'Synthetic review: retain first 2000 samples'} for p in observed]
    altered=deepcopy(confirmations);altered[0]['input_sha256']='0'*64
    with pytest.raises(ValueError,match='does not match'):confirm(svc,'owner',job.job_id,Confirmations(confirmations=altered))
    amended=confirm(svc,'owner',job.job_id,Confirmations(confirmations=confirmations))
    assert amended['plan_ref']!=pref
    assert svc.store.status('owner',job.job_id).status=='waiting_decision'
    svc.submit('owner',amended['plan_ref']);done=Worker(svc.store,svc.allowed_roots).run_once()
    assert done.status=='completed',done.model_dump()
    assert all(verify_result(svc.store.root,r['result']) for r in done.records)


def test_bounded_graph_search_executes_every_candidate(tmp_path):
    from app.search.unit_graph_space import GraphSweep,plan_sweep,candidates,operation_space
    data=make_dataset(tmp_path/'bids');svc=PreprocessingService(tmp_path/'out',[tmp_path/'bids']);inp=svc.register_input('owner',data)
    m=method([step('filter','EEG-FILTER','filter',dict(l_freq=1.,h_freq=30.,method='iir',phase='zero',picks='$eeg_channels'))])
    assert len(operation_space()['operators'])==len(inventory())
    with pytest.raises(ValueError,match='outside finite domain'):candidates(m,{'filter.l_freq':[123.]})
    planned=plan_sweep(svc,'owner',GraphSweep(input_ref=inp,method=m,grid={'filter.l_freq':[1.,2.]},mode='validation'))
    assert len(planned['plan'].records)==4,planned['plan'].screening
    svc.submit('owner',planned['plan_ref']);done=Worker(svc.store,svc.allowed_roots).run_once()
    assert done.status=='completed' and done.completed==4


def test_registered_annotation_asset_is_hash_bound(tmp_path):
    from app.preprocessing.assets import AssetRegistration,register
    from app.preprocessing.storage import file_hash
    data=make_dataset(tmp_path/'bids');svc=PreprocessingService(tmp_path/'out',[tmp_path/'bids']);inp=svc.register_input('owner',data)
    path=tmp_path/'bids'/'audited-annot.fif';mne.Annotations([2.],[.2],['BAD_audit']).save(path)
    asset=register(svc,'owner',AssetRegistration(path=str(path),sha256=file_hash(path),kind='annotations',provenance='synthetic human reviewed interval'))
    # External assets retain ownership and cannot be fetched by another owner.
    with pytest.raises(KeyError):svc.store.get('other',asset,'unit_asset')
    snapshot=svc.store.get('owner',asset,'unit_asset')
    from app.preprocessing.assets import load
    assert load(svc.store.root,snapshot).description.tolist()==['BAD_audit']
    (svc.store.root/next(iter(snapshot['files']))).write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='changed'):load(svc.store.root,snapshot)


def test_partition_fit_replays_filter_only_on_calibration(tmp_path):
    from types import SimpleNamespace
    from app.preprocessing.units.contracts_v2 import invoke_source
    raw,events=raw_fixture();packet=Packet(raw,events,np.arange(4),['a','b','c','d'],'acquisition')
    record=SimpleNamespace(id='r',sfreq=200.,intervals=[SimpleNamespace(id='cal',start=0,stop=2000,role='calibration')])
    filt=step('filter','EEG-FILTER','filter',dict(l_freq=1.,h_freq=30.,method='iir',phase='zero',picks=raw.ch_names))
    fit=step('fit','EEG-CCA','cca_fit',dict(scope='$scope',reference_id='$reference_id',lags=1),input='filter',fit_scope=Scope(role='calibration',ids=['cal']))
    engine=GraphExecutor(record,[filt,fit],packet,tmp_path/'first');engine.execute(filt);engine.execute(fit)
    changed=deepcopy(packet);changed.data._data[:,2000:]+=np.random.default_rng(1).normal(0,.001,(4,2000))
    second=GraphExecutor(record,[filt,fit],changed,tmp_path/'second');second.execute(filt);second.execute(fit)
    assert fingerprint(engine.nodes['fit']['model'])==fingerprint(second.nodes['fit']['model'])
    assert any(log['branch']=='fit_replay' for log in engine.logs)


def test_closed_ports_and_cca_model_diagnostic_decision(tmp_path):
    from types import SimpleNamespace
    from app.preprocessing.schemas import ArtifactValue
    from app.preprocessing.units.contracts_v2 import invoke_source
    raw,events=raw_fixture();packet=Packet(raw,events,np.arange(4),['a','b','c','d'],'acquisition')
    fit=step('fit','EEG-CCA','cca_fit',dict(scope='$scope',reference_id='$reference_id',lags=1),adaptation_scope='record_unlabeled')
    expression=ArtifactValue(kind='nonzero',items=[ArtifactValue(kind='less',items=[ArtifactValue(kind='port',source=ArtifactPort(step='fit',path=['canonical_correlations'])),ArtifactValue(kind='literal',value=.99)])])
    apply=step('apply','EEG-CCA','cca_apply',dict(reference_id='$reference_id',decision_id='fixed-correlation-threshold'),model_from='fit',decision_from='fit',parameter_inputs={'exclude':expression},decision=DecisionPolicy(mode='accept_candidates',reason='Explicit threshold .99'))
    engine=GraphExecutor(SimpleNamespace(id='r'),[fit,apply],packet,tmp_path)
    engine.execute(fit);out=engine.execute(apply)
    indices=np.flatnonzero(engine.nodes['fit']['artifacts']['canonical_correlations']<.99).tolist()
    expected=invoke_source('EEG-CCA','cca_apply',raw,model=engine.nodes['fit']['model'],exclude=indices,reference_id='acquisition',decision_id='fixed-correlation-threshold')
    assert indices
    np.testing.assert_allclose(out.data.get_data(),expected['data'].get_data(),atol=1e-16)
    # A channel-order change must not consume the fitted model.
    reordered=step('wrong','EEG-CCA','cca_apply',dict(reference_id='$reference_id',exclude=[],decision_id='bad-binding'),model_from='fit',input_channels=list(reversed(raw.ch_names)),decision=DecisionPolicy(mode='manual',reason='invalid binding'))
    with pytest.raises(ValueError,match='channels'):engine.execute(reordered)
    engine.nodes['fit']['model']['estimator']['mixing'][0,0]+=1
    with pytest.raises(ValueError,match='model changed'):engine.execute(apply.model_copy(update={'id':'tampered'}))


def test_sparse_forward_data_and_complex_scalar_roundtrip(tmp_path):
    from scipy import sparse
    payload={'distances':sparse.csc_matrix([[0.,1.],[2.,0.]]),'phase':np.complex128(1+2j)}
    codec=Codec(tmp_path);encoded=codec.verified_dump(payload)
    actual=codec.load(encoded)
    np.testing.assert_array_equal(actual['distances'].toarray(),payload['distances'].toarray())
    assert actual['phase']==1+2j


def test_cancel_before_algorithm_and_retry_completed_job(tmp_path):
    from app.preprocessing.runner import Cancelled
    raw,events=raw_fixture();packet=Packet(raw,events,np.arange(4),['a','b','c','d'],'acquisition')
    s=step('filter','EEG-FILTER','filter',dict(l_freq=1.,h_freq=30.,method='iir',picks=raw.ch_names))
    with pytest.raises(Cancelled):GraphExecutor(None,[s],packet,tmp_path,cancelled=lambda:True).execute(s)
    assert not (tmp_path/'filter').exists()


def test_eog_raw_calibration_model_applies_to_epochs(tmp_path):
    data=make_dataset(tmp_path/'bids');svc=PreprocessingService(tmp_path/'out',[tmp_path/'bids']);inp=svc.register_input('owner',data)
    scope=next(p for p in data.collection.records[0].intervals if p.role=='calibration')
    recipe=[step('ref','EEG-REREFERENCE','reference',dict(ref_channels='average')),
        step('fit','EEG-EOG-REGRESSION','eog_fit',dict(picks='$eeg_channels',picks_artifact='$eog_channels',scope='$scope',reference_id='$reference_id'),input='ref',fit_scope=Scope(role='calibration',ids=[scope.id])),
        step('epoch','EEG-EPOCH','epoch',dict(events='$events',event_id='$event_id',tmin=0.,tmax=.5,picks='$all_channels'),input='ref'),
        step('apply','EEG-EOG-REGRESSION','eog_apply',dict(reference_id='$reference_id'),input='epoch',model_from='fit')]
    ref=svc.register_method('owner',method(recipe));pref,plan=svc.plan('owner',PlanRequest(input_ref=inp,methods=[ref],mode='validation'))
    svc.submit('owner',pref);done=Worker(svc.store,svc.allowed_roots).run_once()
    assert done.status=='completed',done.model_dump()
    for record in done.records:assert verify_result(svc.store.root,record['result'])


def test_v2_api_capabilities_search_run_and_owned_download(tmp_path):
    from fastapi.testclient import TestClient
    from app.core.config import Settings
    from app.main import create_app
    from tests.fakes import ScriptedLLMClient
    from tests.preprocessing.test_integration import KEY
    data=make_dataset(tmp_path/'bids');settings=Settings(database_url_override=f"sqlite+aiosqlite:///{tmp_path/'chat.db'}",brain_agent_credential_encryption_key=KEY,preprocessing_root=str(tmp_path/'out'),preprocessing_input_roots=[data.collection.root])
    app=create_app(settings,ScriptedLLMClient([]));headers={'X-Brain-Agent-Owner-ID':'owner'}
    with TestClient(app) as client:
        c=client.get('/api/preprocessing/capabilities').json();assert c['counts']=={'units':53,'operations':90,'profiles':len(inventory())}
        inp=client.post('/api/preprocessing/inputs',headers=headers,json=data.model_dump(mode='json')).json()
        assert client.post('/api/preprocessing/capabilities/input',headers={'X-Brain-Agent-Owner-ID':'other'},json=inp).status_code==404
        assert client.post('/api/preprocessing/capabilities/input',headers=headers,json=inp).status_code==200
        m=method([step('filter','EEG-FILTER','filter',dict(l_freq=1.,h_freq=30.,method='iir',phase='zero',picks='$eeg_channels'))])
        planned=client.post('/api/preprocessing/graph-search/plans',headers=headers,json={'input_ref':inp,'method':m.model_dump(mode='json'),'grid':{'filter.l_freq':[1.,2.]},'mode':'validation'})
        assert planned.status_code==201,planned.text
        job=client.post('/api/preprocessing/jobs',headers=headers,json={'plan_ref':planned.json()['plan_ref']}).json()
        done=Worker(app.state.preprocessing.store,app.state.preprocessing.allowed_roots).run_once();assert done.status=='completed'
        key=done.records[0]['key'];url=f"/api/preprocessing/jobs/{job['job_id']}/artifacts/{key}/axes.json"
        reply=client.get(url,headers=headers);assert reply.status_code==200 and reply.json()['trial_ids']
        assert client.get(url,headers={'X-Brain-Agent-Owner-ID':'other'}).status_code==404


def test_retry_keeps_completed_record_and_failed_attempt(tmp_path,monkeypatch):
    import app.preprocessing.worker as worker_module
    data=make_dataset(tmp_path/'bids');svc=PreprocessingService(tmp_path/'out',[tmp_path/'bids']);inp=svc.register_input('owner',data)
    ref=svc.register_method('owner',method([step('ref','EEG-REREFERENCE','reference',dict(ref_channels='average'))]))
    pref,_=svc.plan('owner',PlanRequest(input_ref=inp,methods=[ref],mode='validation'));job=svc.submit('owner',pref)
    original=worker_module.run_record;calls=[]
    def interrupted(plan,config,*args):
        calls.append(config.record_id)
        if config.record_id==data.collection.records[1].id:raise OSError('injected temporary storage outage')
        return original(plan,config,*args)
    monkeypatch.setattr(worker_module,'run_record',interrupted)
    first=Worker(svc.store,svc.allowed_roots).run_once();assert first.status=='partial'
    completed=next(r for r in first.records if r['status']=='completed');saved=deepcopy(completed['result'])
    monkeypatch.setattr(worker_module,'run_record',original)
    svc.store.control('owner',job.job_id,'retry');done=Worker(svc.store,svc.allowed_roots).run_once()
    assert done.status=='completed'
    assert next(r for r in done.records if r['key']==completed['key'])['result']==saved
    assert all(verify_result(svc.store.root,r['result']) for r in done.records)


def test_record_adaptation_uses_current_processed_branch(tmp_path):
    from types import SimpleNamespace
    raw,events=raw_fixture();raw.filter(1.,None,verbose='ERROR');packet=Packet(raw,events,np.arange(4),['a','b','c','d'],'acquisition')
    first=step('fit','EEG-CCA','cca_fit',dict(scope='$scope',reference_id='$reference_id',lags=1),adaptation_scope='record_unlabeled')
    engine=GraphExecutor(SimpleNamespace(id='r'),[first],packet,tmp_path);engine.execute(first)
    apply=step('clean','EEG-CCA','cca_apply',dict(reference_id='$reference_id',exclude=[0],decision_id='audited-cca'),model_from='fit',decision=DecisionPolicy(mode='manual',status='confirmed',reason='synthetic first component',input_sha256=identity(packet),model_sha256=fingerprint(engine.nodes['fit']['model'])))
    engine.execute(apply)
    second=step('ica','EEG-ICA','ica_fit',dict(scope='$scope',reference_id='$reference_id',method='fastica',n_components=2,seed=0,max_iter=1000),input='clean',adaptation_scope='record_unlabeled')
    engine.steps.update(clean=apply,ica=second);engine.execute(second)
    assert engine.nodes['ica']['binding']['input_hash']==identity(engine.nodes['clean']['packet'])
    assert engine.nodes['ica']['binding']['input_hash']!=identity(packet)
    assert not any(log['branch']=='fit_replay' for log in engine.logs)


def test_different_custom_references_cannot_share_a_model(tmp_path):
    from types import SimpleNamespace
    raw,events=raw_fixture();raw.filter(1.,None,verbose='ERROR');packet=Packet(raw,events,np.arange(4),['a','b','c','d'],'acquisition')
    a=step('refa','EEG-REREFERENCE','reference',dict(ref_channels=['C3']))
    b=step('refb','EEG-REREFERENCE','reference',dict(ref_channels=['Cz']))
    fit=step('fit','EEG-ICA','ica_fit',dict(scope='$scope',reference_id='$reference_id',method='fastica',n_components=2,seed=0,max_iter=1000),input='refa',adaptation_scope='record_unlabeled')
    engine=GraphExecutor(SimpleNamespace(id='r'),[a,b,fit],packet,tmp_path)
    engine.execute(a);engine.execute(b);engine.execute(fit)
    assert engine.nodes['refa']['packet'].reference!=engine.nodes['refb']['packet'].reference
    wrong=step('wrong','EEG-ICA','ica_apply',dict(exclude=[],reference_id='$reference_id'),input='refb',model_from='fit',decision=DecisionPolicy(mode='manual',reason='should fail before decision'))
    with pytest.raises(ValueError,match='reference'):engine.execute(wrong)


@pytest.mark.parametrize('array',[False,True])
@pytest.mark.parametrize('factor_columns',[1,2])
def test_regression_covariates_fit_only_on_declared_training_trials(tmp_path,array,factor_columns):
    from types import SimpleNamespace
    from scripts.validate_units_v2 import fixture
    from app.preprocessing.graph_planner import compile_graph
    packet=fixture();names=packet.data.copy().pick('eeg').ch_names
    record=SimpleNamespace(id='r',sfreq=400.,reference='acquisition',channel_order=packet.data.ch_names,channels=dict(zip(packet.data.ch_names,packet.data.get_channel_types())),intervals=[SimpleNamespace(id='train',role='train',start=0,stop=16000)])
    ep=step('ep','EEG-EPOCH','epoch',dict(events='$events',event_id={'a':1,'b':2},tmin=-.5,tmax=1.,picks=names))
    operation='regression_baseline_fit' if array else 'regression_baseline_epochs_fit'
    p=dict(scope='$scope',baseline=[-.5,0.],factors=[[float(2*((i//(2**j))%2)-1) for j in range(factor_columns)] for i in range(19)],factor_names=[f'condition{j}' for j in range(factor_columns)])
    p.update(axes='$axes',times='$times') if array else p.update(picks=names)
    fit=step('fit','EEG-REGRESSION-BASELINE',operation,p,input='ep',input_representation='array' if array else 'native',fit_scope=Scope(role='train',ids=['train']))
    data=SimpleNamespace(survey=SimpleNamespace(event_id={'a':1,'b':2}))
    compiled=compile_graph(method([ep,fit]),record,data,{})
    first=GraphExecutor(record,compiled,packet,tmp_path/'first');first.execute(compiled[0]);first.execute(compiled[1])
    changed=deepcopy(packet);changed.data._data[:,16000:]+=np.random.default_rng(3).normal(0,.01,(34,8000))
    second=GraphExecutor(record,compiled,changed,tmp_path/'second');second.execute(compiled[0]);second.execute(compiled[1])
    assert fingerprint(first.nodes['fit']['model'])==fingerprint(second.nodes['fit']['model'])
    apply_op='regression_baseline_apply' if array else 'regression_baseline_epochs_apply'
    apply_params=dict(axes='$axes',times='$times',trial_ids='$trial_ids') if array else dict(picks=names,trial_ids='$trial_ids')
    application=step('apply','EEG-REGRESSION-BASELINE',apply_op,apply_params,input='ep',model_from='fit',input_representation='array' if array else 'native')
    actual=first.execute(application)
    from app.preprocessing.units.contracts_v2 import invoke_source
    source_packet=deepcopy(first.nodes['ep']['packet'])
    if array:source_packet.epoch_template=source_packet.data;source_packet.data=source_packet.data.get_data()
    expected=invoke_source('EEG-REGRESSION-BASELINE',apply_op,source_packet.data,model=first.nodes['fit']['model'],**first.runtime_params(application,source_packet))
    assert fingerprint(actual.data)==fingerprint(expected['data'])
    forbidden=fit.model_copy(update={'fit_scope':None,'adaptation_scope':'record_unlabeled'})
    with pytest.raises(ValueError,match='regression factors'):compile_graph(method([ep,forbidden]),record,data,{})
