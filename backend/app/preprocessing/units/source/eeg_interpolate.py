# Python 3.12 | MNE 1.10.2 | NumPy 1.26.4 | SciPy 1.15.3
import numpy as np
import mne
from numbers import Real
from scipy.spatial.distance import cdist as _cdist
from numpy.polynomial.legendre import legval as _legval
import importlib.metadata as _core_metadata
import warnings as _core_warnings

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

def _operation_interpolate(op, x, **p):
    y = _copy(x)
    before = y.get_data().copy()
    _args(p, 'max_fraction origin')
    if 'eeg' not in y.get_channel_types():
        raise ValueError('插值输入必须含有EEG通道')
    _number(p['max_fraction'], 'max_fraction', 0, 1)
    if not isinstance(p['origin'], str) or p['origin'] != 'auto':
        _vector(p['origin'], 'origin', 3)
    eeg = set(np.array(y.ch_names)[mne.pick_types(y.info, eeg=True, exclude=[])])
    bads = [name for name in y.info['bads'] if name in eeg]
    auxiliary = [name for name in y.info['bads'] if name not in eeg]
    n = len(eeg)
    if not 0 <= p['max_fraction'] < 1 or len(bads) > n * p['max_fraction']:
        raise ValueError('插值比例超限')
    if bads and len(eeg - set(bads)) < 4:
        raise ValueError('当前模板要求至少4个好EEG通道用于插值')
    if bads:
        y.interpolate_bads(reset_bads=False, method=dict(eeg='spline'), origin=p['origin'], exclude=auxiliary)
    return _out(y, repaired=bads, before=before)

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

def _sequence(value, name, length=None):
    if not isinstance(value, (list, tuple, np.ndarray)) or (isinstance(value, np.ndarray) and value.ndim != 1):
        raise TypeError(name + '需要一维列表/元组/数组')
    if length is not None and len(value) != length:
        raise ValueError(name + '长度错误')

def _vector(value, name, length):
    _sequence(value, name, length)
    for item in value:
        _number(item, name)

def _sig_int(value, name, minimum=0):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise ValueError(name + ' requires an integer >= ' + str(minimum))
    return int(value)

def _operation_spherical(x, **p):
    _args(p, 'bad_channels origin kernel regularization stiffness terms max_fraction')
    y = _copy(x)
    bad = p['bad_channels']
    if not isinstance(bad, (list, tuple)) or len(set(bad)) != len(bad) or (not all((isinstance(k, str) for k in bad))):
        raise ValueError('bad_channels requires unique names')
    eeg = mne.pick_types(y.info, eeg=True, exclude=[])
    names = [y.ch_names[i] for i in eeg]
    if not len(eeg) or any((k not in names for k in bad)):
        raise ValueError('unknown or non-EEG bad channel')
    _number(p['max_fraction'], 'max_fraction', 0, 1)
    if p['max_fraction'] >= 1 or len(bad) > len(eeg) * p['max_fraction']:
        raise ValueError('interpolation proportion exceeded')
    o = np.asarray(p['origin'])
    if o.dtype.kind not in 'iuf' or o.shape != (3,) or (not np.isfinite(o).all()):
        raise ValueError('origin requires 3 coordinates in meters')
    if p['kernel'] not in ('eeglab', 'perrin'):
        raise ValueError('kernel must be eeglab or perrin')
    _number(p['regularization'], 'regularization', 0)
    m = _sig_int(p['stiffness'], 'stiffness', 2)
    n = _sig_int(p['terms'], 'terms', 1)
    if n > 500:
        raise ValueError('terms >500 unsupported')
    excluded = set(bad) | set(y.info['bads'])
    good = [i for i in eeg if y.ch_names[i] not in excluded]
    bad_idx = [y.ch_names.index(k) for k in bad]
    if not bad:
        return _out(y, repaired=[], interpolation_matrix=np.empty((0, len(good))), good_channels=[y.ch_names[i] for i in good])
    if len(good) < 4:
        raise ValueError('at least four good EEG channels required')
    positions = np.array([y.info['chs'][i]['loc'][:3] for i in good + bad_idx], float) - o
    radii = np.linalg.norm(positions, axis=1)
    if not np.isfinite(positions).all() or np.any(radii <= 0):
        raise ValueError('valid nonzero geometry required')
    pos = positions / radii[:, None]
    src = pos[:len(good)]
    dst = pos[len(good):]
    if np.min(_cdist(src, src) + np.eye(len(src)) * 10) < 1e-08:
        raise ValueError('duplicate good-channel geometry')
    factors = [0.0] + [(2 * k + 1) / (k ** m * (k + 1) ** m * 4 * np.pi) for k in range(1, n + 1)]
    arg = lambda a, b: 1 - _cdist(a, b) if p['kernel'] == 'eeglab' else np.clip(a @ b.T, -1, 1)
    G = _legval(arg(src, src), factors)
    H = _legval(arg(dst, src), factors)
    G += p['regularization'] * np.eye(len(good))
    if p['kernel'] == 'eeglab':
        centering = np.eye(len(good)) - np.ones((len(good), len(good))) / len(good)
        coeff = np.linalg.pinv(np.vstack([G, np.ones((1, len(good)))])) @ np.vstack([centering, np.zeros((1, len(good)))])
        matrix = H @ coeff + np.ones((len(bad), len(good))) / len(good)
    else:
        C = np.block([[G, np.ones((len(good), 1))], [np.ones((1, len(good))), np.zeros((1, 1))]])
        matrix = np.column_stack([H, np.ones(len(bad))]) @ np.linalg.pinv(C)[:, :len(good)]
    before = y.get_data()
    if before.ndim == 2:
        y._data[bad_idx] = matrix @ before[good]
    else:
        y._data[:, bad_idx, :] = np.einsum('bg,egt->ebt', matrix, before[:, good, :])
    return _out(y, repaired=list(bad), good_channels=[y.ch_names[i] for i in good], interpolation_matrix=matrix, kernel=p['kernel'], bads_preserved=list(y.info['bads']))

