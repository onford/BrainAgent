"""Immutable step observations and explicit engineering shadow plans."""
import json
import math

from pydantic import Field

from .schemas import Contract, ExecutionPlan, MethodSpec, Step, ParameterSource
from .storage import canonical, digest, file_hash, within


def _exclusive_json(path, value):
    # A crashed/partial checkpoint is rejected, never repaired in place.
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(canonical(value))


def checkpoint(executor, step, original, packet, descriptor, log):
    import numpy as np
    from .graph_runtime import values
    x = values(packet.data)
    finite_count, count, maximum, square_sum = 0, 0, 0., 0.
    # Bounded work buffers; no sample/channel deletion or rank-based pass gate.
    for start in range(0, x.shape[-1], 16384):
        executor.check()
        part = x[..., start:start+16384]
        good = np.isfinite(part)
        finite_count += int(good.sum()); count += part.size
        if good.any():
            absolute = np.abs(part[good])
            current = float(absolute.max())
            if current > maximum:
                square_sum *= (maximum/current)**2
                maximum = current
            if maximum:
                square_sum += float(np.sum((absolute/maximum)**2))
    observed = dict(finite_fraction=finite_count/count if count else None,
        maximum_abs=maximum if count and finite_count==count else None,
        rms=maximum*math.sqrt(square_sum/count) if count and finite_count==count else None,
        event_retention=len(packet.event_indices)/len(original.event_indices) if len(original.event_indices) else None,
        channel_retention=x.shape[-2]/values(original.data).shape[-2])
    decisions = []
    for condition in step.postconditions:
        value = observed[condition.metric]
        satisfied = (value >= condition.threshold if condition.comparison=='ge' else value <= condition.threshold) if value is not None else None
        decisions.append(dict(policy=condition.model_dump(mode='json'), value=value,
            result='unavailable' if satisfied is None else 'satisfied' if satisfied else 'violated'))
    pause = any(d['result']!='satisfied' and d['policy']['on_failure']=='pause' for d in decisions)
    directory = executor.directory/step.id
    payload = dict(schema_version='step-checkpoint-1', record_id=executor.record.id if executor.record else None,
        step_id=step.id, step_contract_sha256=digest(step.model_dump(mode='json')),
        root_input_hash=executor.root_identity, input_hash=log['input_hash'], output_hash=log['output_hash'],
        graph_sha256=digest([s.model_dump(mode='json') for s in executor.steps.values()]),
        partition_scope=executor.partition_scope, state=log['state'],
        events=packet.events.tolist(), event_indices=packet.event_indices.tolist(), trial_ids=packet.trial_ids,
        reference=packet.reference, unit=packet.unit, artifact_descriptor=descriptor,
        model_binding=log['model_binding'], observations=observed,
        observation_units=dict(finite_fraction='ratio',maximum_abs=packet.unit,rms=packet.unit,
            event_retention='ratio_to_input_packet',channel_retention='ratio_to_input_packet'),
        postconditions=decisions, review_status='pause_required' if pause else 'observed',
        interpretation='Engineering conditions, not a scientific quality score or neural preservation certificate.',
        recovery_policy='Explicit new shared graph compilation and execution from original input; no cached fitted-state transplantation.')
    # Codec descriptors carry array/model hashes. Also bind every completed step
    # file, excluding execution.json: partition replay adds audit context to that
    # log after the numerical step, while checkpoint state remains immutable.
    payload['files'] = [{ 'path':p.relative_to(directory).as_posix(), 'sha256':file_hash(p), 'bytes':p.stat().st_size}
                        for p in sorted(directory.rglob('*')) if p.is_file() and p.name != 'execution.json']
    path = directory/'checkpoint.json'
    _exclusive_json(path,payload)
    return dict(path=path.name,sha256=file_hash(path),review_status=payload['review_status']), pause


def verify_checkpoint(path, expected_hash):
    if file_hash(path) != expected_hash:
        raise ValueError('step checkpoint checksum mismatch')
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('schema_version') != 'step-checkpoint-1':
        raise ValueError('unsupported step checkpoint version')
    files = value['files']
    if not files or len({a['path'] for a in files}) != len(files):
        raise ValueError('empty or duplicate checkpoint artifact inventory')
    for artifact in files:
        p = within(path.parent,artifact['path'])
        if p.stat().st_size != artifact['bytes'] or file_hash(p) != artifact['sha256']:
            raise ValueError('step checkpoint artifact changed')
    return value


