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

def _events(events, raw=None):
    e = np.asarray(events)
    if e.dtype.kind not in 'iu' or e.ndim != 2 or e.shape[1] != 3:
        raise ValueError('events 必须为整数 n×3，禁止自动截断小数')
    if len(e) and (np.any(e[:, 0] < 0) or np.any(np.diff(e[:, 0].astype(float)) <= 0)):
        raise ValueError('events 样点必须非负且严格递增；有重复/碰撞')
    if raw is not None and len(e) and (e[0, 0] < raw.first_samp or e[-1, 0] > raw.last_samp):
        raise ValueError('events 超出当前 Raw 范围')
    return e.astype(np.int64, copy=True)

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

def _eeg_crop_crop(op, x, **p):
    y = _copy(x)
    _args(p, 'tmin tmax events')
    _number(p['tmin'], 'tmin', 0)
    _number(p['tmax'], 'tmax', 0)
    if p['tmin'] > p['tmax']:
        raise ValueError('裁剪起点不能晚于终点')
    if not isinstance(y, mne.io.BaseRaw):
        raise TypeError('crop 仅 Raw')
    e = _events(p['events'], y)
    y.crop(tmin=p['tmin'], tmax=p['tmax'], include_tmax=True)
    keep = (e[:, 0] >= y.first_samp) & (e[:, 0] <= y.last_samp)
    return _out(y, events=e[keep], event_keep=keep, first_samp=y.first_samp)

def eeg_crop(op, x, model=None, **p):
    if op == 'crop':
        if model is not None:
            raise ValueError('此操作不接受模型')
        return _eeg_crop_crop(op, x, **p)
    raise NotImplementedError(op)


from fractions import Fraction
from scipy import signal as _sig
from scipy.spatial.distance import cdist as _cdist
from numpy.polynomial.legendre import legval as _legval

def _sig_events(events,y,fractional=False):
    a=np.asarray(events)
    allowed='iuf' if fractional else 'iu'
    if a.dtype.kind not in allowed or a.ndim!=2 or a.shape[1]!=3 or not np.isfinite(a).all():raise ValueError('events requires finite n×3 sample table')
    if len(a) and (np.any(np.diff(a[:,0])<=0) or np.any(a[:,0]<y.first_samp) or np.any(a[:,0]>y.last_samp)):raise ValueError('events outside input or non-increasing')
    if fractional and np.any(a[:,1:]!=np.round(a[:,1:])):raise ValueError('event codes must be integers')
    return a.copy()

def _sig_crop_join(x,**p):
    _args(p,'keep_intervals events decision_id')
    y=_copy(x)
    if not isinstance(y,mne.io.BaseRaw):raise ValueError('crop_join requires Raw')
    if not isinstance(p['decision_id'],str) or not p['decision_id']:raise ValueError('confirmed decision_id required')
    intervals=np.asarray(p['keep_intervals'])
    if intervals.dtype.kind not in 'iu' or intervals.ndim!=2 or intervals.shape[1]!=2 or not len(intervals):raise ValueError('keep_intervals requires nonempty integer n×2')
    if np.any(intervals[:,0]<0) or np.any(intervals[:,1]>y.n_times) or np.any(intervals[:,1]<=intervals[:,0]) or np.any(intervals[1:,0]<intervals[:-1,1]):raise ValueError('invalid/overlapping intervals')
    merged=[]
    for start,stop in intervals.tolist():
        if merged and start==merged[-1][1]:merged[-1][1]=stop
        else:merged.append([start,stop])
    intervals=np.asarray(merged,dtype=np.int64)
    events=_sig_events(p['events'],y);fs=y.info['sfreq'];parts=[];sample_map=[];new_events=[];kept_ids=[];offset=0
    new_first=y.first_samp+int(intervals[0,0])
    for start,stop in intervals:
        parts.append(y.copy().crop(start/fs,(stop-1)/fs));sample_map.extend(range(int(start),int(stop)))
        mask=(events[:,0]>=y.first_samp+start)&(events[:,0]<y.first_samp+stop)
        e=events[mask].copy();e[:,0]=e[:,0]-y.first_samp-start+new_first+offset;new_events.append(e);kept_ids.extend(np.flatnonzero(mask).tolist());offset+=int(stop-start)
    out=mne.concatenate_raws(parts,preload=True,verbose=False)
    event_out=np.concatenate(new_events,axis=0) if new_events else np.empty((0,3),int)
    inverse=np.full(y.n_times,-1,dtype=np.int64);sample_map=np.array(sample_map,dtype=np.int64);inverse[sample_map]=np.arange(len(sample_map))
    return _out(out,events=event_out,kept_event_indices=np.array(kept_ids),removed_event_indices=np.setdiff1d(np.arange(len(events)),kept_ids),new_to_old_sample=sample_map,old_to_new_sample=inverse,input_first_samp=y.first_samp,output_first_samp=out.first_samp,decision_id=p['decision_id'])

_legacy_eeg_crop = eeg_crop

def eeg_crop(op,x,model=None,**p):
    if op == 'crop_join':
        if model is not None: raise ValueError('operation does not accept model')
        return _sig_crop_join(x,**p)
    return _legacy_eeg_crop(op,x,model=model,**p)
