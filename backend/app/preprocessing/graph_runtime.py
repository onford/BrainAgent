"""V2 graph executor with explicit temporal/trial maps and bound model ports."""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import json
import shutil
import traceback
import numpy as np
import mne

from .artifact_codec import Codec, fingerprint, state
from .inputs import read_record, working_files
from .storage import within, file_hash, write_json, digest
from .units.operations_v2 import DEFINITIONS
from .units.contracts_v2 import invoke_source, dependency_status
from .native_process import native_scope


class PendingDecision(ValueError):
    code='WAITING_DECISION'


@dataclass
class Packet:
    data: object
    events: np.ndarray
    event_indices: np.ndarray
    trial_ids: list[str]
    reference: str
    unit: str='V'
    epoch_template: object=None


def values(x):
    return x if isinstance(x,np.ndarray) else x.get_data()


def identity(packet):
    return fingerprint([packet.data,packet.events,packet.event_indices,packet.trial_ids,packet.reference,packet.unit])


def packet_state(packet):
    result=state(packet.data,packet.unit)
    if isinstance(packet.data,np.ndarray):
        template=packet.epoch_template
        result.update(channels=list(template.ch_names),types=template.get_channel_types(),sfreq=float(template.info['sfreq']),channel_units={n:'V' for n in template.ch_names})
    result.update(reference=packet.reference,times_sha256=fingerprint(packet.data.times if hasattr(packet.data,'times') else packet.epoch_template.times))
    if isinstance(packet.data, mne.BaseEpochs):
        result['epoch_selection'] = packet.data.selection.tolist()
    return result


def quality(x):
    a=values(x);a=a if a.ndim==2 else a.transpose(1,0,2).reshape(a.shape[1],-1)
    finite=np.isfinite(a);valid_columns=finite.all(0)
    return {'finite_fraction':float(finite.mean()),'rank_on_finite_samples':int(np.linalg.matrix_rank(a[:,valid_columns])) if valid_columns.any() else None,
            'rms_per_channel':[float(np.sqrt(np.mean(row[mask]**2))) if mask.any() else None for row,mask in zip(a,finite)],
            'peak_to_peak_per_channel':[float(np.ptp(row[mask])) if mask.any() else None for row,mask in zip(a,finite)]}


def transition(packet,y,artifacts,spec,params,node_id=None):
    """Preserve original event row IDs through destructive operations."""
    out=deepcopy(packet);out.data=y
    effect=spec['effect'];x=packet.data
    if effect=='crop':
        keep=np.asarray(artifacts['event_keep'],bool)
        out.events=np.asarray(artifacts['events']);out.event_indices=packet.event_indices[keep]
    elif effect in ('crop_join','native_pipeline'):
        keep=np.asarray(artifacts['kept_event_indices'],int)
        out.events=np.asarray(artifacts['events']);out.event_indices=packet.event_indices[keep]
        if effect == 'native_pipeline':
            if (out.events.shape != (len(keep), 3) or len(set(keep.tolist())) != len(keep)
                or np.any(keep < 0) or np.any(keep >= len(packet.events))
                or not np.array_equal(out.events[:, 1:], packet.events[keep, 1:])):
                raise ValueError('native pipeline changed retained event identities')
    elif effect=='resample':
        if isinstance(y,mne.BaseEpochs):
            synchronized=y.events.copy()
        else:
            synchronized=np.asarray(artifacts.get('events',artifacts.get('events_nearest')))
        if synchronized.shape!=packet.events.shape or not np.array_equal(synchronized[:,1:],packet.events[:,1:]):raise ValueError('resampling changed event identity')
        out.events=synchronized
    elif effect=='epoch':
        chosen=np.asarray(y.selection,int)
        out.event_indices=packet.event_indices[chosen];out.events=y.events.copy()
    elif effect=='trials':
        # Source selection IDs are immutable within a lineage. Do not confuse
        # position after rejection with selection in the original event list.
        if len(set(x.selection.tolist()))!=len(x.selection):raise ValueError('ambiguous duplicate epoch selection IDs')
        positions={int(v):i for i,v in enumerate(x.selection)}
        keep=np.array([positions[int(v)] for v in y.selection],int)
        out.event_indices=packet.event_indices[keep];out.events=y.events.copy()
    else:
        if effect not in ('decimate','channels','reference_channels') and values(y).shape!=values(x).shape:raise ValueError('operation violated declared shape effect')
        if effect=='decimate' and (len(y)!=len(x) or y.ch_names!=x.ch_names or not np.array_equal(y.events,x.events)):raise ValueError('decimation changed trial/channel identity')
        if effect in ('channels','reference_channels') and (values(y).shape[-1]!=values(x).shape[-1] or (isinstance(x,mne.BaseEpochs) and not np.array_equal(x.events,y.events))):raise ValueError('channel removal changed time/trial identity')
    if effect in ('reference','reference_model','reference_channels','native_pipeline'):
        out.reference=artifacts.get('reference_id',params.get('reference_id','average' if params.get('ref_channels')=='average' else spec['op']))
        if node_id is not None:out.reference=node_id+':'+out.reference
    if effect=='csd':out.unit='V/m^2'
    if isinstance(y,mne.BaseEpochs):out.epoch_template=y
    out.trial_ids=[packet.trial_ids[list(packet.event_indices).index(i)] for i in out.event_indices]
    if len(out.events)!=len(out.event_indices) or len(out.trial_ids)!=len(out.events):raise ValueError('event/trial lineage length mismatch')
    a=values(y)
    allows_nan=(params.get('nonfinite')=='propagate' or spec['op'] in ('prep_detect','prep_detect_native','deviation_detect','correlation_detect','hf_ratio_detect','prep_reference_fit','epoch_with_nonfinite'))
    if not a.size or np.isinf(a).any() or (not allows_nan and not np.isfinite(a).all()):raise ValueError('output violates nonfinite policy')
    return out


