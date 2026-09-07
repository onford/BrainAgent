# Python 3.12 | MNE 1.10.2 | NumPy 1.26.4 | SciPy 1.15.3
import numpy as np
import mne
from scipy import signal as _sig
import hashlib as _core_hashlib
import warnings as _core_warnings

def _core_array_hash(a):
    a = np.ascontiguousarray(a)
    return _core_hashlib.sha256(str((a.dtype.str, a.shape)).encode() + a.tobytes()).hexdigest()

def _core_kwargs(p, defaults, required=()):
    missing = set(required) - set(p)
    unknown = set(p) - set(defaults)
    if missing or unknown:
        raise ValueError('missing parameters=' + str(sorted(missing)) + '; unknown=' + str(sorted(unknown)))
    return dict(defaults, **p)

def _core_names(y, names, allow_empty=False):
    if not isinstance(names, (list, tuple)) or (not names and (not allow_empty)) or any((not isinstance(n, str) for n in names)) or (len(set(names)) != len(names)):
        raise ValueError('channel names must be unique')
    good = {n for (n, t) in zip(y.ch_names, y.get_channel_types()) if t == 'eeg'}
    if not set(names) <= good:
        raise ValueError('existing EEG names required')
    return [y.ch_names.index(n) for n in names]

def _core_nonfinite_policy(value):
    if value not in ('reject', 'propagate'):
        raise ValueError('nonfinite must be reject or propagate')
    return value == 'propagate'

def _core_out(data, model=None, **artifacts):
    return {'data': data, 'model': model, 'artifacts': artifacts}

def _core_raw(x, allow_nan=False, epochs=False):
    if not isinstance(x, (mne.io.BaseRaw, mne.BaseEpochs) if epochs else mne.io.BaseRaw):
        raise TypeError('expected ' + ('Raw/Epochs' if epochs else 'Raw'))
    if isinstance(x, mne.BaseEpochs) and (not x.preload):
        raise ValueError('Epochs must be preloaded')
    y = x.copy().load_data()
    a = y.get_data()
    if not a.size or np.iscomplexobj(a) or np.isinf(a).any() or (not allow_nan and np.isnan(a).any()):
        raise ValueError('empty, complex or unsupported nonfinite signal')
    return y

def _core_real(value, name, low=None, high=None, strict=False):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)) or (not np.isfinite(value)):
        raise ValueError(name + ' must be finite real')
    if low is not None and (value <= low if strict else value < low):
        raise ValueError(name + ' below range')
    if high is not None and value > high:
        raise ValueError(name + ' above range')
    return float(value)

