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
from importlib.metadata import version
from copy import deepcopy

from sklearn.model_selection import check_cv

def _cv_folds(cv,n):
    if not isinstance(cv,(list,tuple)) or len(cv)<2:raise ValueError('cv 需要至少两组实际 (train,validation) 索引')
    folds=[];coverage=np.zeros(n,int)
    for pair in cv:
        if not isinstance(pair,(list,tuple)) or len(pair)!=2:raise ValueError('cv 中每项是 (train,validation)')
        train,test=map(np.asarray,pair)
        for a in (train,test):
            if a.ndim!=1 or a.dtype.kind not in 'iu' or len(set(a.tolist()))!=len(a) or np.any((a<0)|(a>=n)):raise ValueError('cv 索引需要唯一且合法整数')
        if len(train)<2 or len(test)<1 or np.intersect1d(train,test).size:raise ValueError('CV 训练≥2、验证≥1，且互不相交')
        folds.append((train.astype(int),test.astype(int)));coverage[test]+=1
    if np.any(coverage!=1):raise ValueError('CV 验证索引必须恰好覆盖每个 Epoch 一次')
    return folds

def eeg_autoreject(op,x,model=None,**p):
    y=_epochs(x)
    if op=='autoreject_fit':
        if model is not None:raise ValueError('fit 不接受模型')
        if p.get('mode')=='global' and set(p)&{'n_interpolate','consensus','thresh_method'}:
            raise ValueError('global 不接受 local 插值/搜索参数')
        p=_exact(p,'mode scope reference_id trial_ids cv',seed=0,n_interpolate=(1,4),consensus=(.5,.75,1.),thresh_method='bayesian_optimization')
        _scope(p['scope'],('train','calibration'));_ref(p['reference_id']);_ids(p['trial_ids']);_integer(p['seed'],'seed')
        if len(p['trial_ids'])!=len(y):raise ValueError('trial_ids 必须逐 Epoch 对齐')
        folds=_cv_folds(p['cv'],len(y));picks=_good(y,4)
        if p['mode']=='global':
            from autoreject import get_rejection_threshold
            est=get_rejection_threshold(y,ch_types='eeg',cv=check_cv(folds),random_state=p['seed'],verbose=False)
            if not np.isfinite(est['eeg']) or est['eeg']<=0:raise ValueError('全局阈值退化')
            extra=dict(thresholds=est.copy())
        elif p['mode']=='local':
            from autoreject import AutoReject
            ni=np.asarray(p['n_interpolate']);co=_finite_array(p['consensus'],'consensus',1)
            if ni.ndim!=1 or not len(ni) or ni.dtype.kind not in 'iu' or np.any((ni<0)|(ni>len(picks)-4)):raise ValueError('n_interpolate 需唯一整数网格且至少保留 4 个好通道')
            if len(set(ni.tolist()))!=len(ni) or not len(co) or np.any((co<=0)|(co>1)) or len(set(co.tolist()))!=len(co):raise ValueError('consensus 为 (0,1] 唯一网格')
            if not np.any(co[:,None]*len(picks)>ni):raise ValueError('consensus 与插值数没有可行组合')
            if p['thresh_method'] not in ('bayesian_optimization','random_search'):raise ValueError('thresh_method 未支持')
            est=AutoReject(n_interpolate=ni,consensus=co,cv=check_cv(folds),picks=picks,random_state=p['seed'],thresh_method=p['thresh_method'],n_jobs=1,verbose=False).fit(y)
            if not all(np.isfinite(v) and v>0 for v in est.threshes_.values()):raise ValueError('逐通道阈值退化')
            if not np.any(np.isfinite(est.loss_['eeg'])):raise ValueError('交叉验证损失均无效')
            extra=dict(thresholds=est.threshes_.copy(),loss=deepcopy(est.loss_),n_interpolate=deepcopy(est.n_interpolate_),consensus=deepcopy(est.consensus_))
        else:raise ValueError('mode=global|local')
        fitted=_fitted('autoreject',est,y,p['scope'],p['reference_id'],mode=p['mode'],times=y.times.copy())
        return _out(y,fitted,cv=folds,trial_ids=list(p['trial_ids']),version=version('autoreject'),**extra)
    if op=='autoreject_apply':
        p=_exact(p,'reference_id trial_ids');_ids(p['trial_ids']);est=_same(model,'autoreject',y,p['reference_id'])
        if len(p['trial_ids'])!=len(y) or not np.array_equal(y.times,model['times']):raise ValueError('Trial ID/时间轴与模型不兼容')
        if model['mode']=='global':
            # Track current positions, including Epochs with duplicated original selection IDs.
            picks=_good(y,4);bad=np.any(np.ptp(y.get_data(picks=picks),axis=-1)>est['eeg'],axis=1)
            y.drop(np.flatnonzero(bad),reason='AUTOREJECT',verbose=False);labels=None
        else:
            y,log=deepcopy(est).transform(y,return_log=True);bad=log.bad_epochs.copy();labels=log.labels.copy()
        if len(y)==0:raise ValueError('全部 Epoch 被拒绝')
        ids=np.asarray(p['trial_ids'])
        return _out(y,model,bad_epochs=bad,labels=labels,kept_ids=ids[~bad].tolist(),rejected_ids=ids[bad].tolist(),selection=y.selection.copy())
    raise NotImplementedError(op)
