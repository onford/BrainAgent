"""Lossless source graph projection and dependency renaming for composition."""
from copy import deepcopy
from app.preprocessing.schemas import Step
from app.preprocessing.storage import digest
from app.preprocessing.ports import sources


def rename_ports(step, names):
    for port in list(step.artifact_inputs.values()) + [p for e in step.parameter_inputs.values() for p in sources(e)]:
        if port.step not in names:
            raise ValueError('fragment has external artifact/parameter dependencies; include prerequisite nodes')
        port.step = names[port.step]


def graph_operator(step, space):
    from app.preprocessing.units.operations_v2 import DEFINITIONS
    spec = DEFINITIONS[(step.unit_id, step.op)]
    params = {**deepcopy(spec['defaults']), **deepcopy(step.params)}
    for key in step.artifact_inputs.keys() | step.parameter_inputs.keys() | step.asset_inputs.keys():
        params.pop(key, None)
    from .unit_graph_space import DOMAINS
    domains, defaults = {}, {}
    profile_fields = {part.split('=')[0] for part in step.profile.split(',') if '=' in part}
    for key, choices in DOMAINS.get(step.op,{}).items():
        if key not in params or key in profile_fields or type(params[key]) not in (float,int):continue
        if not all(type(v) in (float,int) for v in choices):continue
        bounds=[*choices,params[key]]
        domains[key]=dict(kind='integer' if all(type(v) is int for v in bounds) else 'number',minimum=min(bounds),maximum=max(bounds),
            unit='operation contract',origin='engineering',rationale='Bounded engineering search around the registered source value; edits are not paper parameters.')
        defaults[key]=params[key]
    bindings={k:v for k,v in params.items() if k not in domains}
    identity = 'graph-op-' + digest([step.unit_id, step.op, step.profile, params])[:20]
    if identity not in {o['id'] for o in space['operators']}:
        space['operators'].append(dict(id=identity, title=f'{step.unit_id} / {step.op}', unit_id=step.unit_id,
            op=step.op, implementation_version='2', profile=step.profile,
            input_stage='continuous' if spec['input_kind'] == 'raw' else 'epochs' if spec['input_kind'] in ('epochs', 'array') else 'either',
            output_stage='epochs' if spec['effect'] == 'epoch' else 'same', fit_scope='none',
            domains=domains, defaults=defaults, bindings=bindings, emit_mark=False, max_instances=4))
    return identity, defaults, params


def graph_seed(method, ref, base, output):
    value = deepcopy(base)
    method = method.model_copy(deep=True)
    steps = method.recipe
    # Attach engineering preparation only to the actual output lineage. Side
    # branches and their fit/decision inputs remain untouched.
    by_id={s.id:s for s in steps}; cursor=method.output; ancestry=[]
    while cursor!='raw':
        if cursor not in by_id or cursor in {s.id for s in ancestry}:
            raise ValueError('invalid source output dependency')
        ancestry.append(by_id[cursor]); cursor=by_id[cursor].input
    has_epoch = any(s.op in ('epoch','epoch_with_nonfinite') for s in ancestry)
    if has_epoch and not any(s.op in ('resample','resample_fft','resample_fir','resample_eeglab') for s in ancestry):
        by_id={s.id:s for s in steps};cursor=method.output;epoch=None
        while cursor!='raw':
            s=by_id[cursor]
            if s.op in ('epoch','epoch_with_nonfinite'):epoch=s;break
            cursor=s.input
        if epoch:
            adapter=Step(id='shared_resample',unit_id='EEG-RESAMPLE',op='resample',implementation_version='2',
                input=epoch.input,params={'sfreq':output['sfreq'],'events':'$events'},evidence_indices=[0],
                parameter_sources={k:dict(origin='target_binding',evidence_indices=[],rationale='Explicit frozen output-grid adapter') for k in ('sfreq','events')})
            if adapter.id in by_id:raise ValueError('source node collides with shared resample adapter')
            steps.insert(steps.index(epoch),adapter);epoch.input=adapter.id
            method.adaptations.append('Explicit synchronized output-grid resampling before the source epoch; all source windows/operations are retained.')
    if not has_epoch:
        for op, unit, params in [('resample','EEG-RESAMPLE', {'sfreq':output['sfreq'], 'events':'$events'}),
                                ('epoch','EEG-EPOCH', {'tmin':output['tmin'], 'tmax':output['tmax'],
                                 'events':'$events','event_id':'$event_id','picks':'$eeg_channels'})]:
            sid='shared_'+op
            if sid in {s.id for s in steps}:
                raise ValueError('source node collides with explicit output adapter')
            steps.append(Step(id=sid,unit_id=unit,op=op,implementation_version='2',input=method.output,
                params=params,evidence_indices=[0],parameter_sources={k:dict(origin='target_binding',evidence_indices=[],
                    rationale='Frozen common evaluation adapter; not a published value.') for k in params}))
            method.output=sid
        method.adaptations.append('Explicit common resample/epoch output adapter; immutable source method remains in method_ref.')
    evidence_ids=[]
    for e in method.evidence:
        key='source-'+digest(e.model_dump(mode='json'))[:24]
        value['evidence'][key]=e.model_dump(mode='json');evidence_ids.append(key)
    nodes=[];previous='raw'
    for s in steps:
        op, params, expanded=graph_operator(s,value)
        sources_={k:{'origin':p.origin,'rationale':p.rationale,
                      'evidence_ids':[evidence_ids[i] for i in p.evidence_indices]} for k,p in s.parameter_sources.items()}
        for k in expanded.keys()-s.params.keys():
            sources_[k]={'origin':'engineering','evidence_ids':[], 'rationale':'Expanded source implementation default; not a paper claim.'}
        nodes.append(dict(id=s.id,operator=op,parameters=params,input_from=s.input if s.input!=previous else None,
            model_from=s.model_from,decision_from=s.decision_from,fit_scope=s.fit_scope.model_dump() if s.fit_scope else None,
            optional=s.optional,graph=s.model_dump(mode='json'),trace=[{'method_ref':ref,'branch_id':method.lineage.get('branch_id'),
                'step_id':s.id,'evidence_ids':[evidence_ids[i] for i in s.evidence_indices],
                'parameters':expanded,'parameter_sources':sources_}]))
        previous=s.id
    identity='paper-'+digest([ref,method.lineage])[:24]
    value['methods'].append(dict(id=identity,title=method.title,origin='literature_adaptation' if method.evaluation_window else 'literature',
        recipe={'nodes':nodes,'output':method.output,'evaluation_window':method.evaluation_window.model_dump() if method.evaluation_window else None,
                'output_roles':method.output_roles},
        evidence_ids=evidence_ids,deviations=method.adaptations,lineage=[{**method.lineage,'method_ref':ref,'method_id':method.id,'version':method.version}],
        issues=[i.model_dump(mode='json') for i in method.issues]))
    return value,identity
