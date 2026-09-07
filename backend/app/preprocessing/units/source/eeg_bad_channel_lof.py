# Python 3.12 | MNE 1.10.2 | NumPy 1.26.4 | SciPy 1.15.3 | scikit-learn 1.6.1
import numpy as np
import mne
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

def _integer(v, name, minimum=0):
    if isinstance(v, bool) or not isinstance(v, Integral) or v < minimum:
        raise ValueError(f'{name} 需要 >= {minimum} 的整数')

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

def _eeg_bad_channel_lof_lof_detect(op, x, **p):
    y = _copy(x)
    _args(p, 'n_neighbors threshold metric')
    _number(p['threshold'], 'threshold', 0, strict_low=True)
    _integer(p['n_neighbors'], 'n_neighbors', 2)
    if not p['n_neighbors'] < len(mne.pick_types(y.info, eeg=True, exclude='bads')):
        raise ValueError('LOF 邻居数需小于好 EEG 通道数')
    (bads, scores) = mne.preprocessing.find_bad_channels_lof(y, picks='eeg', return_scores=True, **p)
    return _out(y, bads=bads, scores=scores, score_channels=[y.ch_names[i] for i in mne.pick_types(y.info, eeg=True, exclude='bads')])

def eeg_bad_channel_lof(op, x, model=None, **p):
    if op == 'lof_detect':
        if model is not None:
            raise ValueError('此操作不接受模型')
        return _eeg_bad_channel_lof_lof_detect(op, x, **p)
    raise NotImplementedError(op)


from fractions import Fraction
from scipy import signal as _sig
from scipy.spatial.distance import cdist as _cdist
from numpy.polynomial.legendre import legval as _legval

def _number(value,name,low=None,high=None,strict_low=False):
    if isinstance(value,(bool,np.bool_)) or not isinstance(value,(int,float,np.integer,np.floating)) or not np.isfinite(value):raise ValueError(name+' requires finite real scalar')
    if low is not None and (value<=low if strict_low else value<low):raise ValueError(name+' below permitted range')
    if high is not None and value>high:raise ValueError(name+' above permitted range')

def _sig_int(value,name,minimum=0):
    if isinstance(value,(bool,np.bool_)) or not isinstance(value,(int,np.integer)) or value<minimum:
        raise ValueError(name+' requires an integer >= '+str(minimum))
    return int(value)

def _sig_lof(x,**p):
    _args(p,'n_neighbors threshold metric');y=_copy(x)
    if not isinstance(y,mne.io.BaseRaw):raise ValueError('LOF requires Raw')
    n=_sig_int(p['n_neighbors'],'n_neighbors',1);_number(p['threshold'],'threshold',0,strict_low=True)
    if p['metric'] not in ('euclidean','manhattan','chebyshev','cosine','correlation'):raise ValueError('supported LOF metric required')
    picks=mne.pick_types(y.info,eeg=True,exclude='bads')
    if len(picks)<2:raise ValueError('LOF requires at least 2 good EEG channels')
    effective=min(n,len(picks)-1)
    bads,scores=mne.preprocessing.find_bad_channels_lof(y,n_neighbors=effective,threshold=p['threshold'],metric=p['metric'],picks=picks,return_scores=True,verbose=False)
    return _out(y,bads=bads,scores=scores,score_channels=[y.ch_names[i] for i in picks],requested_neighbors=n,effective_neighbors=effective)

_legacy_eeg_bad_channel_lof = eeg_bad_channel_lof

def eeg_bad_channel_lof(op,x,model=None,**p):
    if op == 'lof_detect':
        if model is not None: raise ValueError('operation does not accept model')
        return _sig_lof(x,**p)
    return _legacy_eeg_bad_channel_lof(op,x,model=model,**p)
