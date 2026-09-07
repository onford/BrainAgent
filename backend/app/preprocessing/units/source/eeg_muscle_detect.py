# Python 3.12 | MNE 1.10.2 | NumPy 1.26.4 | SciPy 1.15.3 | scikit-learn 1.6.1
import numpy as np
import mne
from numbers import Integral, Real

def _vector(value, name, length):
    _sequence(value, name, length)
    for item in value:
        _number(item, name)

def _sequence(value, name, length=None):
    if not isinstance(value, (list, tuple, np.ndarray)) or (isinstance(value, np.ndarray) and value.ndim != 1):
        raise TypeError(name + '需要一维列表/元组/数组')
    if length is not None and len(value) != length:
        raise ValueError(name + '长度错误')

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

def _eeg_muscle_detect_muscle_detect(op, x, **p):
    y = _copy(x)
    _args(p, 'threshold filter_freq min_length_good')
    if not isinstance(y, mne.io.BaseRaw):
        raise TypeError('肌电坏段检测需要Raw')
    _number(p['threshold'], 'threshold')
    _number(p['min_length_good'], 'min_length_good', 0)
    _vector(p['filter_freq'], 'filter_freq', 2)
    if not 0 < p['filter_freq'][0] < p['filter_freq'][1] < y.info['sfreq'] / 2:
        raise ValueError('肌电检测频带需满足0<低<高<Nyquist')
    score_expected = np.isfinite(y.copy().pick('eeg').get_data(reject_by_annotation='NaN')[0])
    if not score_expected.any():
        raise ValueError('没有可评分的有效样点')
    (ann, scores) = mne.preprocessing.annotate_muscle_zscore(y, ch_type='eeg', **p)
    scores = np.asarray(scores)
    if scores.shape != (y.n_times,) or not np.isfinite(scores[score_expected]).all() or np.isinf(scores).any():
        raise ValueError('肌电分数在应评分区没有有效结果；检查平直/退化信号')
    score_valid = score_expected & np.isfinite(scores)
    if not score_valid.any():
        raise ValueError('没有任何有效肌电分数')
    edges = np.diff(np.r_[False, score_valid, False].astype(int))
    score_valid_ranges = np.column_stack((np.flatnonzero(edges == 1), np.flatnonzero(edges == -1))).tolist()
    return _out(y, annotations=ann, scores=scores, frame=_frame(y), score_valid=score_valid, score_valid_ranges=score_valid_ranges)

def eeg_muscle_detect(op, x, model=None, **p):
    if op == 'muscle_detect':
        if model is not None:
            raise ValueError('此操作不接受模型')
        return _eeg_muscle_detect_muscle_detect(op, x, **p)
    raise NotImplementedError(op)
