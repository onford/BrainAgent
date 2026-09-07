# Python 3.12 | MNE 1.10.2 | NumPy 1.26.4 | SciPy 1.15.3
import numpy as np
import mne
from fractions import Fraction
from scipy import signal as _sig

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

def _continuous(raw, bad=False):
    if isinstance(raw, mne.io.BaseRaw):
        prefixes = ('edge', 'bad_acq_skip', 'boundary') + (('bad',) if bad else ())
        if any((d.lower().startswith(prefixes) for d in raw.annotations.description)):
            raise ValueError('存在断点/不允许的BAD段；先按有效连续区间拆分')

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

def _operation_resample(op, x, **p):
    y = _copy(x)
    _args(p, 'sfreq events')
    _number(p['sfreq'], 'sfreq', 0, strict_low=True)
    if p['sfreq'] <= 0:
        raise ValueError('sfreq > 0')
    if isinstance(y, mne.io.BaseRaw):
        if p['events'] is None:
            raise ValueError('Raw 必须显式传入事件数组，允许 shape=(0,3)')
        _continuous(y)
        (y, events) = y.resample(p['sfreq'], events=_events(p['events'], y), method='polyphase')
        _events(events, y)
    else:
        if p['events'] is not None:
            raise ValueError('Epochs events 必须为 None；原始 events 不重标样点')
        y.resample(p['sfreq'], method='polyphase')
        events = y.events.copy()
    return _out(y, events=events, sfreq=y.info['sfreq'])

def _events(events, raw=None):
    e = np.asarray(events)
    if e.dtype.kind not in 'iu' or e.ndim != 2 or e.shape[1] != 3:
        raise ValueError('events 必须为整数 n×3，禁止自动截断小数')
    if len(e) and (np.any(e[:, 0] < 0) or np.any(np.diff(e[:, 0].astype(float)) <= 0)):
        raise ValueError('events 样点必须非负且严格递增；有重复/碰撞')
    if raw is not None and len(e) and (e[0, 0] < raw.first_samp or e[-1, 0] > raw.last_samp):
        raise ValueError('events 超出当前 Raw 范围')
    return e.astype(np.int64, copy=True)

def _number(value, name, low=None, high=None, strict_low=False):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)) or (not np.isfinite(value)):
        raise ValueError(name + ' requires finite real scalar')
    if low is not None and (value <= low if strict_low else value < low):
        raise ValueError(name + ' below permitted range')
    if high is not None and value > high:
        raise ValueError(name + ' above permitted range')

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

def _sig_continuous(y):
    if isinstance(y, mne.io.BaseRaw) and any((str(d).lower().startswith(('boundary', 'edge', 'bad_acq_skip', 'bad boundary', 'bad_boundary')) for d in y.annotations.description)):
        raise ValueError('split acquisition boundaries before this operation')

def _sig_events(events, y, fractional=False):
    a = np.asarray(events)
    allowed = 'iuf' if fractional else 'iu'
    if a.dtype.kind not in allowed or a.ndim != 2 or a.shape[1] != 3 or (not np.isfinite(a).all()):
        raise ValueError('events requires finite n×3 sample table')
    if len(a) and (np.any(np.diff(a[:, 0]) <= 0) or np.any(a[:, 0] < y.first_samp) or np.any(a[:, 0] > y.last_samp)):
        raise ValueError('events outside input or non-increasing')
    if fractional and np.any(a[:, 1:] != np.round(a[:, 1:])):
        raise ValueError('event codes must be integers')
    return a.copy()

def _operation_resample_fft(x, **p):
    _args(p, 'sfreq events npad window pad')
    y = _copy(x)
    if not isinstance(y, mne.io.BaseRaw):
        raise ValueError('FFT resample requires Raw')
    _sig_continuous(y)
    _number(p['sfreq'], 'sfreq', 0, strict_low=True)
    events = _sig_events(p['events'], y)
    if p['npad'] != 'auto':
        _sig_int(p['npad'], 'npad')
    if p['window'] not in ('boxcar', 'hann', 'hamming', 'blackman'):
        raise ValueError('unsupported named FFT window')
    if p['pad'] not in ('reflect_limited', 'reflect', 'edge', 'constant'):
        raise ValueError('unsupported padding')
    (out, event_out) = y.resample(p['sfreq'], npad=p['npad'], window=p['window'], pad=p['pad'], events=events, method='fft', verbose=False)
    collisions = np.flatnonzero(np.diff(event_out[:, 0]) == 0) + 1
    return _out(out, events=event_out, collision_indices=collisions, sfreq=out.info['sfreq'], method='fft', npad=p['npad'], window=p['window'], pad=p['pad'])

def _sig_int(value, name, minimum=0):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise ValueError(name + ' requires an integer >= ' + str(minimum))
    return int(value)

