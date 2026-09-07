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

def _ids(ids):
    if not isinstance(ids, (list, tuple)) or not ids or any((not isinstance(i, str) or not i.strip() for i in ids)) or (len(set(ids)) != len(ids)):
        raise ValueError('ID 必须为非空、唯一的字符串列表')

def _channels(x, names, kind='eeg'):
    _ids(names)
    valid = {n for (n, t) in zip(x.ch_names, x.get_channel_types()) if t == kind}
    if not set(names) <= valid:
        raise ValueError(f'需要已有 {kind} 通道列表')

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

def _eeg_rereference_reference(op, x, **p):
    y = _copy(x)
    _args(p, 'ref_channels')
    if p['ref_channels'] == 'REST':
        raise ValueError('REST 使用独立 rest 分支')
    if p['ref_channels'] != 'average' and (not isinstance(p['ref_channels'], list) or not p['ref_channels']):
        raise ValueError('指定参考需非空通道列表')
    if p['ref_channels'] == 'average' and len(mne.pick_types(y.info, eeg=True, exclude='bads')) < 2:
        raise ValueError('CAR 至少2个好 EEG')
    if isinstance(p['ref_channels'], list) and set(p['ref_channels']) & set(y.info['bads']):
        raise ValueError('指定参考包含坏道')
    if isinstance(p['ref_channels'], list):
        _channels(y, p['ref_channels'])
    y.set_eeg_reference(ref_channels=p['ref_channels'], projection=False)
    return _out(y, unit='V', representation='potential')

def eeg_rereference(op, x, model=None, **p):
    if op == 'reference':
        if model is not None:
            raise ValueError('此操作不接受模型')
        return _eeg_rereference_reference(op, x, **p)
    raise NotImplementedError(op)


from fractions import Fraction
from scipy import signal as _sig
from scipy.spatial.distance import cdist as _cdist
from numpy.polynomial.legendre import legval as _legval

def _sig_relax_car(x,**p):
    _args(p,'original_channels confirmed_bad_channels reference_id')
    y=_copy(x);original=p['original_channels'];bad=p['confirmed_bad_channels']
    if not isinstance(original,(list,tuple)) or len(original)!=len(set(original)) or not original:raise ValueError('original_channels requires unique names')
    eeg_names=[y.ch_names[i] for i in mne.pick_types(y.info,eeg=True,exclude=[])]
    if set(original)!=set(eeg_names):raise ValueError('temporarily interpolated full original scalp axis required')
    if not isinstance(bad,(list,tuple)) or len(bad)!=len(set(bad)) or not set(bad)<=set(original):raise ValueError('invalid confirmed_bad_channels')
    if len(bad)>=len(original):raise ValueError('cannot drop all EEG channels')
    if set(bad)!=(set(y.info['bads'])&set(eeg_names)):raise ValueError('confirmed bad list differs from temporary input bad state')
    if y.info['projs']:raise ValueError('resolve existing projectors before explicit RELAX reference')
    if not isinstance(p['reference_id'],str) or not p['reference_id']:raise ValueError('reference_id required')
    idx=[y.ch_names.index(k) for k in original];values=y.get_data();axis=0 if values.ndim==2 else 1
    selected=values[idx] if axis==0 else values[:,idx,:]
    reference=selected.sum(axis=axis,keepdims=True)/(len(original)+1)
    if axis==0:y._data[idx]=selected-reference
    else:y._data[:,idx,:]=selected-reference
    y.drop_channels(list(bad))
    with y.info._unlock():y.info['custom_ref_applied']=1
    return _out(y,reference=reference,reference_channels=list(original)+['initialReference_zero'],reference_id=p['reference_id'],removed_channels=list(bad),channel_order=list(y.ch_names),rank=int(np.linalg.matrix_rank(y.get_data(picks='eeg') if isinstance(y,mne.io.BaseRaw) else y.get_data(picks='eeg').transpose(1,0,2).reshape(len(eeg_names)-len(bad),-1))))

_legacy_eeg_rereference = eeg_rereference

def eeg_rereference(op,x,model=None,**p):
    if op == 'relax_car':
        if model is not None: raise ValueError('operation does not accept model')
        return _sig_relax_car(x,**p)
    return _legacy_eeg_rereference(op,x,model=model,**p)


# Extensions for the frozen MNE 1.10.2 / PyPREP 0.7.1 contracts.
import copy as _core_copylib
import hashlib as _core_hashlib
import importlib.metadata as _core_metadata
import warnings as _core_warnings
import json as _core_json
import numpy as np
import mne

