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

def eeg_eog_step(op,x,model=None,**p):
    p=_params(p,{'channels':None,'search_interval_s':[-.2,.3],'half_window_s':.1,'threshold_V':32e-6,'statistic':'trimmean95'})
    if not isinstance(p['channels'],(list,tuple)) or len(p['channels']) not in (1,2):raise ValueError('channels must name one signal or two channels to subtract')
    a,names,sf=_start(op,'eog_step',x,model,True,p['channels'])
    if not isinstance(x,mne.BaseEpochs):raise TypeError('EOG step requires Epochs')
    h=_samples(p['half_window_s'],sf,'half_window_s');limit=_positive(p['threshold_V'],'threshold_V');interval=np.asarray(p['search_interval_s'],float)
    if interval.shape!=(2,) or not np.isfinite(interval).all() or interval[1]<interval[0]:raise ValueError('invalid search interval')
    endpoints=[int(np.argmin(abs(x.times-t))) for t in interval]
    if any(abs(x.times[i]-t)>1e-9 for i,t in zip(endpoints,interval)):raise ValueError('search interval endpoints must coincide with epoch samples')
    lo,hi=endpoints
    if lo-h<0 or hi+h>=len(x.times):raise ValueError('epoch does not contain the complete step windows')
    v=a[:,0] if len(names)==1 else a[:,0]-a[:,1];out=[]
    def avg(y):
        if p['statistic']=='mean':return np.mean(y,axis=-1)
        if p['statistic']=='trimmean95':
            k=int(np.floor(y.shape[-1]*.95/2+.5));ys=np.sort(y,axis=-1)
            if 2*k>=y.shape[-1]:raise ValueError('trimmean95 leaves no observations for this sample rate/window')
            return np.mean(ys[...,k:y.shape[-1]-k],axis=-1)
        raise ValueError('statistic must be mean or trimmean95')
    for t in range(lo,hi+1):out.append(avg(v[:,t-h:t+1])-avg(v[:,t:t+h+1]))
    steps=np.asarray(out).T;maximum=np.max(abs(steps),axis=1)
    return _result(x,names,epoch_selection=x.selection.copy(),search_times_s=x.times[lo:hi+1].copy(),step_V=steps,maximum_absolute_step_V=maximum,epoch_mask=maximum>limit,statistic=p['statistic'],window_samples_each_side=h+1)
