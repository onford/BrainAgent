# Python 3.12 | MNE 1.10.2 | NumPy 1.26.4 | SciPy 1.15.3 | scikit-learn 1.6.1
import numpy as np
import mne
import warnings
from sklearn.exceptions import ConvergenceWarning
from numbers import Integral, Real

def _number(value, name, low=None, high=None, strict_low=False):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) or (not np.isfinite(value)):
        raise ValueError(name + '需要有限实数标量')
    if low is not None and (value <= low if strict_low else value < low):
        raise ValueError(name + '低于允许范围')
    if high is not None and value > high:
        raise ValueError(name + '高于允许范围')

def _args(p, keys):
    expected = set(keys.split())
    if set(p) != expected:
        raise ValueError(f'参数缺失={expected - set(p)}; 未定义={set(p) - expected}')

    def finite(value):
        if isinstance(value, (bool, np.bool_)) or (isinstance(value, np.ndarray) and value.dtype.kind == 'b'):
            raise TypeError('数值参数不能使用布尔值')
        if isinstance(value, np.ndarray) and value.dtype.hasobject:
            finite(value.tolist())
        if isinstance(value, (float, complex, np.number)) and (np.iscomplexobj(value) or not np.isfinite(value)):
            raise ValueError('参数必须为有限实数')
        if isinstance(value, np.ndarray) and value.dtype.kind in 'fc' and (np.iscomplexobj(value) or not np.isfinite(value).all()):
            raise ValueError('数组参数包含复数/NaN/Inf')
        if type(value) is dict:
            for item in value.values():
                finite(item)
        if isinstance(value, (list, tuple)):
            for item in value:
                finite(item)
    for (key, value) in p.items():
        if isinstance(value, (bool, np.bool_)):
            raise TypeError(f'{key} 不接受布尔值代替数值/枚举')
        if key not in {'models', 'artifacts', 'forward', 'projs', 'montage', 'annotations'}:
            finite(value)

def _copy(x):
    if not isinstance(x, (mne.io.BaseRaw, mne.BaseEpochs)):
        raise TypeError('需要 MNE Raw/Epochs，电位单位 V')
    if isinstance(x, mne.BaseEpochs) and (not x.preload):
        raise ValueError('Epochs须已preload并记录已有drop_log，禁止普通操作隐式加载/剔除Trial')
    y = x.copy().load_data()
    values = y.get_data()
    if not values.size or np.iscomplexobj(values) or (not np.isfinite(values).all()):
        raise ValueError('空数据、复数或 NaN/Inf，先返回接入异常流程')
    return y

def _scope(s, roles=('train',)):
    if not isinstance(s, dict) or set(s) != {'role', 'ids'} or s['role'] not in roles:
        raise ValueError('scope={role,ids}；仅使用允许的训练/校准对象')
    _ids(s['ids'])

def _ids(ids):
    if not isinstance(ids, (list, tuple)) or not ids or any((not isinstance(i, str) or not i.strip() for i in ids)) or (len(set(ids)) != len(ids)):
        raise ValueError('ID 必须为非空、唯一的字符串列表')

def _integer(v, name, minimum=0):
    if isinstance(v, bool) or not isinstance(v, Integral) or v < minimum:
        raise ValueError(f'{name} 需要 >= {minimum} 的整数')

def _channels(x, names, kind='eeg'):
    _ids(names)
    valid = {n for (n, t) in zip(x.ch_names, x.get_channel_types()) if t == kind}
    if not set(names) <= valid:
        raise ValueError(f'需要已有 {kind} 通道列表')

def _signature(x):
    import hashlib
    projs = tuple(((p['desc'], int(p['kind']), bool(p['active']), tuple(p['data']['col_names']), hashlib.sha256(np.asarray(p['data']['data']).tobytes()).hexdigest()) for p in x.info['projs']))
    return (tuple(x.ch_names), tuple(x.get_channel_types()), tuple(x.info['bads']), int(x.info['custom_ref_applied']), projs)

def _model(m, kind, x=None):
    if not isinstance(m, dict) or m.get('kind') != kind:
        raise ValueError('模型种类不匹配')
    if x is not None and m['signature'] != _signature(x):
        raise ValueError('通道/顺序/bads/参考/投影与拟合数据不兼容')
    if 'estimator' not in m:
        raise ValueError('模型缺 estimator')
    return m['estimator']

def _out(data=None, model=None, **artifacts):

    def finite(v):
        if isinstance(v, (mne.io.BaseRaw, mne.BaseEpochs)):
            v = v.get_data()
        if isinstance(v, mne.time_frequency.BaseTFR):
            v = v.data
        if isinstance(v, np.ndarray) and (not v.size or not np.isfinite(v).all()):
            raise ValueError('输出为空或包含 NaN/Inf')
        if isinstance(v, (list, tuple)):
            for item in v:
                finite(item)
    finite(data)
    if isinstance(model, dict):
        finite(model.get('estimator'))
    return {'data': data, 'model': model, 'artifacts': artifacts}


