from app.preprocessing.native_process import run as native_run
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
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess,hashlib,json
from scipy.io import savemat,loadmat

# MATLAB classify's default: linear Gaussian discrimination, pooled unbiased
# within-class covariance and uniform priors. Only its 3-argument form is needed.
_CLASSIFY=r'''function [C,err,posterior] = classify(sample,training,group)
  global MARA_CLASSIFY_DIAGNOSTICS;MARA_CLASSIFY_DIAGNOSTICS=[];
  groups=unique(group(:));K=length(groups);[N,P]=size(training);
  if K~=2 || any(groups(:)'~=[0 1]),error('MARA classifier expects labels 0 and 1');end
  mu=zeros(K,P);centered=zeros(size(training));
  for k=1:K
    rows=find(group(:)==groups(k));mu(k,:)=mean(training(rows,:),1);
    centered(rows,:)=training(rows,:)-mu(k,:);
  end
  pooled=(centered'*centered)/(N-K);R=chol(pooled);
  score=zeros(size(sample,1),K);
  for k=1:K
    Z=(sample-mu(k,:))/R;score(:,k)=-.5*sum(Z.^2,2)-log(K);
  end
  score=score-max(score,[],2);posterior=exp(score);posterior=posterior./sum(posterior,2);
  [~,idx]=max(posterior,[],2);C=groups(idx);
  training_score=zeros(N,K);
  for k=1:K,Z=(training-mu(k,:))/R;training_score(:,k)=-.5*sum(Z.^2,2);end
  [~,pred]=max(training_score,[],2);err=0;
  for k=1:K,rows=find(group(:)==groups(k));err=err+mean(groups(pred(rows))~=groups(k))/K;end
  MARA_CLASSIFY_DIAGNOSTICS=struct('means',mu,'covariance',pooled,'sample',sample,'priors',ones(1,K)/K);
end
'''
_EEGLAB_ERROR="function eeglab_error(varargin)\n e=lasterror();error('MARA: %s',e.message);\nend\n"

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

def _legacy_id(ic):return _component_id(ic)

def _native_eeg(y,ic,scale=1000.):
    if ic.noise_cov is not None:raise ValueError('原生适配器要求 ICA noise_cov=None')
    picks=[y.ch_names.index(n) for n in ic.ch_names]
    if any(y.info['chs'][k]['coord_frame']!=mne.io.constants.FIFF.FIFFV_COORD_HEAD for k in picks):raise ValueError('坐标需要 MNE head 坐标系')
    xyz=np.array([y.info['chs'][k]['loc'][:3] for k in picks])
    if not np.isfinite(xyz).all() or np.any(np.linalg.norm(xyz,axis=1)==0):raise ValueError('需要全部 ICA 通道的头皮坐标')
    xyz=xyz[:,[1,0,2]]*np.array([1,-1,1])*scale # MNE RAS head -> EEGLAB nose-left-up.
    W=(ic.unmixing_matrix_@ic.pca_components_[:ic.n_components_])/ic.pre_whitener_.T/1e6
    A=np.linalg.pinv(W)
    values=y.get_data(picks=ic.ch_names)*1e6
    if isinstance(y,mne.BaseEpochs):values=values.transpose(1,2,0)
    trials=values.shape[2] if values.ndim==3 else 1;pnts=values.shape[1]
    activations=(W@values.reshape(len(picks),-1,order='F')).reshape(ic.n_components_,pnts,trials,order='F')
    locs=np.empty((1,len(picks)),dtype=[(n,'O') for n in ('labels','X','Y','Z','theta','radius','sph_theta','sph_phi','sph_radius','type','urchan')])
    for k,(name,pos) in enumerate(zip(ic.ch_names,xyz)):
        radius=np.linalg.norm(pos);theta=np.degrees(np.arctan2(pos[1],pos[0]));phi=np.degrees(np.arctan2(pos[2],np.linalg.norm(pos[:2])))
        vals=dict(labels=name,X=pos[0],Y=pos[1],Z=pos[2],theta=-theta,radius=.5-phi/180,sph_theta=theta,sph_phi=phi,sph_radius=radius,type='EEG',urchan=k+1)
        for key,value in vals.items():locs[key][0,k]=value
    return dict(data=values,srate=float(y.info['sfreq']),nbchan=len(picks),pnts=pnts,trials=trials,
        xmin=float(y.times[0]),xmax=float(y.times[-1]),times=np.asarray(y.times)*1000,
        chanlocs=locs,icaweights=W,icasphere=np.eye(len(picks)),icawinv=A,icaact=activations,
        icachansind=np.arange(1,len(picks)+1),ref='average',setname='native_ica_assess',filename=''),xyz

