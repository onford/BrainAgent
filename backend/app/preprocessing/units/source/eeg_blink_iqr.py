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

def eeg_blink_iqr(op,x,model=None,**p):
    if 'reference_evidence' not in p:raise ValueError('reference_evidence is required')
    p=_params(p,{'blink_channels':['Fp1','Fpz','Fp2','AF3','AF4','F3','F1','Fz','F2','F4'],'lowpass_Hz':25.,'zero_intervals':None,'reference_evidence':p['reference_evidence'],'variant':'relax_2_0_1'})
    if not isinstance(p['blink_channels'],(list,tuple)) or not p['blink_channels'] or len(set(v.lower() for v in p['blink_channels']))!=len(p['blink_channels']):raise ValueError('blink_channels must be unique names')
    names=[n for n in x.ch_names if n.lower() in {s.lower() for s in p['blink_channels']}]
    a,names,sf=_start(op,'blink_iqr',x,model,picks=names)
    ref=p['reference_evidence'];required={'original_channel_names','interpolated_channel_names','zero_reference_included','reference_denominator'}
    if not isinstance(ref,dict) or set(ref)!=required:raise ValueError('reference_evidence requires full original channel axis, interpolated channels, zero reference and denominator')
    original=ref['original_channel_names'];interpolated=ref['interpolated_channel_names']
    if not isinstance(original,list) or len(set(original))!=len(original) or not set(x.ch_names)<=set(original) or not set(interpolated)<=set(original) or ref['zero_reference_included'] is not True or ref['reference_denominator']!=len(original)+1:raise ValueError('expected RELAX detection reference: restored original electrodes plus zero initial reference, then original good-axis selection')
    if p['lowpass_Hz'] not in (6.,25.) or sf<=2*p['lowpass_Hz']:raise ValueError('lowpass_Hz must be 6 or 25 and below Nyquist')
    if p['variant'] not in ('relax_2_0_1','repaired_indices'):raise ValueError('unknown blink variant')
    b,aa=signal.butter(2,[1.,p['lowpass_Hz']],btype='bandpass',fs=sf);padlen=3*(max(len(aa),len(b))-1)
    if a.shape[-1]<=padlen:raise ValueError('insufficient samples for blink filter')
    filtered=signal.filtfilt(b,aa,a,axis=-1,padlen=padlen)
    if p['zero_intervals'] is not None and np.asarray(p['zero_intervals']).size:
        for lo,hi in _segments(x,p['zero_intervals']):filtered[:,lo:hi]=0
    trace=np.mean(filtered,axis=0);q25,q75=np.quantile(trace,[.25,.75],method='hazen');threshold=q75+3*(q75-q25)
    exceed=trace>threshold
    if p['variant']=='relax_2_0_1':
        assigned=np.flatnonzero(trace!=threshold)
        if not len(assigned):raise ValueError('RELAX legacy never initializes its blink metric when all samples equal threshold')
        metric=exceed[:assigned[-1]+1]
    else:metric=exceed
    starts=np.flatnonzero(np.diff(metric.astype(int))==1)+1;ends=np.flatnonzero(np.diff(metric.astype(int))==-1)
    if len(starts) and not len(ends) and p['variant']=='relax_2_0_1':raise ValueError('RELAX legacy has an unclosed blink run')
    pairs=[(int(s),int(ends[ends>=s][0])) for s in starts if np.any(ends>=s)]
    min_len=int(np.floor(.05*sf+.5));peaks=[];mask=np.zeros(len(trace),bool);events=[];detected=False;edge_discarded=[]
    for s,e in pairs:
        if e-s<=min_len:continue
        peak=s+int(np.argmax(trace[s:e+1]))+(1 if p['variant']=='relax_2_0_1' else 0);peaks.append(peak);left=peak-.4*sf;right=peak+.4*sf
        lo=int(np.floor(left+.5));hi=int(np.floor(right+.5))
        if lo>=0 and hi<len(trace)-1:
            mask[lo:hi+1]=True;events.append({'peak_raw_sample':peak+x.first_samp,'left_base_raw_sample':left+x.first_samp,'right_base_raw_sample':right+x.first_samp});detected=True
        else:
            edge_discarded.append(peak)
            if p['variant']=='relax_2_0_1':detected=False
    return _result(x,names,trace_V=trace,threshold_V=threshold,threshold_exceeded_mask=exceed,legacy_metric_sample_count=len(metric),blink_mask=mask,peak_samples=np.asarray(peaks,dtype=int),events=events,detected_blinks=detected,edge_discarded_peaks=edge_discarded,reference_evidence=ref,variant=p['variant'],legacy_behavior={'peak_plus_one':p['variant']=='relax_2_0_1','edge_peak_resets_detected_flag':p['variant']=='relax_2_0_1'})