def _core_bool(value, name):
    if not isinstance(value, (bool, np.bool_)):
        raise TypeError(name + ' must be boolean')
    return bool(value)

def _core_kwargs(p, defaults, required=()):
    missing = set(required) - set(p)
    unknown = set(p) - set(defaults)
    if missing or unknown:
        raise ValueError('missing parameters=' + str(sorted(missing)) + '; unknown=' + str(sorted(unknown)))
    return dict(defaults, **p)

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

def _core_versions():
    if _core_metadata.version('pyprep') != '0.7.1' or mne.__version__ != '1.10.2':
        raise RuntimeError('profile requires PyPREP 0.7.1 and MNE 1.10.2')

def _operation_interpolate_native(op, x, model=None, **p):
    if model is not None:
        raise ValueError('interpolate_native does not accept model')
    p = _core_kwargs(p, {'source_profile': 'pyprep_071', 'origin': 'auto', 'reset_bads': True, 'nonfinite': 'propagate'})
    if p['source_profile'] != 'pyprep_071':
        raise ValueError('unknown source profile')
    _core_versions()
    _core_bool(p['reset_bads'], 'reset_bads')
    if not isinstance(p['origin'], str):
        origin = np.asarray(p['origin'])
        if origin.shape != (3,) or origin.dtype.kind not in 'fiu' or (not np.isfinite(origin).all()):
            raise ValueError('invalid origin')
    elif p['origin'] != 'auto':
        raise ValueError('origin must be auto or xyz')
    y = _core_raw(x, allow_nan=_core_nonfinite_policy(p['nonfinite']), epochs=True)
    eeg = {n for (n, t) in zip(y.ch_names, y.get_channel_types()) if t == 'eeg'}
    if not eeg:
        raise ValueError('EEG required')
    bads = [n for n in y.info['bads'] if n in eeg]
    aux = [n for n in y.info['bads'] if n not in eeg]
    before = y.get_data().copy()
    with _core_warnings.catch_warnings(record=True) as caught:
        _core_warnings.simplefilter('always')
        if bads:
            y.interpolate_bads(reset_bads=bool(p['reset_bads']), method={'eeg': 'spline'}, origin=p['origin'], exclude=aux)
    if bads and (not np.isfinite(y.get_data(picks=bads)).all()):
        raise ValueError('interpolation left nonfinite repaired EEG')
    return _core_out(y, repaired=bads, retained_bads=list(y.info['bads']), source_profile=p['source_profile'], before=before, warnings=[str(w.message) for w in caught])

def _epochs(x):
    y = _copy(x)
    if not isinstance(y, mne.BaseEpochs):
        raise TypeError('需要已加载 Epochs')
    return y

def _exact(p, required='', **defaults):
    required = set(required.split())
    if required - set(p) or set(p) - required - set(defaults):
        raise ValueError(f'参数缺失={required - set(p)}; 未定义={set(p) - required - set(defaults)}')
    return dict(defaults, **p)

