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


def _eeg_ica_ica_fit(op, x, model=None, **p):
    y = _copy(x)
    p=_exact(p, 'method n_components seed max_iter scope reference_id',
             tol=None,
             ortho=None, extended=None, reject=None, flat=None, tstep=2.)
    if p['tol'] is None:
        p['tol']={'picard':1e-6,'infomax':1e-12}.get(p['method'],1e-4)
    _scope(p['scope'], ('train', 'calibration'))
    _integer(p['seed'], 'seed')
    if not isinstance(p['reference_id'], str) or not p['reference_id'].strip():
        raise ValueError('reference_id缺失')
    if p['method'] not in ('fastica','picard','infomax'):
        raise NotImplementedError(p['method'])
    if y.info['highpass'] < (0.5 if p['method']=='picard' else 1):
        raise ValueError('ICA 拟合高通下限：PICARD 0.5 Hz；FastICA/Infomax 1 Hz')
    if isinstance(y, mne.BaseEpochs) and y.baseline is not None:
        raise ValueError('ICA 前不做基线')
    if p['max_iter'] != 'auto' and (isinstance(p['max_iter'], (bool,np.bool_)) or not isinstance(p['max_iter'], Integral) or p['max_iter'] < 1):
        raise ValueError('max_iter 需要正整数或 auto')
    _number(p['tol'],'tol',0,strict_low=True)
    _number(p['tstep'],'tstep',0,strict_low=True)
    for key in ('ortho','extended'):
        if p[key] is not None and not isinstance(p[key],bool):
            raise ValueError(key+' 必须为 bool 或 None')
    if p['method']=='fastica' and (p['ortho'] is not None or p['extended'] is not None):
        raise ValueError('FastICA 不使用 ortho/extended')
    if p['method']=='infomax' and p['ortho'] is not None:
        raise ValueError('Infomax 不使用 ortho')
    for key in ('reject','flat'):
        if p[key] is not None:
            if not isinstance(p[key],dict) or set(p[key]) != {'eeg'}:
                raise ValueError(key+' 需 None 或 {eeg: 正数V}')
            _number(p[key]['eeg'],key,0,strict_low=True)
    if p['reject'] is not None and p['flat'] is not None and p['flat']['eeg'] >= p['reject']['eeg']:
        raise ValueError('flat 阈值必须低于 reject')
    if isinstance(y,mne.BaseEpochs) and (p['reject'] is not None or p['flat'] is not None or p['tstep'] != 2.):
        raise ValueError('Epochs 输入须在上游剔除 Trial；reject/flat/tstep 仅用于 Raw 拟合分段')
    if p['method']=='picard':
        fit_params=dict(ortho=True if p['ortho'] is None else p['ortho'],
                        extended=True if p['extended'] is None else p['extended'],tol=p['tol'])
    elif p['method']=='infomax':
        fit_params=dict(extended=True if p['extended'] is None else p['extended'],w_change=p['tol'])
    else:
        fit_params=dict(tol=p['tol'])
    ic = mne.preprocessing.ICA(method=p['method'], n_components=p['n_components'], random_state=p['seed'], max_iter=p['max_iter'], fit_params=fit_params)
    with warnings.catch_warnings(record=True) as notices:
        warnings.simplefilter('always')
        stop = None
        if p['method'] == 'infomax':
            stop = _private_infomax_stop(ic, y, picks='eeg', reject_by_annotation=True,
                                        reject=p['reject'], flat=p['flat'], tstep=p['tstep'])
        else:
            ic.fit(y, picks='eeg', reject_by_annotation=True,
                   reject=p['reject'],flat=p['flat'],tstep=p['tstep'])
    for notice in notices:
        if issubclass(notice.category, ConvergenceWarning) or 'did not converge' in str(notice.message).lower():
            raise RuntimeError(f'ICA 未收敛：迭代 {ic.n_iter_} 次，上限 {p["max_iter"]}；{notice.message}')
        warnings.warn_explicit(str(notice.message), notice.category, notice.filename, notice.lineno)
    if ((p['method'] == 'infomax' and stop['reason'] == 'budget_exhausted')
            or (p['method'] != 'infomax' and ic.n_iter_ >= ic.max_iter)):
        raise RuntimeError(f'ICA 迭代预算耗尽，尚未确认收敛：{ic.n_iter_}/{ic.max_iter}')
    return _out(y, dict(kind='ica', estimator=ic, signature=_signature(y), scope=p['scope'], reference_id=p['reference_id'], sfreq=float(y.info['sfreq'])), iterations=ic.n_iter_, method=p['method'], fit_params=fit_params, fit_channels=list(ic.ch_names), reject_by_annotation=True,
                max_iter_resolved=ic.max_iter,infomax_stop=stop,reject=p['reject'],flat=p['flat'],tstep=p['tstep'],fit_samples=int(ic.n_samples_))

