"""EEG detection basic unit; inputs are read-only, values use SI volts."""
import numpy as np
import mne
from scipy import signal, stats

def _params(p, defaults):
    unknown=set(p)-set(defaults)
    if unknown: raise TypeError('unknown parameters: '+str(sorted(unknown)))
    return dict(defaults, **p)

def _start(op, expected, x, model, allow_epochs=False, picks=None):
    if op != expected: raise ValueError('operation must be '+expected)
    if model is not None: raise ValueError('detection does not accept a fitted model')
    valid=(mne.io.BaseRaw,mne.BaseEpochs) if allow_epochs else (mne.io.BaseRaw,)
    if not isinstance(x,valid): raise TypeError('expected Raw or supported Epochs')
    if picks is None: picks=mne.pick_types(x.info, eeg=True, exclude='bads').tolist()
    else:
        if not isinstance(picks,(list,tuple)) or not picks or len(set(picks))!=len(picks): raise ValueError('picks must be unique channel names')
        if any(c not in x.ch_names for c in picks): raise ValueError('unknown channel')
        picks=[x.ch_names.index(c) for c in picks]
    if not picks: raise ValueError('no selected channels')
    a=x.get_data(picks=picks)
    if not np.isfinite(a).all(): raise ValueError('selected data must be finite')
    return a,[x.ch_names[k] for k in picks],float(x.info['sfreq'])

def _positive(v, name, zero=False):
    if isinstance(v,(bool,np.bool_)) or not np.isscalar(v) or not np.isfinite(v) or (v<0 if zero else v<=0): raise ValueError(name+' must be finite '+('nonnegative' if zero else 'positive'))
    return float(v)

def _fraction(v,name):
    v=_positive(v,name,True)
    if v>1: raise ValueError(name+' must be in [0,1]')
    return v

def _samples(seconds, sf, name):
    n=_positive(seconds,name)*sf
    if n<1 or not np.isclose(n,round(n),rtol=0,atol=1e-8): raise ValueError(name+' must contain an integer number of samples')
    return int(round(n))

def _segments(x, intervals=None):
    n=x.n_times
    if intervals is not None:
        v=np.asarray(intervals)
        if v.ndim!=2 or v.shape[1]!=2 or not len(v) or v.dtype.kind not in 'iu': raise ValueError('valid_intervals must be nonempty integer [start, stop) sample pairs')
        if np.any(v[:,0]<0) or np.any(v[:,1]>n) or np.any(v[:,1]<=v[:,0]) or np.any(v[1:,0]<v[:-1,1]): raise ValueError('invalid/overlapping intervals')
        return v
    from mne.annotations import _annotations_starts_stops
    starts,ends=_annotations_starts_stops(x,('bad','edge'),invert=True)
    return np.array([(s,e) for s,e in zip(starts,ends) if e>s],dtype=int).reshape(-1,2)

def _windows(x,a,p):
    sf=float(x.info['sfreq']);win=_samples(p['window_s'],sf,'window_s');step=_samples(p['stride_s'],sf,'stride_s')
    if p['tail']!='drop': raise ValueError('tail must be drop')
    iv=_segments(x,p['valid_intervals']);bounds=np.array([(s,e) for lo,hi in iv for s in range(lo,hi-win+1,step) for e in [s+win]],dtype=int).reshape(-1,2)
    if len(bounds)<p['min_windows'] or not isinstance(p['min_windows'],int) or isinstance(p['min_windows'],bool) or p['min_windows']<1: raise ValueError('insufficient valid windows or invalid min_windows')
    return np.stack([a[:,s:e] for s,e in bounds],axis=1),bounds

def _result(x,names,**artifacts):
    return {'data':x.copy(),'model':None,'artifacts':{'channel_names':names,**artifacts}}

def _candidates(names,mask): return [n for n,b in zip(names,np.asarray(mask,dtype=bool)) if b]

def _epoch_axes(x,names):
    return {'channel_names':names,'epoch_selection':np.asarray(x.selection).copy(),'events':x.events.copy(),'times_s':x.times.copy()}


import copy
import importlib.metadata
from pyprep import NoisyChannels
from pyprep.utils import _mat_iqr, _mad

