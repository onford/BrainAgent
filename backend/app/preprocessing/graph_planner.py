"""Typed v2 graph compilation, independent of numerical execution."""
from copy import deepcopy

from .units.operations_v2 import DEFINITIONS
from .units.contracts_v2 import validate_parameters, dependency_status, RUNTIME


def compile_graph(method,record,data,parameters):
    bindings={'profile.'+k:v for k,v in parameters.items()}
    bindings.update(eeg_channels=[n for n in record.channel_order if record.channels[n]=='eeg'],
        eog_channels=[n for n in record.channel_order if record.channels[n]=='eog'],
        all_channels=record.channel_order,event_id=data.survey.event_id)
    def bind(v):
        if isinstance(v,str) and v.startswith('$'):
            if v[1:] in bindings:return deepcopy(bindings[v[1:]])
            if v in RUNTIME.values():return v
            raise ValueError('missing parameter/fact: '+v)
        if isinstance(v,dict):return {k:bind(x) for k,x in v.items()}
        if isinstance(v,list):return [bind(x) for x in v]
        return deepcopy(v)
    nodes={'raw':dict(kind='raw',channels=list(record.channel_order),sfreq=record.sfreq,
                      reference=record.reference,unit='V',model=None)}
    steps=[]
    for original in method.recipe:
        step=original.model_copy(deep=True)
        if record.id in step.record_decisions:step.decision=step.record_decisions[record.id].model_copy(deep=True)
        if step.implementation_version!='2':raise ValueError('a v2 graph requires every step to explicitly select implementation_version=2')
        key=(step.unit_id,step.op)
        if key not in DEFINITIONS:raise ValueError('operation not integrated: '+str(key))
        spec=DEFINITIONS[key]
        if step.id in nodes or step.input not in nodes:raise ValueError('step dependencies must be unique and topologically ordered')
        if any(i<0 or i>=len(method.evidence) for i in step.evidence_indices):raise ValueError('unresolved step evidence')
        source=nodes[step.input];state=deepcopy(source);kind=source['kind']
        if step.input_channels is not None:
            selected=bind(step.input_channels)
            step.input_channels=selected
            if len(set(selected))!=len(selected) or not set(selected)<=set(source['channels']):raise ValueError('invalid explicit input channel projection')
            source=deepcopy(source);source['channels']=list(selected);state=deepcopy(source)
        if step.input_representation=='array':
            if kind!='epochs':raise ValueError('array input projection requires Epochs with preserved axes')
            kind='array';state['kind']='array'
        if spec['input_kind']!='either' and kind!=spec['input_kind']:raise ValueError(f'{step.op} requires {spec["input_kind"]}, got {kind}')
        if source['unit']!='V':raise ValueError('this source operation requires voltage input, not CSD')
        for param,port in step.artifact_inputs.items():
            if port.step not in nodes:raise ValueError('artifact input must name an earlier step')
            if port.port=='model' and not nodes[port.step].get('model'):raise ValueError('artifact model port has no model')
        from .ports import sources
        for expression in step.parameter_inputs.values():
            for port in sources(expression):
                if port.step not in nodes:raise ValueError('constructed parameter requires an earlier graph node')
                if port.port=='model' and not nodes[port.step].get('model'):raise ValueError('constructed model port has no fitted model')
        if len(set(step.asset_inputs)|set(step.artifact_inputs)|set(step.parameter_inputs))!=len(step.asset_inputs)+len(step.artifact_inputs)+len(step.parameter_inputs):raise ValueError('duplicate parameter binding')
        if set(step.asset_inputs)-{'forward','projs','annotations'}:raise ValueError('only forward, projs and annotations accept external scientific assets')
        step.params=validate_parameters(*key,bind(step.params),profile=step.profile,bound=set(step.artifact_inputs)|set(step.asset_inputs)|set(step.parameter_inputs))
        p=step.params
        if step.op=='ecg_assess' and p['method']=='ctps' and kind!='raw':raise ValueError('CTPS requires Raw ECG peak detection before heartbeat epoching')
        missing_dependencies=dependency_status(spec,p)
        if missing_dependencies:raise ValueError('dependency_missing: '+str(missing_dependencies))
        if step.op in ('detect_bad_channels','asr_clean','prep_native','automagic_native'):
            if step.adaptation_scope!=p['adaptation_scope']:raise ValueError('engineering adaptation scope must also be declared on the graph step')
            if step.op in ('prep_native','automagic_native') and p['adaptation_scope']!='record_unlabeled':raise ValueError('complete native pipelines require explicit record-local fitting permission')
        for field in ('picks','picks_artifact','donors','targets','ref_chs','reref_chs'):
            selected=p.get(field)
            if isinstance(selected,list) and (len(selected)!=len(set(selected)) or not set(selected)<=set(source['channels'])):raise ValueError('invalid/duplicate channels: '+field)
            if field in ('picks','picks_artifact','donors','targets','ref_chs','reref_chs') and isinstance(selected,list) and not selected:raise ValueError('required channel selection is empty: '+field)
        for cutoff in ('l_freq','h_freq'):
            value=p.get(cutoff)
            if isinstance(value,(int,float)) and not 0<value<source['sfreq']/2:raise ValueError('filter bounds violate sampling rate')
        produces=spec['effect'] in ('model','reference_model')
        if spec['model_kind'] and not produces:
            if not step.model_from or step.model_from not in nodes or nodes[step.model_from].get('model')!=spec['model_kind']:raise ValueError('application requires compatible model_from')
            if nodes[step.model_from]['reference']!=source['reference']:raise ValueError('model reference incompatible with data')
        elif step.model_from:raise ValueError('unexpected fitted model input')
        if spec['fit']:
            if step.adaptation_scope=='record_unlabeled' and step.op in ('regression_baseline_fit','regression_baseline_epochs_fit'):
                if 'factors' in step.artifact_inputs or 'factors' in step.parameter_inputs or any(p.get('factors',[])):
                    raise ValueError('nonempty regression factors require explicit train/calibration scope; they cannot be declared unlabeled implicitly')
            if step.adaptation_scope=='record_unlabeled':
                if step.fit_scope:raise ValueError('record adaptation cannot also declare partition fit_scope')
            else:
                if not step.fit_scope or len(step.fit_scope.ids)!=1:raise ValueError('fit needs one explicit train/calibration partition')
                partitions={i.id:i for i in record.intervals}
                if any(i not in partitions or partitions[i].role!=step.fit_scope.role for i in step.fit_scope.ids):raise ValueError('fit scope includes unknown/test/incompatible partition')
                if step.adaptation_scope not in ('none',step.fit_scope.role):raise ValueError('declared adaptation and fit role disagree')
            cursor='raw' if step.adaptation_scope=='record_unlabeled' else step.input
            while cursor!='raw':
                ancestor=next(s for s in steps if s.id==cursor);a=DEFINITIONS[(ancestor.unit_id,ancestor.op)]
                if a['model_kind'] or a['decision'] or ancestor.adaptation_scope!='none' or ancestor.artifact_inputs or ancestor.parameter_inputs:
                    raise ValueError('partition fit ancestors must be replayable without fitted state or externally bound decisions')
                cursor=ancestor.input
            if 'scope' in p and p['scope']!='$scope':raise ValueError('scope must be runtime-bound to actual selected samples/trials')
        elif step.fit_scope:raise ValueError('fit_scope supplied to non-fitting operation')
        if spec['decision']:
            if step.decision is None:raise ValueError('operation requires an explicit decision policy')
            if step.decision.mode=='accept_candidates' and not step.decision_from:raise ValueError('automatic decision needs a diagnostic source')
        elif step.decision is not None:raise ValueError('unexpected decision policy')
        if step.decision_from:
            if not spec['decision'] or step.decision_from not in nodes:raise ValueError('unexpected/forward decision dependency')
            diagnostic=next(s for s in steps if s.id==step.decision_from)
            if (diagnostic.id if step.decision_target=='output' else diagnostic.input)!=step.input:raise ValueError('decision must be bound to the declared input or output data version')
            if diagnostic.model_from!=step.model_from and diagnostic.id!=step.model_from:raise ValueError('decision and application use different models')
        if spec['effect']=='epoch':
            if p.get('event_id')!=data.survey.event_id:raise ValueError('epoch event_id differs from Survey')
            state['kind']='epochs';state['channels']=p['picks']
        if spec['effect'] in ('channels','reference_channels'):
            field='channels' if spec['effect']=='channels' else 'confirmed_bad_channels'
            removed=p.get(field)
            if removed is None:
                state['dynamic_channels']=True
            else:state['channels']=[n for n in source['channels'] if n not in removed]
            if not state['channels']:raise ValueError('cannot drop all channels')
        if spec['effect']=='resample':state['sfreq']=p['sfreq']
        if spec['effect']=='decimate':state['sfreq']/=p['decim']
        if spec['effect'] in ('reference','reference_model','reference_channels'):
            target=p.get('reference_id', 'average' if p.get('ref_channels')=='average' else step.op)
            if step.op=='reference_apply':
                producer=next(s for s in steps if s.id==step.model_from)
                target=producer.params['reference_id']
            state['reference']=step.id+':'+(source['reference'] if target=='$reference_id' else target)
        if spec['effect']=='csd':state['unit']='V/m^2'
        if produces:
            state['model']=spec['model_kind']
        else:state['model']=None
        nodes[step.id]=state;steps.append(step)
    if method.output not in nodes or method.output=='raw':raise ValueError('method output must be an executed data port')
    return steps