def _eeg_ica_eog_assess(op, x, model=None, **p):
    y = _copy(x)
    p=_exact(p, 'ch_name threshold l_freq h_freq reference_id', reference_role=None, channel_decision_id=None)
    if p['threshold']!='auto': _number(p['threshold'], 'threshold', 0, strict_low=True)
    _number(p['l_freq'], 'l_freq', 0, strict_low=True)
    _number(p['h_freq'], 'h_freq', 0, strict_low=True)
    if not p['l_freq'] < p['h_freq'] < y.info['sfreq'] / 2:
        raise ValueError('检测带通频率需满足0<低<高<Nyquist')
    _assess_channel(y,p,'eog')
    ic = _model(model, 'ica', y).copy()
    if p['reference_id'] != model['reference_id']:
        raise ValueError('参考配置不一致')
    metadata={k:p[k] for k in ('ch_name','reference_role','channel_decision_id')}
    kwargs={k:p[k] for k in ('ch_name','threshold','l_freq','h_freq')}
    (idx, scores) = ic.find_bads_eog(y, **kwargs, reject_by_annotation=True)
    scores = np.asarray(scores)
    if scores.shape != (ic.n_components_,) or not np.isfinite(scores).all():
        raise ValueError('ICA EOG候选分数必须逐组件有限；检查EOG/成分退化')
    return _out(y, model, candidates=idx, scores=scores, channel_metadata=metadata, assessment_params=dict(p))

def _eeg_ica_ica_apply(op, x, model=None, **p):
    y = _copy(x)
    before = y.get_data().copy()
    if isinstance(y, mne.BaseEpochs) and y.baseline is not None:
        raise ValueError('先伪迹校正，后基线；不自动重做基线')
    _args(p, 'exclude reference_id')
    if not isinstance(p['exclude'], (list, tuple)):
        raise TypeError('exclude需要索引列表/元组')
    if len(set(p['exclude'])) != len(p['exclude']):
        raise ValueError('exclude不能含重复成分')
    ic = _model(model, 'ica', y).copy()
    if p['reference_id'] != model['reference_id']:
        raise ValueError('参考配置不一致')
    for i in p['exclude']:
        _integer(i, 'exclude IC')
    if any((i >= ic.n_components_ for i in p['exclude'])):
        raise ValueError('IC 索引越界')
    ic.exclude = list(p['exclude'])
    ic.apply(y, exclude=p['exclude'], n_pca_components=None)
    return _out(y, model, removed=before - y.get_data(), exclude=list(p['exclude']))


def _assess_channel(y,p,kind):
    name=p['ch_name']
    if p['channel_decision_id'] is not None and (not isinstance(p['channel_decision_id'],str) or not p['channel_decision_id'].strip()):raise ValueError('channel_decision_id 需非空字符串或 None')
    if not isinstance(name,str) or name not in y.ch_names:raise ValueError('参照通道必须存在')
    actual=y.get_channel_types()[y.ch_names.index(name)]
    if actual==kind:
        if p['reference_role'] not in (None,kind):raise ValueError('通道类型与声明的参照角色冲突')
    elif actual=='eeg':
        if p['reference_role']!=kind or not isinstance(p['channel_decision_id'],str) or not p['channel_decision_id'].strip():
            raise ValueError('EEG 类型参照需要明确 reference_role 与 channel_decision_id')
    else:raise ValueError('参照通道需为对应生理类型，或经元数据指定的 EEG')