def _prep(x, model, p, methods):
    bandwidth_policy=p.pop('retained_bandwidth_policy','require')
    if bandwidth_policy not in ('require','author_attenuated'):raise ValueError('invalid retained_bandwidth_policy')
    if model is not None:raise ValueError('no model accepted')
    if not isinstance(x,mne.io.BaseRaw):raise TypeError('PyPREP detection requires Raw')
    if importlib.metadata.version('pyprep')!='0.7.1':raise RuntimeError('requires pyprep==0.7.1')
    for key in ('do_detrend','matlab_strict'):
        if not isinstance(p[key],bool):raise TypeError(key+' must be boolean')
    if not isinstance(p['random_state'],int) or isinstance(p['random_state'],bool) or not 0<=p['random_state']<2**32:raise ValueError('random_state must be a uint32 seed')
    if p['reject_by_annotation'] not in (None,'omit'):raise ValueError('reject_by_annotation must be None or omit')
    if p['matlab_strict'] and p['reject_by_annotation'] is not None:raise ValueError('matlab_strict cannot honor annotation omission; choose one explicitly')
    allowed={'deviation':{'deviation_threshold':5.},'hfnoise':{'HF_zscore_threshold':5.},'correlation':{'correlation_secs':1.,'correlation_threshold':.4,'frac_bad':.01},'snr':{},'ransac':{'n_samples':50,'sample_prop':.25,'corr_thresh':.75,'frac_bad':.4,'corr_window_secs':5.,'channel_wise':False,'max_chunk_size':None}}
    if not isinstance(methods,dict) or not methods or set(methods)-set(allowed):raise ValueError('invalid criteria')
    cfg={}
    for name,kw in methods.items():
        if not isinstance(kw,dict):raise TypeError('criterion parameters must be dict')
        cfg[name]=_params(kw,allowed[name])
    if 'snr' in cfg and not {'hfnoise','correlation'}<=set(cfg):raise ValueError('SNR requires explicit hfnoise and correlation')
    if 'ransac' in cfg and not {'deviation','correlation'}<=set(cfg):raise ValueError('RANSAC requires explicit deviation and correlation')
    obj=NoisyChannels(x.copy().load_data(),**p,ransac='ransac' in cfg,correlation='correlation' in cfg)
    if obj.n_chans_new<2:raise ValueError('fewer than two usable EEG channels after constructor NaN/flat checks')
    if np.isinf(obj.EEGData).any():raise ValueError('infinite data is invalid')
    native_reasons={'nan':list(obj.bad_by_nan),'flat':list(obj.bad_by_flat),'manual':list(obj.bad_by_manual)};status={};rng_before=obj.random_state.get_state();measures={}
    for name in allowed:
        if name not in cfg:continue
        kw=cfg[name]
        if name=='deviation':
            _positive(kw['deviation_threshold'],'deviation_threshold');amp=_mat_iqr(obj.EEGData,axis=1)*.7413;scale=_mat_iqr(amp)*.7413
            if not np.isfinite(scale) or scale<=0:raise ValueError('deviation undefined: zero population amplitude scale')
            measures['channel_amplitude_V']=amp
            obj.find_bad_by_deviation(**kw)
        elif name=='hfnoise':
            _positive(kw['HF_zscore_threshold'],'HF_zscore_threshold')
            if obj.sample_rate<=100:raise ValueError('HF ratio not applicable at sfreq <= 100 Hz')
            if x.info.get('lowpass') is not None and x.info['lowpass']<=50 and bandwidth_policy=='require':raise ValueError('HF ratio not applicable after lowpass <= 50 Hz')
            if obj.EEGFiltered is None:obj.EEGFiltered=obj._get_filtered_data()
            num=_mad(obj.EEGData-obj.EEGFiltered,axis=1);den=_mad(obj.EEGFiltered,axis=1)
            if np.any(den<=0):raise ValueError('HF ratio undefined: zero denominator')
            ratio=num/den;scale=np.median(abs(ratio-np.median(ratio)))*1.4826
            if not np.isfinite(scale) or scale<=0:raise ValueError('HF ratio undefined: zero population scale')
            measures.update(hf_numerator_V=num,hf_denominator_V=den,hf_noisiness=ratio)
            obj.find_bad_by_hfnoise(**kw)
        elif name=='correlation':
            win=_samples(kw['correlation_secs'],obj.sample_rate,'correlation_secs');_fraction(kw['correlation_threshold'],'correlation_threshold');_fraction(kw['frac_bad'],'frac_bad')
            count=len(np.arange(1,obj.n_samples-win,win))
            if count<1:raise ValueError('insufficient PyPREP correlation windows')
            if obj.EEGFiltered is None:obj.EEGFiltered=obj._get_filtered_data()
            for w in range(count):
                if np.sum(_mad(obj.EEGFiltered[:,w*win:(w+1)*win],axis=1)>0)<2:raise ValueError('correlation window has fewer than two nonflat channels')
            measures['correlation_windows_work_samples']=np.array([[w*win,(w+1)*win] for w in range(count)])
            obj.find_bad_by_correlation(**kw)
        elif name=='snr':obj.bad_by_SNR=sorted(set(obj.bad_by_hf_noise)&set(obj.bad_by_correlation))
        elif name=='ransac':
            for key in ('corr_thresh','frac_bad','sample_prop'):_fraction(kw[key],key)
            if not 0<kw['sample_prop']<1:raise ValueError('sample_prop must be in (0,1)')
            _positive(kw['corr_window_secs'],'corr_window_secs')
            if not isinstance(kw['n_samples'],int) or isinstance(kw['n_samples'],bool) or kw['n_samples']<1:raise ValueError('n_samples must be positive integer')
            if not isinstance(kw['channel_wise'],bool):raise ValueError('channel_wise must be boolean')
            chunk=kw['max_chunk_size']
            if chunk is not None and (not isinstance(chunk,int) or isinstance(chunk,bool) or chunk<1 or not kw['channel_wise']):raise ValueError('max_chunk_size needs channel_wise and positive integer')
            xyz=obj.raw_mne._get_channel_positions(obj.raw_mne.ch_names)[obj.usable_idx]
            if not np.isfinite(xyz).all() or np.any(np.linalg.norm(xyz,axis=1)==0):raise ValueError('RANSAC requires valid electrode positions')
            obj.find_bad_by_ransac(**kw)
        status[name]='executed'
    attr={'deviation':'bad_by_deviation','hfnoise':'bad_by_hf_noise','correlation':'bad_by_correlation','snr':'bad_by_SNR','ransac':'bad_by_ransac'}
    by={name:list(getattr(obj,attr[name])) for name in cfg}
    if 'correlation' in cfg:by['dropout']=list(obj.bad_by_dropout)
    candidates=set(obj.bad_by_nan+obj.bad_by_flat)
    for vals in by.values():candidates.update(vals)
    names=list(obj.ch_names_original);original_index=np.arange(x.n_times)
    if p['reject_by_annotation']=='omit':
        _,tt=x.get_data(picks=[0],reject_by_annotation='omit',return_times=True);original_index=np.rint(tt*x.info['sfreq']).astype(int)
    return _result(x,names,candidates=[n for n in names if n in candidates],criterion_candidates=by,constructor_reasons=native_reasons,usable_channel_names=list(obj.ch_names_new),scores=copy.deepcopy(obj._extra_info),measures=measures,work_to_raw_sample=original_index,raw_first_samp=x.first_samp,status=status,parameters={'constructor':p,'criteria':cfg},pyprep_version='0.7.1',retained_bandwidth_policy=bandwidth_policy,hf_band_attenuated=bool(x.info.get('lowpass') is not None and x.info['lowpass']<=50),rng_before=rng_before,rng_after=obj.random_state.get_state(),detection_copy={'detrend':p['do_detrend'],'lowpass':'PyPREP 100th-order FIR pass 0–45 Hz transition 45–50 Hz, filtfilt' if obj.EEGFiltered is not None and obj.sample_rate>100 else None,'annotation_omission_concatenates':p['reject_by_annotation']=='omit'})

