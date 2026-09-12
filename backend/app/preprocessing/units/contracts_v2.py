"""Closed, JSON-safe parameter contracts and source-bound dispatch for v2."""
from copy import deepcopy
from importlib import import_module, metadata
import math
from pathlib import Path
import shutil

from .operations_v2 import DEFINITIONS, profiles

STRINGS = set('adaptation_scope annotation_policy backend ch_name channel_decision_id clean_other component_id decision_id direction estimator fir_design fir_window kind mask_id measure method metric mode nonfinite octave octave_path on_insufficient_calibration phase profile reason reference_id reference_role retained_bandwidth_policy selection_policy source_profile source_root statistic tail tail_policy thresh_method treatnans type variant'.split())
LISTS = set('axes background_bands_Hz bad_channels bads baseline blink_channels blink_upper_bound_V bridged_idx channel_epoch_mask confirmed_bad_channels consensus donors event_id_dummy events exclude excluded_bands_Hz extra_eye eye_components eye_weights factor_names factors filter_freq fit_range_Hz freqs frequencies_Hz keep_intervals line_bands_Hz line_frequencies mask metrics muscle_slopes n_interpolate noise_frequencies original_channels picks picks_artifact power_range_Hz probabilities raw_blink_mask ref_chs reject_mask repaired_channels reref_chs search_interval_s skip_by_annotation slopes targets thresholds times trial_ids valid_intervals window_starts zero_intervals'.split())
DICTS = set('criteria event_id external_assessments frame reference_evidence review scope'.split())
LISTS.add('channels')
STRINGS.update(('eeglab_root', 'matlab_path', 'prep_root', 'ica_random_policy'))
BOOLS = set('adaptive_sigma channel_wise correlation do_detrend extended matlab_strict ortho ransac reset_bads singlesided'.split())
INTS = set('bad_limit bins blocksize chunk_filter_order decim delay delay_spacing fixed_remove lags max_chunk_size max_iterations mem_splits min_windows n_fft n_legendre_terms n_neighbors offset padlen prototype_order seed smoothing start stepsize stop terms window_samples'.split())
UNIONS = {
    'cv':['array'],
    'noise_frequencies':['array','string'],
    'filter_length':['string','integer'], 'h_trans_bandwidth':['string','number'],
    'l_trans_bandwidth':['string','number'], 'kernel':['string','array'],
    'max_iter':['integer','string'], 'n_components':['integer','number','null'],
    'npad':['integer','string'], 'origin':['array','string'], 'pad':['string','integer'],
    'peak':['number','object','null'], 'flat':['number','object','null'],
    'random_state':['integer','object','null'], 'rank':['string','integer'],
    'rankopt':['number','integer'], 'ref_channels':['string','array'],
    'reject':['object','null'], 'reject_by_annotation':['string','null'],
    'sphere':['array','string','null'], 'threshold':['number','string'],
    'window':['string','array','null'],
    'annotations':['object'], 'forward':['object'], 'projs':['array','object'], 'blink_epochs':['object','null'],
}
NUMBERS = set('HF_zscore_threshold alpha bad_percent bad_window_fraction bandwidth beta chunk_seconds correlation_secs correlation_threshold cutoff detection_width deviation_threshold deviation_z epoch_duration epoch_threshold extreme_fraction fallback_percentile flat_duration_s flat_limit_V flat_ptp_V frac_bad global_threshold h_freq half_window_s l_freq lambda2 limit_V line_freq lm_cutoff local_threshold lookahead lowpass_Hz mad_multiplier max_bad_chans max_dropout_fraction max_flatline_duration max_fraction max_sigma maxdims maximum min_chunk_seconds min_clean_fraction min_clean_seconds min_duration min_length_good min_sigma mt_bandwidth mu muscle_fraction muscle_slope muscle_threshold overlap_fraction p_value peak_to_peak_limit_V persistent_low_corr_fraction persistent_low_corr_seconds prominence_quantile ratio_threshold regularization ripple scan_bandwidth sfreq shared_correlation_threshold sigma slope_threshold spectrum_window_seconds step_seconds stiffness stride_s threshold_V timeout timeout_seconds tmax tmin tol tolerance_V transition tstep welch_segment_s win_len win_overlap window_s window_seconds xyz_scale'.split())
FRACTIONS=set('bad_window_fraction correlation_threshold extreme_fraction frac_bad max_bad_chans max_dropout_fraction max_fraction maximum min_clean_fraction muscle_fraction overlap_fraction persistent_low_corr_fraction shared_correlation_threshold win_overlap prominence_quantile alpha p_value'.split())
POSITIVE=set('sfreq bandwidth blocksize bins decim delay_spacing epoch_duration half_window_s lags lookahead max_flatline_duration mem_splits min_windows n_neighbors n_legendre_terms prototype_order stepsize terms window_samples window_s stride_s win_len timeout timeout_seconds tstep'.split())
ENUMS={'nonfinite':['reject','propagate'], 'annotation_policy':['raw','array'],
       'tail':['drop'], 'tail_policy':['preserve'], 'type':['constant','linear'],
       'retained_bandwidth_policy':['require','author_attenuated'],
       'ica_random_policy':['author_clock','fixed_loop_seed_zero'],
       'adaptation_scope':['record_unlabeled'], 'on_insufficient_calibration':['error','identity']}