def _eeg_ica_ecg_assess(op,x,model=None,**p):
    y=_copy(x)
    if p.get('method')=='ctps' and 'measure' in p:raise ValueError('CTPS 不使用相关分数 measure')
    p=_exact(p,'ch_name method threshold reference_id',l_freq=8.,h_freq=16.,measure='zscore',reference_role=None,channel_decision_id=None)
    if p['method'] not in ('ctps','correlation'):raise ValueError('method=ctps|correlation')
    if p['method']=='ctps' and not isinstance(y,mne.io.BaseRaw):raise ValueError('本 CTPS 操作从 Raw ECG 检出 R 峰并生成心搏 Epoch')
    if p['measure'] not in ('zscore','correlation'):raise ValueError('measure=zscore|correlation')
    if p['threshold']!='auto':
        _number(p['threshold'],'threshold',0,strict_low=True)
        if (p['method']=='ctps' or p['measure']=='correlation') and p['threshold']>1:raise ValueError('CTPS/相关阈值须≤1')
    _number(p['l_freq'],'l_freq',0,strict_low=True);_number(p['h_freq'],'h_freq',0,strict_low=True)
    if not p['l_freq']<p['h_freq']<y.info['sfreq']/2:raise ValueError('频带须满足0<低<高<Nyquist')
    _assess_channel(y,p,'ecg');ic=_model(model,'ica',y).copy()
    if p['reference_id']!=model['reference_id']:raise ValueError('参考配置不一致')
    kwargs={k:p[k] for k in ('ch_name','method','threshold','l_freq','h_freq','measure')}
    idx,scores=ic.find_bads_ecg(y,**kwargs,reject_by_annotation=True)
    scores=np.asarray(scores)
    if scores.shape!=(ic.n_components_,) or not np.isfinite(scores).all():raise ValueError('ECG 成分评分退化')
    return _out(y,model,candidates=idx,scores=scores,method=p['method'],channel_metadata={k:p[k] for k in ('ch_name','reference_role','channel_decision_id')},assessment_params={k:v for k,v in p.items() if k!='measure' or p['method']=='correlation'})

def _eeg_ica_muscle_assess(op,x,model=None,**p):
    y=_copy(x);p=_exact(p,'mode reference_id',threshold=.5,l_freq=7.,h_freq=45.,sphere=None)
    if p['mode'] not in ('spatial','slope'):raise ValueError('mode=spatial|slope')
    _number(p['threshold'],'threshold',0,1,True);_number(p['l_freq'],'l_freq',0,strict_low=True);_number(p['h_freq'],'h_freq',0,strict_low=True)
    if not p['l_freq']<p['h_freq']<y.info['sfreq']/2:raise ValueError('频带须满足0<低<高<Nyquist')
    ic=_model(model,'ica',y).copy()
    if p['reference_id']!=model['reference_id']:raise ValueError('参考配置不一致')
    assess=y.copy()
    if p['mode']=='spatial':
        xyz=np.asarray([y.info['chs'][y.ch_names.index(n)]['loc'][:3] for n in ic.ch_names])
        if not np.isfinite(xyz).all() or np.any(np.linalg.norm(xyz,axis=1)==0):raise ValueError('spatial 模式需要全部 ICA 通道真实坐标')
        if p['sphere'] is not None:
            sphere=np.asarray(p['sphere'])
            if sphere.shape!=(4,) or sphere.dtype.kind not in 'fiu' or not np.isfinite(sphere).all() or sphere[3]<=0:raise ValueError('sphere 需米单位 (x,y,z,r>0) 或 None')
    else:
        if p['sphere'] is not None:raise ValueError('slope 模式不接受 sphere')
        assess.set_montage(None)
    idx,scores=ic.find_bads_muscle(assess,threshold=p['threshold'],l_freq=p['l_freq'],h_freq=p['h_freq'],sphere=p['sphere'])
    scores=np.asarray(scores)
    if scores.shape!=(ic.n_components_,) or not np.isfinite(scores).all():raise ValueError('肌电成分评分退化')
    return _out(y,model,candidates=idx,scores=scores,mode=p['mode'],criteria_count=3 if p['mode']=='spatial' else 1,assessment_params=dict(p))


def eeg_ica(op, x, model=None, **p):
    if op == 'ica_fit':
        if model is not None:
            raise ValueError('此操作不接受模型')
        return _eeg_ica_ica_fit(op, x, model=model, **p)
    if op == 'eog_assess':
        if model is None:
            raise ValueError('此操作需要已拟合模型')
        return _eeg_ica_eog_assess(op, x, model=model, **p)
    if op == 'ica_apply':
        if model is None:
            raise ValueError('此操作需要已拟合模型')
        return _eeg_ica_ica_apply(op, x, model=model, **p)
    if op in ('ecg_assess','muscle_assess'):
        if model is None:raise ValueError('评估需要已拟合 ICA model')
        return (_eeg_ica_ecg_assess if op=='ecg_assess' else _eeg_ica_muscle_assess)(op,x,model=model,**p)
    raise NotImplementedError(op)


