# Python 3.12 | MNE 1.10.2 | NumPy 1.26.4 | SciPy 1.15.3 | scikit-learn 1.6.1
import numpy as np
import mne
from numbers import Integral, Real

def _sequence(value, name, length=None):
    if not isinstance(value, (list, tuple, np.ndarray)) or (isinstance(value, np.ndarray) and value.ndim != 1):
        raise TypeError(name + '需要一维列表/元组/数组')
    if length is not None and len(value) != length:
        raise ValueError(name + '长度错误')

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

def _integer(v, name, minimum=0):
    if isinstance(v, bool) or not isinstance(v, Integral) or v < minimum:
        raise ValueError(f'{name} 需要 >= {minimum} 的整数')

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

def _eeg_bridge_repair_bridge_repair(op, x, **p):
    y = _copy(x)
    before = y.get_data().copy()
    _args(p, 'bridged_idx bad_limit')
    if not isinstance(y, mne.io.BaseRaw):
        raise TypeError('当前桥接方法只接受Raw')
    if not isinstance(p['bridged_idx'], (list, tuple)):
        raise TypeError('bridged_idx需要索引对列表/元组')
    for pair in p['bridged_idx']:
        _sequence(pair, 'bridged_idx pair', 2)
    _integer(p['bad_limit'], 'bad_limit', 1)
    eeg = set(mne.pick_types(y.info, eeg=True, exclude=[]))
    for pair in p['bridged_idx']:
        if len(pair) != 2 or pair[0] == pair[1] or (not set(pair) <= eeg):
            raise ValueError('桥接对必须指向两个不同的EEG通道')
        for i in pair:
            _integer(i, 'bridged_idx')
    if p['bridged_idx']:
        y = mne.preprocessing.interpolate_bridged_electrodes(y, **p)
    return _out(y, pairs=p['bridged_idx'], before=before)

def eeg_bridge_repair(op, x, model=None, **p):
    if op == 'bridge_repair':
        if model is not None:
            raise ValueError('此操作不接受模型')
        return _eeg_bridge_repair_bridge_repair(op, x, **p)
    raise NotImplementedError(op)
