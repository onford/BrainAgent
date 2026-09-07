

# Extensions for the frozen MNE 1.10.2 / PyPREP 0.7.1 contracts.
import copy as _core_copylib
import hashlib as _core_hashlib
import importlib.metadata as _core_metadata
import warnings as _core_warnings
import json as _core_json
import numpy as np
import mne

def _core_kwargs(p, defaults, required=()):
    missing=set(required)-set(p);unknown=set(p)-set(defaults)
    if missing or unknown:raise ValueError('missing parameters='+str(sorted(missing))+'; unknown='+str(sorted(unknown)))
    return dict(defaults,**p)

def _core_bool(value,name):
    if not isinstance(value,(bool,np.bool_)):raise TypeError(name+' must be boolean')
    return bool(value)

def _core_int(value,name,low=0,high=None):
    if isinstance(value,(bool,np.bool_)) or not isinstance(value,(int,np.integer)) or value<low or (high is not None and value>high):raise ValueError(name+' invalid integer')
    return int(value)

def _core_real(value,name,low=None,high=None,strict=False):
    if isinstance(value,(bool,np.bool_)) or not isinstance(value,(int,float,np.integer,np.floating)) or not np.isfinite(value):raise ValueError(name+' must be finite real')
    if low is not None and (value<=low if strict else value<low):raise ValueError(name+' below range')
    if high is not None and value>high:raise ValueError(name+' above range')
    return float(value)

def _core_raw(x,allow_nan=False,epochs=False):
    if not isinstance(x,(mne.io.BaseRaw,mne.BaseEpochs) if epochs else mne.io.BaseRaw):raise TypeError('expected '+('Raw/Epochs' if epochs else 'Raw'))
    if isinstance(x,mne.BaseEpochs) and not x.preload:raise ValueError('Epochs must be preloaded')
    y=x.copy().load_data();a=y.get_data()
    if not a.size or np.iscomplexobj(a) or np.isinf(a).any() or (not allow_nan and np.isnan(a).any()):raise ValueError('empty, complex or unsupported nonfinite signal')
    return y

def _core_names(y,names,allow_empty=False):
    if not isinstance(names,(list,tuple)) or (not names and not allow_empty) or any(not isinstance(n,str) for n in names) or len(set(names))!=len(names):raise ValueError('channel names must be unique')
    good={n for n,t in zip(y.ch_names,y.get_channel_types()) if t=='eeg'}
    if not set(names)<=good:raise ValueError('existing EEG names required')
    return [y.ch_names.index(n) for n in names]

def _core_array_hash(a):
    a=np.ascontiguousarray(a)
    return _core_hashlib.sha256(str((a.dtype.str,a.shape)).encode()+a.tobytes()).hexdigest()

def _core_frame(y):
    return {'sfreq':float(y.info['sfreq']),'n_times':len(y.times),
            'first_samp':int(y.first_samp) if isinstance(y,mne.io.BaseRaw) else None,
            'epoch_selection':None if isinstance(y,mne.io.BaseRaw) else y.selection.tolist(),
            'epoch_events':None if isinstance(y,mne.io.BaseRaw) else y.events.tolist(),
            'tmin':float(y.times[0]),'meas_date':str(y.info.get('meas_date'))}

def _core_raw_hash(y):
    return _core_value_hash({'frame':_core_frame(y),'names':y.ch_names,'types':y.get_channel_types(),
        'bads':y.info['bads'],'data':y.get_data(),'locs':[c['loc'] for c in y.info['chs']],
        'dig':y.info['dig'],'projs':[dict(v) for v in y.info['projs']],
        'custom_ref_applied':int(y.info['custom_ref_applied']),
        'highpass':y.info['highpass'],'lowpass':y.info['lowpass'],
        'annotations':None if y.annotations is None else {'onset':y.annotations.onset,'duration':y.annotations.duration,
            'description':y.annotations.description,'ch_names':y.annotations.ch_names,
            'orig_time':str(y.annotations.orig_time)}})

def _core_value_hash(v):
    def plain(a):
        if isinstance(a,np.ndarray):
            if a.dtype.kind=='O':return {'shape':list(a.shape),'values':plain(a.tolist())}
            return {'dtype':a.dtype.str,'shape':list(a.shape),'hash':_core_array_hash(a)}
        if isinstance(a,np.generic):return plain(a.item())
        if isinstance(a,dict):return {str(k):plain(v) for k,v in a.items()}
        if isinstance(a,(list,tuple)):return [plain(v) for v in a]
        if isinstance(a,(str,int,float,bool)) or a is None:return a
        raise TypeError('unsupported state value: '+str(type(a)))
    return _core_hashlib.sha256(_core_json.dumps(plain(v),sort_keys=True,separators=(',',':'),allow_nan=True).encode()).hexdigest()

def _core_out(data,model=None,**artifacts):
    return {'data':data,'model':model,'artifacts':artifacts}

