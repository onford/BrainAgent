# Python 3.12 | MNE 1.10.2 | NumPy 1.26.4
import numpy as np
import mne
from numbers import Real

def _amplitude_detect_args(p, keys):
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
    for key, value in p.items():
        if isinstance(value, (bool, np.bool_)):
            raise TypeError(f'{key} 不接受布尔值代替数值/枚举')
        if key not in {'models', 'artifacts', 'forward', 'projs', 'montage', 'annotations'}:
            finite(value)

def _amplitude_detect_channels(x, names, kind='eeg'):
    _amplitude_detect_ids(names)
    valid = {n for n, t in zip(x.ch_names, x.get_channel_types()) if t == kind}
    if not set(names) <= valid:
        raise ValueError(f'需要已有 {kind} 通道列表')

def _amplitude_detect_copy(x):
    if not isinstance(x, (mne.io.BaseRaw, mne.BaseEpochs)):
        raise TypeError('需要 MNE Raw/Epochs，电位单位 V')
    if isinstance(x, mne.BaseEpochs) and (not x.preload):
        raise ValueError('Epochs须已preload并记录已有drop_log，禁止普通操作隐式加载/剔除Trial')
    y = x.copy().load_data()
    values = y.get_data()
    if not values.size or np.iscomplexobj(values) or (not np.isfinite(values).all()):
        raise ValueError('空数据、复数或 NaN/Inf，先返回接入异常流程')
    return y

def _amplitude_detect_eeg_amplitude_flat_amplitude_detect(op, x, **p):
    y = _amplitude_detect_copy(x)
    _amplitude_detect_args(p, 'peak flat bad_percent min_duration picks')
    for key in ('peak', 'flat'):
        threshold = p[key]
        if threshold is not None:
            if isinstance(threshold, dict):
                if set(threshold) != {'eeg'}:
                    raise ValueError(key + '只接受eeg阈值字典')
                threshold = threshold['eeg']
            _amplitude_detect_number(threshold, key, 0)
    _amplitude_detect_number(p['bad_percent'], 'bad_percent', 0, 100)
    _amplitude_detect_number(p['min_duration'], 'min_duration', 0, strict_low=True)
    _amplitude_detect_channels(y, p['picks'])
    ann, bads = mne.preprocessing.annotate_amplitude(y, **p)
    return _amplitude_detect_out(y, annotations=ann, bads=bads, frame=_amplitude_detect_frame(y))

def _amplitude_detect_frame(raw):
    if not isinstance(raw, mne.io.BaseRaw):
        raise TypeError('需要 Raw')
    return dict(first_samp=raw.first_samp, n_times=raw.n_times, sfreq=raw.info['sfreq'], meas_date=str(raw.info['meas_date']))

def _amplitude_detect_ids(ids):
    if not isinstance(ids, (list, tuple)) or not ids or any((not isinstance(i, str) or not i.strip() for i in ids)) or (len(set(ids)) != len(ids)):
        raise ValueError('ID 必须为非空、唯一的字符串列表')

def _amplitude_detect_number(value, name, low=None, high=None, strict_low=False):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) or (not np.isfinite(value)):
        raise ValueError(name + '需要有限实数标量')
    if low is not None and (value <= low if strict_low else value < low):
        raise ValueError(name + '低于允许范围')
    if high is not None and value > high:
        raise ValueError(name + '高于允许范围')

def _amplitude_detect_out(data=None, model=None, **artifacts):

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

def _operation_amplitude_detect(op, x, model=None, **p):
    if op == 'amplitude_detect':
        if model is not None:
            raise ValueError('此操作不接受模型')
        return _amplitude_detect_eeg_amplitude_flat_amplitude_detect(op, x, **p)
    raise NotImplementedError(op)

def _flat_detect_candidates(names, mask):
    return [n for n, b in zip(names, np.asarray(mask, dtype=bool)) if b]

def _flat_detect_params(p, defaults):
    unknown = set(p) - set(defaults)
    if unknown:
        raise TypeError('unknown parameters: ' + str(sorted(unknown)))
    return dict(defaults, **p)