"""Private MNE 1.10.2 stop receipt; native arithmetic and return values unchanged."""
import ast
import hashlib
import inspect
import textwrap
import types
import mne

_INFOMAX_SOURCE_SHA256='3721f9ce83ab4fee1384b9f323b7505e19bcfd0cf1074e4f20e9ee7e28bb0d2b'
_ICA_FIT_SOURCE_SHA256='252c0e6d5b07a824f08bab7ca12381dd1109c4029451bf465c262dd6572bd210'

def _private_infomax_stop(fitted_ica, data, **fit_kwargs):
    from mne.preprocessing import ICA, infomax
    native = inspect.unwrap(infomax)
    src = textwrap.dedent(inspect.getsource(native))
    fit_src = textwrap.dedent(inspect.getsource(ICA._fit))
    if (mne.__version__ != '1.10.2' or hashlib.sha256(src.encode()).hexdigest() != _INFOMAX_SOURCE_SHA256
            or hashlib.sha256(fit_src.encode()).hexdigest() != _ICA_FIT_SOURCE_SHA256):
        raise RuntimeError('Infomax stopping adapter requires verified MNE 1.10.2 sources')
    if fitted_ica.method != 'infomax' or '_fit' in fitted_ica.__dict__:
        raise ValueError('fresh native Infomax estimator required')
    stop = {}
    tree = ast.parse(src)
    counts = {'tolerance': 0, 'small_angle': 0, 'final': 0}
    class AddReceipt(ast.NodeTransformer):
        def visit_Assign(self, node):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Name):
                target, value = node.targets[0].id, node.value.id
                reason = 'tolerance' if (target, value) == ('step', 'max_iter') else 'small_angle' if (target, value) == ('max_iter', 'step') else None
                if reason:
                    counts[reason] += 1
                    extra = ast.parse("_eeg_stop.update(reason=%r, actual_iterations=int(step), original_budget=int(_eeg_budget), effective_budget=int(max_iter), change=float(change), tolerance=float(w_change), small_angle_count=int(count_small_angle), small_angle_limit=n_small_angle)" % reason).body[0]
                    return [ast.copy_location(extra, node), node]
            return node
        def visit_If(self, node):
            self.generic_visit(node)
            if isinstance(node.test, ast.Name) and node.test.id == 'return_n_iter':
                counts['final'] += 1
                extra = ast.parse("\nif not _eeg_stop:\n    _eeg_stop.update(reason='budget_exhausted', actual_iterations=int(step), original_budget=int(_eeg_budget), effective_budget=int(max_iter), change=float(change), tolerance=float(w_change), small_angle_count=int(count_small_angle), small_angle_limit=n_small_angle)\n_eeg_stop['native_reported_iterations'] = int(step)\n_eeg_stop['effective_budget'] = int(max_iter)\n").body
                return [*(ast.copy_location(n, node) for n in extra), node]
            return node
    tree = AddReceipt().visit(tree)
    if counts != {'tolerance':1,'small_angle':1,'final':1}:
        raise RuntimeError('Infomax source stop anchors changed')
    ast.fix_missing_locations(tree)
    private_globals = native.__globals__.copy()
    private_globals.update(_eeg_stop=stop, _eeg_budget=fitted_ica.max_iter)
    exec(compile(tree, '<mne-1.10.2-infomax-private-stop>', 'exec'), private_globals)
    native_fit = ICA._fit
    fit_globals = native_fit.__globals__.copy()
    fit_globals['infomax'] = private_globals['infomax']
    private_fit = types.FunctionType(native_fit.__code__, fit_globals, native_fit.__name__, native_fit.__defaults__, native_fit.__closure__)
    private_fit.__kwdefaults__ = native_fit.__kwdefaults__
    fitted_ica._fit = types.MethodType(private_fit, fitted_ica)
    try:
        fitted_ica.fit(data, **fit_kwargs)
    finally:
        del fitted_ica.__dict__['_fit']
    if not stop:
        raise RuntimeError('Infomax did not produce a stop receipt')
    return stop