class GraphExecutor:
    def __init__(self,record,steps,packet,directory,cancelled=lambda:False,assets=None,_partition_scope=None):
        self.record=record;self.steps={s.id:s for s in steps};self.root_packet=packet
        self.directory=Path(directory);self.cancelled=cancelled
        self.assets=assets or {}
        self.partition_scope = deepcopy(_partition_scope)
        self.nodes={'raw':{'packet':packet,'model':None,'artifacts':{}}};self.logs=[]

    def check(self):
        if self.cancelled():
            from .runner import Cancelled
            raise Cancelled('cancelled at graph step boundary')

    def runtime_params(self,step,packet,scope=None):
        x=packet.data;template=x if isinstance(x,mne.BaseEpochs) else packet.epoch_template
        bindings={'$events':packet.events.copy(),'$trial_ids':list(packet.trial_ids),'$reference_id':packet.reference,'$scope':scope,'$n_samples':values(x).shape[-1]}
        if template is not None:bindings.update({'$times':template.times.copy(),'$axes':list(template.ch_names)})
        result=deepcopy(step.params)
        for k,v in list(result.items()):
            if isinstance(v,str) and v.startswith('$'):
                if v not in bindings or bindings[v] is None:raise ValueError('unresolved runtime parameter: '+v)
                result[k]=bindings[v]
        for name,port in step.artifact_inputs.items():
            from .ports import port_value
            result[name]=port_value(port,self.nodes)
        from .ports import evaluate
        for name,expression in step.parameter_inputs.items():result[name]=evaluate(expression,self.nodes)
        for name,ref in step.asset_inputs.items():result[name]=deepcopy(self.assets[ref.id])
        # Source contracts describe sequence parameters; normalize array-valued
        # diagnostic ports to those sequences, retaining order and scalar types.
        from .units.contracts_v2 import parameter_schema
        fields=parameter_schema(DEFINITIONS[(step.unit_id,step.op)])['properties']
        for name,value in result.items():
            field_type=fields[name]['type']
            if isinstance(value,np.ndarray) and ('array'==field_type or isinstance(field_type,list) and 'array' in field_type):result[name]=value.tolist()
        if isinstance(x,mne.BaseEpochs) and step.op.startswith('resample'):result['events']=None
        return result

    def scoped_packet(self,step):
        if self.partition_scope is not None:
            packet = deepcopy(self.nodes[step.input]['packet'])
            scope = deepcopy(self.partition_scope)
            if isinstance(packet.data, mne.BaseEpochs):
                scope['ids'] = list(packet.trial_ids)
            return packet, scope
        if step.adaptation_scope=='record_unlabeled':
            # Explicit record adaptation fits the selected, already processed
            # data branch. Never refit or replay upstream model/decision nodes.
            packet=deepcopy(self.nodes[step.input]['packet'])
            scope={'role':'calibration','ids':list(packet.trial_ids) if isinstance(packet.data,mne.BaseEpochs) else [self.record.id+':'+step.input+':record_unlabeled']}
            return packet,scope
        raise ValueError('partition fits require an isolated dependency executor')

    def partition_fit(self, step):
        from .graph_partition import replay_ancestors
        ancestors = replay_ancestors(step, list(self.steps.values()))
        packet=deepcopy(self.root_packet)
        if not step.fit_scope or len(step.fit_scope.ids) != 1:
            raise ValueError('partition fit requires one explicit calibration/train interval')
        part=next(p for p in self.record.intervals if p.id==step.fit_scope.ids[0])
        if part.role not in ('train', 'calibration') or part.role != step.fit_scope.role:
            raise ValueError('partition fit cannot consume a test or incompatible interval')
        raw=packet.data;lo=raw.first_samp+part.start;hi=raw.first_samp+part.stop
        keep=(packet.events[:,0]>=lo)&(packet.events[:,0]<hi)
        packet.events=packet.events[keep];packet.event_indices=packet.event_indices[keep]
        packet.trial_ids=[v for v,k in zip(packet.trial_ids,keep) if k]
        packet.data=raw.copy().crop(part.start/self.record.sfreq,(part.stop-1)/self.record.sfreq)
        scope={'role':part.role,'ids':[part.id]}
        folder = self.directory / ('fit-replay-' + step.id)
        folder.mkdir(parents=True, exist_ok=False)
        context = dict(policy='isolated-partition-dependency-replay-v1', target_step=step.id,
            partition=dict(id=part.id, role=part.role, start=part.start, stop=part.stop),
            root_input_hash=identity(packet), ancestor_step_ids=[s.id for s in ancestors],
            external_fitted_state_reused=False)
        write_json(folder/'context.json', context)
        child = GraphExecutor(self.record, ancestors + [step], packet, folder, self.cancelled,
            assets=self.assets, _partition_scope=scope)
        for ancestor in ancestors:
            child.execute(ancestor)
            log = child.logs[-1]
            log.update(branch='fit_replay', replay_target=step.id, replay_context=context)
            self.logs.append(deepcopy(log))
            write_json(folder/ancestor.id/'execution.json', log)
        # Keep the target's normal artifact path. Every dependency is resolved
        # against the isolated child nodes, including diagnostic parameter ports.
        child.directory = self.directory
        out = child.execute(step)
        log = child.logs[-1]
        original = self.nodes[step.input]['packet']
        removed = {r['event_index']: r for r in log['removed_events']}
        for index, trial in zip(original.event_indices, original.trial_ids):
            if index not in out.event_indices and int(index) not in removed:
                removed[int(index)] = dict(event_index=int(index), trial_id=trial, reasons=['FIT_SCOPE_SELECTION'])
        log.update(removed_events=list(removed.values()), partition_replay=context)
        self.nodes[step.id] = child.nodes[step.id]
        self.logs.append(log)
        write_json(self.directory/step.id/'execution.json', log)
        return out

    def execute(self,step):
        self.check();spec=DEFINITIONS[(step.unit_id,step.op)]
        if spec['fit'] and self.partition_scope is None and step.adaptation_scope != 'record_unlabeled':
            return self.partition_fit(step)
        original=self.nodes[step.input]['packet'];packet=deepcopy(original);scope=None
        if spec['fit']:packet,scope=self.scoped_packet(step)
        if step.input_channels is not None:packet.data.pick(step.input_channels)
        if step.input_representation=='array':
            packet.epoch_template=packet.data;packet.data=packet.data.get_data().copy()
        params=self.runtime_params(step,packet,scope)
        if step.op=='asr_fit':
            # Source interval is relative to the scoped Raw, never the full record.
            if params['start']!=0 or params['stop']!=packet.data.n_times:raise ValueError('ASR start/stop must cover the actual selected calibration packet')
        model=None;model_hash=None
        if step.model_from:
            node=self.nodes[step.model_from];binding=node['binding']
            if fingerprint(node['model'])!=binding['model_hash']:raise ValueError('model changed after fitting')
            for field,actual in [('channels',getattr(packet.data,'ch_names',list(packet.epoch_template.ch_names) if packet.epoch_template is not None else [])),('reference',packet.reference)]:
                if binding[field]!=actual:raise ValueError('model binding mismatch: '+field)
            info=packet.data.info if hasattr(packet.data,'info') else packet.epoch_template.info
            for field,actual in [('sfreq',float(info['sfreq'])),('bads',list(info['bads'])),('projection_hash',fingerprint(info['projs']))]:
                if field in binding and binding[field]!=actual:raise ValueError('model binding mismatch: '+field)
            if spec['same_data'] and binding['application_input_hash']!=identity(packet):raise ValueError('model requires its exact bound data version')
            model=deepcopy(node['model']);model_hash=binding['model_hash']
        before=identity(packet);directory=self.directory/step.id;directory.mkdir(parents=True)
        codec=Codec(directory)
        if step.op=='sasica_assess' and params.get('external_assessments'):
            from .ports import sources
            refs=list(sources(step.parameter_inputs['external_assessments'])) if 'external_assessments' in step.parameter_inputs else [step.artifact_inputs['external_assessments']] if 'external_assessments' in step.artifact_inputs else []
            if not refs:raise ValueError('external assessments require data/model-bound diagnostic ports')
            for ref in refs:
                origin=self.nodes[ref.step]
                if origin.get('input_hash')!=before or origin.get('model_hash')!=model_hash:raise ValueError('external assessment data/model binding mismatch')
        if spec['decision']:
            policy=step.decision
            if policy.mode=='manual':
                if policy.status!='confirmed' or policy.input_sha256!=before or policy.model_sha256!=model_hash:
                    write_json(directory/'pending-decision.json',dict(input_sha256=before,model_sha256=model_hash,step_id=step.id,reason=policy.reason,parameters=codec.dump(params)))
                    raise PendingDecision('manual decision must confirm the current input and model hashes')
            else:
                detected=self.nodes[step.decision_from]
                decision_hash=identity(detected['packet']) if step.decision_target=='output' else detected['input_hash']
                diagnostic_model=detected['binding']['model_hash'] if detected.get('binding') else detected.get('model_hash')
                if decision_hash!=before or diagnostic_model!=model_hash:raise ValueError('decision refers to different data/model')
                # Numeric masks/exclusions must originate in this bound diagnostic.
                decision_fields={k for k in ('bads','exclude','mask','reject_mask','keep_intervals','bridged_idx','bad_channels','channels','confirmed_bad_channels','repaired_channels','annotations','probabilities','component_id','eye_weights','extra_eye') if k in params and params[k] is not None}
                from .ports import sources
                if not decision_fields:raise ValueError('automatic decision has no diagnostic fields')
                for key in decision_fields:
                    refs=[step.artifact_inputs[key]] if key in step.artifact_inputs else list(sources(step.parameter_inputs[key])) if key in step.parameter_inputs else []
                    if not refs:raise ValueError('automatic decisions require bound diagnostic parameter ports')
                    for ref in refs:
                        origin=self.nodes[ref.step]
                        bound_hash=identity(origin['packet']) if step.decision_target=='output' else origin['input_hash']
                        origin_model=origin['binding']['model_hash'] if origin.get('binding') else origin.get('model_hash')
                        if bound_hash!=before or origin_model!=model_hash:raise ValueError('constructed decision field refers to another data/model version')
            params.setdefault('decision_id',digest([step.id,before,model_hash,policy.model_dump()])) if 'decision_id' in spec['required'] else None
            write_json(directory/'decision.json',{'policy':policy.model_dump(),'input_sha256':before,'model_sha256':model_hash})
        missing=dependency_status(spec,params)
        if missing:raise ValueError('dependency_missing: '+str(missing))
        with native_scope(self.cancelled, directory):
            result=invoke_source(step.unit_id,step.op,packet.data,model=model,**params)
        if identity(packet)!=before:raise ValueError('source operation mutated its input')
        y=result['data'];artifacts=result.get('artifacts',{})
        out=transition(packet,y,artifacts,spec,params,node_id=step.id)
        saved=codec.verified_dump({'data':y,'model':result.get('model'),'artifacts':artifacts})
        write_json(directory/'artifacts.json',saved)
        restored=codec.load(saved)
        binding=None
        if spec['effect'] in ('model','reference_model'):
            template=packet.epoch_template
            binding=dict(model_hash=fingerprint(restored['model']),input_hash=before,
                application_input_hash=identity(out) if spec['effect']=='reference_model' else before,
                channels=list(y.ch_names) if hasattr(y,'ch_names') else list(template.ch_names),
                reference=out.reference if spec['effect']=='reference_model' else packet.reference,
                scope=scope,adaptation_scope=step.adaptation_scope,record_id=self.record.id if self.record else None,
                sfreq=float(y.info['sfreq']) if hasattr(y,'info') else float(template.info['sfreq']),
                bads=list(y.info['bads']) if hasattr(y,'info') else list(template.info['bads']),
                projection_hash=fingerprint(y.info['projs'] if hasattr(y,'info') else template.info['projs']))
            write_json(directory/'model-binding.json',binding)
        node=dict(packet=out,model=restored['model'],artifacts=restored['artifacts'],binding=binding,input_hash=before,model_hash=model_hash)
        self.nodes[step.id]=node
        removed=[]
        for position,event_index in enumerate(original.event_indices):
            if event_index in out.event_indices:continue
            reason=['FIT_SCOPE_SELECTION'] if spec['fit'] else ['OUTSIDE_RETAINED_INTERVAL'] if spec['effect'] in ('crop','crop_join') else ['REMOVED_BY_'+step.op]
            if isinstance(y,mne.BaseEpochs):
                selection=position if spec['effect']=='epoch' else int(packet.data.selection[position]) if isinstance(packet.data,mne.BaseEpochs) and position<len(packet.data) else None
                if selection is not None and selection<len(y.drop_log) and y.drop_log[selection]:reason=list(y.drop_log[selection])
            removed.append({'event_index':int(event_index),'trial_id':original.trial_ids[position],'reasons':reason})
        log=dict(step_id=step.id,unit_id=step.unit_id,op=step.op,profile=step.profile,
            step_contract=step.model_dump(mode='json'),
            implementation_version='2',branch='main',parameters=codec.dump(params),
            input_hash=before,output_hash=identity(out),state=packet_state(out),scope=scope,removed_events=removed,
            adaptation_scope=step.adaptation_scope,model_binding=binding,
            event_indices=out.event_indices.tolist(),trial_ids=out.trial_ids,
            channel_mapping={n:(getattr(y,'ch_names',[]).index(n) if n in getattr(y,'ch_names',[]) else None) for n in getattr(packet.data,'ch_names',[])})
        self.logs.append(log);write_json(directory/'execution.json',log)
        return out