def _flat_detect_positive(v, name, zero=False):
    if isinstance(v, (bool, np.bool_)) or not np.isscalar(v) or (not np.isfinite(v)) or (v < 0 if zero else v <= 0):
        raise ValueError(name + ' must be finite ' + ('nonnegative' if zero else 'positive'))
    return float(v)

def _flat_detect_result(x, names, **artifacts):
    return {'data': x.copy(), 'model': None, 'artifacts': {'channel_names': names, **artifacts}}

def _flat_detect_segments(x, intervals=None):
    n = x.n_times
    if intervals is not None:
        v = np.asarray(intervals)
        if v.ndim != 2 or v.shape[1] != 2 or (not len(v)) or (v.dtype.kind not in 'iu'):
            raise ValueError('valid_intervals must be nonempty integer [start, stop) sample pairs')
        if np.any(v[:, 0] < 0) or np.any(v[:, 1] > n) or np.any(v[:, 1] <= v[:, 0]) or np.any(v[1:, 0] < v[:-1, 1]):
            raise ValueError('invalid/overlapping intervals')
        return v
    from mne.annotations import _annotations_starts_stops
    starts, ends = _annotations_starts_stops(x, ('bad', 'edge'), invert=True)
    return np.array([(s, e) for s, e in zip(starts, ends) if e > s], dtype=int).reshape(-1, 2)

def _flat_detect_start(op, expected, x, model, allow_epochs=False, picks=None):
    if op != expected:
        raise ValueError('operation must be ' + expected)
    if model is not None:
        raise ValueError('detection does not accept a fitted model')
    valid = (mne.io.BaseRaw, mne.BaseEpochs) if allow_epochs else (mne.io.BaseRaw,)
    if not isinstance(x, valid):
        raise TypeError('expected Raw or supported Epochs')
    if picks is None:
        picks = mne.pick_types(x.info, eeg=True, exclude='bads').tolist()
    else:
        if not isinstance(picks, (list, tuple)) or not picks or len(set(picks)) != len(picks):
            raise ValueError('picks must be unique channel names')
        if any((c not in x.ch_names for c in picks)):
            raise ValueError('unknown channel')
        picks = [x.ch_names.index(c) for c in picks]
    if not picks:
        raise ValueError('no selected channels')
    a = x.get_data(picks=picks)
    if not np.isfinite(a).all():
        raise ValueError('selected data must be finite')
    return (a, [x.ch_names[k] for k in picks], float(x.info['sfreq']))

def _operation_flat_detect(op, x, model=None, **p):
    p = _flat_detect_params(p, {'max_flatline_duration': 5.0, 'tolerance_V': 1e-15, 'valid_intervals': None})
    a, names, sf = _flat_detect_start(op, 'flat_detect', x, model)
    duration = _flat_detect_positive(p['max_flatline_duration'], 'max_flatline_duration', True)
    tol = _flat_detect_positive(p['tolerance_V'], 'tolerance_V', True)
    intervals = _flat_detect_segments(x, p['valid_intervals'])
    if not len(intervals):
        raise ValueError('no valid continuous intervals')
    longest = np.zeros(len(names))
    runs = []
    for c in range(len(names)):
        cr = []
        for lo, hi in intervals:
            flat = np.abs(np.diff(a[c, lo:hi])) <= tol
            z = np.diff(np.r_[False, flat, False].astype(int))
            starts = np.flatnonzero(z == 1)
            ends = np.flatnonzero(z == -1)
            for s, e in zip(starts, ends):
                cr.append([int(lo + s), int(lo + e + 1)])
                longest[c] = max(longest[c], (e - s) / sf)
        runs.append(cr)
    bad = longest > duration
    return _flat_detect_result(x, names, longest_duration_s=longest, flat_runs_samples=runs, candidates=_flat_detect_candidates(names, bad), all_channels_flat=bool(np.all(bad)), tolerance_V=tol, comparison='duration > threshold; adjacent absolute difference <= tolerance')

def _amplitude_windows_fraction(v, name):
    v = _flat_detect_positive(v, name, True)
    if v > 1:
        raise ValueError(name + ' must be in [0,1]')
    return v