def _finite_array(a, name, ndim=None):
    a = np.asarray(a)
    if a.dtype.kind not in 'fiu' or not np.isfinite(a).all() or (ndim is not None and a.ndim != ndim):
        raise ValueError(name + '需要有限实数数组')
    return a.astype(float, copy=False)

def _ids(ids):
    if not isinstance(ids, (list, tuple)) or not ids or any((not isinstance(i, str) or not i.strip() for i in ids)) or (len(set(ids)) != len(ids)):
        raise ValueError('ID 必须为非空、唯一的字符串列表')

def _mask(a, shape, name='mask'):
    a = np.asarray(a)
    if a.dtype.kind != 'b' or a.shape != shape:
        raise ValueError(f'{name} 需要形状 {shape} 的布尔数组')
    return a

def _eeg_trial_interpolate_number(value, name, low=None, high=None, strict_low=False):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) or (not np.isfinite(value)):
        raise ValueError(name + '需要有限实数标量')
    if low is not None and (value <= low if strict_low else value < low):
        raise ValueError(name + '低于允许范围')
    if high is not None and value > high:
        raise ValueError(name + '高于允许范围')

def _ref(s):
    if not isinstance(s, str) or not s.strip():
        raise ValueError('需要非空 reference_id')

def _operation_trial_interpolate(op, x, model=None, **p):
    if op != 'trial_interpolate':
        raise NotImplementedError(op)
    if model is not None:
        raise ValueError('固定掩码插值不接受模型')
    y = _epochs(x)
    p = _exact(p, 'mask trial_ids decision_id', max_fraction=0.1, origin='auto')
    _ids(p['trial_ids'])
    _ref(p['decision_id'])
    _eeg_trial_interpolate_number(p['max_fraction'], 'max_fraction', 0, 1)
    if len(p['trial_ids']) != len(y):
        raise ValueError('trial_ids 必须逐 Epoch 对齐')
    mask = _mask(p['mask'], (len(y), len(y.ch_names)))
    eeg = np.array(y.get_channel_types()) == 'eeg'
    if np.any(mask[:, ~eeg]):
        raise ValueError('只能插值 EEG 通道')
    if any((n in y.info['bads'] for (n, t) in zip(y.ch_names, y.get_channel_types()) if t == 'eeg')):
        raise ValueError('固定逐 Trial 掩码必须包含全部已知坏道；先清理全局 bads 并冻结掩码')
    coords = np.array([ch['loc'][:3] for (ch, t) in zip(y.info['chs'], y.get_channel_types()) if t == 'eeg'])
    if not np.isfinite(coords).all() or np.any(np.linalg.norm(coords, axis=1) == 0):
        raise ValueError('插值需要全部 EEG 的坐标')
    if not isinstance(p['origin'], str):
        origin = _finite_array(p['origin'], 'origin', 1)
        if origin.shape != (3,):
            raise ValueError('origin 必须为 3 坐标或 auto')
    elif p['origin'] != 'auto':
        raise ValueError('origin=auto 或米单位三坐标')
    before = y.get_data().copy()
    repairs = []
    for j in range(len(y)):
        names = [n for (n, bad) in zip(y.ch_names, mask[j]) if bad]
        if len(names) > p['max_fraction'] * eeg.sum():
            raise ValueError(f"Trial {p['trial_ids'][j]} 插值比例超限")
        if names:
            if eeg.sum() - len(names) < 4:
                raise ValueError('每个 Trial 至少 4 个好 EEG')
            one = y[j:j + 1].copy()
            one.info['bads'] = names
            one.interpolate_bads(reset_bads=True, method=dict(eeg='spline'), origin=p['origin'], verbose=False)
            y._data[j, mask[j], :] = one.get_data()[0, mask[j], :]
        repairs.append(names)
    if not np.array_equal(before[~mask], y.get_data()[~mask]):
        raise RuntimeError('掩码外数据被改变')
    return _out(y, None, mask=mask.copy(), trial_ids=list(p['trial_ids']), decision_id=p['decision_id'], repaired_channels=repairs, selection=y.selection.copy())

def eeg_interpolate(op, x, model=None, **p):
    if model is not None:
        raise ValueError('operation does not accept model')
    if op == 'interpolate':
        return _operation_interpolate(op, x, **p)
    if op == 'spherical':
        return _operation_spherical(x, **p)
    if op == 'interpolate_native':
        return _operation_interpolate_native(op, x, model=None, **p)
    if op == 'trial_interpolate':
        return _operation_trial_interpolate(op, x, model=None, **p)
    raise NotImplementedError(op)