RUNTIME={'events':'$events','trial_ids':'$trial_ids','times':'$times','axes':'$axes','reference_id':'$reference_id','scope':'$scope','stop':'$n_samples'}


def parameter_schema(spec):
    properties={}
    for name in dict.fromkeys(spec['required']+list(spec['defaults'])):
        if name in UNIONS: types=list(UNIONS[name])
        elif name in STRINGS: types=['string']
        elif name in LISTS: types=['array']
        elif name in DICTS: types=['object']
        elif name in BOOLS: types=['boolean']
        elif name in INTS: types=['integer']
        elif name in NUMBERS: types=['number']
        else: raise ValueError('parameter has no explicit contract: '+name)
        default=spec['defaults'].get(name)
        if name in spec['defaults'] and default is None and 'null' not in types:types.append('null')
        if name in ('l_freq','h_freq','baseline','scan_bandwidth','padlen') and 'null' not in types:types.append('null')
        field={'type':types[0] if len(types)==1 else types}
        if name in spec['defaults']:field['default']=deepcopy(default)
        if name in ENUMS:field['enum']=ENUMS[name]
        if name in spec['variants']:field['enum']=spec['variants'][name]
        if name in FRACTIONS:field.update(minimum=0,maximum=1)
        if name in POSITIVE:field['exclusiveMinimum']=0
        if name=='prototype_order':field['maximum']=12
        if name in ('bad_percent','fallback_percentile'):field.update(minimum=0,maximum=100)
        if name in RUNTIME:field['runtime_binding']=RUNTIME[name]
        properties[name]=field
    return {'type':'object','additionalProperties':False,'required':spec['required'],'properties':properties}


def _finite_json(value):
    if value is None or type(value) in (str,int,bool):return
    if type(value) is float:
        if not math.isfinite(value):raise ValueError('nonfinite JSON parameter')
        return
    if isinstance(value,list):
        for v in value:_finite_json(v)
        return
    if isinstance(value,dict) and all(isinstance(k,str) for k in value):
        for v in value.values():_finite_json(v)
        return
    raise ValueError('parameters must be JSON; bind typed artifacts using artifact_inputs')