def _operation_filter(op, x, model=None, **p):
    if model is not None:
        raise ValueError('filter does not accept model')
    p = _core_kwargs(p, {'l_freq': None, 'h_freq': None, 'method': 'fir', 'phase': 'zero', 'picks': None, 'fir_design': 'firwin', 'fir_window': 'hamming', 'filter_length': 'auto', 'l_trans_bandwidth': 'auto', 'h_trans_bandwidth': 'auto', 'pad': 'reflect_limited', 'annotation_policy': 'raw', 'skip_by_annotation': ('edge', 'bad_acq_skip', 'boundary'), 'nonfinite': 'reject'}, ('l_freq', 'h_freq', 'method', 'phase', 'picks'))
    y = _core_raw(x, allow_nan=_core_nonfinite_policy(p['nonfinite']))
    idx = _core_names(y, p['picks'])
    sf = float(y.info['sfreq'])
    (lo, hi) = (p['l_freq'], p['h_freq'])
    if lo is None and hi is None:
        raise ValueError('a cutoff is required')
    for name in ('l_freq', 'h_freq'):
        if p[name] is not None:
            _core_real(p[name], name, 0, sf / 2, True)
            if p[name] >= sf / 2:
                raise ValueError('cutoff must be below Nyquist')
    if lo is not None and hi is not None and (lo >= hi):
        raise ValueError('filter requires l_freq < h_freq')
    if p['annotation_policy'] not in ('raw', 'array'):
        raise ValueError('annotation_policy must be raw or array')
    if p['annotation_policy'] == 'raw' and p['nonfinite'] != 'reject':
        raise ValueError('propagation requires explicit array policy')
    skip = p['skip_by_annotation']
    if not isinstance(skip, (list, tuple)) or any((not isinstance(v, str) or not v for v in skip)):
        raise ValueError('invalid annotation prefixes')
    if p['annotation_policy'] == 'array' and tuple(skip) != ('edge', 'bad_acq_skip', 'boundary'):
        raise ValueError('custom skip_by_annotation only applies to raw policy')
    if p['method'] == 'fir':
        if p['phase'] not in ('zero', 'zero-double', 'minimum', 'minimum-half'):
            raise ValueError('invalid FIR phase')
        if p['fir_design'] not in ('firwin', 'firwin2'):
            raise ValueError('invalid FIR design')
        if p['fir_window'] not in ('hamming', 'hann', 'blackman'):
            raise ValueError('invalid FIR window')
        if isinstance(p['filter_length'], (bool, np.bool_)):
            raise ValueError('invalid filter length')
        for key in ('l_trans_bandwidth', 'h_trans_bandwidth'):
            if p[key] != 'auto':
                _core_real(p[key], key, 0, strict=True)
        kw = {k: p[k] for k in ('method', 'phase', 'fir_design', 'fir_window', 'filter_length', 'l_trans_bandwidth', 'h_trans_bandwidth', 'pad')}
    elif p['method'] == 'iir':
        if p['phase'] not in ('zero', 'forward', 'zero-double'):
            raise ValueError('invalid IIR phase')
        if any((p[k] != v for (k, v) in {'fir_design': 'firwin', 'fir_window': 'hamming', 'filter_length': 'auto', 'l_trans_bandwidth': 'auto', 'h_trans_bandwidth': 'auto'}.items())):
            raise ValueError('FIR parameters inactive for IIR')
        kw = {'method': 'iir', 'phase': p['phase'], 'iir_params': dict(order=4, ftype='butter', output='sos'), 'pad': p['pad']}
    else:
        raise ValueError('method must be fir or iir')
    before = y.get_data().copy()
    with _core_warnings.catch_warnings(record=True) as caught:
        _core_warnings.simplefilter('always')
        if p['annotation_policy'] == 'array':
            y._data[idx] = mne.filter.filter_data(before[idx], sf, lo, hi, copy=True, **kw)
        else:
            y.filter(lo, hi, picks=list(p['picks']), skip_by_annotation=tuple(skip), **kw)
    return _core_out(y, parameters=p, array_filter_preserves_info=p['annotation_policy'] == 'array', warnings=[str(w.message) for w in caught], input_hash=_core_array_hash(before), output_hash=_core_array_hash(y.get_data()))

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

def _operation_butter(x, **p):
    _args(p, 'kind l_freq h_freq prototype_order phase picks padlen')
    y = _copy(x)
    _sig_continuous(y)
    indices = _sig_picks(y, p['picks'])
    fs = y.info['sfreq']
    order = _sig_int(p['prototype_order'], 'prototype_order', 1)
    if order > 12:
        raise ValueError('prototype_order exceeds supported stable design range 1..12')
    kind = p['kind']
    lo = p['l_freq']
    hi = p['h_freq']
    if kind not in ('highpass', 'lowpass', 'bandpass', 'bandstop'):
        raise ValueError('unknown filter kind')
    if p['phase'] not in ('zero', 'forward'):
        raise ValueError('phase must be zero or forward')
    if lo is not None:
        _number(lo, 'l_freq', 0, fs / 2, strict_low=True)
    if hi is not None:
        _number(hi, 'h_freq', 0, fs / 2, strict_low=True)
    if lo is not None and lo >= fs / 2 or (hi is not None and hi >= fs / 2):
        raise ValueError('cutoff must be below Nyquist')
    if kind == 'highpass' and (lo is None or hi is not None):
        raise ValueError('highpass requires l_freq only')
    if kind == 'lowpass' and (hi is None or lo is not None):
        raise ValueError('lowpass requires h_freq only')
    if kind in ('bandpass', 'bandstop') and (lo is None or hi is None or lo >= hi):
        raise ValueError('band filter requires l_freq < h_freq')
    wn = [lo, hi] if kind in ('bandpass', 'bandstop') else lo if kind == 'highpass' else hi
    (b, a) = _sig.butter(order, wn, btype=kind, fs=fs)
    if np.any(np.abs(np.roots(a)) >= 1):
        raise ValueError('direct-form design numerically unstable; change supported order/cutoffs')
    padlen = 3 * (max(len(a), len(b)) - 1) if p['padlen'] is None else _sig_int(p['padlen'], 'padlen')
    before = y.get_data()
    values = before[indices] if before.ndim == 2 else before[:, indices, :]
    if p['phase'] == 'zero':
        if values.shape[-1] <= padlen:
            raise ValueError('record/window shorter than padding')
        after = _sig.filtfilt(b, a, values, axis=-1, padtype='odd', padlen=padlen)
    else:
        if p['padlen'] not in (None, 0):
            raise ValueError('forward filtering has zero initial state and no padding')
        after = _sig.lfilter(b, a, values, axis=-1)
        padlen = 0
    if not np.isfinite(after).all():
        raise ValueError('filter produced nonfinite output')
    if before.ndim == 2:
        y._data[indices] = after
    else:
        y._data[:, indices, :] = after
    all_eeg = {n for (n, t) in zip(y.ch_names, y.get_channel_types()) if t in ('eeg', 'eog', 'ecg', 'emg', 'misc')}
    if set(p['picks']) == all_eeg:
        with y.info._unlock():
            if kind in ('highpass', 'bandpass'):
                y.info['highpass'] = max(y.info['highpass'], lo)
            if kind in ('lowpass', 'bandpass'):
                y.info['lowpass'] = min(y.info['lowpass'], hi)
    return _out(y, b=b, a=a, prototype_order=order, phase=p['phase'], padlen=padlen, picks=list(p['picks']), removed=before - y.get_data())

