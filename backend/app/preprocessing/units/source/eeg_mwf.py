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
# Somers/ExpORL MWF numerical equations, source commit 85115641b36b711a4263eeb83f60e4706ea4e732.
# Numerical formulation: Somers et al., J Neural Engineering (2018), doi:10.1088/1741-2552/aaac92.
# Upstream validation reference has a KU Leuven internal academic-use license; do not redistribute vendor files.
from scipy import linalg

def _lagged(a,lags,spacing=1,single=False):
    blocks=[]
    for lag in range(0 if single else -lags,lags+1):
        shift=lag*spacing;b=np.roll(a,shift,axis=1)
        if shift>0:b[:,:shift]=0
        elif shift<0:b[:,shift:]=0
        blocks.append(b)
    return np.vstack(blocks)

def eeg_mwf(op,x,model=None,**p):
    y=_raw(x)
    if op=='mwf_fit':
        if model is not None: raise ValueError('fit 不接受模型')
        p=_exact(p,'mask scope reference_id mask_id',delay=0,delay_spacing=1,singlesided=False,rank='poseig',rankopt=1,treatnans='ignore',mu=1.)
        _scope(p['scope'],('train','calibration'));_ref(p['reference_id']);_ref(p['mask_id'])
        _integer(p['delay'],'delay');_integer(p['delay_spacing'],'delay_spacing',1);_number(p['mu'],'mu',1)
        if not isinstance(p['singlesided'],(bool,np.bool_)): raise ValueError('singlesided 需要 bool')
        picks=_good(y);a=y.get_data(picks=picks);c,n=a.shape
        if p['delay']*p['delay_spacing']>=n: raise ValueError('延迟超过记录长度')
        mask=np.asarray(p['mask'],float)
        if mask.shape!=(n,) or np.isinf(mask).any() or not np.isin(mask[np.isfinite(mask)],[0,1]).all(): raise ValueError('mask 为逐样点 0/1/NaN')
        mask=mask.copy()
        if p['treatnans']=='artifact':mask[np.isnan(mask)]=1
        elif p['treatnans']=='clean':mask[np.isnan(mask)]=0
        elif p['treatnans']!='ignore':raise ValueError('treatnans=ignore|artifact|clean')
        stacked=_lagged(a,p['delay'],p['delay_spacing'],p['singlesided']);m=len(stacked)
        if min(np.sum(mask==0),np.sum(mask==1))<=m: raise ValueError('干净/伪迹样点必须各多于延迟维度')
        Ryy=np.cov(stacked[:,mask==1]);Rnn=np.cov(stacked[:,mask==0])
        try: values,V=linalg.eigh(Ryy,Rnn)
        except linalg.LinAlgError as e:raise ValueError('MWF 干净协方差非正定，需减小延迟或处理秩') from e
        order=np.argsort(values)[::-1];values=values[order];V=V[:,order]
        if values[-1]<=values[0]*1e-12:raise ValueError('MWF 伪迹协方差秩不足')
        if not np.allclose(V.T@Rnn@V,np.eye(m),atol=1e-2):raise ValueError('MWF 广义特征向量缩放不稳定')
        Delta=V.T@(Ryy-Rnn)@V
        if p['rank']=='poseig':rank=m-int(np.sum(np.diag(Delta)<0))
        elif p['rank']=='full':rank=m
        elif p['rank']=='pct':
            _number(p['rankopt'],'rankopt',0,100,True);rank=int(np.ceil(p['rankopt']*m/100))
        elif p['rank']=='first':
            _integer(p['rankopt'],'rankopt',1);rank=p['rankopt']
            if rank>m:raise ValueError('rankopt 超过延迟维数')
        else:raise ValueError('rank=poseig|full|pct|first')
        for k in range(rank,m):Delta[k,k]=0
        W=V@np.diag(1/(values+p['mu']-1))@Delta@linalg.inv(V)
        est=dict(W=W,picks=picks,delay=p['delay'],delay_spacing=p['delay_spacing'],singlesided=p['singlesided'])
        fitted=_fitted('mwf',est,y,p['scope'],p['reference_id'],mask_id=p['mask_id'])
        return _out(y,fitted,artifact_covariance=Ryy,clean_covariance=Rnn,mask=mask,eigenvalues=values,rank=rank,
            covariance_condition=dict(artifact=np.linalg.cond(Ryy),clean=np.linalg.cond(Rnn)),params=p)
    if op=='mwf_apply':
        p=_exact(p,'reference_id');est=_same(model,'mwf',y,p['reference_id']);a=y.get_data(picks=est['picks'])
        if est['delay']*est['delay_spacing']>=a.shape[1]:raise ValueError('延迟超过目标记录长度')
        stacked=_lagged(a-a.mean(1,keepdims=True),est['delay'],est['delay_spacing'],est['singlesided'])
        c=len(a);start=0 if est['singlesided'] else est['delay']*c
        removed=est['W'][:,start:start+c].T@stacked
        y._data[est['picks']]-=removed
        return _out(y,model,removed=removed,mask_id=model['mask_id'],delay_samples=est['delay']*est['delay_spacing'])
    raise NotImplementedError(op)