def _operation_resample_fir(x, **p):
    _args(p, 'sfreq events kernel')
    y = _copy(x)
    if not isinstance(y, mne.io.BaseRaw):
        raise ValueError('resample_fir requires continuous Raw')
    _sig_continuous(y)
    _number(p['sfreq'], 'sfreq', 0, strict_low=True)
    oldfs = y.info['sfreq']
    ratio = Fraction(float(p['sfreq'] / oldfs)).limit_denominator(100000)
    (up, down) = (ratio.numerator, ratio.denominator)
    if not np.isclose(up / down, p['sfreq'] / oldfs, rtol=0, atol=1e-12):
        raise ValueError('sampling ratio not representable within limit')
    kernel = np.asarray(p['kernel'])
    if kernel.dtype.kind not in 'iuf' or kernel.ndim != 1 or len(kernel) < 3 or (len(kernel) % 2 != 1) or (not np.isfinite(kernel).all()) or (not np.allclose(kernel, kernel[::-1], rtol=1e-12, atol=1e-15)) or (not np.isclose(kernel.sum(), 1.0, rtol=1e-10, atol=1e-14)):
        raise ValueError('odd symmetric finite unit-DC FIR kernel required')
    events = _sig_events(p['events'], y, fractional=True)
    n_pad = int(np.ceil((len(kernel) - 1) / 2 / down) * down)
    old = y.get_data()
    padded = np.pad(old, ((0, 0), (n_pad, n_pad)), mode='edge')
    values = _sig.resample_poly(padded, up, down, axis=-1, window=kernel, padtype='constant')
    trim = n_pad * up // down
    values = values[:, trim:len(values[0]) - trim] if trim else values
    expected = int(np.ceil(y.n_times * up / down))
    if values.shape[1] != expected:
        raise RuntimeError('resampling length mismatch')
    info = y.info.copy()
    with info._unlock():
        info['sfreq'] = float(p['sfreq'])
        info['lowpass'] = min(info['lowpass'], float(p['sfreq']) / 2)
    first = int(np.floor(y.first_samp * up / down))
    out = mne.io.RawArray(values, info, first_samp=first, verbose=False)
    relative_onsets = y.annotations.onset - out.first_time
    ann = mne.Annotations(relative_onsets.copy(), y.annotations.duration.copy(), y.annotations.description.copy(), orig_time=None, ch_names=y.annotations.ch_names)
    out.set_annotations(ann)
    mapped = events.astype(float)
    mapped[:, 0] = events[:, 0] * up / down
    rounded = mapped.copy()
    rounded[:, 0] = np.floor(mapped[:, 0] + 0.5)
    collisions = np.flatnonzero(np.diff(rounded[:, 0]) == 0) + 1
    outside = np.flatnonzero((rounded[:, 0] < out.first_samp) | (rounded[:, 0] > out.last_samp))
    return _out(out, events_fractional=mapped, events_nearest=rounded.astype(np.int64), collision_indices=collisions, out_of_range_event_indices=outside, up=up, down=down, kernel=kernel.copy(), endpoint_padding=n_pad, input_first_samp=y.first_samp, output_first_samp=first, origin_quantization_s=out.first_time - y.first_time, event_frame='absolute output samples; validate collisions and out_of_range_event_indices before Epochs')

def _operation_resample_eeglab(x, **p):
    _args(p, 'sfreq events cutoff transition ripple beta')
    y = _copy(x)
    if not isinstance(y, mne.io.BaseRaw):
        raise ValueError('continuous Raw required')
    _number(p['sfreq'], 'sfreq', 0, strict_low=True)
    for key in ('cutoff', 'transition', 'ripple'):
        _number(p[key], key, 0, 1, strict_low=True)
    if p['cutoff'] >= 1 or p['ripple'] >= 1 or p['transition'] >= 1:
        raise ValueError('cutoff/transition/ripple require values <1')
    _number(p['beta'], 'beta', 0, 30)
    ratio = Fraction(float(p['sfreq'] / y.info['sfreq'])).limit_denominator(100000)
    scale = max(ratio.numerator, ratio.denominator)
    fc = p['cutoff'] / scale
    df = p['transition'] / scale
    order = int(np.ceil((1 + (-20 * np.log10(p['ripple']) - 8) / (2.285 * np.pi * df)) / 2) * 2)
    if order < 2 or order > 100000:
        raise ValueError('derived FIR order unsupported')
    kernel = _sig.firwin(order + 1, fc, window=('kaiser', p['beta']), scale=True)
    result = _sig_resample_fir(y, sfreq=p['sfreq'], events=p['events'], kernel=kernel)
    result['artifacts'].update(cutoff=p['cutoff'], transition=p['transition'], ripple=p['ripple'], beta=p['beta'], fir_order=order, normalized_cutoff=fc, normalized_transition=df)
    return result