def failure_artifacts(output, storage_root):
    return {'artifacts': [dict(name=p.relative_to(output).as_posix(),path=p.relative_to(storage_root).as_posix(),
        sha256=file_hash(p),bytes=p.stat().st_size,kind='stopped_attempt')
        for p in sorted(output.rglob('*')) if p.is_file() and not p.is_relative_to(output/'input')]}


def _anchor(service,status,record_key,path,step_id):
    row=next(r for r in status.records if r['key']==record_key)
    artifacts=(row.get('result') or {}).get('artifacts',[])
    refs=[a for a in artifacts if a['name']==step_id+'/checkpoint.json']
    if len(refs)!=1 or within(service.store.root,refs[0]['path'])!=path:
        raise ValueError('checkpoint lacks the immutable stopped-attempt receipt anchor')
    return refs[0]['sha256']


class ShadowRequest(Contract):
    record_key: str = Field(pattern='^[a-f0-9]{64}$')
    checkpoint_step: str = Field(pattern='^[a-z][a-z0-9_]*$')
    checkpoint_sha256: str = Field(pattern='^[a-f0-9]{64}$')
    replacement: Step
    reason: str = Field(min_length=1,max_length=4000)


def _job_checkpoint(service,owner,job_id,record_key,step_id):
    status = service.store.status(owner,job_id)
    row = next((r for r in status.records if r['key']==record_key),None)
    if row is None or row['status'] not in ('completed','waiting_decision','failed','cancelled','interrupted'):
        raise ValueError('review requires a stopped record attempt owned by this user')
    plan = ExecutionPlan.model_validate(service.store.get(owner,status.plan_ref,'plan'))
    indexed = [(i,r) for i,r in enumerate(plan.records) if r.record_id==row['record_id'] and r.method_ref.id==row['method_id']]
    if len(indexed)!=1 or row['attempt']<1:
        raise ValueError('ambiguous or unstarted reviewed record')
    index, config = indexed[0]
    if step_id not in {s.id for s in config.steps}:
        raise ValueError('review step is absent from the frozen plan')
    path = within(service.store.root,f'runs/{job_id}/r{index:04}/a{row["attempt"]}/{step_id}/checkpoint.json')
    return status,plan,config,path


def reviews(service,owner,job_id):
    status=service.store.status(owner,job_id)
    plan=ExecutionPlan.model_validate(service.store.get(owner,status.plan_ref,'plan'))
    records=[]
    for row in status.records:
        if row['status'] not in ('completed','waiting_decision','failed','cancelled','interrupted') or row['attempt']<1:
            continue
        configs=[r for r in plan.records if r.record_id==row['record_id'] and r.method_ref.id==row['method_id']]
        for step in configs[0].steps if len(configs)==1 else []:
            _,_,_,path=_job_checkpoint(service,owner,job_id,row['key'],step.id)
            if not path.exists():continue
            expected=_anchor(service,status,row['key'],path,step.id)
            value=verify_checkpoint(path,expected)
            records.append(dict(record_key=row['key'],record_id=row['record_id'],step_id=step.id,
                checkpoint_sha256=expected,review_status=value['review_status'],observations=value['observations'],
                observation_units=value['observation_units'],postconditions=value['postconditions']))
    return dict(parent_job_id=job_id,checkpoints=records,policy='Read-only observations; replacements are shared new plans, never per-subject recipes.')


