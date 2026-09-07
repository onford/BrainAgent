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

def _zscore(a,axis):
    center=np.mean(a,axis=axis,keepdims=True);scale=np.std(a,axis=axis,ddof=1,keepdims=True)
    return (a-center)/np.where(scale==0,1,scale)

def _threshold(value,data,direction):
    if isinstance(value,str):
        import re
        match=re.fullmatch(r'auto(?: ([0-9]+(?:\.[0-9]+)?))?',value)
        if not match:raise ValueError('threshold string must be auto or auto N')
        n=2. if match[1] is None else float(match[1]);return np.mean(data,axis=-1)+direction*n*np.std(data,axis=-1,ddof=1)
    return _finite(value,'threshold')

def _corr(a,b):
    aa=a-a.mean(axis=-1,keepdims=True);bb=b-b.mean(axis=-1,keepdims=True);den=np.sqrt(np.sum(aa*aa,axis=-1)[:,None]*np.sum(bb*bb,axis=-1)[None,:]);return np.divide(aa@bb.T,den,out=np.full((len(a),len(b)),np.nan),where=den>0)

def eeg_sasica(op,x,model=None,**p):
    if op!='sasica_assess':raise ValueError('operation must be sasica_assess')
    p=_params(p,('reference_id','criteria'),external_assessments={},review=None)
    y,ic,s=_bind(x,model,p['reference_id']);n=ic.n_components_;cid=_component_id(ic)
    cfg=p['criteria'];defaults={'autocorr':{'lag_ms':20.,'threshold':'auto'},'focalcomp':{'threshold':'auto'},'trialfoc':{'threshold':'auto'},'snr':{'signal_interval_s':[0.,.5],'baseline_interval_s':[-.5,0.],'threshold':1.},'eogcorr':{'vertical_channels':[],'horizontal_channels':[],'vertical_threshold':'auto 4','horizontal_threshold':'auto 4'},'chancorr':{'channels':[],'threshold':'auto 4'}}
    if not isinstance(cfg,dict) or set(cfg)-set(defaults):raise ValueError('unsupported SASICA criterion')
    external=p['external_assessments']
    if not isinstance(external,dict) or set(external)-{'EEG-ADJUST','EEG-FASTER-IC'}:raise ValueError('unsupported external assessment')
    if not cfg and not external:raise ValueError('at least one criterion required')
    flat=s.transpose(1,0,2).reshape(n,-1);scores={};thresholds={};masks={};valid={};bindings={}
    def save(name,score,threshold,direction):
        score=np.asarray(score,float).reshape(n);threshold=np.broadcast_to(threshold,(n,)).copy();good=np.isfinite(score)&np.isfinite(threshold)
        scores[name]=score;thresholds[name]=threshold;valid[name]=good;masks[name]=good&((score>threshold) if direction>0 else (score<threshold))
    def channel_signal(names):
        if not isinstance(names,(list,tuple)) or len(names) not in (1,2) or len(set(names))!=len(names) or any(c not in y.ch_names for c in names):raise ValueError('specify one channel or two distinct channels to subtract')
        a=y.get_data(picks=list(names))
        if a.ndim==2:a=a[None]
        a=a.transpose(1,0,2).reshape(len(names),-1);return a[:1] if len(names)==1 else a[:1]-a[1:2]
    for name,parameters in cfg.items():
        if not isinstance(parameters,dict):raise ValueError('criterion config must be dict')
        q=_params(parameters,**defaults[name]);bindings[name]=q
        if name=='autocorr':
            lag=int(np.floor(_finite(q['lag_ms'],'lag_ms',True)*y.info['sfreq']/1000+.5))
            if lag<1 or lag>=s.shape[-1]:raise ValueError('autocorrelation lag must span 1..n_times-1 samples')
            average=s.mean(axis=0);den=np.sum(average*average,axis=-1);score=np.divide(np.sum(average[:,:-lag]*average[:,lag:],axis=-1),den,out=np.full(n,np.nan),where=den>0);save(name,score,_threshold(q['threshold'],score,-1),-1)
        elif name=='focalcomp':
            maps=ic.get_components();score=np.max(abs(_zscore(maps,0)),axis=0);save(name,score,_threshold(q['threshold'],score,1),1)
        elif name=='trialfoc':
            if not isinstance(y,mne.BaseEpochs) or len(y)<2:raise ValueError('trialfoc requires multiple Epochs')
            ptp=np.ptp(s,axis=-1).T;score=np.max(abs(_zscore(ptp,1)),axis=1);save(name,score,_threshold(q['threshold'],score,1),1)
        elif name=='snr':
            if not isinstance(y,mne.BaseEpochs):raise ValueError('SNR requires Epochs')
            windows=[]
            for key in ('signal_interval_s','baseline_interval_s'):
                bounds=np.asarray(q[key],float)
                if bounds.shape!=(2,) or np.isnan(bounds).any() or bounds[1]<bounds[0]:raise ValueError('invalid SNR time window')
                mask=(y.times>=bounds[0])&(y.times<=bounds[1])
                if mask.sum()<2:raise ValueError('SNR time window needs at least two samples')
                windows.append(mask)
            zz=_zscore(s,-1).mean(axis=0);num=np.std(zz[:,windows[0]],axis=1,ddof=1);den=np.std(zz[:,windows[1]],axis=1,ddof=1);score=np.divide(num,den,out=np.full(n,np.nan),where=den>0);save(name,score,_finite(q['threshold'],'SNR threshold'),-1)
        elif name=='eogcorr':
            if not q['vertical_channels'] and not q['horizontal_channels']:raise ValueError('at least one EOG signal required')
            for label in ('vertical','horizontal'):
                if q[label+'_channels']:
                    score=abs(_corr(flat,channel_signal(q[label+'_channels']))[:,0]);save(name+'_'+label,score,_threshold(q[label+'_threshold'],score,1),1)
        elif name=='chancorr':
            names=q['channels']
            if not isinstance(names,(list,tuple)) or not names or len(set(names))!=len(names) or any(c not in y.ch_names for c in names):raise ValueError('channels must be existing unique channel names')
            a=y.get_data(picks=list(names));a=a[None] if a.ndim==2 else a;a=a.transpose(1,0,2).reshape(len(names),-1);matrix=abs(_corr(flat,a)).T;threshold=float(np.mean(_threshold(q['threshold'],matrix,1)));score=np.max(matrix,axis=0);save(name,score,threshold,1);scores['chancorr_matrix']=matrix
    for mid,assessment in external.items():
        if not isinstance(assessment,dict) or set(assessment)!={'component_id','candidate_indices','assessment_id','algorithm'} or assessment['component_id']!=cid or not isinstance(assessment['assessment_id'],str) or not assessment['assessment_id'] or not isinstance(assessment['algorithm'],str) or not assessment['algorithm']:raise ValueError('external assessment identity missing or mismatched')
        indices=np.asarray(assessment['candidate_indices'])
        if indices.ndim!=1 or (indices.size and indices.dtype.kind not in 'iu') or len(set(indices.tolist()))!=len(indices) or np.any(indices<0) or np.any(indices>=n):raise ValueError('invalid external component indices')
        mask=np.zeros(n,bool);mask[indices.astype(int)]=True;masks[mid]=mask;bindings[mid]=copy.deepcopy(assessment)
    candidate=np.any(np.stack(list(masks.values())),axis=0);assessment_id=hashlib.sha256((cid+_data_id(y)+json.dumps(bindings,sort_keys=True,default=lambda a:np.asarray(a).tolist())).encode()).hexdigest()
    decisions=['pending']*n;review=p['review']
    if review is not None:
        from datetime import datetime
        if not isinstance(review,dict) or set(review)!={'component_id','assessment_id','reviewer','timestamp','decisions'} or review['component_id']!=cid or review['assessment_id']!=assessment_id:raise ValueError('human review must bind this exact assessment')
        if not isinstance(review['reviewer'],str) or not review['reviewer'].strip():raise ValueError('reviewer required')
        parsed=datetime.fromisoformat(review['timestamp'])
        if parsed.tzinfo is None:raise ValueError('review timestamp needs timezone')
        if not isinstance(review['decisions'],dict):raise ValueError('decisions must map component indices to exclude/keep/pending')
        for key,value in review['decisions'].items():
            if not isinstance(key,str) or not key.isdigit() or str(int(key))!=key or int(key)>=n or value not in ('exclude','keep','pending'):raise ValueError('invalid component decision')
            decisions[int(key)]=value
    confirmed=np.array([i for i,d in enumerate(decisions) if d=='exclude'],dtype=int)
    return _out(y,model,ic,assessment_id=assessment_id,scores=scores,thresholds=thresholds,valid_masks=valid,criterion_masks=masks,candidate_indices=np.flatnonzero(candidate),decisions=decisions,confirmed_exclude_indices=confirmed,review=copy.deepcopy(review),config=bindings,topographies=ic.get_components(),topography_channel_names=ic.ch_names,component_times_s=y.times.copy(),epoch_average_activations=s.mean(axis=0),algorithm='SASICA 9ab76 core numerical criteria; explicit external ADJUST/FASTER composition')
