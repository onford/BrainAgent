# Python 3.12; NumPy 1.26.4; SciPy 1.15.3
import numpy as np
from numbers import Real, Integral

def _args(p, names):
    required=set(names.split())
    if set(p)!=required:
        raise ValueError(f'参数缺失={required-set(p)}; 未定义={set(p)-required}')

def _arr(x, ndim):
    a=np.asarray(x)
    if a.dtype.kind not in 'fiu' or a.ndim!=ndim or not a.size or not np.isfinite(a).all():
        raise ValueError(f'需要非空有限实数 {ndim} 维数组')
    return a.astype(float,copy=True)

def _ids(v,n=None):
    if not isinstance(v,(list,tuple)) or not v or any(not isinstance(s,str) or not s.strip() for s in v) or len(set(v))!=len(v) or (n is not None and len(v)!=n):
        raise ValueError('ID/列名需要唯一非空字符串，数量与轴一致')
    return tuple(v)

def _scope(v,n,roles=('train',)):
    if not isinstance(v,dict) or set(v)!={'role','ids'} or v['role'] not in roles:
        raise ValueError('scope={role,ids}，role 必须在允许的训练/校准范围')
    return {'role':v['role'],'ids':list(_ids(v['ids'],n))}

def _num(v,name,lo=None,hi=None):
    if isinstance(v,(bool,np.bool_)) or not isinstance(v,Real) or not np.isfinite(v) or (lo is not None and v<lo) or (hi is not None and v>hi):
        raise ValueError(f'{name} 需要范围 [{lo},{hi}] 内有限实数')
    return float(v)

def _int(v,name,lo=0,hi=None):
    if isinstance(v,(bool,np.bool_)) or not isinstance(v,Integral) or v<lo or (hi is not None and v>hi):
        raise ValueError(f'{name} 需要范围 [{lo},{hi}] 内整数')
    return int(v)

def _labels(y,n):
    a=np.asarray(y)
    if a.ndim!=1 or len(a)!=n or a.dtype.kind not in 'iuUS' or any(not str(v).strip() for v in a):
        raise ValueError('标签需要一维整数或非空字符串；数量与 Trial 一致')
    return a.copy()

def _out(data=None,model=None,**artifacts):
    if data is not None and (not np.asarray(data).size or not np.isfinite(data).all()):
        raise ValueError('结果为空或含非有限数值')
    return {'data':data,'model':model,'artifacts':artifacts}

def _model(model,kind,axes):
    if not isinstance(model,dict) or model.get('kind')!=kind or tuple(axes)!=model.get('axes'):
        raise ValueError('配套模型种类或通道轴不匹配')
    return model

def _aug(a,p):
    scope=_scope(p['scope'],len(a))
    parents=_ids(p['parent_ids'],len(a))
    if parents!=tuple(scope['ids']): raise ValueError('parent_ids 顺序必须等于训练 scope.ids')
    axes=_ids(p['axes'],a.shape[1])
    if p['label_invariant'] is not True: raise ValueError('此变体要求任务标签对所选变换保持有效')
    y=_labels(p['y'],len(a)); seed=_int(p['seed'],'seed'); prob=_num(p['probability'],'probability',0,1)
    rng=np.random.default_rng(seed)
    selected=rng.random(len(a))<prob
    return rng,selected,y,parents,axes