def _sig_resample_fir(x, **p):
    _args(p, 'sfreq events kernel')
    y = _copy(x)
    if not isinstance(y, mne.io.BaseRaw):
        raise ValueError('resample_fir requires continuous Raw')
    _sig_continuous(y)
    _number(p['sfreq'], 'sfreq', 0, strict_low=True)
    oldfs = y.info['sfreq']
    ratio = Fraction(float(p['sfreq'] / oldfs)).limit_denominator(100000)
    (up, down) = (ratio.numerator, ratio.denominator)
    if not np.isclose(up / down, p['sfreq'] / oldfs, rtol=0, atol=1e-12):
        raise ValueError('sampling ratio not representable within limit')
    kernel = np.asarray(p['kernel'])
    if kernel.dtype.kind not in 'iuf' or kernel.ndim != 1 or len(kernel) < 3 or (len(kernel) % 2 != 1) or (not np.isfinite(kernel).all()) or (not np.allclose(kernel, kernel[::-1], rtol=1e-12, atol=1e-15)) or (not np.isclose(kernel.sum(), 1.0, rtol=1e-10, atol=1e-14)):
        raise ValueError('odd symmetric finite unit-DC FIR kernel required')
    events = _sig_events(p['events'], y, fractional=True)
    n_pad = int(np.ceil((len(kernel) - 1) / 2 / down) * down)
    old = y.get_data()
    padded = np.pad(old, ((0, 0), (n_pad, n_pad)), mode='edge')
    values = _sig.resample_poly(padded, up, down, axis=-1, window=kernel, padtype='constant')
    trim = n_pad * up // down
    values = values[:, trim:len(values[0]) - trim] if trim else values
    expected = int(np.ceil(y.n_times * up / down))
    if values.shape[1] != expected:
        raise RuntimeError('resampling length mismatch')
    info = y.info.copy()
    with info._unlock():
        info['sfreq'] = float(p['sfreq'])
        info['lowpass'] = min(info['lowpass'], float(p['sfreq']) / 2)
    first = int(np.floor(y.first_samp * up / down))
    out = mne.io.RawArray(values, info, first_samp=first, verbose=False)
    relative_onsets = y.annotations.onset - out.first_time
    ann = mne.Annotations(relative_onsets.copy(), y.annotations.duration.copy(), y.annotations.description.copy(), orig_time=None, ch_names=y.annotations.ch_names)
    out.set_annotations(ann)
    mapped = events.astype(float)
    mapped[:, 0] = events[:, 0] * up / down
    rounded = mapped.copy()
    rounded[:, 0] = np.floor(mapped[:, 0] + 0.5)
    collisions = np.flatnonzero(np.diff(rounded[:, 0]) == 0) + 1
    outside = np.flatnonzero((rounded[:, 0] < out.first_samp) | (rounded[:, 0] > out.last_samp))
    return _out(out, events_fractional=mapped, events_nearest=rounded.astype(np.int64), collision_indices=collisions, out_of_range_event_indices=outside, up=up, down=down, kernel=kernel.copy(), endpoint_padding=n_pad, input_first_samp=y.first_samp, output_first_samp=first, origin_quantization_s=out.first_time - y.first_time, event_frame='absolute output samples; validate collisions and out_of_range_event_indices before Epochs')

def _operation_decimate(x, **p):
    _args(p, 'decim offset')
    y = _copy(x)
    if not isinstance(y, mne.BaseEpochs):
        raise ValueError('decimate requires Epochs')
    d = _sig_int(p['decim'], 'decim', 1)
    offset = _sig_int(p['offset'], 'offset')
    if offset >= d:
        raise ValueError('offset must be < decim')
    if d > 1 and y.info['lowpass'] > y.info['sfreq'] / d / 3:
        raise ValueError('apply lowpass <= target sfreq/3 before decimation')
    old_times = y.times.copy()
    y.decimate(d, offset=offset, verbose=False)
    if not y.get_data().size:
        raise ValueError('decimation left no samples')
    indices = np.array([np.argmin(abs(old_times - t)) for t in y.times], dtype=np.int64)
    return _out(y, retained_time_indices=indices, old_times=old_times, new_times=y.times.copy(), decim=d, offset=offset)

def eeg_resample(op, x, model=None, **p):
    if model is not None:
        raise ValueError('operation does not accept model')
    if op == 'resample':
        return _operation_resample(op, x, **p)
    if op == 'resample_fft':
        return _operation_resample_fft(x, **p)
    if op == 'resample_fir':
        return _operation_resample_fir(x, **p)
    if op == 'resample_eeglab':
        return _operation_resample_eeglab(x, **p)
    if op == 'decimate':
        return _operation_decimate(x, **p)
    raise NotImplementedError(op)
