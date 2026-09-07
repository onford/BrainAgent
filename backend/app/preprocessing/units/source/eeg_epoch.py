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

def _ids(ids):
    if not isinstance(ids, (list, tuple)) or not ids or any((not isinstance(i, str) or not i.strip() for i in ids)) or (len(set(ids)) != len(ids)):
        raise ValueError('ID 必须为非空、唯一的字符串列表')

def _events(events, raw=None):
    e = np.asarray(events)
    if e.dtype.kind not in 'iu' or e.ndim != 2 or e.shape[1] != 3:
        raise ValueError('events 必须为整数 n×3，禁止自动截断小数')
    if len(e) and (np.any(e[:, 0] < 0) or np.any(np.diff(e[:, 0].astype(float)) <= 0)):
        raise ValueError('events 样点必须非负且严格递增；有重复/碰撞')
    if raw is not None and len(e) and (e[0, 0] < raw.first_samp or e[-1, 0] > raw.last_samp):
        raise ValueError('events 超出当前 Raw 范围')
    return e.astype(np.int64, copy=True)

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

def _eeg_epoch_epoch(op, x, **p):
    y = _copy(x)
    _args(p, 'events event_id tmin tmax picks')
    if not isinstance(p['event_id'], dict) or not p['event_id']:
        raise ValueError('event_id需要非空显式名称到正整数码字典')
    for (name, code) in p['event_id'].items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError('事件名称必须是非空字符串')
        if isinstance(code, (bool, np.bool_)) or not isinstance(code, Integral) or code <= 0:
            raise ValueError('事件码必须是正整数')
    if not isinstance(y, mne.io.BaseRaw):
        raise TypeError('epoch需要Raw')
    p['events'] = _events(p['events'], y)
    _sig_epoch_picks(y, p['picks'])
    boundary_annotations = []
    for annotation in list(y.annotations):
        if annotation['description'].lower().startswith(('edge', 'boundary')):
            item = dict(onset=float(annotation['onset']), duration=float(annotation['duration']), original_description=annotation['description'])
            boundary_annotations.append(item)
            y.annotations.append(item['onset'], item['duration'], 'BAD_acquisition_boundary')
    y = mne.Epochs(y, **p, baseline=None, detrend=None, proj=False, reject=None, flat=None, reject_by_annotation=True, event_repeated='error', preload=True)
    return _out(y, kept=y.selection.copy(), drop_log=y.drop_log, boundary_annotations=boundary_annotations)

def eeg_epoch(op, x, model=None, **p):
    if op == 'epoch':
        if model is not None:
            raise ValueError('此操作不接受模型')
        return _eeg_epoch_epoch(op, x, **p)
    raise NotImplementedError(op)


from fractions import Fraction
from scipy import signal as _sig
from scipy.spatial.distance import cdist as _cdist
from numpy.polynomial.legendre import legval as _legval

def _sig_epoch_picks(y,names):
    if not isinstance(names,(list,tuple)) or not names or not all(isinstance(k,str) for k in names) or len(names)!=len(set(names)) or not set(names)<=set(y.ch_names):raise ValueError('picks requires unique existing channel names')

def _sig_epoch_nonfinite(x,**p):
    _args(p,'events event_id tmin tmax picks')
    if not isinstance(x,mne.io.BaseRaw):raise ValueError('epoch_with_nonfinite requires Raw')
    y=x.copy().load_data()
    _sig_epoch_picks(y,p['picks']);data=y.get_data(picks=p['picks'])
    if np.iscomplexobj(data):raise ValueError('complex input not supported')
    invalid=~np.isfinite(data).all(axis=0);changes=np.diff(np.r_[False,invalid,False].astype(int));starts=np.flatnonzero(changes==1);stops=np.flatnonzero(changes==-1)
    for a,b in zip(starts,stops):y.annotations.append(y.first_time+a/y.info['sfreq'],(b-a)/y.info['sfreq'],'BAD_nonfinite')
    # Only invalid samples are replaced, and every intersecting Epoch is rejected.
    # This copy exists solely for Epoch extraction; repaired Raw is never returned.
    y._data[~np.isfinite(y._data)]=0
    result=_eeg_epoch_epoch('epoch',y,**p)
    result['artifacts'].update(nonfinite_intervals=np.column_stack([starts,stops]),nonfinite_policy='drop intersecting selected-channel trials',input_event_indices=result['data'].selection.copy())
    return result

_legacy_eeg_epoch = eeg_epoch

def eeg_epoch(op,x,model=None,**p):
    if op == 'epoch_with_nonfinite':
        if model is not None: raise ValueError('operation does not accept model')
        return _sig_epoch_nonfinite(x,**p)
    return _legacy_eeg_epoch(op,x,model=model,**p)