def _core_rng_dump(rng):
    name,keys,pos,has,cached=rng.get_state()
    return {'bit_generator':name,'keys':keys.copy(),'pos':int(pos),'has_gauss':int(has),'cached_gaussian':float(cached)}

def _core_rng(value):
    if value is None:
        rng=np.random.RandomState();rng.set_state(np.random.get_state());return rng
    if isinstance(value,(int,np.integer)) and not isinstance(value,(bool,np.bool_)):
        return np.random.RandomState(_core_int(value,'random_state',0,2**32-1))
    if not isinstance(value,dict) or set(value)!={'bit_generator','keys','pos','has_gauss','cached_gaussian'} or value['bit_generator']!='MT19937':raise ValueError('random_state must be None, uint32 seed, or MT19937 state')
    keys=np.asarray(value['keys'])
    if keys.shape!=(624,) or keys.dtype.kind not in 'iu' or np.any(keys<0) or np.any(keys>2**32-1):raise ValueError('invalid MT19937 keys')
    pos=_core_int(value['pos'],'pos',0,624);has=_core_int(value['has_gauss'],'has_gauss',0,1);cached=_core_real(value['cached_gaussian'],'cached_gaussian')
    rng=np.random.RandomState();rng.set_state(('MT19937',keys.astype(np.uint32),pos,has,cached));return rng

def _core_versions():
    if _core_metadata.version('pyprep')!='0.7.1' or mne.__version__!='1.10.2':raise RuntimeError('profile requires PyPREP 0.7.1 and MNE 1.10.2')

def _core_nonfinite_policy(value):
    if value not in ('reject','propagate'):raise ValueError('nonfinite must be reject or propagate')
    return value=='propagate'

# Author Reference phases, with read-only loop observations and explicit state.
import inspect as _core_inspect
import textwrap as _core_textwrap
from pathlib import Path as _CorePath
import pyprep.reference as _core_reference_module

_CORE_REFERENCE_SOURCE_SHA256='893ad8dbc7110a6ec3a2fa84da1330f1ebc990babd730c01742a719e3a1a0074'

class _CoreObservedReference(_core_reference_module.Reference):
    def _core_loop_start(self,loc):
        self._core_pending={'iteration':int(loc['iterations']),
            'rng_before':_core_rng_dump(self.random_state),
            'reference_before_V':self.reference_signal.copy(),
            'original_detrended_hash':_core_array_hash(loc['signal']),
            'detection_input_hash':_core_array_hash(loc['signal_tmp'])}

    def _core_loop_decision(self,loc):
        i=loc['iterations'];b=loc['bad_chans'];previous=loc['previous_bads']
        stable=i>1 and (len(b)==0 or b==previous);limited=i>loc['max_iterations']
        self._core_pending.update(rng_after=_core_rng_dump(self.random_state),
            detected=_core_copylib.deepcopy(loc['noisy_new']),
            accumulated=_core_copylib.deepcopy(loc['noisy']),
            reference_donors=list(loc['reference_channels']),reference_targets=list(loc['reference_channels']),
            stop=bool(stable or limited),stop_reason='stable' if stable else ('iteration_limit' if limited else None))
        self._core_trace.append(self._core_pending)

    def _core_loop_updated(self,loc):
        self._core_trace[-1].update(reference_after_V=self.reference_signal.copy(),
            reference_input_hash=_core_array_hash(loc['raw_tmp'].get_data()),
            next_detection_input_hash=_core_array_hash(loc['signal_tmp']))

def _core_observed_reference():
    _core_versions()
    path=_CorePath(_core_reference_module.__file__)
    if _core_hashlib.sha256(path.read_bytes()).hexdigest()!=_CORE_REFERENCE_SOURCE_SHA256:raise RuntimeError('author reference source changed')
    source=_core_textwrap.dedent(_core_inspect.getsource(_core_reference_module.Reference.robust_reference))
    changes={
        '    while True:\n':'    while True:\n        self._core_loop_start(locals())\n',
        '        if (\n            iterations > 1\n':'        self._core_loop_decision(locals())\n        if (\n            iterations > 1\n',
        '        iterations = iterations + 1\n':'        self._core_loop_updated(locals())\n        iterations = iterations + 1\n'}
    for old,new in changes.items():
        if source.count(old)!=1:raise RuntimeError('author loop observation anchor changed')
        source=source.replace(old,new)
    namespace=dict(vars(_core_reference_module));exec(compile(source,str(path)+':observed','exec'),namespace)
    _CoreObservedReference.robust_reference=namespace['robust_reference']
    return _CoreObservedReference

def _core_reference_model(ref,stage):
    state={k:_core_copylib.deepcopy(v) for k,v in ref.__dict__.items()
           if k not in ('raw','random_state','_core_pending')}
    state['random_state']=_core_rng_dump(ref.random_state)
    model={'kind':'eeg_prep_reference_071_v1','stage':stage,'state':state,
        'data_hash':_core_raw_hash(ref.raw),'author_source_sha256':_CORE_REFERENCE_SOURCE_SHA256}
    model['state_hash']=_core_value_hash(model)
    return model