def run_graph_record(plan,config,source_root,output,storage_root,cancelled):
    record=next(r for r in plan.input_snapshot.collection.records if r.id==config.record_id)
    output.mkdir(parents=True,exist_ok=False);work=output/'input';executor=None
    try:
        from .assets import verify_native
        verify_native(config.native_files)
        for relative,expected in working_files(record).items():
            src=within(source_root,relative);dst=within(work,relative)
            if file_hash(src)!=expected:raise ValueError('source changed before copy')
            dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
            if file_hash(dst)!=expected:raise ValueError('working copy hash mismatch')
        raw,events,event_map=read_record(work,record,plan.input_snapshot.survey.event_id,plan.input_snapshot.survey.context_event_id)
        packet=Packet(raw,events,np.arange(len(events)),[r['trial_id'] for r in event_map],record.reference)
        from .assets import load as load_asset
        assets={key:load_asset(storage_root,snapshot) for key,snapshot in config.asset_snapshots.items()}
        executor=GraphExecutor(record,config.steps,packet,output,cancelled,assets=assets)
        for step in config.steps:executor.execute(step)
        final=executor.nodes[config.output]['packet']
        for role,node in config.output_roles.items():
            if node not in executor.nodes or not role.replace('_','').isalnum():raise ValueError('invalid declared output role')
            role_codec=Codec(output/'outputs'/role)
            write_json(output/'outputs'/role/'data.json',role_codec.verified_dump(executor.nodes[node]['packet'].data))
        if config.evaluation_window:
            from .scoring_window import project
            final, source, adaptation = project(executor, config.output, config.evaluation_window)
            original_codec=Codec(output/'source-output')
            write_json(output/'source-output'/'data.json',original_codec.verified_dump(source.data))
            write_json(output/'evaluation-adapter.json',adaptation)
        codec=Codec(output/'final')
        saved=codec.verified_dump(final.data);write_json(output/'final'/'data.json',saved)
        axes={'state':packet_state(final),'events':final.events.tolist(),'event_indices':final.event_indices.tolist(),'trial_ids':final.trial_ids,
              'times':(final.data.times if hasattr(final.data,'times') else final.epoch_template.times).tolist()}
        write_json(output/'axes.json',axes)
        np.save(output/('signal_V.npy' if final.unit=='V' else 'signal.npy'),values(final.data),allow_pickle=False)
        retained={int(v):i for i,v in enumerate(final.event_indices)}
        data_lineage=set();cursor=config.output
        while cursor!='raw':data_lineage.add(cursor);cursor=executor.steps[cursor].input
        continuous_raw = None
        epoch_steps = [s for s in config.steps if s.id in data_lineage and DEFINITIONS[(s.unit_id,s.op)]['effect']=='epoch']
        event_samples = {int(i):int(e[0]) for i,e in zip(final.event_indices, final.events)}
        if isinstance(final.data, mne.BaseEpochs) and final.unit == 'V':
            final.data.save(output/'data-epo.fif',fmt='double',overwrite=False,verbose='ERROR')
        if len(epoch_steps)==1:
            epoch=epoch_steps[0];continuous=executor.nodes[epoch.input]['packet']
            event_samples.update({int(i):int(e[0]) for i,e in zip(continuous.event_indices,continuous.events)})
            if isinstance(continuous.data,mne.io.BaseRaw) and continuous.unit=='V':
                path=output/'continuous-raw.fif';continuous.data.save(path,fmt='double',overwrite=False,verbose='ERROR')
                chain=[];cursor=config.output
                while cursor!='raw':chain.append(cursor);cursor=executor.steps[cursor].input
                chain.reverse();position=chain.index(epoch.id)
                epoch_log=next(l for l in executor.logs if l['step_id']==epoch.id)
                continuous_raw=dict(file=path.name,path=path.relative_to(storage_root).as_posix(),sha256=file_hash(path),bytes=path.stat().st_size,
                    before_epoch_step_id=epoch.id,source_node_id=epoch.input,unit='V',sfreq=float(continuous.data.info['sfreq']),
                    channels=continuous.data.ch_names,first_sample=int(continuous.data.first_samp),source_data_hash=epoch_log['input_hash'],
                    target_events=continuous.events.tolist(),pre_epoch_step_ids=chain[:position],post_epoch_step_ids=chain[position+1:],
                    post_epoch_steps=[executor.steps[n].model_dump(mode='json') for n in chain[position+1:]],post_epoch_operations_applied=False)
        removals={}
        for log in executor.logs:
            if log['step_id'] not in data_lineage or log['branch']!='main':continue
            for entry in log.get('removed_events',[]):removals.setdefault(entry['event_index'],[]).append({'step_id':log['step_id'],**entry})
        mapped=[]
        for i,row in enumerate(event_map):
            j=retained.get(i)
            mapped.append({**row,'retained':j is not None,'output_index':j,
                'output_sample':event_samples.get(i), 'epoch_index':j if isinstance(final.data,mne.BaseEpochs) else None,
                'output_sfreq':float(final.data.info['sfreq']) if hasattr(final.data,'info') else None,
                'reason':[] if j is not None else list(dict.fromkeys(reason for item in removals.get(i,[]) for reason in item['reasons'])),
                'mapping_steps':[entry['step_id'] for entry in removals.get(i,[])]})
        delta=dict(before=packet_state(packet),after=packet_state(final),quality_before=quality(raw),quality_after=quality(final.data),events_before=len(events),events_retained=len(retained),
            channels_removed=sorted(set(raw.ch_names)-set(getattr(final.data,'ch_names',raw.ch_names))),
            trials_before=len(event_map),trials_fully_retained=len(retained))
        write_json(output/'events.json',mapped);write_json(output/'delta.json',delta)
        write_json(output/'provenance.json',dict(schema_version='2',steps=executor.logs,environment=plan.environment,engine_sha256=plan.engine_sha256,method_ref=config.method_ref.model_dump(),input_ref=plan.request.input_ref.model_dump(),mode=plan.request.mode,continuous_raw=continuous_raw,native_dependencies=config.native_files,scientific_assets=config.asset_snapshots))
        verify_native(config.native_files)
        for relative,expected in working_files(record).items():
            if file_hash(within(source_root,relative))!=expected:raise ValueError('source changed during processing')
        artifacts=[dict(name=p.relative_to(output).as_posix(),path=p.relative_to(storage_root).as_posix(),sha256=file_hash(p),bytes=p.stat().st_size,kind='data' if p.name=='data.json' else 'provenance') for p in sorted(output.rglob('*')) if p.is_file() and not p.is_relative_to(work)]
        result=dict(schema_version='2',artifacts=artifacts,delta=delta,source_unchanged=True,mode=plan.request.mode,
            final_descriptor=(output/'final'/'data.json').relative_to(storage_root).as_posix(),final_hash=fingerprint(final.data))
        if not verify_graph_result(storage_root,result):raise ValueError('graph final verification failed')
        return result
    except BaseException as exc:
        write_json(output/'failure.json',dict(schema_version='2',completed_steps=executor.logs if executor else [],error=traceback.format_exc(),failure_code=getattr(exc,'code',type(exc).__name__)))
        raise


