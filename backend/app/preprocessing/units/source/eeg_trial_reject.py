# Python 3.12 | MNE 1.10.2 | NumPy 1.26.4 | SciPy 1.15.3 | scikit-learn 1.6.1
import numpy as np
import mne
from numbers import Integral, Real

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

def _eeg_trial_reject_reject_trials(op, x, **p):
    y = _copy(x)
    _args(p, 'reject flat max_fraction')
    if not isinstance(y, mne.BaseEpochs):
        raise TypeError('需要 Epochs')
    before = y.selection.copy()
    y.drop_bad(reject=p['reject'], flat=p['flat'])
    if not 0 <= p['max_fraction'] < 1 or len(y) < (1 - p['max_fraction']) * len(before):
        raise ValueError('Trial 剔除超硬限')
    return _out(y, kept=y.selection.copy(), removed=np.setdiff1d(before, y.selection), drop_log=y.drop_log)

def eeg_trial_reject(op, x, model=None, **p):
    if op == 'reject_trials':
        if model is not None:
            raise ValueError('此操作不接受模型')
        return _eeg_trial_reject_reject_trials(op, x, **p)
    raise NotImplementedError(op)


from fractions import Fraction
from scipy import signal as _sig
from scipy.spatial.distance import cdist as _cdist
from numpy.polynomial.legendre import legval as _legval

def _number(value,name,low=None,high=None,strict_low=False):
    if isinstance(value,(bool,np.bool_)) or not isinstance(value,(int,float,np.integer,np.floating)) or not np.isfinite(value):raise ValueError(name+' requires finite real scalar')
    if low is not None and (value<=low if strict_low else value<low):raise ValueError(name+' below permitted range')
    if high is not None and value>high:raise ValueError(name+' above permitted range')

def _sig_trial_drop(x,**p):
    if set(p)!=set('reject_mask trial_ids decision_id'.split()):raise ValueError('drop_mask parameter keys mismatch')
    y=_copy(x)
    if not isinstance(y,mne.BaseEpochs):raise ValueError('drop_mask requires Epochs')
    mask=np.asarray(p['reject_mask']);ids=p['trial_ids']
    if mask.dtype.kind!='b' or mask.shape!=(len(y),):raise ValueError('reject_mask requires one boolean per current Trial')
    if not isinstance(ids,(list,tuple)) or len(ids)!=len(y) or len(set(ids))!=len(ids) or not all(isinstance(i,str) and i for i in ids):raise ValueError('unique trial_ids required')
    if not isinstance(p['decision_id'],str) or not p['decision_id']:raise ValueError('decision_id required')
    if mask.all():raise ValueError('all trials rejected; return record-level failure with supplied mask')
    removed=np.flatnonzero(mask);y.drop(removed,reason='CONFIRMED_MASK',verbose=False)
    return _out(y,removed=removed,removed_trial_ids=[i for i,m in zip(ids,mask) if m],retained_trial_ids=[i for i,m in zip(ids,mask) if not m],decision_id=p['decision_id'])

def _sig_reject_trials(x,**p):
    _args(p,'reject flat max_fraction');y=_copy(x)
    if not isinstance(y,mne.BaseEpochs):raise ValueError('reject_trials requires Epochs')
    _number(p['max_fraction'],'max_fraction',0,1)
    if p['max_fraction']>=1:raise ValueError('max_fraction must be <1')
    original=y.selection.copy();probe=y.copy();probe.selection=np.arange(len(y));probe.drop_log=tuple(() for _ in range(len(y)))
    probe.drop_bad(reject=p['reject'],flat=p['flat'],verbose=False);positions=probe.selection.copy();removed=np.setdiff1d(np.arange(len(y)),positions)
    if len(removed)>len(y)*p['max_fraction']:raise ValueError('Trial rejection fraction exceeded')
    y.drop_bad(reject=p['reject'],flat=p['flat'],verbose=False)
    if len(y)!=len(probe) or not np.array_equal(y.get_data(),probe.get_data()):raise RuntimeError('Trial selection remapping differs from native rejection')
    return _out(y,kept=y.selection.copy(),kept_positions=positions,removed=removed,removed_selection=original[removed],input_selection=original,drop_log=y.drop_log,current_drop_log=probe.drop_log)

_legacy_eeg_trial_reject = eeg_trial_reject

def eeg_trial_reject(op,x,model=None,**p):
    if op == 'reject_trials':
        if model is not None: raise ValueError('operation does not accept model')
        return _sig_reject_trials(x,**p)
    if op == 'drop_mask':
        if model is not None: raise ValueError('operation does not accept model')
        return _sig_trial_drop(x,**p)
    return _legacy_eeg_trial_reject(op,x,model=model,**p)