def _exact(p, required='', **defaults):
    required=set(required.split())
    if required-set(p) or set(p)-required-set(defaults):
        raise ValueError(f'参数缺失={required-set(p)}; 未定义={set(p)-required-set(defaults)}')
    return dict(defaults, **p)

def _raw(x):
    y=_copy(x)
    if not isinstance(y,mne.io.BaseRaw): raise TypeError('需要连续 Raw')
    return y

def _epochs(x):
    y=_copy(x)
    if not isinstance(y,mne.BaseEpochs): raise TypeError('需要已加载 Epochs')
    return y

def _good(y, minimum=2):
    picks=mne.pick_types(y.info,eeg=True,exclude='bads')
    if len(picks)<minimum: raise ValueError(f'至少需要 {minimum} 个好 EEG 通道')
    return picks

def _ref(s):
    if not isinstance(s,str) or not s.strip(): raise ValueError('需要非空 reference_id')

def _mask(a,shape,name='mask'):
    a=np.asarray(a)
    if a.dtype.kind!='b' or a.shape!=shape: raise ValueError(f'{name} 需要形状 {shape} 的布尔数组')
    return a

def _finite_array(a,name,ndim=None):
    a=np.asarray(a)
    if a.dtype.kind not in 'fiu' or not np.isfinite(a).all() or (ndim is not None and a.ndim!=ndim):
        raise ValueError(name+'需要有限实数数组')
    return a.astype(float,copy=False)

def _same(model,kind,y,reference_id):
    est=_model(model,kind,y)
    if model.get('reference_id')!=reference_id or model.get('sfreq',float(y.info['sfreq']))!=float(y.info['sfreq']):
        raise ValueError('参考/采样率与模型不匹配')
    return est

def _fitted(kind,est,y,scope,reference_id,**extra):
    return dict(kind=kind,estimator=est,signature=_signature(y),sfreq=float(y.info['sfreq']),scope=scope,reference_id=reference_id,**extra)

def _probs(v,n):
    a=_finite_array(v,'probabilities',2)
    if a.shape!=(n,7) or np.any(a<0) or np.any(a>1) or not np.allclose(a.sum(1),1,atol=1e-5):
        raise ValueError('probabilities 需要 IC×7 概率且逐行和为 1')
    return a
# RELAX v2.0.1 formula port, GPL-3.0-or-later; original: Neil Bailey et al.
# Source: 318300217bdb7ed47a19a892fed16690c5bb77b4, RELAX_targeted_wICA.m.
import hashlib
import json

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


def _source_maps(ic,y):
    if ic.noise_cov is not None: raise ValueError('此适配器要求 ICA noise_cov=None')
    # EEGLAB activations are W @ data, without subtracting ICA fitting means.
    values=y.get_data(picks=ic.ch_names)/ic.pre_whitener_
    S=(ic.unmixing_matrix_@ic.pca_components_[:ic.n_components_])@values
    A=ic.get_components()*ic.pre_whitener_
    return S,A

def _wavelet_artifact(s, multiplier):
    import pywt
    n=len(s); padded=np.pad(s,(0,(-n)%32))
    # ddencmp('den','wv'): Haar detail MAD / 0.6745, universal threshold.
    _,detail=pywt.dwt(padded,'db1',mode='periodization')
    threshold=float(multiplier*np.median(np.abs(detail))/0.6745*np.sqrt(2*np.log(len(padded))))
    coeffs=pywt.swt(padded,'coif5',level=5,trim_approx=True,norm=False)
    clean_coeffs=[np.sign(a)*np.maximum(np.abs(a)-threshold,0) for a in coeffs]
    artifact=pywt.iswt(clean_coeffs,'coif5',norm=False)[:n]
    return artifact,threshold

