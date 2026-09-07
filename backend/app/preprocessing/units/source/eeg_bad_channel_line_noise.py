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

def eeg_bad_channel_line_noise(op,x,model=None,**p):
    p=_params(p,{'window_s':4.,'stride_s':2.,'tail':'drop','valid_intervals':None,'min_windows':1,'line_bands_Hz':[[49.,51.]],'background_bands_Hz':[[40.,48.],[52.,60.]],'welch_segment_s':2.,'overlap_fraction':.5,'n_fft':None,'ratio_threshold':5.,'frac_bad':.25})
    a,names,sf=_start(op,'line_noise_detect',x,model);w,bounds=_windows(x,a,p)
    nper=_samples(p['welch_segment_s'],sf,'welch_segment_s');overlap=_fraction(p['overlap_fraction'],'overlap_fraction');nfft=nper if p['n_fft'] is None else p['n_fft']
    if overlap==1 or nper>w.shape[-1] or not isinstance(nfft,int) or isinstance(nfft,bool) or nfft<nper: raise ValueError('invalid Welch segment, overlap or n_fft')
    groups=[]
    for key in ('line_bands_Hz','background_bands_Hz'):
        bands=np.asarray(p[key],float)
        if bands.ndim!=2 or bands.shape[1]!=2 or not len(bands) or not np.isfinite(bands).all() or np.any(bands[:,0]<0) or np.any(bands[:,1]>=sf/2) or np.any(bands[:,1]<=bands[:,0]): raise ValueError('invalid '+key)
        groups.append(bands)
    allbands=sorted(np.concatenate(groups).tolist())
    if x.info.get('lowpass') is not None and x.info['lowpass']<max(v[1] for v in allbands):raise ValueError('requested bands exceed retained lowpass bandwidth')
    if any(v[1]>q[0] for v,q in zip(allbands,allbands[1:])): raise ValueError('line and background bands must not overlap')
    f,psd=signal.welch(w,fs=sf,window='hann',nperseg=nper,noverlap=int(np.floor(nper*overlap)),nfft=nfft,detrend='constant',scaling='density',axis=-1)
    means=[]
    for bands in groups:
        total=np.zeros(psd.shape[:-1]);bandwidth=0.
        for lo,hi in bands:
            inner=f[(f>lo)&(f<hi)]
            if np.sum((f>=lo)&(f<=hi))<2: raise ValueError('PSD resolution insufficient for requested band')
            ff=np.r_[lo,inner,hi];yy=np.stack([np.interp(ff,f,row) for row in psd.reshape(-1,len(f))]).reshape(psd.shape[:-1]+(len(ff),))
            total+=np.trapz(yy,ff,axis=-1);bandwidth+=hi-lo
        means.append(total/bandwidth)
    line,bg=means;valid=bg>0;ratio=np.divide(line,bg,out=np.full_like(bg,np.nan),where=valid);threshold=_positive(p['ratio_threshold'],'ratio_threshold');frac=_fraction(p['frac_bad'],'frac_bad');mask=valid&(ratio>threshold);den=valid.sum(axis=1);rate=np.divide(mask.sum(axis=1),den,out=np.full(len(names),np.nan),where=den>0)
    return _result(x,names,windows_samples=bounds,frequencies_Hz=f,line_mean_PSD_V2_Hz=line,background_mean_PSD_V2_Hz=bg,ratio=ratio,valid_window_mask=valid,bad_window_mask=mask,valid_denominator=den,bad_fraction=rate,candidates=_candidates(names,rate>frac),undefined_channels=_candidates(names,den==0),welch={'window':'periodic Hann','detrend':'constant','nperseg':nper,'noverlap':int(np.floor(nper*overlap)),'nfft':nfft})
