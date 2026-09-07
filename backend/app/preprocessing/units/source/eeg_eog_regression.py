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

def _scope(s, roles=('train',)):
    if not isinstance(s, dict) or set(s) != {'role', 'ids'} or s['role'] not in roles:
        raise ValueError('scope={role,ids}；仅使用允许的训练/校准对象')
    _ids(s['ids'])

def _ids(ids):
    if not isinstance(ids, (list, tuple)) or not ids or any((not isinstance(i, str) or not i.strip() for i in ids)) or (len(set(ids)) != len(ids)):
        raise ValueError('ID 必须为非空、唯一的字符串列表')

def _continuous(raw, bad=False):
    if isinstance(raw, mne.io.BaseRaw):
        prefixes = ('edge', 'bad_acq_skip', 'boundary') + (('bad',) if bad else ())
        if any((d.lower().startswith(prefixes) for d in raw.annotations.description)):
            raise ValueError('存在断点/不允许的BAD段；先按有效连续区间拆分')

def _channels(x, names, kind='eeg'):
    _ids(names)
    valid = {n for (n, t) in zip(x.ch_names, x.get_channel_types()) if t == kind}
    if not set(names) <= valid:
        raise ValueError(f'需要已有 {kind} 通道列表')

def _signature(x):
    import hashlib
    projs = tuple(((p['desc'], int(p['kind']), bool(p['active']), tuple(p['data']['col_names']), hashlib.sha256(np.asarray(p['data']['data']).tobytes()).hexdigest()) for p in x.info['projs']))
    return (tuple(x.ch_names), tuple(x.get_channel_types()), tuple(x.info['bads']), int(x.info['custom_ref_applied']), projs)

def _model(m, kind, x=None):
    if not isinstance(m, dict) or m.get('kind') != kind:
        raise ValueError('模型种类不匹配')
    if x is not None and m['signature'] != _signature(x):
        raise ValueError('通道/顺序/bads/参考/投影与拟合数据不兼容')
    if 'estimator' not in m:
        raise ValueError('模型缺 estimator')
    return m['estimator']

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

def _eeg_eog_regression_eog_fit(op, x, model=None, **p):
    y = _copy(x)
    before = y.get_data().copy()
    if isinstance(y, mne.BaseEpochs) and y.baseline is not None:
        raise ValueError('先伪迹校正，后基线；不自动重做基线')
    _args(p, 'picks picks_artifact scope reference_id')
    _scope(p['scope'], ('train', 'calibration'))
    _channels(y, p['picks'])
    _channels(y, p['picks_artifact'], 'eog')
    if set(p['picks'] + p['picks_artifact']) & set(y.info['bads']):
        raise ValueError('回归通道含坏道')
    _continuous(y, bad=True)
    if not isinstance(p['reference_id'], str) or not p['reference_id'].strip():
        raise ValueError('reference_id缺失')
    est = mne.preprocessing.EOGRegression(picks=p['picks'], picks_artifact=p['picks_artifact'], proj=False).fit(y)
    return _out(y, dict(kind='eog', estimator=est, signature=_signature(y), scope=p['scope'], reference_id=p['reference_id']))

def _eeg_eog_regression_eog_apply(op, x, model=None, **p):
    y = _copy(x)
    before = y.get_data().copy()
    if isinstance(y, mne.BaseEpochs) and y.baseline is not None:
        raise ValueError('先伪迹校正，后基线；不自动重做基线')
    _args(p, 'reference_id')
    _model(model, 'eog', y)
    if p['reference_id'] != model['reference_id']:
        raise ValueError('参考配置不一致')
    y = _model(model, 'eog', y).apply(y, copy=True)
    return _out(y, model, removed=before - y.get_data())

def eeg_eog_regression(op, x, model=None, **p):
    if op == 'eog_fit':
        if model is not None:
            raise ValueError('此操作不接受模型')
        return _eeg_eog_regression_eog_fit(op, x, model=model, **p)
    if op == 'eog_apply':
        if model is None:
            raise ValueError('此操作需要已拟合模型')
        return _eeg_eog_regression_eog_apply(op, x, model=model, **p)
    raise NotImplementedError(op)
