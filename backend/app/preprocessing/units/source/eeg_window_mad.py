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

def eeg_window_mad(op,x,model=None,**p):
    p=_params(p,{'mad_multiplier':25.,'flat_limit_V':2e-6,'blink_upper_bound_V':None})
    a,names,sf=_start(op,'window_mad',x,model,True)
    if not isinstance(x,mne.BaseEpochs): raise TypeError('window_mad requires already constructed diagnostic Epochs')
    factor=_positive(p['mad_multiplier'],'mad_multiplier',True);flat=_positive(p['flat_limit_V'],'flat_limit_V',True)
    ptp=np.ptp(a,axis=-1).T;med=np.median(ptp,axis=1);mad=np.median(np.abs(ptp-med[:,None]),axis=1);bound=med+factor*mad
    if p['blink_upper_bound_V'] is not None:
        b=np.asarray(p['blink_upper_bound_V'],float)
        if b.shape!=(len(names),) or not np.isfinite(b).all() or np.any(b<0): raise ValueError('blink_upper_bound_V must match channels and be finite nonnegative')
        bound=np.maximum(bound,b)
    mask=ptp>bound[:,None];flatmask=ptp<flat
    return _result(x,names,epoch_selection=x.selection.copy(),axis_order='channel, epoch',ptp_V=ptp,median_V=med,mad_V=mad,upper_bound_V=bound,shift_mask=mask,flat_mask=flatmask,combined_mask=mask|flatmask)


_ordinary_window_mad=eeg_window_mad

def eeg_window_mad(op,x,model=None,**p):
 if op!='blink_upper_bound':return _ordinary_window_mad(op,x,model=model,**p)
 p=_params(p,dict(blink_epochs=None,mad_multiplier=10.,fallback_percentile=80.))
 a,names,sf=_start('window_mad','window_mad',x,model,True)
 if not isinstance(x,mne.BaseEpochs) or not len(x):raise ValueError('nonempty diagnostic Epochs required')
 factor=_positive(p['mad_multiplier'],'mad_multiplier',True);q=_positive(p['fallback_percentile'],'fallback_percentile',True)
 if q>100:raise ValueError('fallback_percentile must be <=100')
 b=p['blink_epochs'];cuts=None;selected=None
 if b is not None:
  if not isinstance(b,mne.BaseEpochs) or not len(b) or b.ch_names!=x.ch_names or b.info['sfreq']!=sf or len(b.times)!=len(x.times) or b.get_channel_types()!=x.get_channel_types() or b.info['bads']!=x.info['bads']:raise ValueError('blink Epochs must match diagnostic channel and sample axes')
  ba=b.get_data(picks=names)
  if not np.isfinite(ba).all():raise ValueError('blink Epochs must be finite')
  ptp=np.ptp(ba,axis=-1).T;med=np.median(ptp,axis=1);mad=np.median(np.abs(ptp-med[:,None]),axis=1);mode='detected_blink_epochs'
 else:
  ptp=np.ptp(a,axis=-1).T;cuts=np.percentile(ptp,q,axis=1,method='hazen');selected=ptp>=cuts[:,None];med=[];mad=[]
  for row,mask in zip(ptp,selected):
   v=row[mask];center=np.median(v);med.append(center);mad.append(np.median(abs(v-center)))
  med=np.asarray(med);mad=np.asarray(mad);mode='diagnostic_upper_tail'
 return _result(x,names,epoch_selection=x.selection.copy(),axis_order='channel, epoch',upper_bound_V=med+factor*mad,median_V=med,mad_V=mad,mode=mode,fallback_cutoff_V=cuts,fallback_selected=selected,quantile_method='hazen',blink_epoch_selection=None if b is None else b.selection.copy())