def _amplitude_windows_samples(seconds, sf, name):
    n = _flat_detect_positive(seconds, name) * sf
    if n < 1 or not np.isclose(n, round(n), rtol=0, atol=1e-08):
        raise ValueError(name + ' must contain an integer number of samples')
    return int(round(n))

def _amplitude_windows_windows(x, a, p):
    sf = float(x.info['sfreq'])
    win = _amplitude_windows_samples(p['window_s'], sf, 'window_s')
    step = _amplitude_windows_samples(p['stride_s'], sf, 'stride_s')
    if p['tail'] != 'drop':
        raise ValueError('tail must be drop')
    iv = _flat_detect_segments(x, p['valid_intervals'])
    bounds = np.array([(s, e) for lo, hi in iv for s in range(lo, hi - win + 1, step) for e in [s + win]], dtype=int).reshape(-1, 2)
    if len(bounds) < p['min_windows'] or not isinstance(p['min_windows'], int) or isinstance(p['min_windows'], bool) or (p['min_windows'] < 1):
        raise ValueError('insufficient valid windows or invalid min_windows')
    return (np.stack([a[:, s:e] for s, e in bounds], axis=1), bounds)

def _operation_amplitude_windows(op, x, model=None, **p):
    p = _flat_detect_params(p, {'window_s': 1.0, 'stride_s': 0.5, 'tail': 'drop', 'valid_intervals': None, 'min_windows': 1, 'peak_to_peak_limit_V': 0.0001, 'frac_bad': 0.25})
    a, names, sf = _flat_detect_start(op, 'amplitude_windows', x, model)
    w, bounds = _amplitude_windows_windows(x, a, p)
    limit = _flat_detect_positive(p['peak_to_peak_limit_V'], 'peak_to_peak_limit_V')
    frac = _amplitude_windows_fraction(p['frac_bad'], 'frac_bad')
    ptp = np.ptp(w, axis=-1)
    mask = ptp > limit
    rate = mask.mean(axis=1)
    return _flat_detect_result(x, names, windows_samples=bounds, ptp_V=ptp, bad_window_mask=mask, bad_fraction=rate, candidates=_flat_detect_candidates(names, rate > frac), denominator=len(bounds), comparison='ptp > limit; fraction > frac_bad')

def _absolute_voltage_epoch_axes(x, names):
    return {'channel_names': names, 'epoch_selection': np.asarray(x.selection).copy(), 'events': x.events.copy(), 'times_s': x.times.copy()}

def _operation_absolute_voltage(op, x, model=None, **p):
    p = _flat_detect_params(p, {'limit_V': 0.001, 'picks': None})
    a, names, sf = _flat_detect_start(op, 'absolute_voltage', x, model, True, p['picks'])
    limit = _flat_detect_positive(p['limit_V'], 'limit_V')
    mask = np.abs(a) > limit
    art = {'sample_mask': mask, 'maximum_absolute_V': np.max(np.abs(a), axis=-1), 'exceeded': np.any(mask, axis=-1), 'limit_V': limit}
    if isinstance(x, mne.BaseEpochs):
        art.update(_absolute_voltage_epoch_axes(x, names))
        art['axis_order'] = 'epoch, channel, time'
        art['epoch_mask'] = np.any(mask, axis=(1, 2))
    else:
        art['axis_order'] = 'channel, time'
        art['candidates'] = _flat_detect_candidates(names, np.any(mask, axis=-1))
        art['first_samp'] = x.first_samp
    return _flat_detect_result(x, names, **{k: v for k, v in art.items() if k != 'channel_names'})

def eeg_amplitude_threshold(op, x, model=None, **p):
    if op == 'amplitude_detect':
        return _operation_amplitude_detect(op, x, model=model, **p)
    if op == 'flat_detect':
        return _operation_flat_detect(op, x, model=model, **p)
    if op == 'amplitude_windows':
        return _operation_amplitude_windows(op, x, model=model, **p)
    if op == 'absolute_voltage':
        return _operation_absolute_voltage(op, x, model=model, **p)
    raise NotImplementedError(op)