def _quote(path):return "'"+str(path).replace("'","''")+"'"

def _run_native(algorithm,eeg,root,octave,timeout,pins):
    root=Path(root).expanduser().resolve()
    if not root.is_dir():raise ValueError('source_root 目录不存在')
    for path,expected in pins.items():
        f=root/path
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest()!=expected:raise ValueError('作者版本或资产 hash 不匹配: '+path)
    with TemporaryDirectory(prefix='eeg-legacy-ica-') as tmp:
        tmp=Path(tmp);savemat(tmp/'input.mat',dict(payload=eeg),do_compression=True)
        common="pkg load signal;pkg load statistics;pkg load optim;"
        common+="if ~strcmp(OCTAVE_VERSION,'11.3.0'),error('Require Octave 11.3.0');end;pkginfo=pkg('list');expected={'signal','1.4.8';'statistics','1.7.7';'optim','1.6.3'};for q=1:rows(expected),ok=false;for z=1:numel(pkginfo),if strcmp(pkginfo{z}.name,expected{q,1}) && strcmp(pkginfo{z}.version,expected{q,2}),ok=true;end;end;if ~ok,error('Octave package version mismatch: %s',expected{q,1});end;end;"
        common+=f"addpath({_quote(root/'eeglab/functions/popfunc')});addpath({_quote(root/'eeglab/functions/sigprocfunc')});addpath({_quote(root/'eeglab/functions/adminfunc')});"
        common+=f"load({_quote(tmp/'input.mat')});EEG=eeg_emptyset();names=fieldnames(payload);for k=1:length(names),EEG.(names{{k}})=payload.(names{{k}});end;"
        if algorithm=='mara':
            (tmp/'classify.m').write_text(_CLASSIFY);(tmp/'eeglab_error.m').write_text(_EEGLAB_ERROR)
            common+=f"addpath({_quote(root/'MARA')});addpath({_quote(tmp)});pwelch('R12+');"
            command="[art,info]=MARA(EEG);if ~exist('info','var')||~isfield(info,'normfeats'),error('MARA did not return features');end;"
            command+="global MARA_CLASSIFY_DIAGNOSTICS;result=struct('indices',art,'posterior',info.posterior_artefactprob,'features',info.normfeats,'classifier',MARA_CLASSIFY_DIAGNOSTICS);"
        else:
            common+=f"addpath({_quote(root/'SASICA/private')});"
            outputs=['art','horiz','vert','blink','disc','soglia_DV','diff_var','soglia_K','med2_K','meanK','soglia_SED','med2_SED','SED','soglia_SAD','med2_SAD','SAD','soglia_GDSF','med2_GDSF','GDSF','soglia_V','med2_V','nuovaV','soglia_D','maxdin']
            command="if isfield(EEG,'dipfit') && isempty(EEG.dipfit),EEG=rmfield(EEG,'dipfit');end;"+'['+','.join(outputs)+']=ADJUST(EEG);result=struct();'
            command+=''.join(f'result.{name}={name};' for name in outputs)
        code="warning('off','Octave:shadowed-function');try;"+common+command+f"save('-mat7-binary',{_quote(tmp/'output.mat')},'result');catch err;fprintf(2,'%s\\n',err.message);for k=1:length(err.stack),fprintf(2,'%s:%d\\n',err.stack(k).file,err.stack(k).line);end;exit(1);end;"
        (tmp/'driver.m').write_text(code)
        # Isolate Octave startup and EEGLAB preferences from the caller's user
        # profile. Scientific options come from the pinned author bundle.
        import os
        env=os.environ.copy()
        if os.name=='nt':env['USERPROFILE']=str(tmp)
        run=native_run([octave,'--no-init-file','--no-gui','--quiet',str(tmp/'driver.m')],capture_output=True,text=True,timeout=timeout,env=env)
        if run.returncode or not (tmp/'output.mat').exists():raise RuntimeError(algorithm+' 原生执行失败: '+(run.stdout+run.stderr)[-6000:])
        result=loadmat(tmp/'output.mat',simplify_cells=True)['result']
    return result,dict(source_hashes=pins,source_root=str(root),runtime='Octave 11.3.0 / signal 1.4.8 / statistics 1.7.7 / optim 1.6.3',stdout=run.stdout[-4000:],stderr=run.stderr[-4000:])