def shadow_plan(service,owner,job_id,request):
    from .units import engine_hash,environment
    status,plan,config,path=_job_checkpoint(service,owner,job_id,request.record_key,request.checkpoint_step)
    if plan.engine_sha256!=engine_hash() or plan.environment!=environment():
        raise ValueError('implementation/environment changed; execute a new plan before using step review')
    observed=verify_checkpoint(path,request.checkpoint_sha256)
    if _anchor(service,status,request.record_key,path,request.checkpoint_step)!=request.checkpoint_sha256:
        raise ValueError('requested checkpoint differs from the stopped-attempt receipt')
    compiled=next(s for s in config.steps if s.id==request.checkpoint_step)
    if observed['record_id']!=config.record_id or observed['step_contract_sha256']!=digest(compiled.model_dump(mode='json')):
        raise ValueError('checkpoint does not bind the reviewed compiled step')
    if observed.get('partition_scope') is not None:
        raise ValueError('partition replay checkpoint cannot authorize a full-record shadow plan')
    if observed.get('graph_sha256')!=digest([s.model_dump(mode='json') for s in config.steps]):
        raise ValueError('checkpoint dependency graph differs from the frozen record plan')
    method=MethodSpec.model_validate(service.store.get(owner,config.method_ref,'method'))
    service.check_knowledge(owner,method)
    index=next(i for i,s in enumerate(method.recipe) if s.id==request.checkpoint_step)
    original=method.recipe[index]
    replacement=request.replacement.model_copy(deep=True)
    if replacement.id!=original.id or replacement.implementation_version!='2':
        raise ValueError('local replacement must preserve the reviewed node id and v2 graph contract')
    if replacement.record_decisions:
        raise ValueError('shadow replacement must be shared across the original record selection')
    # Review cannot silently relax its own predeclared stop criterion.
    if replacement.postconditions!=original.postconditions:
        raise ValueError('shadow replacement must retain the original postconditions')
    if replacement.model_dump(mode='json')==original.model_dump(mode='json'):
        raise ValueError('shadow plan requires an explicit changed operation or parameter')
    changed_operation=(replacement.unit_id,replacement.op,replacement.profile)!=(original.unit_id,original.op,original.profile)
    for key,value in replacement.params.items():
        if changed_operation or key not in original.params or value!=original.params[key]:
            replacement.parameter_sources[key]=ParameterSource(origin='engineering',evidence_indices=[],
                rationale='Explicit engineering shadow replacement: '+request.reason)
    method.recipe[index]=replacement
    method.status='draft';method.validation=[];method.validated_profiles=[]
    method.source='classic'
    method.title+=' [engineering shadow]'
    method.version+='-shadow-'+digest(request.model_dump(mode='json'))[:12]
    method.adaptations.append('Explicit engineering replacement of '+original.id+': '+request.reason)
    method.lineage={**method.lineage,'branch_kind':'engineering_step_replacement',
        'parent_method':config.method_ref.model_dump(),'parent_plan':status.plan_ref.model_dump(),
        'parent_job_id':job_id,'reviewed_record_id':config.record_id,'checkpoint_sha256':request.checkpoint_sha256,
        'original_step':original.model_dump(mode='json'),'replacement_step':replacement.model_dump(mode='json'),
        'reason':request.reason,'scope':'one_shared_graph_for_the_entire_original_input_selection',
        'recovery':'reexecute_from_original_input; cached fitted state is not reused'}
    service.check_knowledge(owner,method)
    ref=service.register_method(owner,method)
    new_request=plan.request.model_copy(deep=True)
    new_request.methods=[ref];new_request.selection='all';new_request.max_candidates=1
    if new_request.mode=='production':
        new_request.mode='exploratory'
    new_ref,resolved=service.plan(owner,new_request)
    expected=set(plan.input_snapshot.collection.selected_record_ids)
    if {r.record_id for r in resolved.records}!=expected or any(r.method_ref!=ref for r in resolved.records):
        raise ValueError('shadow compilation does not cover every originally selected record; inspect applicability and screening gaps')
    audit=service.store.put(owner,'step_review',dict(request=request.model_dump(mode='json'),parent_job_id=job_id,
        parent_plan_ref=status.plan_ref.model_dump(),new_plan_ref=new_ref.model_dump(),new_method_ref=ref.model_dump(),
        checkpoint_sha256=request.checkpoint_sha256,decision='compiled_shared_shadow_plan; not executed or promoted'))
    return dict(plan_ref=new_ref,plan=resolved,review_ref=audit,parent_job_id=job_id,
        execution_status='not_submitted',recovery='full shared reexecution from immutable original input')
