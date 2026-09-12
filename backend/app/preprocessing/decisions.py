"""A human confirmation creates a new immutable method and execution plan."""
import json
from pydantic import Field
from .schemas import Contract, DecisionPolicy, ExecutionPlan, MethodSpec


class Confirmation(Contract):
    record_key:str
    step_id:str
    input_sha256:str=Field(pattern='^[a-f0-9]{64}$')
    model_sha256:str|None=Field(default=None,pattern='^[a-f0-9]{64}$')
    reason:str=Field(min_length=1,max_length=4000)


class Confirmations(Contract):
    confirmations:list[Confirmation]=Field(min_length=1)


def pending(service,owner,job_id):
    status=service.store.status(owner,job_id);out=[]
    for record in status.records:
        if record['status']!='waiting_decision':continue
        for artifact in record['result']['artifacts']:
            if artifact['name'].endswith('/pending-decision.json'):
                path=service.store.artifact(owner,job_id,record['key'],artifact['name'])
                value=json.loads(path.read_text(encoding='utf-8'))
                out.append({**value,'record_key':record['key'],'record_id':record['record_id'],'method_id':record['method_id']})
    return out


def confirm(service,owner,job_id,request):
    from .units import engine_hash,environment
    status=service.store.status(owner,job_id)
    plan=ExecutionPlan.model_validate(service.store.get(owner,status.plan_ref,'plan'))
    if plan.engine_sha256!=engine_hash() or plan.environment!=environment():raise ValueError('implementation/environment changed; run a new plan before reviewing decisions')
    observed={(p['record_key'],p['step_id']):p for p in pending(service,owner,job_id)}
    updates={}
    for confirmation in request.confirmations:
        key=(confirmation.record_key,confirmation.step_id)
        if key not in observed or key in updates:raise ValueError('unknown or duplicate pending decision')
        receipt=observed[key]
        if receipt['input_sha256']!=confirmation.input_sha256 or receipt['model_sha256']!=confirmation.model_sha256:raise ValueError('confirmation does not match observed data and model')
        updates[key]=(receipt,confirmation)
    refs=[]
    for original_ref in plan.request.methods:
        method=MethodSpec.model_validate(service.store.get(owner,original_ref,'method'))
        relevant=[(r,c) for r,c in updates.values() if r['method_id']==original_ref.id]
        if not relevant:refs.append(original_ref);continue
        method.status='draft';method.validation=[];method.validated_profiles=[]
        for receipt,c in relevant:
            step=next(s for s in method.recipe if s.id==c.step_id)
            step.record_decisions[receipt['record_id']]=DecisionPolicy(mode='manual',status='confirmed',reason=c.reason,input_sha256=c.input_sha256,model_sha256=c.model_sha256)
        method.lineage={**method.lineage,'decision_parent_method':original_ref.model_dump(),'decision_parent_plan':status.plan_ref.model_dump(),'decision_job':job_id}
        refs.append(service.register_method(owner,method))
    new_request=plan.request.model_copy(deep=True);new_request.methods=refs
    ref,resolved=service.plan(owner,new_request)
    return {'plan_ref':ref,'plan':resolved,'confirmed_count':len(updates),'parent_job_id':job_id}
