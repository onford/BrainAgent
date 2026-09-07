import numpy as np
import mne
import hashlib
import json
import copy
from scipy import stats, signal
from importlib.metadata import version

def _params(p, required=(), **defaults):
    if set(required)-set(p) or set(p)-set(defaults)-set(required):raise ValueError('missing or unknown parameters')
    return dict(defaults,**p)

def _identity_value(value):
    if isinstance(value,np.ndarray):
        if value.dtype.hasobject:raise TypeError('ICA identity cannot encode object arrays')
        if value.dtype.kind in 'fc' and not np.isfinite(value).all():raise ValueError('ICA identity parameters must be finite')
        return {'__ndarray__':{'dtype':value.dtype.str,'shape':list(value.shape),'sha256':hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()}}
    if isinstance(value,np.generic):return _identity_value(value.item())
    if value is None or isinstance(value,(str,bool,int)):return value
    if isinstance(value,float):
        if not np.isfinite(value):raise ValueError('ICA identity parameters must be finite')
        return value
    if isinstance(value,(list,tuple)):return [_identity_value(v) for v in value]
    if isinstance(value,dict):
        if any(not isinstance(k,str) for k in value):raise TypeError('ICA identity dictionary keys must be strings')
        return {k:_identity_value(value[k]) for k in sorted(value)}
    raise TypeError('Unsupported ICA identity parameter type: '+type(value).__name__)

def _component_id(ic):
    metadata=dict(method=ic.method,n_components=int(ic.n_components_),fit_params=ic.fit_params,ch_names=ic.ch_names)
    h=hashlib.sha256(json.dumps(_identity_value(metadata),sort_keys=True,allow_nan=False).encode())
    for a in (ic.unmixing_matrix_,ic.mixing_matrix_,ic.pca_components_,ic.pre_whitener_,ic.pca_mean_):
        h.update(str(np.shape(a)).encode());h.update(np.asarray(a,dtype='<f8').tobytes())
    h.update('\0'.join(ic.ch_names).encode())
    return h.hexdigest()

def _signature(x):
    projs=tuple((p['desc'],int(p['kind']),bool(p['active']),tuple(p['data']['col_names']),hashlib.sha256(np.asarray(p['data']['data']).tobytes()).hexdigest()) for p in x.info['projs'])
    return (tuple(x.ch_names),tuple(x.get_channel_types()),tuple(x.info['bads']),int(x.info['custom_ref_applied']),projs)

def _bind(x,model,reference_id):
    if not isinstance(x,(mne.io.BaseRaw,mne.BaseEpochs)):raise TypeError('requires Raw or Epochs')
    if isinstance(x,mne.BaseEpochs) and not x.preload:raise ValueError('Epochs must be loaded before assessment')
    if not isinstance(reference_id,str) or not reference_id.strip():raise ValueError('reference_id required')
    if not isinstance(model,dict) or model.get('kind')!='ica' or not isinstance(model.get('estimator'),mne.preprocessing.ICA):raise ValueError('requires fitted ICA model envelope')
    ic=model['estimator']
    if model.get('signature')!=_signature(x) or model.get('sfreq')!=float(x.info['sfreq']) or model.get('reference_id')!=reference_id:raise ValueError('model/data signature, sampling or reference mismatch')
    if float(ic.info['sfreq'])!=float(x.info['sfreq']):raise ValueError('estimator sampling frequency differs from data')
    if not hasattr(ic,'n_components_') or ic.n_components_<2:raise ValueError('at least two fitted components required')
    if not set(ic.ch_names)<=set(x.ch_names):raise ValueError('ICA channels missing')
    y=x.copy().load_data()
    if not np.isfinite(y.get_data()).all():raise ValueError('data must be finite')
    sources=ic.get_sources(y).get_data()
    if sources.ndim==2:sources=sources[None]
    if not np.isfinite(sources).all():raise ValueError('component activations must be finite')
    return y,ic,sources

def _finite(v,name,positive=False):
    if isinstance(v,(bool,np.bool_)) or not np.isscalar(v) or not np.isfinite(v) or (positive and v<=0):raise ValueError(name+' must be finite numeric'+(' and positive' if positive else ''))
    return float(v)

def _data_id(y):
    h=hashlib.sha256(np.asarray(y.get_data(),dtype='<f8').tobytes());h.update(np.asarray(y.times,dtype='<f8').tobytes())
    if isinstance(y,mne.BaseEpochs):h.update(np.asarray(y.events,dtype='<i8').tobytes());h.update(np.asarray(y.selection,dtype='<i8').tobytes())
    else:h.update(str(y.first_samp).encode())
    return h.hexdigest()

def _out(y,model,ic,**art):
    return {'data':y,'model':copy.deepcopy(model),'artifacts':{'component_id':_component_id(ic),'component_indices':np.arange(ic.n_components_,dtype=int),**art}}