def validate_parameters(unit,op,params,profile='source',bound=()):
    spec=DEFINITIONS[(unit,op)]
    if profile!='source':
        selected=next((v for v in profiles(spec) if ','.join(f'{k}={x}' for k,x in v.items())==profile),None)
        if selected is None:raise ValueError('unknown op/profile')
        if any(k in params and params[k]!=v for k,v in selected.items()):raise ValueError('parameters contradict selected profile')
        params={**selected,**params}
    schema=parameter_schema(spec)
    unknown=(params.keys()|set(bound))-schema['properties'].keys()
    missing=set(spec['required'])-params.keys()-set(bound)
    if unknown or missing:raise ValueError(f'{unit}/{op}: unknown={sorted(unknown)}, missing={sorted(missing)}')
    if set(bound)&params.keys():raise ValueError('parameter supplied both literally and through artifact port')
    result=deepcopy(spec['defaults']);result.update(deepcopy(params))
    conditional_forbidden=set()
    if op=='wica_apply' and result.get('variant')=='ordinary':
        conditional_forbidden={'eye_weights','extra_eye','line_freq','muscle_slope'}
    if op=='ecg_assess' and result.get('method')=='ctps':conditional_forbidden={'measure'}
    if op=='autoreject_fit' and result.get('mode')=='global':conditional_forbidden={'n_interpolate','consensus','thresh_method'}
    if conditional_forbidden & (params.keys() | set(bound)):
        raise ValueError('parameters forbidden for selected variant: '+str(sorted(conditional_forbidden & (params.keys() | set(bound)))))
    for k in conditional_forbidden:result.pop(k,None)
    for k in bound:result.pop(k,None)
    for name,value in result.items():
        _finite_json(value)
        if isinstance(value,str) and value.startswith('$'):
            if RUNTIME.get(name)!=value:raise ValueError('invalid runtime parameter binding: '+name)
            continue
        field=schema['properties'][name];types=field['type']
        if isinstance(types,str):types=[types]
        checks={'null':value is None,'boolean':type(value) is bool,'integer':type(value) is int,
                'number':type(value) in (int,float),'string':type(value) is str,'array':type(value) is list,'object':type(value) is dict}
        if not any(checks[t] for t in types):raise ValueError(f'{name}: expected {types}')
        if value is None:continue
        if 'enum' in field and value not in field['enum']:raise ValueError(name+': invalid choice')
        if type(value) in (int,float):
            if 'minimum' in field and value<field['minimum'] or 'maximum' in field and value>field['maximum'] or 'exclusiveMinimum' in field and value<=field['exclusiveMinimum']:
                raise ValueError(name+': outside parameter bounds')
    lo,hi=result.get('l_freq'),result.get('h_freq')
    if isinstance(lo,(int,float)) and isinstance(hi,(int,float)) and lo>=hi:raise ValueError('l_freq must be less than h_freq')
    if op=='crop' and result['tmin']>result['tmax']:raise ValueError('crop tmin exceeds tmax')
    if op in ('epoch','epoch_with_nonfinite') and result['tmin']>=result['tmax']:raise ValueError('invalid epoch window')
    if op=='detect_bad_channels' and (result['shared_correlation_threshold']<=result['correlation_threshold'] or result['persistent_low_corr_fraction']<result['bad_window_fraction']):raise ValueError('inconsistent detector thresholds')
    if op=='filter':
        if lo is None and hi is None:raise ValueError('filter needs at least one cutoff')
        if result['annotation_policy']=='raw' and result['nonfinite']!='reject':raise ValueError('Raw annotation segmentation requires finite input')
        if result['method']=='fir':
            if result['phase'] not in ('zero','zero-double','minimum','minimum-half') or result['fir_design'] not in ('firwin','firwin2') or result['fir_window'] not in ('hamming','hann','blackman'):raise ValueError('unsupported FIR design/window/phase')
        elif result['method']=='iir':
            if result['phase'] not in ('zero','forward','zero-double'):raise ValueError('unsupported IIR phase')
            if any(result[k]!=spec['defaults'][k] for k in ('fir_design','fir_window','filter_length','l_trans_bandwidth','h_trans_bandwidth')):raise ValueError('IIR does not accept FIR design options')
    if op=='butter':
        if result['kind']=='highpass' and (lo is None or hi is not None) or result['kind']=='lowpass' and (hi is None or lo is not None) or result['kind'] in ('bandpass','bandstop') and (lo is None or hi is None):raise ValueError('cutoffs contradict Butterworth kind')
        if result['phase']=='forward' and result['padlen'] not in (None,0):raise ValueError('causal filtering does not use padding')
    if op=='decimate' and not 0<=result['offset']<result['decim']:raise ValueError('decimation offset must be below decim')
    if op=='spectrum_fit' and (result['p_value']!=.01 or result['annotation_policy']!='array'):raise ValueError('specified-frequency spectrum_fit fixes p_value and full-array policy')
    if op=='ica_fit':
        if result['method']=='fastica' and (result['ortho'] is not None or result['extended'] is not None):raise ValueError('FastICA has no ortho/extended options')
        if result['method']=='infomax' and result['ortho'] is not None:raise ValueError('Infomax has no ortho option')
    if op=='mwf_fit' and (result['mu']<1 or result['treatnans'] not in ('ignore','artifact','clean')):raise ValueError('MWF requires mu >= 1 and explicit missing-mask policy')
    return result


def dependency_status(spec,params=None):
    params=params or {};issues=[];requirements=dict(spec['dependencies'])
    if spec['op']=='ica_fit' and params.get('method')=='picard':requirements['python-picard']='0.8.1'
    if spec['op']=='iclabel_assess' and params.get('backend')=='onnx':requirements['onnxruntime']='1.22.1'
    for name,wanted in requirements.items():
        try:actual=metadata.version(name)
        except metadata.PackageNotFoundError:actual=None
        if actual!=wanted:issues.append({'kind':'package','name':name,'required':wanted,'actual':actual})
    for name in spec['assets']:
        if name in ('forward','projs'):continue  # typed, hash-bound graph assets
        value=params.get(name,spec['defaults'].get(name))
        exists=isinstance(value,str) and (Path(value).exists() or (name.startswith('octave') and shutil.which(value)))
        if not exists:issues.append({'kind':'asset','name':name,'required':'explicit verified local asset','actual':value})
    return issues


def invoke_source(unit,op,x,model=None,**params):
    from . import specification,ROOT
    from ..storage import file_hash
    spec=DEFINITIONS[(unit,op)]
    missing=dependency_status(spec,params)
    if missing:raise ValueError('dependency_missing: '+str(missing))
    source=specification(unit);module=source.implementation['module']
    if file_hash(ROOT/'source'/f'{module}.py')!=source.source['code_sha256']:raise ValueError('source checksum changed')
    return getattr(import_module('app.preprocessing.units.source.'+module),source.implementation['entry'])(op,x,model=model,**params)