def verify_graph_result(root,result):
    try:
        entries=result['artifacts']
        if not entries or len({a['path'] for a in entries})!=len(entries):return False
        for a in entries:
            if file_hash(within(root,a['path']))!=a['sha256']:return False
        descriptor=within(root,result['final_descriptor'])
        if result['final_descriptor'] not in {a['path'] for a in entries}:return False
        x=Codec(descriptor.parent).load(json.loads(descriptor.read_text(encoding='utf-8')))
        if fingerprint(x)!=result['final_hash'] or list(values(x).shape)!=result['delta']['after']['shape']:return False
        directory=descriptor.parent.parent
        for name in ['events.json','delta.json','provenance.json','axes.json']:
            if (directory/name).relative_to(root).as_posix() not in {a['path'] for a in entries}:return False
        events=json.loads((directory/'events.json').read_text(encoding='utf-8'))
        delta=json.loads((directory/'delta.json').read_text(encoding='utf-8'))
        axes=json.loads((directory/'axes.json').read_text(encoding='utf-8'))
        signal_path=directory/('signal_V.npy' if axes['state']['unit']=='V' else 'signal.npy')
        if signal_path.relative_to(root).as_posix() not in {a['path'] for a in entries} or not np.array_equal(np.load(signal_path,allow_pickle=False),values(x),equal_nan=True):return False
        if delta!=result['delta'] or len(axes['times'])!=values(x).shape[-1] or len(set(axes['trial_ids']))!=len(axes['trial_ids']):return False
        if len(axes['events'])!=len(axes['trial_ids']) or len(axes['event_indices'])!=len(axes['trial_ids']):return False
        if isinstance(x,mne.BaseEpochs) and not np.array_equal(x.events,axes['events']):return False
        return len(events)==result['delta']['events_before'] and sum(e['retained'] for e in events)==result['delta']['events_retained'] and len(axes['trial_ids'])==result['delta']['events_retained']
    except (ValueError,KeyError,TypeError,OSError,ImportError):return False