def eeg_faster_ic(op,x,model=None,**p):
    if op!='faster_ic_assess':raise ValueError('operation must be faster_ic_assess')
    p=_params(p,('reference_id',),metrics=['eog_correlation','kurtosis','power_gradient','hurst','median_gradient'],threshold=3.,max_iter=1,power_range_Hz=None)
    if not isinstance(x,mne.BaseEpochs):raise TypeError('FASTER IC requires Epochs')
    y,ic,sources=_bind(x,model,p['reference_id'])
    if version('mne-faster')!='1.2.2':raise RuntimeError('requires mne-faster==1.2.2')
    from mne_faster import faster as mf
    from mne.preprocessing.bads import _find_outliers
    metrics=p['metrics'];allowed={'eog_correlation','kurtosis','power_gradient','hurst','median_gradient','line_noise'}
    if not isinstance(metrics,(list,tuple)) or not metrics or len(set(metrics))!=len(metrics) or set(metrics)-allowed:raise ValueError('metrics must be nonempty unique supported names')
    threshold=_finite(p['threshold'],'threshold',True);iters=p['max_iter']
    if not isinstance(iters,int) or isinstance(iters,bool) or iters<1:raise ValueError('max_iter must be positive integer')
    flat=sources.transpose(1,0,2).reshape(ic.n_components_,-1)
    prange=p['power_range_Hz']
    if 'power_gradient' in metrics:
        if prange is None:prange=[ic.info['highpass'],ic.info['lowpass']]
        prange=np.asarray(prange,float)
        if prange.shape!=(2,) or not np.isfinite(prange).all() or prange[0]<0 or prange[1]<=prange[0] or prange[1]>y.info['sfreq']/2:raise ValueError('invalid power gradient range')
        ff,_=mf._efficient_welch(flat,float(y.info['sfreq']))
        if np.searchsorted(ff,prange[1])-np.searchsorted(ff,prange[0])<2:raise ValueError('fewer than two gradient spectrum bins')
    elif prange is not None:raise ValueError('power_range_Hz requires power_gradient metric')
    if 'line_noise' in metrics and y.info['sfreq']/2<60:raise ValueError('line_noise requires 60 Hz within Nyquist')
    if 'eog_correlation' in metrics and not len(mne.pick_types(y.info,eog=True)):raise ValueError('eog_correlation requires typed EOG channels')
    evaluations={
        'eog_correlation':lambda:ic.copy().find_bads_eog(y)[1],
        'kurtosis':lambda:stats.kurtosis(np.dot(ic.mixing_matrix_.T,ic.pca_components_[:ic.n_components_]),axis=1),
        'power_gradient':lambda:mf._power_gradient(flat,float(ic.info['sfreq']),prange),
        'hurst':lambda:mf.hurst(flat),
        'median_gradient':lambda:np.median(abs(np.diff(flat)),axis=1),
        'line_noise':lambda:mf._freqs_power(flat,float(y.info['sfreq']),[50,60])}
    scores={};by={};history={};statuses={}
    for metric in metrics:
        values=np.atleast_2d(evaluations[metric]());scores[metric]=values;by[metric]=[];history[metric]=[];statuses[metric]=[]
        for values_row in values:
            if values_row.shape!=(ic.n_components_,):raise ValueError('metric component axis mismatch')
            valid=np.isfinite(values_row).all() and np.std(values_row)>0
            statuses[metric].append('defined' if valid else 'undefined')
            if not valid:history[metric].append([]);continue
            indices=_find_outliers(values_row,threshold,iters);by[metric].extend(indices.tolist())
            mask=np.zeros(ic.n_components_,bool);trace=[]
            for iteration in range(iters):
                active=~mask;center=values_row[active].mean();scale=values_row[active].std(ddof=0)
                zz=np.divide(values_row-center,scale,out=np.full_like(values_row,np.nan),where=scale>0);new=active&(np.abs(zz)>threshold)
                trace.append({'center':float(center),'scale':float(scale),'z':zz,'active':active.copy(),'new_outlier_mask':new.copy()});mask|=new
                if not new.any():break
            history[metric].append(trace)
        by[metric]=sorted(set(by[metric]))
    candidate=sorted(set(c for ids in by.values() for c in ids))
    p['power_range_Hz']=None if prange is None else np.asarray(prange).tolist()
    p['metrics']=list(metrics);p['threshold']=threshold
    return _out(y,model,ic,assessment_id=hashlib.sha256((_component_id(ic)+_data_id(y)+json.dumps(p,sort_keys=True)).encode()).hexdigest(),scores=scores,criterion_candidates=by,candidate_indices=np.array(candidate,dtype=int),z_history=history,statuses=statuses,metrics=metrics,threshold=threshold,max_iter=iters,power_range_Hz=None if prange is None else np.asarray(prange),epoch_selection=x.selection.copy(),algorithm='mne-faster 1.2.2 IC stage',normalization='iterative absolute population z-score across all fitted ICs')
