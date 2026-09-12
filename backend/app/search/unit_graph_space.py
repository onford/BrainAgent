"""Bounded operation-graph search compiled to the common preprocessing engine.

Numerical domains below are engineering search bounds, not literature claims.
Assets, fitted state, masks, trial labels, fit scopes and decisions are never
search parameters. A candidate must still pass per-record graph compilation.
"""
from copy import deepcopy
from itertools import product
from pydantic import Field
from app.preprocessing.schemas import Contract, MethodSpec, Ref, PlanRequest
from app.preprocessing.units.operations_v2 import inventory, DEFINITIONS
from app.preprocessing.units.contracts_v2 import validate_parameters
from app.preprocessing.storage import digest


DOMAINS={
 'crop':{},'detrend':{},
 'filter':{'l_freq':[.5,1.,2.,4.,8.],'h_freq':[30.,40.,75.,100.]},
 'butter':{'prototype_order':[2,4,6],'l_freq':[.5,1.,2.,4.,8.],'h_freq':[30.,40.,75.,100.]},
 'spectrum_fit':{'mt_bandwidth':[1.,2.,4.]},
 'cleanline':{'bandwidth':[1.,2.,4.],'window_seconds':[4.,8.,10.],'step_seconds':[2.,4.],'max_iterations':[1,5,10]},
 'resample':{'sfreq':[128.,160.,200.,250.,256.]},
 'resample_fft':{'sfreq':[128.,160.,200.,250.,256.]},
 'resample_fir':{'sfreq':[128.,160.,200.,250.,256.]},
 'resample_eeglab':{'sfreq':[128.,160.,200.,250.,256.],'cutoff':[.8,.9,.95],'transition':[.05,.1,.2]},
 'decimate':{'decim':[1,2,4]},
 'csd':{'lambda2':[1e-6,1e-5,1e-4],'stiffness':[3.,4.,5.],'n_legendre_terms':[30,50]},
 'lof_detect':{'n_neighbors':[5,10,20],'threshold':[1.2,1.5,2.]},
 'amplitude_detect':{'bad_percent':[5.,10.,20.],'min_duration':[.005,.01,.02]},
 'flat_detect':{'max_flatline_duration':[1.,3.,5.]},
 'amplitude_windows':{'window_s':[.5,1.,2.],'stride_s':[.25,.5,1.],'peak_to_peak_limit_V':[100e-6,150e-6,200e-6],'frac_bad':[.1,.25,.5]},
 'absolute_voltage':{'limit_V':[.0002,.0005,.001]},
 'muscle_detect':{'threshold':[3.,4.,5.],'min_length_good':[.1,.2,.5]},
 'ica_fit':{'max_iter':[500,1000,2000],'seed':[0,42]},
 'eog_assess':{'threshold':[2.,3.,4.]},'ecg_assess':{'threshold':['auto']},
 'muscle_assess':{'threshold':[.3,.5,.7]},
 'bridge_detect':{'lm_cutoff':[8.,16.,24.],'epoch_threshold':[.3,.5,.7]},
 'interpolate':{'max_fraction':[.05,.1,.2]},'spherical':{'regularization':[1e-6,1e-5,1e-4],'max_fraction':[.05,.1,.2]},
 'trial_interpolate':{'max_fraction':[.05,.1,.2]},
 'reject_trials':{'max_fraction':[.1,.25,.5]},
 'zapline_plus':{'sigma':[2.,3.,4.],'adaptive_sigma':[False,True],'chunk_seconds':[0,20,30]},
 'deviation_detect':{'deviation_threshold':[3.,5.,7.]},
 'correlation_detect':{'correlation_threshold':[.3,.4,.5],'frac_bad':[.01,.05,.1]},
 'hf_ratio_detect':{'HF_zscore_threshold':[3.,5.,7.]},
 'line_noise_detect':{'ratio_threshold':[3.,5.,10.],'frac_bad':[.1,.25,.5]},
 'faster_ic_assess':{'threshold':[2.,3.,4.]},
 'asr_fit':{'cutoff':[10.,20.,30.],'blocksize':[50,100,200]},
 'asr_apply':{'maxdims':[.33,.5,.66],'stepsize':[16,32,64]},
 'cca_fit':{'lags':[1,2,3]},
 'mwf_fit':{'delay':[0,1,2],'delay_spacing':[1,2],'mu':[1.,2.,3.]},
 'autoreject_fit':{'seed':[0,42]},
 'window_mad':{'mad_multiplier':[15.,25.,35.],'flat_limit_V':[1e-6,2e-6,5e-6]},
 'blink_upper_bound':{'mad_multiplier':[5.,10.,15.],'fallback_percentile':[70.,80.,90.]},
 'spectral_slope':{'slope_threshold':[-.5,-.31,0.]},
 'eog_step':{'threshold_V':[16e-6,32e-6,64e-6]},
 'joint_probability':{'local_threshold':[3.,5.,10.],'global_threshold':[3.,5.,10.]},
 'kurtosis':{'local_threshold':[3.,5.,10.],'global_threshold':[3.,5.,10.]},
 'blink_iqr':{'lowpass_Hz':[6.,25.]},
 'prep_reference_fit':{'max_iterations':[2,4,6]},
 'relax_budget':{'maximum':[.05,.1,.2]},'relax_muscle_trials':{'maximum':[.25,.5]},
 'detect_bad_channels':{'deviation_z':[3.,5.,7.],'correlation_threshold':[.3,.4,.5]},
 'interpolate_bad_channels':{'max_fraction':[.05,.1,.2]},
 'asr_clean':{'cutoff':[10.,20.,30.],'min_clean_seconds':[30.,45.]},
}


