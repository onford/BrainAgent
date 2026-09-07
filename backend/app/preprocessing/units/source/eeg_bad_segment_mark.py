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

def _frame(raw):
    if not isinstance(raw, mne.io.BaseRaw):
        raise TypeError('需要 Raw')
    return dict(first_samp=raw.first_samp, n_times=raw.n_times, sfreq=raw.info['sfreq'], meas_date=str(raw.info['meas_date']))

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

def _eeg_bad_segment_mark_mark_segments(op, x, **p):
    y = _copy(x)
    _args(p, 'annotations frame')
    ann = p['annotations']
    if p['frame'] != _frame(y):
        raise ValueError('注释来源的时间轴与当前数据不一致')
    if not isinstance(ann, mne.Annotations):
        raise TypeError('需要mne.Annotations')
    if not isinstance(y, mne.io.BaseRaw) or ann.orig_time != y.annotations.orig_time:
        raise ValueError('注释时基不兼容')
    if any((not s.lower().startswith('bad') for s in ann.description)):
        raise ValueError('只接收明确 BAD 注释')
    onsets = ann.onset + (y.first_time if ann.orig_time is None else 0)
    if not np.isfinite(onsets).all() or not np.isfinite(ann.duration).all() or np.any(ann.duration < 0) or np.any(onsets < y.first_time - 1e-10) or np.any(onsets + ann.duration > (y.last_samp + 1) / y.info['sfreq'] + 1e-10):
        raise ValueError('BAD注释超出当前Raw时间范围')
    if any((not set(ch) <= set(y.ch_names) for ch in ann.ch_names)):
        raise ValueError('注释涉及不存在的通道')
    y.annotations.append(onsets, ann.duration, ann.description, ch_names=ann.ch_names)
    return _out(y, annotations=y.annotations.copy())

def eeg_bad_segment_mark(op, x, model=None, **p):
    if op == 'mark_segments':
        if model is not None:
            raise ValueError('此操作不接受模型')
        return _eeg_bad_segment_mark_mark_segments(op, x, **p)
    raise NotImplementedError(op)
