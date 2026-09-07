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
from scipy import linalg

def _lagged(a,lags,spacing=1,single=True):
    blocks=[]
    for lag in range(0 if single else -lags,lags+1):
        shift=lag*spacing;b=np.roll(a,shift,axis=1)
        if shift>0:b[:,:shift]=0
        elif shift<0:b[:,shift:]=0
        blocks.append(b)
    return np.vstack(blocks)

def _inverse_sqrt(a):
    v,q=linalg.eigh(a)
    if v[0]<=v[-1]*1e-12: raise ValueError('协方差秩不足；先处理坏道或降低延迟维度')
    return (q/np.sqrt(v))@q.T

def eeg_cca(op,x,model=None,**p):
    y=_raw(x)
    if op=='cca_fit':
        if model is not None: raise ValueError('fit 不接受已有模型')
        p=_exact(p,'scope reference_id',lags=1)
        _scope(p['scope'],('train','calibration'));_ref(p['reference_id']);_integer(p['lags'],'lags',1)
        picks=_good(y);a=y.get_data(picks=picks);c,n=a.shape
        if p['lags']>=n or n<=c*p['lags']+1: raise ValueError('样点不足以估计延迟协方差')
        delayed=_lagged(a,p['lags'])[c:]
        ac=a-a.mean(1,keepdims=True);bc=delayed-delayed.mean(1,keepdims=True)
        Cxx=ac@ac.T/(n-1);Cyy=bc@bc.T/(n-1);Cxy=ac@bc.T/(n-1)
        ix=_inverse_sqrt(Cxx);iy=_inverse_sqrt(Cyy)
        U,s,Vt=linalg.svd(ix@Cxy@iy,full_matrices=False)
        W=U.T@ix;A=linalg.inv(W)
        est=dict(unmixing=W,mixing=A,correlations=np.clip(s,0,1),picks=picks,lags=p['lags'])
        fitted=_fitted('cca',est,y,p['scope'],p['reference_id'])
        return _out(y,fitted,canonical_correlations=est['correlations'],components=W@a)
    if op=='cca_apply':
        p=_exact(p,'exclude reference_id decision_id');est=_same(model,'cca',y,p['reference_id']);_ref(p['decision_id'])
        exclude=p['exclude']
        if not isinstance(exclude,(list,tuple)) or len(set(exclude))!=len(exclude): raise ValueError('exclude 需要唯一整数列表')
        for k in exclude:_integer(k,'exclude')
        if any(k>=len(est['picks']) for k in exclude): raise ValueError('CCA 成分索引越界')
        components=est['unmixing']@y.get_data(picks=est['picks'])
        removed=est['mixing'][:,exclude]@components[exclude]
        y._data[est['picks']]-=removed
        return _out(y,model,removed=removed,exclude=list(exclude),decision_id=p['decision_id'],components=components)
    raise NotImplementedError(op)