def _relax_muscle_slopes(S,fs,line_freq):
    from scipy.signal import welch
    N=S.shape[1]
    fp,psd=welch(S,fs=fs,window=np.hamming(N),nperseg=N,noverlap=N//2,nfft=N,detrend=False,axis=-1)
    freq=np.arange(1.,100.01,.5)
    bins=np.stack([psd[:,np.argmin(abs(fp-(f-.25))):np.argmin(abs(fp-(f+.25)))+1].mean(1) for f in freq],axis=1)
    keep=(freq>=7)&(freq<=70)
    if line_freq is not None:
        indices=np.flatnonzero(keep);selected=freq[indices]
        lo=np.argmin(abs(selected-(line_freq-2)));hi=np.argmin(abs(selected-(line_freq+2)))
        keep[indices[lo:hi+1]]=False
    if np.any(bins[:,keep]<=0): raise ValueError('IC 的谱功率退化，无法计算 log-log 肌电斜率')
    slopes=np.polyfit(np.log(freq[keep]),np.log(bins[:,keep]).T,1)[0]
    return slopes,freq,bins

def eeg_wica(op,x,model=None,**p):
    if op!='wica_apply': raise NotImplementedError(op)
    y=_raw(x)
    if p.get('variant')=='ordinary' and set(p)&{'eye_weights','extra_eye','line_freq','muscle_slope'}:
        raise ValueError('ordinary 不接受 targeted 眼动/肌电参数')
    p=_exact(p,'variant probabilities component_id decision_id reference_id',
        thresholds=(0.,)*7,clean_other='no',eye_weights=None,extra_eye=None,line_freq=None,muscle_slope=-.31)
    ic=_same(model,'ica',y,p['reference_id'])
    if p['component_id']!=_component_id(ic): raise ValueError('分类决定不属于当前 ICA')
    _ref(p['decision_id'])
    if p['variant'] not in ('ordinary','targeted'): raise ValueError('variant=ordinary|targeted')
    if p['clean_other'] not in ('no','yes'): raise ValueError('clean_other=no|yes')
    probabilities=_probs(p['probabilities'],ic.n_components_)
    thresholds=_finite_array(p['thresholds'],'thresholds',1)
    if thresholds.shape!=(7,) or np.any((thresholds<0)|(thresholds>1)): raise ValueError('七类阈值须在 [0,1]')
    masked=np.where(probabilities>=thresholds,probabilities,0.)
    labels=masked.argmax(1) # all zero ties select brain, matching MATLAB max.
    candidates=(labels!=0) if p['clean_other']=='yes' else np.isin(labels,[1,2])
    eyes=labels==2
    if p['extra_eye'] is not None:
        extra=_mask(p['extra_eye'],(ic.n_components_,),'extra_eye')
        if p['variant']!='targeted': raise ValueError('extra_eye 仅用于 targeted')
        eyes=eyes|extra;candidates=candidates|extra
    S,A=_source_maps(ic,y)
    if S.shape[1]<32: raise ValueError('wICA 至少需要 32 样点')
    artifact=np.zeros_like(S);levels=np.zeros(len(S))
    for k in np.flatnonzero(candidates):
        artifact[k],levels[k]=_wavelet_artifact(S[k],2 if p['variant']=='targeted' and eyes[k] else 1)
    slopes=None;muscles=np.zeros(len(S),dtype=bool);freq=None;bins=None
    if p['variant']=='targeted':
        if y.info['sfreq']<250 or y.info['lowpass']<75: raise ValueError('targeted 肌电检测要求采样率≥250 Hz、输入低通≥75 Hz')
        weights=_finite_array(p['eye_weights'],'eye_weights',2)
        if weights.shape!=S.shape or np.any((weights<0)|(weights>1)): raise ValueError('eye_weights 需要 IC×sample 且范围 [0,1]')
        _number(p['muscle_slope'],'muscle_slope')
        if p['line_freq'] is not None: _number(p['line_freq'],'line_freq',45,65)
        artifact[eyes]*=weights[eyes]
        slopes,freq,bins=_relax_muscle_slopes(S,y.info['sfreq'],p['line_freq'])
        muscles=slopes>=p['muscle_slope']
        if muscles.any():
            from scipy.signal import butter,filtfilt
            b,a=butter(2,15/(y.info['sfreq']/2),'highpass')
            # MATLAB filtfilt's odd extension length, 3*(filter order).
            artifact[muscles]=filtfilt(b,a,S[muscles],axis=-1,padlen=3*(max(len(a),len(b))-1))
    elif p['eye_weights'] is not None or p['line_freq'] is not None or p['extra_eye'] is not None:
        raise ValueError('ordinary 不接受 targeted 的眼动/肌电参数')
    removed=A@artifact
    picks=[y.ch_names.index(n) for n in ic.ch_names]
    y._data[picks]-=removed
    return _out(y,model,component_id=p['component_id'],decision_id=p['decision_id'],labels=labels,
        wavelet_candidates=candidates,eyes=eyes,muscle_candidates=muscles,muscle_slopes=slopes,
        thresholds=levels,original_components=S,artifact_components=artifact,cleaned_components=S-artifact,
        removed=removed,eye_weights=p['eye_weights'],spectral_frequencies=freq,spectral_power=bins,
        variant=p['variant'],source_commit='318300217bdb7ed47a19a892fed16690c5bb77b4')