def _core_kwargs(p, defaults, required=()):
    missing=set(required)-set(p);unknown=set(p)-set(defaults)
    if missing or unknown:raise ValueError('missing parameters='+str(sorted(missing))+'; unknown='+str(sorted(unknown)))
    return dict(defaults,**p)

def _core_bool(value,name):
    if not isinstance(value,(bool,np.bool_)):raise TypeError(name+' must be boolean')
    return bool(value)

def _core_int(value,name,low=0,high=None):
    if isinstance(value,(bool,np.bool_)) or not isinstance(value,(int,np.integer)) or value<low or (high is not None and value>high):raise ValueError(name+' invalid integer')
    return int(value)

def _core_real(value,name,low=None,high=None,strict=False):
    if isinstance(value,(bool,np.bool_)) or not isinstance(value,(int,float,np.integer,np.floating)) or not np.isfinite(value):raise ValueError(name+' must be finite real')
    if low is not None and (value<=low if strict else value<low):raise ValueError(name+' below range')
    if high is not None and value>high:raise ValueError(name+' above range')
    return float(value)

def _core_raw(x,allow_nan=False,epochs=False):
    if not isinstance(x,(mne.io.BaseRaw,mne.BaseEpochs) if epochs else mne.io.BaseRaw):raise TypeError('expected '+('Raw/Epochs' if epochs else 'Raw'))
    if isinstance(x,mne.BaseEpochs) and not x.preload:raise ValueError('Epochs must be preloaded')
    y=x.copy().load_data();a=y.get_data()
    if not a.size or np.iscomplexobj(a) or np.isinf(a).any() or (not allow_nan and np.isnan(a).any()):raise ValueError('empty, complex or unsupported nonfinite signal')
    return y

def _core_names(y,names,allow_empty=False):
    if not isinstance(names,(list,tuple)) or (not names and not allow_empty) or any(not isinstance(n,str) for n in names) or len(set(names))!=len(names):raise ValueError('channel names must be unique')
    good={n for n,t in zip(y.ch_names,y.get_channel_types()) if t=='eeg'}
    if not set(names)<=good:raise ValueError('existing EEG names required')
    return [y.ch_names.index(n) for n in names]

def _core_array_hash(a):
    a=np.ascontiguousarray(a)
    return _core_hashlib.sha256(str((a.dtype.str,a.shape)).encode()+a.tobytes()).hexdigest()

def _core_frame(y):
    return {'sfreq':float(y.info['sfreq']),'n_times':len(y.times),
            'first_samp':int(y.first_samp) if isinstance(y,mne.io.BaseRaw) else None,
            'epoch_selection':None if isinstance(y,mne.io.BaseRaw) else y.selection.tolist(),
            'epoch_events':None if isinstance(y,mne.io.BaseRaw) else y.events.tolist(),
            'tmin':float(y.times[0]),'meas_date':str(y.info.get('meas_date'))}

def _core_raw_hash(y):
    return _core_value_hash({'frame':_core_frame(y),'names':y.ch_names,'types':y.get_channel_types(),
        'bads':y.info['bads'],'data':y.get_data(),'locs':[c['loc'] for c in y.info['chs']],
        'dig':y.info['dig'],'projs':[dict(v) for v in y.info['projs']],
        'custom_ref_applied':int(y.info['custom_ref_applied']),
        'highpass':y.info['highpass'],'lowpass':y.info['lowpass'],
        'annotations':None if y.annotations is None else {'onset':y.annotations.onset,'duration':y.annotations.duration,
            'description':y.annotations.description,'ch_names':y.annotations.ch_names,
            'orig_time':str(y.annotations.orig_time)}})

def _core_value_hash(v):
    def plain(a):
        if isinstance(a,np.ndarray):
            if a.dtype.kind=='O':return {'shape':list(a.shape),'values':plain(a.tolist())}
            return {'dtype':a.dtype.str,'shape':list(a.shape),'hash':_core_array_hash(a)}
        if isinstance(a,np.generic):return plain(a.item())
        if isinstance(a,dict):return {str(k):plain(v) for k,v in a.items()}
        if isinstance(a,(list,tuple)):return [plain(v) for v in a]
        if isinstance(a,(str,int,float,bool)) or a is None:return a
        raise TypeError('unsupported state value: '+str(type(a)))
    return _core_hashlib.sha256(_core_json.dumps(plain(v),sort_keys=True,separators=(',',':'),allow_nan=True).encode()).hexdigest()

