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

def _ids(ids):
    if not isinstance(ids, (list, tuple)) or not ids or any((not isinstance(i, str) or not i.strip() for i in ids)) or (len(set(ids)) != len(ids)):
        raise ValueError('ID 必须为非空、唯一的字符串列表')

def _channels(x, names, kind='eeg'):
    _ids(names)
    valid = {n for (n, t) in zip(x.ch_names, x.get_channel_types()) if t == kind}
    if not set(names) <= valid:
        raise ValueError(f'需要已有 {kind} 通道列表')

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

def _eeg_bad_channel_mark_mark_channels(op, x, **p):
    y = _copy(x)
    _args(p, 'bads max_fraction')
    if not isinstance(p['bads'], (list, tuple)):
        raise TypeError('bads需要通道名列表/元组')
    _number(p['max_fraction'], 'max_fraction', 0, 1)
    if p['bads']:
        _channels(y, p['bads'])
    names = sorted(set(y.info['bads']) | set(p['bads']))
    eeg = set(np.array(y.ch_names)[mne.pick_types(y.info, eeg=True, exclude=[])])
    if not eeg or not 0 <= p['max_fraction'] < 1 or len(set(names) & eeg) > p['max_fraction'] * len(eeg):
        raise ValueError('坏道超硬限')
    y.info['bads'] = names
    return _out(y, bads=names)

def eeg_bad_channel_mark(op, x, model=None, **p):
    if op == 'mark_channels':
        if model is not None:
            raise ValueError('此操作不接受模型')
        return _eeg_bad_channel_mark_mark_channels(op, x, **p)
    raise NotImplementedError(op)


from fractions import Fraction
from scipy import signal as _sig
from scipy.spatial.distance import cdist as _cdist
from numpy.polynomial.legendre import legval as _legval

def _sig_mark_repaired(x,**p):
    _args(p,'repaired_channels decision_id');y=_copy(x);names=p['repaired_channels']
    if not isinstance(names,(list,tuple)) or len(names)!=len(set(names)) or not all(isinstance(n,str) for n in names):raise ValueError('repaired_channels unique names required')
    if not set(names)<=set(y.info['bads']):raise ValueError('repair list must be current bad channels')
    if any(y.get_channel_types()[y.ch_names.index(n)]!='eeg' for n in names):raise ValueError('only repaired scalp EEG may be cleared')
    if not isinstance(p['decision_id'],str) or not p['decision_id']:raise ValueError('repair decision_id required')
    before=list(y.info['bads']);y.info['bads']=[n for n in before if n not in names]
    return _out(y,bads_before=before,bads_after=list(y.info['bads']),repaired_channels=list(names),decision_id=p['decision_id'])

_legacy_eeg_bad_channel_mark = eeg_bad_channel_mark

def eeg_bad_channel_mark(op,x,model=None,**p):
    if op == 'mark_repaired':
        if model is not None: raise ValueError('operation does not accept model')
        return _sig_mark_repaired(x,**p)
    return _legacy_eeg_bad_channel_mark(op,x,model=model,**p)