def eeg_bad_channel_ensemble(op,x,model=None,**p):
    if op != 'prep_detect':raise ValueError("invalid operation")
    p=_params(p,{'retained_bandwidth_policy':'require','do_detrend': True, 'matlab_strict': True, 'random_state': 0, 'reject_by_annotation': None, 'criteria': {'deviation': {'deviation_threshold': 5.0}, 'hfnoise': {'HF_zscore_threshold': 5.0}, 'correlation': {'correlation_secs': 1.0, 'correlation_threshold': 0.4, 'frac_bad': 0.01}, 'snr': {}, 'ransac': {'n_samples': 50, 'sample_prop': 0.25, 'corr_thresh': 0.75, 'frac_bad': 0.4, 'corr_window_secs': 5.0, 'channel_wise': False, 'max_chunk_size': None}}})
    methods=p.pop('criteria')
    return _prep(x,model,p,methods)


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

_core_previous_prep=eeg_bad_channel_ensemble

def eeg_bad_channel_ensemble(op,x,model=None,**p):
    if op!='prep_detect_native':return _core_previous_prep(op,x,model=model,**p)
    if model is not None:raise ValueError('detector model is supplied as random_state parameter')
    _core_versions()
    p=_core_kwargs(p,{'do_detrend':True,'random_state':None,'reject_by_annotation':None,
        'ransac':True,'channel_wise':False,'max_chunk_size':None,'correlation':True,
        'criteria':{}})
    for k in ('do_detrend','ransac','channel_wise','correlation'):p[k]=_core_bool(p[k],k)
    if p['reject_by_annotation'] not in (None,'omit'):raise ValueError('invalid reject_by_annotation')
    if p['max_chunk_size'] is not None:
        _core_int(p['max_chunk_size'],'max_chunk_size',1)
        if not p['channel_wise'] or not p['ransac']:raise ValueError('max_chunk_size needs channel-wise RANSAC')
    cfg={'deviation':{'deviation_threshold':5.},'hfnoise':{'HF_zscore_threshold':5.},
        'correlation':{'correlation_secs':1.,'correlation_threshold':.4,'frac_bad':.01},
        'psd':{'zscore_threshold':3.,'fmin':1.,'fmax':45.},
        'ransac':{'n_samples':50,'sample_prop':.25,'corr_thresh':.75,'frac_bad':.4,'corr_window_secs':5.}}
    if not isinstance(p['criteria'],dict) or set(p['criteria'])-set(cfg):raise ValueError('unknown criterion')
    for name,overrides in p['criteria'].items():
        if (name=='ransac' and not p['ransac']) or (name=='correlation' and not p['correlation']):raise ValueError('parameters for disabled criterion')
        cfg[name]=_core_kwargs(overrides,cfg[name])
    for name,vals in cfg.items():
        for key,val in vals.items():
            if key=='n_samples':_core_int(val,key,1)
            elif key in ('sample_prop','corr_thresh','frac_bad','correlation_threshold'):
                _core_real(val,key,0,1)
                if key=='sample_prop' and not 0<val<1:raise ValueError('sample_prop outside (0,1)')
            else:_core_real(val,key,0,strict=key!='fmin')
    if cfg['psd']['fmin']>=cfg['psd']['fmax']:raise ValueError('PSD fmin must be below fmax')
    y=_core_raw(x,allow_nan=True);rng=_core_rng(p['random_state']);before=_core_rng_dump(rng)
    from pyprep import NoisyChannels
    with _core_warnings.catch_warnings(record=True) as caught:
        _core_warnings.simplefilter('always')
        obj=NoisyChannels(y.copy(),do_detrend=p['do_detrend'],random_state=rng,
            matlab_strict=False,ransac=p['ransac'],correlation=p['correlation'],reject_by_annotation=p['reject_by_annotation'])
        obj.find_bad_by_deviation(**cfg['deviation'])
        obj.find_bad_by_hfnoise(**cfg['hfnoise'])
        if p['correlation']:obj.find_bad_by_correlation(**cfg['correlation'])
        obj.find_bad_by_SNR()
        obj.find_bad_by_PSD(**cfg['psd'])
        if p['ransac']:obj.find_bad_by_ransac(**cfg['ransac'],channel_wise=p['channel_wise'],max_chunk_size=p['max_chunk_size'])
    by=obj.get_bads(as_dict=True)
    return _core_out(y,candidates=by['bad_all'],criterion_candidates=by,
        usable_channel_names=list(obj.ch_names_new),scores=_core_copylib.deepcopy(obj._extra_info),
        rng_before=before,rng_after=_core_rng_dump(rng),parameters={**p,'criteria':cfg},
        source_profile='pyprep_071',warnings=[str(w.message) for w in caught])