def _sig_continuous(y):
    if isinstance(y, mne.io.BaseRaw) and any((str(d).lower().startswith(('boundary', 'edge', 'bad_acq_skip', 'bad boundary', 'bad_boundary')) for d in y.annotations.description)):
        raise ValueError('split acquisition boundaries before this operation')

def _sig_int(value, name, minimum=0):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise ValueError(name + ' requires an integer >= ' + str(minimum))
    return int(value)

def _sig_picks(y, picks):
    if not isinstance(picks, (list, tuple)) or not picks or len(set(picks)) != len(picks) or (not all((isinstance(k, str) for k in picks))):
        raise ValueError('picks requires unique channel names')
    if any((k not in y.ch_names for k in picks)):
        raise ValueError('unknown channel')
    indices = [y.ch_names.index(k) for k in picks]
    if any((y.get_channel_types()[i] not in ('eeg', 'eog', 'ecg', 'emg', 'misc') for i in indices)):
        raise ValueError('voltage channel picks required')
    return indices

def _channels(x, names, kind='eeg'):
    _ids(names)
    valid = {n for (n, t) in zip(x.ch_names, x.get_channel_types()) if t == kind}
    if not set(names) <= valid:
        raise ValueError(f'需要已有 {kind} 通道列表')

def _continuous(raw, bad=False):
    if isinstance(raw, mne.io.BaseRaw):
        prefixes = ('edge', 'bad_acq_skip', 'boundary') + (('bad',) if bad else ())
        if any((d.lower().startswith(prefixes) for d in raw.annotations.description)):
            raise ValueError('存在断点/不允许的BAD段；先按有效连续区间拆分')

def _operation_notch(op, x, **p):
    y = _copy(x)
    _args(p, 'freqs picks')
    if not isinstance(y, mne.io.BaseRaw):
        raise TypeError('notch 仅 Raw')
    _continuous(y)
    _channels(y, p['picks'])
    freqs = np.asarray(p['freqs'])
    if freqs.ndim != 1 or not len(freqs) or freqs.dtype.kind not in 'fiu' or (not np.isfinite(freqs).all()) or np.any((freqs <= 0) | (freqs >= y.info['sfreq'] / 2)):
        raise ValueError('非法notch频率')
    y.notch_filter(**p, method='fir', phase='zero', fir_design='firwin', notch_widths=None, trans_bandwidth=1.0)
    return _out(y)

def _ids(ids):
    if not isinstance(ids, (list, tuple)) or not ids or any((not isinstance(i, str) or not i.strip() for i in ids)) or (len(set(ids)) != len(ids)):
        raise ValueError('ID 必须为非空、唯一的字符串列表')

def eeg_filter(op, x, model=None, **p):
    if model is not None:
        raise ValueError('operation does not accept model')
    if op == 'filter':
        return _operation_filter(op, x, model=None, **p)
    if op == 'butter':
        return _operation_butter(x, **p)
    if op == 'notch':
        return _operation_notch(op, x, **p)
    raise NotImplementedError(op)