def operation_space():
    return {'schema_version':'unit_graph_v2','max_candidates':32,'operators':[
        {k:r[k] for k in ('identity','unit_id','op','profile','input_kind','effect','fit','decision','model_kind','dependencies','assets')}
        | {'domains':{k:{'kind':'choice','choices':v,'origin':'engineering','rationale':'有限工程候选；逐记录源码合同仍须检查'} for k,v in DOMAINS.get(r['op'],{}).items() if k not in r['profile_parameters']},
           'conditions':r['source']['source']['fields']['输入合同'],
           'combination_constraints':['typed topological data/model/diagnostic ports','same data/model for decisions','explicit train/calibration or record_unlabeled scope','per-record event/channel/time mapping checks'],
           'fixed_panel_compatible':False if r['effect'] in ('crop','crop_join','trials','channels','reference_channels','csd') else None}
        for r in inventory()]}


class GraphSweep(Contract):
    input_ref:Ref
    method:MethodSpec
    grid:dict[str,list[object]]=Field(default_factory=dict)
    max_candidates:int=Field(default=16,ge=1,le=32)
    mode:str=Field(default='exploratory',pattern='^(exploratory|validation)$')


def candidates(method,grid,max_candidates=16):
    if any(s.implementation_version!='2' for s in method.recipe):raise ValueError('graph search requires version 2 steps')
    by_id={s.id:s for s in method.recipe};domains={r['identity']:r['domains'] for r in operation_space()['operators']}
    options=[];fields=[];count=1
    for field,choices in grid.items():
        parts=field.split('.')
        if len(parts)!=2 or parts[0] not in by_id:raise ValueError('grid key must be existing step.parameter')
        step=by_id[parts[0]];spec=DEFINITIONS[(step.unit_id,step.op)]
        allowed=DOMAINS.get(step.op,{}).get(parts[1])
        profile_params=next((r['profile_parameters'] for r in inventory() if r['identity']=='/'.join((step.unit_id,step.op,step.profile))),{})
        if allowed is None or parts[1] in profile_params or parts[1] in (step.artifact_inputs.keys()|step.parameter_inputs.keys()|step.asset_inputs.keys()):raise ValueError('parameter is fixed or not in a declared search domain: '+field)
        if not choices or len({digest(v) for v in choices})!=len(choices) or any(not any((type(v) is type(a) or type(v) in (int,float) and type(a) in (int,float)) and v==a for a in allowed) for v in choices):raise ValueError('search values outside finite domain: '+field)
        count*=len(choices)
        if count>max_candidates:raise ValueError('candidate product exceeds explicit budget')
        options.append(choices);fields.append(parts)
    result=[]
    for values in product(*options):
        candidate=method.model_copy(deep=True);steps={s.id:s for s in candidate.recipe}
        changes={}
        for (sid,key),value in zip(fields,values):steps[sid].params[key]=value;changes[sid+'.'+key]=value
        # Record data facts remain unresolved until Planner binds each record.
        for step in candidate.recipe:
            if not any(isinstance(v,str) and v.startswith('$') and v not in ('$scope','$reference_id','$events','$times','$axes','$trial_ids') for v in step.params.values()):
                validate_parameters(step.unit_id,step.op,step.params,step.profile,step.artifact_inputs.keys()|step.parameter_inputs.keys()|step.asset_inputs.keys())
        candidate.id='graph-'+digest([method.model_dump(),changes])[:24]
        candidate.lineage={**candidate.lineage,'kind':'unit_graph_search','parent_method':method.id,'edits':changes,'space_sha256':digest(operation_space())}
        candidate.adaptations.append('有界工程参数搜索；保留来源算法、拟合范围、产物绑定和未完成的人工决定。')
        result.append(candidate)
    return result


def plan_sweep(service,owner,request):
    methods=candidates(request.method,request.grid,request.max_candidates)
    refs=[service.register_method(owner,m) for m in methods]
    ref,plan=service.plan(owner,PlanRequest(input_ref=request.input_ref,methods=refs,selection='all',max_candidates=request.max_candidates,mode=request.mode))
    return {'plan_ref':ref,'plan':plan,'method_refs':refs,'candidate_count':len(methods),'space_sha256':digest(operation_space())}
