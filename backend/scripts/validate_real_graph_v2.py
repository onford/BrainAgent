"""Representative real EEG methods; no invented EOG or electrode metadata."""
from pathlib import Path
import argparse
import json
from app.preprocessing.schemas import PreprocessInput,PlanRequest,Step,MethodSpec,ArtifactPort,DecisionPolicy
from app.preprocessing.service import PreprocessingService
from app.preprocessing.worker import Worker
from app.preprocessing.runner import verify_result
from app.preprocessing.storage import write_json,file_hash


def step(name,unit,op,params,**extra):return Step(id=name,unit_id=unit,op=op,params=params,implementation_version='2',evidence_indices=[0],**extra)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    data=PreprocessInput.model_validate_json(args.input.read_text(encoding='utf-8'));data.collection.selected_record_ids=data.collection.selected_record_ids[:2]
    # These are real records used as explicitly designated validation fixtures.
    data.purpose='development_fixture'
    svc=PreprocessingService(args.output,[Path(data.collection.root)]);owner='unit-integration-audit';inp=svc.register_input(owner,data)
    evidence=[dict(source_url='brainagent:unit-integration:real-eeg-audit',source_version='2',locator='source operation contracts',text='工程组合验证；EEGMMIDB 真实记录，保持采集信息，不虚构 EOG。ICA 明确采用逐记录无标签适配。')]
    a=[step('ref','EEG-REREFERENCE','reference',dict(ref_channels='average')),
       step('filter','EEG-FILTER','filter',dict(l_freq=1.,h_freq=40.,method='iir',phase='zero',picks='$eeg_channels'),input='ref'),
       step('fit','EEG-ICA','ica_fit',dict(method='picard',n_components=12,seed=0,max_iter=1000,scope='$scope',reference_id='$reference_id'),input='filter',profile='method=picard',adaptation_scope='record_unlabeled'),
       step('assess','EEG-ICA','muscle_assess',dict(mode='slope',reference_id='$reference_id',threshold=.8,l_freq=7.,h_freq=40.),input='filter',model_from='fit',profile='mode=slope'),
       step('apply','EEG-ICA','ica_apply',dict(reference_id='$reference_id'),input='filter',model_from='fit',decision_from='assess',artifact_inputs={'exclude':ArtifactPort(step='assess',path=['candidates'])},decision=DecisionPolicy(mode='accept_candidates',reason='Engineering recipe explicitly accepts slope assessment candidates at threshold 0.8')),
       step('epoch','EEG-EPOCH','epoch',dict(events='$events',event_id='$event_id',tmin=0.,tmax=2.,picks='$eeg_channels'),input='apply'),
       step('baseline','EEG-BASELINE','baseline',dict(baseline=[0.,.2]),input='epoch')]
    b=[step('estimate','EEG-REREFERENCE','reference_estimate',dict(donors='$eeg_channels',reference_id='median_reference',estimator='nanmedian'),profile='estimator=nanmedian'),
       step('apply','EEG-REREFERENCE','reference_apply',dict(targets='$eeg_channels'),model_from='estimate'),
       step('filter','EEG-FILTER','butter',dict(kind='bandpass',l_freq=8.,h_freq=30.,prototype_order=4,phase='zero',picks='$eeg_channels',padlen=None),input='apply',profile='kind=bandpass,phase=zero'),
       step('epoch','EEG-EPOCH','epoch',dict(events='$events',event_id='$event_id',tmin=0.,tmax=2.,picks='$eeg_channels'),input='filter'),
       step('diagnose','EEG-WINDOW-MAD','window_mad',{},input='epoch'),
       step('baseline','EEG-BASELINE','baseline',dict(baseline=[0.,.2]),input='epoch')]
    refs=[]
    for identity,recipe in [('ica_diagnostic_decision',a),('reference_model',b)]:
        refs.append(svc.register_method(owner,MethodSpec(id=identity,version='2',title=identity,source='classic',mechanism='Explicit numerical source composition',recipe=recipe,output='baseline',evidence=evidence)))
    pref,plan=svc.plan(owner,PlanRequest(input_ref=inp,methods=refs,mode='validation',selection='all',max_candidates=2));write_json(args.output/'plan.json',plan.model_dump(mode='json'))
    if len(plan.records)!=4:raise ValueError(str(plan.screening))
    job=svc.submit(owner,pref);result=Worker(svc.store,svc.allowed_roots).run_once()
    checked=[dict(record_id=r['record_id'],method_id=r['method_id'],status=r['status'],error=r['error'],verified=bool(r['result'] and r['status']=='completed' and verify_result(svc.store.root,r['result'])),result=r['result']) for r in result.records]
    receipt=dict(job_id=job.job_id,plan_ref=pref.model_dump(),status=result.status,records=checked,source_input_sha256=file_hash(args.input),real_eeg=True,synthetic=False,source_unchanged=all(r['verified'] for r in checked))
    write_json(args.output/'real-data-receipt.json',receipt)
    print(json.dumps({k:v for k,v in receipt.items() if k!='records'},ensure_ascii=False),flush=True)
    if not all(r['verified'] for r in checked):raise RuntimeError(str([(r['record_id'],r['error']) for r in checked]))


if __name__=='__main__':main()