def _core_out(data,model=None,**artifacts):
    return {'data':data,'model':model,'artifacts':artifacts}

def _core_rng_dump(rng):
    name,keys,pos,has,cached=rng.get_state()
    return {'bit_generator':name,'keys':keys.copy(),'pos':int(pos),'has_gauss':int(has),'cached_gaussian':float(cached)}

def _core_rng(value):
    if value is None:
        rng=np.random.RandomState();rng.set_state(np.random.get_state());return rng
    if isinstance(value,(int,np.integer)) and not isinstance(value,(bool,np.bool_)):
        return np.random.RandomState(_core_int(value,'random_state',0,2**32-1))
    if not isinstance(value,dict) or set(value)!={'bit_generator','keys','pos','has_gauss','cached_gaussian'} or value['bit_generator']!='MT19937':raise ValueError('random_state must be None, uint32 seed, or MT19937 state')
    keys=np.asarray(value['keys'])
    if keys.shape!=(624,) or keys.dtype.kind not in 'iu' or np.any(keys<0) or np.any(keys>2**32-1):raise ValueError('invalid MT19937 keys')
    pos=_core_int(value['pos'],'pos',0,624);has=_core_int(value['has_gauss'],'has_gauss',0,1);cached=_core_real(value['cached_gaussian'],'cached_gaussian')
    rng=np.random.RandomState();rng.set_state(('MT19937',keys.astype(np.uint32),pos,has,cached));return rng

def _core_versions():
    if _core_metadata.version('pyprep')!='0.7.1' or mne.__version__!='1.10.2':raise RuntimeError('profile requires PyPREP 0.7.1 and MNE 1.10.2')

def _core_nonfinite_policy(value):
    if value not in ('reject','propagate'):raise ValueError('nonfinite must be reject or propagate')
    return value=='propagate'

_core_previous_reference=eeg_rereference

def eeg_rereference(op,x,model=None,**p):
    if op not in ('reference_estimate','reference_apply'):return _core_previous_reference(op,x,model=model,**p)
    if op=='reference_estimate':
        if model is not None:raise ValueError('estimate does not accept model')
        p=_core_kwargs(p,{'donors':None,'estimator':'nanmean','reference_id':None,'nonfinite':'reject'},('donors','reference_id'))
        if p['estimator'] not in ('nanmean','nanmedian'):raise ValueError('estimator must be nanmean or nanmedian')
        if not isinstance(p['reference_id'],str) or not p['reference_id'].strip():raise ValueError('reference_id is required')
        y=_core_raw(x,allow_nan=_core_nonfinite_policy(p['nonfinite']),epochs=True);idx=_core_names(y,p['donors'])
        data=y.get_data();axis=0 if data.ndim==2 else 1;selected=np.take(data,idx,axis=axis)
        with _core_warnings.catch_warnings(record=True) as caught:
            _core_warnings.simplefilter('always');reference=getattr(np,p['estimator'])(selected,axis=axis)
        if not np.isfinite(reference).all():raise ValueError('reference undefined at samples with no finite donors')
        fitted={'kind':'eeg_reference_vector_v1','reference':reference.copy(),'frame':_core_frame(y),
            'donor_channels':list(p['donors']),'estimator':p['estimator'],'reference_id':p['reference_id'],
            'source_hash':_core_raw_hash(y)}
        return _core_out(y,fitted,reference_V=reference.copy(),warnings=[str(w.message) for w in caught])
    p=_core_kwargs(p,{'targets':None,'nonfinite':'reject'},('targets',))
    if not isinstance(model,dict) or model.get('kind')!='eeg_reference_vector_v1':raise ValueError('reference_estimate model required')
    y=_core_raw(x,allow_nan=_core_nonfinite_policy(p['nonfinite']),epochs=True);idx=_core_names(y,p['targets'])
    if _core_frame(y)!=model.get('frame'):raise ValueError('reference time/epoch frame mismatch')
    ref=np.asarray(model['reference']);expected=(y.n_times,) if isinstance(y,mne.io.BaseRaw) else (len(y),len(y.times))
    if ref.shape!=expected or not np.isfinite(ref).all():raise ValueError('invalid reference vector shape/value')
    if isinstance(y,mne.io.BaseRaw):y._data[idx]-=ref[None,:]
    else:y._data[:,idx,:]-=ref[:,None,:]
    with y.info._unlock():y.info['custom_ref_applied']=1
    return _core_out(y,_core_copylib.deepcopy(model),reference_V=ref.copy(),reference_id=model['reference_id'],targets=list(p['targets']))