_PINS={'eeglab/functions/popfunc/eeg_emptyset.m': '5359ea9eeb4dc8c85c3465cf6ef7ad8c769f839f027734b268e2b37018cb76be', 'eeglab/functions/popfunc/eeg_getica.m': '46ec2820d4841f2a4c3706bf0e1ba91aa1960a51f95800a24653dedee40b3776', 'eeglab/functions/adminfunc/eeg_checkset.m': 'fa6356b4a64ea6e16683acc4c65b257084dd1bfc995848de402244ccba00d6f0', 'eeglab/functions/sigprocfunc/kurt.m': '987072d6bdf64188c08ae3b85a2815fb357bd6bec034f7b044d33c4c8c169688', 'SASICA/private/ADJUST.m': '5cd93225976e0a64272b270660ccfa6c243cb1aae0c64e99e647d34d648e5fbf', 'SASICA/private/rep2struct.m': '4d2b2b8c11849d0dc26aa537a62b6c6cbeb271eda03e3aff2baf2c837333847e'}
def eeg_adjust(op,x,model=None,**p):
    if op!='adjust_assess':raise NotImplementedError(op)
    y=_epochs(x);p=_exact(p,'source_root reference_id',octave='octave',timeout=180.,xyz_scale=1000.)
    ic=_model(model,'ica',y)
    if p['reference_id']!=model['reference_id']:raise ValueError('参考配置不一致')
    _number(p['timeout'],'timeout',1,600);_number(p['xyz_scale'],'xyz_scale',0,strict_low=True)
    if len(ic.ch_names)<11:raise ValueError('ADJUST GDSF 每通道需要 10 个邻居，至少 11 通道')
    if len(y)<2 or ic.n_components_<4:raise ValueError('ADJUST 至少 2 个 Epoch、4 个 IC')
    eeg,xyz=_native_eeg(y,ic,p['xyz_scale'])
    theta=np.array([eeg['chanlocs']['theta'][0,k] for k in range(len(ic.ch_names))]);radius=np.array([eeg['chanlocs']['radius'][0,k] for k in range(len(ic.ch_names))])
    areas=dict(left_eye=(-61<theta)&(theta<-35)&(radius>.30),right_eye=(34<theta)&(theta<61)&(radius>.30),front=(abs(theta)<60)&(radius>.40),posterior=abs(theta)>110)
    if any(not a.any() for a in areas.values()):raise ValueError('ADJUST 需要左右眼区、额区及后区的有效电极覆盖')
    native,provenance=_run_native('adjust',eeg,p['source_root'],p['octave'],p['timeout'],_PINS)
    names=['diff_var','meanK','SED','SAD','GDSF','nuovaV'];features={k:np.asarray(native[k],float).reshape(-1) for k in names}
    thresholds={k:float(np.asarray(native[k]).item()) for k in ['soglia_K','soglia_SED','soglia_SAD','soglia_GDSF','soglia_V']}
    if any(v.shape!=(ic.n_components_,) or not np.isfinite(v).all() for v in features.values()) or not all(np.isfinite(v) for v in thresholds.values()):raise ValueError('ADJUST 特征或 EM 阈值退化')
    decisions={k:np.asarray(native[k],int).reshape(-1)-1 for k in ['art','horiz','vert','blink','disc']}
    if any(np.any((v<0)|(v>=ic.n_components_)) for v in decisions.values()):raise ValueError('ADJUST 候选索引越界')
    return _out(y,model,candidates=decisions['art'],decisions=decisions,features=features,thresholds=thresholds,
        component_id=_legacy_id(ic),provenance=provenance,coordinates=xyz,xyz_scale=p['xyz_scale'],ica_channels=list(ic.ch_names),input_channel_indices=[y.ch_names.index(n) for n in ic.ch_names],
        feature_thresholds=dict(diff_var=0.,meanK=thresholds['soglia_K'],SED=thresholds['soglia_SED'],SAD=thresholds['soglia_SAD'],GDSF=thresholds['soglia_GDSF'],nuovaV=thresholds['soglia_V']),scalp_areas={k:np.flatnonzero(v) for k,v in areas.items()},trial_selection=y.selection.copy())