def eeg_regression_baseline(op,x,model=None,**p):
    if op in ('regression_baseline_epochs_fit','regression_baseline_epochs_apply'): return _epochs_baseline(op,x,model,p)
    a=_arr(x,3)
    if op=='regression_baseline_fit':
        _args(p,'scope axes times baseline factors factor_names')
        if model is not None: raise ValueError('fit 不接受已有模型')
        axes=_ids(p['axes'],a.shape[1]); scope=_scope(p['scope'],len(a),('train','calibration'))
        times=_arr(p['times'],1)
        if len(times)!=a.shape[-1] or np.any(np.diff(times)<=0): raise ValueError('times 必须严格递增并匹配样点')
        bounds=_arr(p['baseline'],1)
        if len(bounds)!=2 or not times[0]<=bounds[0]<=bounds[1]<=times[-1]: raise ValueError('baseline 必须落在时间轴内')
        lo,hi=[int(np.argmin(np.abs(times-b))) for b in bounds]
        f=np.asarray(p['factors'])
        if f.ndim!=2 or f.shape[0]!=len(a) or f.shape[1] not in (0,1,2) or f.dtype.kind not in 'fiu' or not np.isfinite(f).all() or (f.size and not np.isin(f,[-1,1]).all()):
            raise ValueError('factors 为 N×0/1/2；每列采用 -1/+1 编码')
        names=tuple(p['factor_names'])
        if f.shape[1]: _ids(names,f.shape[1])
        elif names: raise ValueError('无因素时 factor_names=[]')
        baseline=a[:,:,lo:hi+1].mean(axis=-1); beta=[]; conditions=[]
        for c in range(a.shape[1]):
            d=np.column_stack([baseline[:,c],f,np.ones(len(a))])
            if len(a)<=d.shape[1] or np.linalg.matrix_rank(d)!=d.shape[1]: raise ValueError('Trial 不足或基线/因素/截距共线')
            beta.append(np.linalg.lstsq(d,a[:,c,:],rcond=None)[0]); conditions.append(float(np.linalg.cond(d)))
        beta=np.stack(beta); m=dict(kind='regression_baseline',axes=axes,times=times,baseline_indices=(lo,hi),beta_baseline=beta[:,0,:].copy(),beta=beta,factor_names=names,scope=scope)
        return _out(a-baseline[:,:,None]*m['beta_baseline'][None,:,:],m,baseline_indices=(lo,hi),condition_numbers=conditions,trial_ids=scope['ids'])
    if op!='regression_baseline_apply': raise NotImplementedError(op)
    _args(p,'axes times trial_ids')
    m=_model(model,'regression_baseline',_ids(p['axes'],a.shape[1]))
    if not np.array_equal(_arr(p['times'],1),m['times']) or a.shape[-1]!=len(m['times']): raise ValueError('时间轴不匹配')
    ids=_ids(p['trial_ids'],len(a))
    limits=m['baseline_indices']
    if not isinstance(limits,(list,tuple)) or len(limits)!=2: raise ValueError('模型基线索引无效')
    lo=_int(limits[0],'模型基线起点',0,a.shape[-1]-1); hi=_int(limits[1],'模型基线终点',lo,a.shape[-1]-1)
    coefficients=_arr(m['beta_baseline'],2)
    if coefficients.shape!=a.shape[1:]: raise ValueError('模型基线系数轴无效')
    base=a[:,:,lo:hi+1].mean(axis=-1)
    return _out(a-base[:,:,None]*m['beta_baseline'][None,:,:],m,trial_ids=ids,baseline_indices=(lo,hi))

def _epochs_baseline(op,x,model,p):
    import mne,hashlib
    if not isinstance(x,mne.BaseEpochs): raise TypeError('此入口需要 MNE Epochs')
    fit=op=='regression_baseline_epochs_fit'
    _args(p,'scope picks baseline factors factor_names' if fit else 'picks trial_ids')
    picks=_ids(p['picks']);types=dict(zip(x.ch_names,x.get_channel_types()))
    if any(c not in types or types[c]!='eeg' or c in x.info['bads'] for c in picks): raise ValueError('picks 只能选择存在且未标坏的 EEG 通道')
    idx=[x.ch_names.index(c) for c in picks];out=x.copy().load_data();data=out.get_data(picks=idx)
    projection=tuple((v['desc'],int(v['kind']),bool(v['active']),tuple(v['data']['col_names']),hashlib.sha256(np.asarray(v['data']['data']).tobytes()).hexdigest()) for v in x.info['projs'])
    signature=(tuple(x.ch_names),tuple(x.get_channel_types()),tuple(x.info['bads']),int(x.info['custom_ref_applied']),projection)
    if fit:
        result=eeg_regression_baseline('regression_baseline_fit',data,model=model,scope=p['scope'],axes=list(picks),times=x.times,baseline=p['baseline'],factors=p['factors'],factor_names=p['factor_names'])
        result['model']['epochs_signature']=signature
    else:
        if not isinstance(model,dict) or model.get('epochs_signature')!=signature: raise ValueError('Epochs 通道/类型/坏道/参考/投影状态与拟合时不匹配')
        result=eeg_regression_baseline('regression_baseline_apply',data,model=model,axes=list(picks),times=x.times,trial_ids=p['trial_ids'])
    out._data[:,idx,:]=result['data']
    result['data']=out;result['artifacts']['picks']=list(picks);result['artifacts']['selection']=out.selection.copy();result['artifacts']['events']=out.events.copy()
    return result
