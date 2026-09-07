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


def _z(a,axis):
    center=np.mean(a,axis=axis,keepdims=True);scale=np.std(a,axis=axis,ddof=1,keepdims=True);valid=np.isfinite(scale)&(scale>0)
    score=np.divide(a-center,scale,out=np.full_like(a,np.nan),where=valid)
    return score,np.squeeze(center,axis),np.squeeze(scale,axis)
def eeg_joint_probability(op,x,model=None,**p):
    p=_params(p,{'local_threshold':10.,'global_threshold':10.,'bins':1000})
    a,names,sf=_start(op,'joint_probability',x,model,True)
    if not isinstance(x,mne.BaseEpochs):raise TypeError('requires Epochs')
    if len(a)<2 or a.shape[-1]<4:raise ValueError('requires at least two epochs with four samples each')
    lt=_positive(p['local_threshold'],'local_threshold',True);gt=_positive(p['global_threshold'],'global_threshold',True)
    bins=p['bins']
    if not isinstance(bins,int) or isinstance(bins,bool) or bins<2:raise ValueError('bins must be an integer >= 2')
    def surprise(y):
        lo=float(np.min(y));hi=float(np.max(y))
        if hi==lo:return np.full_like(y,np.nan)
        idx=np.floor((y-lo)/(hi-lo)*(bins-1)).astype(int);count=np.bincount(idx.ravel(),minlength=bins);return -np.log(count[idx]/y.size)
    local=np.stack([surprise(a[:,c,:]).sum(axis=-1) for c in range(len(names))],axis=0)
    global_raw=np.array([surprise(epoch).sum() for epoch in a])
    lscore,lcenter,lscale=_z(local,1);gscore,gcenter,gscale=_z(global_raw,0)
    lm=(np.abs(lscore)>lt) if lt else np.zeros_like(lscore,dtype=bool);gm=(np.abs(gscore)>gt) if gt else np.zeros_like(gscore,dtype=bool)
    return _result(x,names,epoch_selection=x.selection.copy(),local_axis_order='channel, epoch',local_raw=local,global_raw=global_raw,local_z=lscore,global_z=gscore,local_center=lcenter,local_scale=lscale,global_center=gcenter,global_scale=gscale,local_valid=np.isfinite(lscore),global_valid=np.isfinite(gscore),local_mask=lm,global_mask=gm,epoch_mask=np.any(lm,axis=0)|gm,normalization='mean and sample SD across epochs',undefined_reason='zero scale or constant signal' if not(np.isfinite(lscore).all() and np.isfinite(gscore).all()) else None)
