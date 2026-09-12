"""Executable diagnostic branches, source comparison and adversarial binding checks."""
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy
import argparse, contextlib, traceback, time
import numpy as np
import mne
from scripts.validate_units_v2 import fixture,epoch_packet,config
from app.preprocessing.schemas import Step,ArtifactPort,ArtifactValue,DecisionPolicy
from app.preprocessing.graph_runtime import GraphExecutor,identity
from app.preprocessing.units.operations_v2 import inventory
from app.preprocessing.units.contracts_v2 import validate_parameters,invoke_source
from app.preprocessing.units import engine_hash,environment
from app.preprocessing.artifact_codec import fingerprint
from app.preprocessing.storage import write_json,file_hash


def port(step,*path):return ArtifactValue(kind='port',source=ArtifactPort(step=step,path=list(path)))
def literal(value):return ArtifactValue(kind='literal',value=value)
def op(sid,name,packet,**kw):
    row=next(r for r in inventory() if r['op']==name)
    params=validate_parameters(row['unit_id'],name,config(row,packet),row['profile'])
    return Step(id=sid,unit_id=row['unit_id'],op=name,params=params,implementation_version='2',evidence_indices=[0],**kw)


def compare(engine,s):
    packet=engine.nodes[s.input]['packet'];model=engine.nodes[s.model_from]['model'] if s.model_from else None
    p=engine.runtime_params(s,packet)
    expected=invoke_source(s.unit_id,s.op,packet.data,model=deepcopy(model),**p)
    out=engine.execute(s)
    assert fingerprint(out.data)==fingerprint(expected['data'])
    return out


def run(name,directory):
    packet=fixture();packet.data.set_eeg_reference('average',verbose='ERROR');packet.reference='average'
    if name=='sasica_external':packet=epoch_packet(packet)
    fit=op('fit','ica_fit',packet,adaptation_scope='record_unlabeled')
    engine=GraphExecutor(SimpleNamespace(id='synthetic-719'),[fit],packet,directory)
    engine.execute(fit);steps=[fit]
    if name=='sasica_external':
        assess=[]
        for sid,operation,field in [('adjust','adjust_assess','candidates'),('faster','faster_ic_assess','candidate_indices')]:
            s=op(sid,operation,packet,model_from='fit');compare(engine,s);steps.append(s)
            assess.append((sid,s.unit_id,field))
        envelope=ArtifactValue(kind='object',fields={uid:ArtifactValue(kind='object',fields={
            'component_id':port(sid,'component_id'),'candidate_indices':port(sid,field),
            'assessment_id':ArtifactValue(kind='digest',items=[port(sid)]),'algorithm':literal(uid+' pinned author implementation')}) for sid,uid,field in assess})
        s=op('sasica','sasica_assess',packet,model_from='fit');s.params.pop('external_assessments')
        s.parameter_inputs={'external_assessments':envelope};compare(engine,s);steps.append(s)
        assert set(engine.nodes['sasica']['artifacts']['config'])>={'EEG-ADJUST','EEG-FASTER-IC'}
        assert set(engine.nodes['sasica']['artifacts']['decisions'])=={'pending'}
        apply=op('apply','ica_apply',packet,model_from='fit',decision_from='sasica',decision=DecisionPolicy(mode='accept_candidates',reason='Synthetic combination audit explicitly accepts combined candidates'))
        apply.params.pop('exclude');apply.artifact_inputs={'exclude':ArtifactPort(step='sasica',path=['candidate_indices'])}
        compare(engine,apply);steps.append(apply)
        engine.nodes['adjust']['input_hash']='0'*64
        try:engine.execute(s.model_copy(update={'id':'wrong_assessment'}))
        except ValueError as e:assert 'binding mismatch' in str(e)
        else:raise AssertionError('different-data external assessment accepted')
    else:
        assess=op('labels','iclabel_assess',packet,model_from='fit');compare(engine,assess);steps.append(assess)
        weights=op('weights','eye_weights',packet,model_from='fit')
        weights.params.pop('eye_components');weights.params.pop('component_id')
        weights.parameter_inputs={'eye_components':ArtifactValue(kind='equal',items=[port('labels','labels'),literal('eye')]),'component_id':port('labels','component_id')}
        compare(engine,weights);steps.append(weights)
        apply=Step(id='apply',unit_id='EEG-WICA',op='wica_apply',params=dict(variant='targeted',reference_id='$reference_id',decision_id='audit-classification',clean_other='yes'),implementation_version='2',evidence_indices=[0],model_from='fit',decision_from='labels',decision=DecisionPolicy(mode='accept_candidates',reason='Synthetic ICLabel plus blink weights audit'),parameter_inputs={'probabilities':port('labels','probabilities'),'component_id':port('labels','component_id'),'eye_weights':port('weights','eye_weights')})
        compare(engine,apply);steps.append(apply)
        engine.nodes['weights']['model_hash']='0'*64
        try:engine.execute(apply.model_copy(update={'id':'wrong_weights'}))
        except ValueError as e:assert 'another data/model' in str(e)
        else:raise AssertionError('different-model weights accepted')
    write_json(directory/'steps.json',[s.model_dump(mode='json') for s in steps])
    return dict(executed=True,numerical_verified=True,negative_binding_verified=True,real_data=False,steps=[s.op for s in steps],final_hash=identity(engine.nodes['apply']['packet']))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True);mne.set_log_level('ERROR')
    results=[]
    for name in ['iclabel_weights_wica','sasica_external']:
        directory=args.output/name;directory.mkdir();receipt=dict(name=name,engine_sha256=engine_hash(),environment=environment(),started=time.time(),status='failed')
        try:
            with (directory/'runtime.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):receipt.update(run(name,directory))
            receipt['status']='passed'
        except Exception as e:receipt.update(error=str(e),traceback=traceback.format_exc())
        receipt['files']=[dict(path=p.relative_to(args.output).as_posix(),sha256=file_hash(p)) for p in directory.rglob('*') if p.is_file()]
        write_json(directory/'receipt.json',receipt);results.append(receipt);print(name,receipt['status'],receipt.get('error',''),flush=True)
    write_json(args.output/'results.json',results)


if __name__=='__main__':main()