def eeg_robust_reference(op,x,model=None,**p):
    _core_versions()
    if op=='prep_reference_fit':
        if model is not None:raise ValueError('fit requires model=None')
        p=_core_kwargs(p,{'ref_chs':None,'reref_chs':None,'max_iterations':4,'ransac':True,
            'channel_wise':False,'max_chunk_size':None,'random_state':None,'reject_by_annotation':None},('ref_chs','reref_chs'))
        y=_core_raw(x,allow_nan=True)
        if any(t!='eeg' for t in y.get_channel_types()):raise ValueError('reference state requires EEG-only Raw; partition auxiliary channels upstream')
        _core_names(y,p['ref_chs']);_core_names(y,p['reref_chs'])
        _core_int(p['max_iterations'],'max_iterations',0)
        for k in ('ransac','channel_wise'):p[k]=_core_bool(p[k],k)
        if p['max_chunk_size'] is not None:
            _core_int(p['max_chunk_size'],'max_chunk_size',1)
            if not p['channel_wise'] or not p['ransac']:raise ValueError('max_chunk_size needs channel-wise RANSAC')
        if p['reject_by_annotation'] not in (None,'omit'):raise ValueError('invalid reject_by_annotation')
        cls=_core_observed_reference();rng=_core_rng(p['random_state']);rng_before=_core_rng_dump(rng)
        ref=cls(y,{'ref_chs':list(p['ref_chs']),'reref_chs':list(p['reref_chs'])},
            ransac=p['ransac'],channel_wise=p['channel_wise'],max_chunk_size=p['max_chunk_size'],
            random_state=rng,reject_by_annotation=p['reject_by_annotation'],matlab_strict=False)
        ref._core_trace=[]
        with _core_warnings.catch_warnings(record=True) as caught:
            _core_warnings.simplefilter('always');ref.perform_reference(max_iterations=p['max_iterations'],interpolate_bads=False)
        if np.isinf(ref.raw.get_data()).any():raise ValueError('native reference produced infinity')
        outmodel=_core_reference_model(ref,'awaiting_final_interpolation')
        return _core_out(ref.raw.copy(),outmodel,parameters=p,rng_before=rng_before,rng_after=_core_rng_dump(rng),
            loop_trace=_core_copylib.deepcopy(ref._core_trace),initial_candidates=_core_copylib.deepcopy(ref.noisy_channels_original),
            cumulative_candidates=_core_copylib.deepcopy(ref.noisy_channels),unusable_channels=list(ref.unusable_channels),
            before_interpolation_candidates=list(ref.bad_before_interpolation),reference_signal_V=ref.reference_signal.copy(),
            warnings=[str(w.message) for w in caught],source_profile='pyprep_071')
    if op=='prep_reference_finalize':
        _core_kwargs(p,{})
        if not isinstance(model,dict) or model.get('kind')!='eeg_prep_reference_071_v1' or model.get('stage')!='awaiting_final_interpolation':raise ValueError('awaiting-final-interpolation model required')
        if model.get('author_source_sha256')!=_CORE_REFERENCE_SOURCE_SHA256 or _core_hashlib.sha256(_CorePath(_core_reference_module.__file__).read_bytes()).hexdigest()!=_CORE_REFERENCE_SOURCE_SHA256:raise ValueError('author source mismatch')
        check={k:v for k,v in model.items() if k!='state_hash'}
        if model.get('state_hash')!=_core_value_hash(check):raise ValueError('reference model state changed')
        y=_core_raw(x,allow_nan=True)
        if _core_raw_hash(y)!=model['data_hash']:raise ValueError('reference data/frame/montage/annotation mismatch')
        state=_core_copylib.deepcopy(model['state']);rng=_core_rng(state.pop('random_state'))
        ref=_core_reference_module.Reference.__new__(_core_reference_module.Reference)
        ref.__dict__.update(state);ref.raw=y;ref.random_state=rng
        before=_core_rng_dump(rng)
        with _core_warnings.catch_warnings(record=True) as caught:
            _core_warnings.simplefilter('always');ref.interpolate_bads()
        if not np.isfinite(ref.raw.get_data()).all():raise ValueError('final interpolation left nonfinite EEG')
        return _core_out(ref.raw.copy(),_core_reference_model(ref,'finalized'),
            interpolated_channels=list(ref.interpolated_channels),still_noisy_channels=list(ref.still_noisy_channels),
            reference_signal_V=ref.reference_signal_new.copy(),reference_correction_V=ref.reference_signal_new-ref.reference_signal,
            criterion_candidates=_core_copylib.deepcopy(ref.noisy_channels_after_interpolation),
            rng_before=before,rng_after=_core_rng_dump(rng),warnings=[str(w.message) for w in caught],source_profile='pyprep_071')
    raise ValueError('invalid operation')
