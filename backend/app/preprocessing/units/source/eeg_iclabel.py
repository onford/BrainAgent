# Python 3.12 | MNE 1.10.2 | NumPy 1.26.4 | SciPy 1.15.3 | scikit-learn 1.6.1
import numpy as np
import mne
import warnings
from sklearn.exceptions import ConvergenceWarning
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

def _scope(s, roles=('train',)):
    if not isinstance(s, dict) or set(s) != {'role', 'ids'} or s['role'] not in roles:
        raise ValueError('scope={role,ids}；仅使用允许的训练/校准对象')
    _ids(s['ids'])

def _ids(ids):
    if not isinstance(ids, (list, tuple)) or not ids or any((not isinstance(i, str) or not i.strip() for i in ids)) or (len(set(ids)) != len(ids)):
        raise ValueError('ID 必须为非空、唯一的字符串列表')

def _integer(v, name, minimum=0):
    if isinstance(v, bool) or not isinstance(v, Integral) or v < minimum:
        raise ValueError(f'{name} 需要 >= {minimum} 的整数')

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


def _exact(p, required='', **defaults):
    required=set(required.split())
    if required-set(p) or set(p)-required-set(defaults):
        raise ValueError(f'参数缺失={required-set(p)}; 未定义={set(p)-required-set(defaults)}')
    return dict(defaults, **p)

def _raw(x):
    y=_copy(x)
    if not isinstance(y,mne.io.BaseRaw): raise TypeError('需要连续 Raw')
    return y

def _epochs(x):
    y=_copy(x)
    if not isinstance(y,mne.BaseEpochs): raise TypeError('需要已加载 Epochs')
    return y

def _good(y, minimum=2):
    picks=mne.pick_types(y.info,eeg=True,exclude='bads')
    if len(picks)<minimum: raise ValueError(f'至少需要 {minimum} 个好 EEG 通道')
    return picks

def _ref(s):
    if not isinstance(s,str) or not s.strip(): raise ValueError('需要非空 reference_id')

def _mask(a,shape,name='mask'):
    a=np.asarray(a)
    if a.dtype.kind!='b' or a.shape!=shape: raise ValueError(f'{name} 需要形状 {shape} 的布尔数组')
    return a

def _finite_array(a,name,ndim=None):
    a=np.asarray(a)
    if a.dtype.kind not in 'fiu' or not np.isfinite(a).all() or (ndim is not None and a.ndim!=ndim):
        raise ValueError(name+'需要有限实数数组')
    return a.astype(float,copy=False)

def _same(model,kind,y,reference_id):
    est=_model(model,kind,y)
    if model.get('reference_id')!=reference_id or model.get('sfreq',float(y.info['sfreq']))!=float(y.info['sfreq']):
        raise ValueError('参考/采样率与模型不匹配')
    return est

def _fitted(kind,est,y,scope,reference_id,**extra):
    return dict(kind=kind,estimator=est,signature=_signature(y),sfreq=float(y.info['sfreq']),scope=scope,reference_id=reference_id,**extra)

def _probs(v,n):
    a=_finite_array(v,'probabilities',2)
    if a.shape!=(n,7) or np.any(a<0) or np.any(a>1) or not np.allclose(a.sum(1),1,atol=1e-5):
        raise ValueError('probabilities 需要 IC×7 概率且逐行和为 1')
    return a
import hashlib
import json
from importlib.metadata import version

def _identity_value(value):
    if isinstance(value,np.ndarray):
        if value.dtype.hasobject:raise TypeError('ICA identity cannot encode object arrays')
        if value.dtype.kind in 'fc' and not np.isfinite(value).all():raise ValueError('ICA identity parameters must be finite')
        return {'__ndarray__':{'dtype':value.dtype.str,'shape':list(value.shape),'sha256':hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()}}
    if isinstance(value,np.generic):return _identity_value(value.item())
    if value is None or isinstance(value,(str,bool,int)):return value
    if isinstance(value,float):
        if not np.isfinite(value):raise ValueError('ICA identity parameters must be finite')
        return value
    if isinstance(value,(list,tuple)):return [_identity_value(v) for v in value]
    if isinstance(value,dict):
        if any(not isinstance(k,str) for k in value):raise TypeError('ICA identity dictionary keys must be strings')
        return {k:_identity_value(value[k]) for k in sorted(value)}
    raise TypeError('Unsupported ICA identity parameter type: '+type(value).__name__)

