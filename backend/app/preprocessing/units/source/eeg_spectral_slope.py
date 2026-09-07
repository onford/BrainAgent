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

def eeg_spectral_slope(op,x,model=None,**p):
    p=_params(p,{'mode':'fieldtrip_mtmfft','frequencies_Hz':list(range(1,76)),'fit_range_Hz':[7.,75.],'excluded_bands_Hz':[],'slope_threshold':-.31,'direction':'above','picks':None,'retained_bandwidth_policy':'require'})
    a,names,sf=_start(op,'spectral_slope',x,model,True,p['picks']);is_ep=isinstance(x,mne.BaseEpochs)
    if not is_ep:a=a[None]
    n=a.shape[-1];freq=np.asarray(p['frequencies_Hz'],float);fit=np.asarray(p['fit_range_Hz'],float)
    if freq.ndim!=1 or len(freq)<2 or np.any(np.diff(freq)<=0) or np.any(freq<=0) or np.any(freq>=sf/2) or not np.isfinite(freq).all() or fit.shape!=(2,) or not np.isfinite(fit).all() or fit[1]<=fit[0]:raise ValueError('invalid frequencies/fit range')
    if p['mode']=='fieldtrip_mtmfft':
        nfft=1<<(n-1).bit_length();f,psd=signal.periodogram(a,fs=sf,window=np.hanning(n),nfft=nfft,detrend='constant',scaling='density',axis=-1);indices=np.floor(freq*nfft/sf+.5).astype(int)
        if len(set(indices))!=len(indices):raise ValueError('requested frequencies collapse onto duplicate FFT bins')
        power=psd[...,indices];actual=f[indices]
        if np.any(actual<=0) or np.any(actual>=sf/2):raise ValueError('rounded FFT frequencies must remain strictly inside (0, Nyquist)')
        bin_bounds=None
    elif p['mode']=='relax_ic_welch':
        f,psd=signal.welch(a,fs=sf,window=np.hamming(n),nperseg=n,noverlap=n//2,nfft=n,detrend=False,scaling='density',axis=-1)
        bins=[(np.argmin(abs(f-(v-.25))),np.argmin(abs(f-(v+.25)))) for v in freq]
        if len(set(bins))!=len(bins):raise ValueError('requested frequencies collapse onto duplicate Welch bins')
        power=np.stack([np.mean(psd[...,lo:hi+1],axis=-1) for lo,hi in bins],axis=-1);actual=np.array([np.mean(f[lo:hi+1]) for lo,hi in bins]);bin_bounds=np.array([[f[lo],f[hi]] for lo,hi in bins])
    else:raise ValueError('unknown spectral estimation mode')
    if p['retained_bandwidth_policy'] not in ('require','author_attenuated'):raise ValueError('retained_bandwidth_policy=require|author_attenuated')
    attenuated=x.info.get('lowpass') is not None and x.info['lowpass']<fit[1]
    if attenuated and p['retained_bandwidth_policy']=='require':raise ValueError('fit range exceeds retained lowpass bandwidth')
    keep=(freq>=fit[0])&(freq<=fit[1]);bands=np.asarray(p['excluded_bands_Hz'],float)
    if bands.size:
        if bands.ndim!=2 or bands.shape[1]!=2 or not np.isfinite(bands).all() or np.any(bands[:,1]<bands[:,0]):raise ValueError('invalid excluded bands')
        for lo,hi in bands:keep&=~((freq>=lo)&(freq<=hi))
    if keep.sum()<2:raise ValueError('fewer than two fitting frequencies')
    xx=np.log(freq[keep]);xx=xx-xx.mean();yy=power[...,keep];valid=np.all(yy>0,axis=-1);slope=np.full(power.shape[:-1],np.nan)
    slope[valid]=(np.log(yy[valid])@xx)/(xx@xx)
    threshold=p['slope_threshold']
    if isinstance(threshold,(bool,np.bool_)) or not np.isscalar(threshold) or not np.isfinite(threshold):raise ValueError('slope threshold must be finite')
    if p['direction']=='above':mask=slope>threshold
    elif p['direction']=='above_or_equal':mask=slope>=threshold
    elif p['direction']=='below':mask=slope<threshold
    else:raise ValueError('direction must be above, above_or_equal or below')
    return _result(x,names,axis_order='epoch, channel',epoch_selection=x.selection.copy() if is_ep else None,requested_frequencies_Hz=freq,actual_frequencies_Hz=actual,welch_bin_bounds_Hz=bin_bounds,power_V2_Hz=power,slope=slope,valid_mask=valid,bad_mask=mask,fit_frequency_mask=keep,mode=p['mode'],retained_bandwidth_policy=p['retained_bandwidth_policy'],fit_exceeds_retained_bandwidth=bool(attenuated))