def _component_id(ic):
    metadata=dict(method=ic.method,n_components=int(ic.n_components_),fit_params=ic.fit_params,ch_names=ic.ch_names)
    h=hashlib.sha256(json.dumps(_identity_value(metadata),sort_keys=True,allow_nan=False).encode())
    for a in (ic.unmixing_matrix_,ic.mixing_matrix_,ic.pca_components_,ic.pre_whitener_,ic.pca_mean_):
        h.update(str(np.shape(a)).encode());h.update(np.asarray(a,dtype='<f8').tobytes())
    h.update('\0'.join(ic.ch_names).encode())
    return h.hexdigest()


def eeg_iclabel(op,x,model=None,**p):
    if op!='iclabel_assess': raise NotImplementedError(op)
    y=_copy(x)
    p=_exact(p,'reference_id',backend='torch')
    if p['backend'] not in ('onnx','torch'): raise ValueError('backend=onnx|torch')
    ic=_same(model,'ica',y,p['reference_id'])
    positions=np.array([y.info['chs'][y.ch_names.index(n)]['loc'][:3] for n in ic.ch_names])
    if not np.isfinite(positions).all() or np.any(np.linalg.norm(positions,axis=1)==0): raise ValueError('ICLabel 需要所有 ICA 通道的头皮坐标')
    from mne._fiff.constants import FIFF
    average_projs=[proj for proj in y.info['projs'] if proj['kind']==FIFF.FIFFV_PROJ_ITEM_EEG_AVREF]
    if any(not proj['active'] for proj in average_projs):
        raise ValueError('ICLabel 平均参考投影须先 apply；评估不会隐式应用投影')
    eeg_values=y.get_data(picks=ic.ch_names)
    car_error=float(np.max(np.abs(eeg_values.mean(axis=-2))))
    car_tolerance=1e-12+1e-7*float(np.max(np.abs(eeg_values)))
    car_check=dict(channels=list(ic.ch_names),max_abs_mean_V=car_error,tolerance_V=car_tolerance,
                   applied_average_projection=any(proj['active'] for proj in average_projs))
    from mne_icalabel.iclabel import iclabel_label_components
    from pathlib import Path
    import mne_icalabel
    probabilities=_probs(iclabel_label_components(y,ic.copy(),inplace=False,backend=p['backend']),ic.n_components_)
    resource=Path(mne_icalabel.__file__).parent/'iclabel'/'network'/'assets'
    weights={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in resource.glob('*') if f.suffix in ('.onnx','.pt')}
    classes=('brain','muscle','eye','heart','line_noise','channel_noise','other')
    labels=probabilities.argmax(1)
    return _out(y,model,probabilities=probabilities,classes=classes,labels=[classes[k] for k in labels],
        component_id=_component_id(ic),weights=weights,backend=p['backend'],version=version('mne-icalabel'),
        input_domain=dict(car_check=car_check,highpass=y.info['highpass'],lowpass=y.info['lowpass'],sfreq=y.info['sfreq'],reference_id=p['reference_id'],ica_method=ic.method,fit_params=ic.fit_params.copy()),
        domain_flags=([] if car_error<=car_tolerance else ['reference_differs_from_common_average_on_ICA_EEG_channels']) +
        ([] if np.isclose(y.info['highpass'],1,rtol=0,atol=1e-8) and np.isclose(y.info['lowpass'],100,rtol=0,atol=1e-8) else ['frequency_band_differs_from_recommended_1_100_Hz']) +
        ([] if ic.method=='infomax' and ic.fit_params.get('extended') or ic.method=='picard' and ic.fit_params.get('extended') and not ic.fit_params.get('ortho') else ['ica_differs_from_extended_infomax']))
