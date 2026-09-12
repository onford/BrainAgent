from app.preprocessing.native_process import run as native_run
import numpy as np
import mne
from pathlib import Path
import tempfile,subprocess,sys,shutil,hashlib,json,shlex
from scipy.io import savemat,loadmat
from numbers import Real,Integral

def _args(p,keys):
    if set(p)!=set(keys.split()): raise ValueError('参数缺失或包含未定义参数：'+str(set(p)^set(keys.split())))

def _number(v,name,lo,hi):
    if isinstance(v,(bool,np.bool_)) or not isinstance(v,Real) or not np.isfinite(v) or not lo<=v<=hi: raise ValueError(name+' 超出有限数值范围')
    return float(v)

def _integer(v,name,lo,hi):
    if isinstance(v,(bool,np.bool_)) or not isinstance(v,Integral) or not lo<=v<=hi: raise ValueError(name+' 超出整数范围')
    return int(v)

def _input(x,p):
    import scipy
    if mne.__version__!='1.10.2' or np.__version__!='1.26.4' or scipy.__version__!='1.15.3': raise RuntimeError('需要冻结的 MNE 1.10.2 / NumPy 1.26.4 / SciPy 1.15.3 profile')
    if not isinstance(x,mne.io.BaseRaw): raise TypeError('输入必须是连续 MNE Raw')
    if any('boundary' in d.lower() or d.lower().startswith(('bad_acq_skip','edge')) for d in x.annotations.description): raise ValueError('请按采集断点拆为连续段后执行')
    picks=p['picks']
    if not isinstance(picks,(list,tuple)) or not picks or len(set(picks))!=len(picks): raise ValueError('picks 需要唯一 EEG 通道名')
    types=dict(zip(x.ch_names,x.get_channel_types()))
    if any(c not in types or types[c]!='eeg' or c in x.info['bads'] for c in picks): raise ValueError('只能选择存在且未标坏的 EEG 通道')
    idx=[x.ch_names.index(c) for c in picks];data=np.asarray(x.get_data(picks=idx),dtype=np.float64)
    if not np.isfinite(data).all(): raise ValueError('输入包含 NaN/Inf')
    sfreq=float(x.info['sfreq']);timeout=_number(p['timeout_seconds'],'timeout_seconds',1,3600)
    runtime=Path(p['octave_path']).expanduser().resolve();source=Path(p['source_root']).expanduser().resolve()
    if not runtime.is_file(): raise FileNotFoundError('octave_path 不是可执行文件')
    for relative,digest in SOURCE_HASHES.items():
        path=source/relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest: raise ValueError('作者源码缺失/版本不符：'+relative)
    return data,idx,sfreq,timeout,runtime,source

def _quote(s): return "'"+str(s).replace("'","''")+"'"

def _replace_once(text,old,new,count=1):
    if count!=1 or text.count(old)!=1: raise RuntimeError('作者源码观察器定位不唯一')
    return text.replace(old,new,1)

def _run(data,fs,cfg,source,runtime,timeout,mode,order=4):
    from scipy.signal.windows import dpss
    with tempfile.TemporaryDirectory(prefix='eeg_line_') as temp:
        work=Path(temp);native=work/'native';compat=work/'compat';native.mkdir();compat.mkdir()
        for relative in SOURCE_HASHES:
            target=native/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/relative,target)
        traces=''
        if mode=='cleanline':
            # Observer only: record the author window loop and iterative stopping inputs.
            fp=native/'removeLinesMovingWindow.m';s=fp.read_text();s=_replace_once(s,'Fs = getStructureParameters',"global BA_TRACE BA_CALL; BA_CALL=BA_CALL+1;\nFs = getStructureParameters",1)
            s=_replace_once(s,'for iteration = 1:lineNoise.maximumIterations','for iteration = 1:lineNoise.maximumIterations\n    BA_TESTED_FREQS=f0; BA_LAST_REDUCTION=[];',1);s=_replace_once(s,'        dBReduction = initialSpectrum - cleanedSpectrum;','        dBReduction = initialSpectrum - cleanedSpectrum; BA_LAST_REDUCTION=dBReduction(fidx);',1)
            s=_replace_once(s,'    if isempty(f0)',"    BA_TRACE(end+1).call=BA_CALL; BA_TRACE(end).iteration=iteration; BA_TRACE(end).remaining_frequencies=f0; BA_TRACE(end).significant=f0Mask; BA_TRACE(end).tested_frequencies=BA_TESTED_FREQS; BA_TRACE(end).line_db_reduction=BA_LAST_REDUCTION;\n    if isempty(f0)",1);fp.write_text(s)
            nwin=int(round(fs*cfg['taperWindowSize']));nw=cfg['taperBandWidth']*cfg['taperWindowSize']/2;k=int(np.floor(2*nw-1));tapers,ratios=dpss(nwin,nw,k,sym=True,norm=2,return_ratios=True)
            savemat(work/'tapers.mat',dict(tapers=tapers.T,eigenvalues=ratios,N=nwin,NW=nw,K=k))
            (compat/'dpss.m').write_text("function [tapers,eigenvalues]=dpss(N,NW,K)\n d=load("+_quote(work/'tapers.mat')+"); if N~=d.N || NW~=d.NW || K~=d.K; error('DPSS profile mismatch'); end; tapers=d.tapers; eigenvalues=d.eigenvalues(:);\nend\n")
            invocation="signal=struct('data',data,'srate',srate); [signal,effective]=cleanLineNoise(signal,cfg); cleaned=signal.data; [F,A,f,sig]=testSignificantFrequencies(data(1,1:size(effective.tapers,1)),effective); analytics=struct('first_window_F',F,'first_window_amplitude',A,'frequencies',f,'F_threshold',sig);"
        else:
            fp=native/'clean_data_with_zapline_plus.m';s=fp.read_text();
            if s.count('addOptional(p,')!=29: raise RuntimeError('作者 name-value 参数声明数量不符')
            s=s.replace('addOptional(p,','addParameter(p,');s=_replace_once(s,'    nChunks = length(chunkIndices)-1;',"    global BA_TRACE; BA_TRACE(end+1).frequency=noisefreq; BA_TRACE(end).chunk_indices=chunkIndices;\n    nChunks = length(chunkIndices)-1;",1);fp.write_text(s)
            (compat/'round.m').write_text("function y=round(x,n)\n if nargin==1; y=builtin('round',x); else; factor=10.^n; y=builtin('round',x.*factor)./factor; end\nend\n");(compat/'pwelch.m').write_text(PWELCH_CODE);(work/'callback.py').write_text(CALLBACK_CODE)
            # Windows cmd.exe does not recognize POSIX single-quote escaping.
            # This changes only process argument quoting, not the DSP callback.
            argv=[sys.executable,str(work/'callback.py')]
            command=subprocess.list2cmdline(argv) if sys.platform=='win32' else shlex.join(argv)
            callback="request=[tempname() '.mat']; response=[tempname() '.mat']; save('-mat7-binary',request,VARS); [status,message]=system([PREFIX ' \"' request '\" \"' response '\"']); if status~=0; error(message); end; result=load(response); delete(request);delete(response);"
            findbody=callback.replace('VARS',"'data','minprominence','mindistance'").replace('PREFIX',_quote(command+' findpeaks'))
            (compat/'findpeaks.m').write_text("function [pks,locs,widths,proms]=findpeaks(data,varargin)\n minprominence=-1;mindistance=0; for k=1:2:numel(varargin); if strcmp(varargin{k},'MinPeakProminence'); minprominence=varargin{k+1}; elseif strcmp(varargin{k},'MinPeakDistance'); mindistance=varargin{k+1}; else; error('Unsupported peak option'); end; end\n"+findbody+"\npks=result.pks;locs=result.locs;widths=result.widths;proms=result.proms;\nend\n")
            filterbody=callback.replace('VARS',"'data','frequency','srate','prototype_order'").replace('PREFIX',_quote(command+' bandpass'))
            (compat/'bandpass.m').write_text("function filtered=bandpass(data,frequency,srate)\nprototype_order="+str(order)+";\n"+filterbody+"\nfiltered=result.filtered;\nend\n")
            invocation="[cleaned,effective,analytics]=clean_data_with_zapline_plus(data,srate,cfg);"
        matcfg={key:(np.asarray(value,dtype=float) if isinstance(value,(int,float,bool,np.number,np.ndarray,list,tuple)) else value) for key,value in cfg.items()}
        savemat(work/'input.mat',dict(data=data,srate=float(fs),cfg=matcfg))
        script="warning('off','Octave:shadowed-function'); pkg load signal; pkg load statistics; if ~strncmp(version,'11.3.',5);error('Octave 11.3.x required');end; if ~strcmp(ver('signal').Version,'1.4.8') || ~strcmp(ver('statistics').Version,'1.7.7');error('Package version mismatch');end; addpath(genpath("+_quote(native)+"));addpath("+_quote(compat)+",'-begin'); load("+_quote(work/'input.mat')+"); global BA_TRACE BA_CALL; BA_TRACE=struct([]);BA_CALL=0; "+invocation+" trace=BA_TRACE; save('-mat7-binary',"+_quote(work/'output.mat')+",'cleaned','effective','analytics','trace');"
        (work/'run.m').write_text(script)
        result=native_run([str(runtime),'--quiet','--no-gui',str(work/'run.m')],capture_output=True,text=True,timeout=timeout)
        if result.returncode!=0 or not (work/'output.mat').exists(): raise RuntimeError('Octave 作者算法执行失败：'+(result.stdout+result.stderr)[-6000:])
        out=loadmat(work/'output.mat',simplify_cells=True)
        value=np.asarray(out['cleaned'])
        if np.iscomplexobj(value) and np.max(np.abs(value.imag))>1e-12*max(1.,np.max(np.abs(value.real))): raise RuntimeError('作者输出含复信号')
        if value.size!=data.size: raise RuntimeError('作者输出样点数量错误')
        cleaned=np.asarray(value.real,dtype=float).reshape(data.shape)
        if cleaned.shape!=data.shape or not np.isfinite(cleaned).all(): raise RuntimeError('作者算法输出形状/有限性错误')
        return cleaned,dict(effective_parameters=out['effective'],analytics=out['analytics'],trace=out['trace'],runtime_log=result.stdout+result.stderr,source_commit=SOURCE_COMMIT,source_sha256=SOURCE_HASHES,profile=mode+'-octave-11.3-scipy-1.15.3',compatibility_patches=(['DPSS from scipy.signal.windows.dpss norm=2 sym=True','numeric config encoded as MATLAB double','iteration observer'] if mode=='cleanline' else ['inputParser addOptional converted to addParameter for name-value parsing','numeric config encoded as MATLAB double','explicit real-matrix Welch profile','SciPy find_peaks prominence profile','explicit Butterworth chunk bandpass','decimal round compatibility','chunk observer']))

SOURCE_COMMIT='f4628a32f4ec53cebfb07b1f6a8f465f44f1377a'
SOURCE_HASHES={'nt_regcov.m': '659d41fdab77d9934f2989aab416f6a82ecaa7cedf79d9477a015a1b9d196c19', 'nt_zapline_plus.m': '4f08ae167dac04ff2d1367e5ca211a553aec551130f392324db0470b43f2de14', 'clean_data_with_zapline_plus_eeglab_wrapper.m': 'd1b7aad1ab14a57f9dc6d49a69becc79de7958be4e9116417262b645b97e805b', 'nt_demean.m': '2863cf477a70264d76e5e44d13796a22378db4b4b74225a9fb0681c0a7b24b70', 'nt_dss0.m': '6c8c3bf741768cd0d781986f86d768a97880626a35cb280f3dadfc5091656736', 'nt_normcol.m': '2bf6cf8b8ecb72b78dc4840f8f3be52fe3c7fcd3a30f146c5ca7b5d4ed4af1b8', 'clean_data_with_zapline_plus.m': '27e292b7e04c98b8c79ac0bd900971856a94b3cd4fc80a14524bf33ecf614a8b', 'nt_bias_fft.m': 'ba01b651569b6107fccd75c244e6ddfa3416574d982711e82b5226d42f79d195', 'nt_unfold.m': '716da208df6812ec889ba1e7f43322b7d38a4a147ab90ca401369d762144c633', 'nt_smooth.m': '8a7038e96d8c2302580ee4f4b609b22acae1f5c988b92a08ec96f363dec2972d', 'find_next_noisefreq.m': '682aab66c3576889274dfcc7419f7d38ebdb00d37db22e0771bfc53f4e19ba04', 'nt_version.m': '2599ff3c189e8a492147cbf58d96aeed9de677da31055188427251710ba62396', 'iterative_outlier_removal.m': '9e922b54b3a79f666429e17e30890e61e9bc89719be5f63979216f700d16954f', 'nt_mmat.m': 'fc016e715580250d3a253db5b85fed5dd3090af58398a5a0c6a7ee502ef8b9c8', 'nt_pca.m': 'f90e20267e7ed1b917114492765c105ef7a15d6fca780d29c656b334a5776667', 'eegplugin_zapline_plus.m': '0a08f2bfdaebbcbb274bd3aebe7cf08ba8d8fa26c17bfb8073a7189e4255f58a', 'nt_xcov.m': '102734f915e6ac7a17065262b808ec12efbd592428d9b5510cff687e2c83548f', 'nt_vecmult.m': 'ad19b85d4b1e66bdb9b6f464a303be8ab365b8f1655de206f44e9826714953bc', 'nt_vecadd.m': 'fa4604fda3d4aa1e6c31c8033398db4022a34df90039b212acd52d41dd5358f8', 'nt_tsr.m': 'c8b05cf73a9da014ec780d115793616e43e19325c7acf734840c374b6f72f8ae', 'nt_cov.m': '90986240014616d507422fa39f0c89022aa35d9d0be5e8a8c1ece3d10a0651a4', 'nt_fold.m': 'ee6b6fef9c2bf86079ef4b78e981819ce6fc6269ab5619eaa8191585b18370df', 'pop_zapline_plus.m': '27804a0c25233d1ba0d08c05510bd238888b64cad731032185484f7b3e8deeb7', 'nt_pcarot.m': '78aed329cb254b4e5c43950e7db3799377fc398f57acbe191a3aa34f86949901', 'nt_multishift.m': '34d7cfa10131db01ebf91e6c9358243f0d8ce4239bdb0524fd3d697ca86a726c', 'nt_greetings.m': 'abc03a2a77cb6f8c9614a5e859553fba08e25e04366e5e3f49f8fe08f2b6e82b', 'LICENSE': '3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986'}
PWELCH_CODE="function [power, frequencies] = pwelch(data, window, overlap, nfft, srate)\n  if nargin ~= 5 || ~isreal(data) || isscalar(window)\n    error('Only the frozen real matrix / explicit window / Fs Welch profile is supported');\n  end\n  if isrow(data); data=data'; end\n  window=window(:); L=length(window);\n  if isempty(overlap); overlap=floor(L/2); end\n  if isempty(nfft); nfft=max(256,2^nextpow2(L)); end\n  if L<2 || L>size(data,1) || overlap<0 || overlap>=L || nfft<L; error('Invalid Welch window'); end\n  starts=1:(L-overlap):(size(data,1)-L+1);\n  power=zeros(floor(nfft/2)+1,size(data,2));\n  for start=starts\n    spectrum=fft(bsxfun(@times,data(start:start+L-1,:),window),nfft,1);\n    power=power+abs(spectrum(1:floor(nfft/2)+1,:)).^2;\n  end\n  power=power/(numel(starts)*srate*sum(window.^2));\n  if mod(nfft,2)==0; power(2:end-1,:)=2*power(2:end-1,:); else; power(2:end,:)=2*power(2:end,:); end\n  frequencies=(0:floor(nfft/2))'*srate/nfft;\nend\n"
CALLBACK_CODE="import sys\nimport numpy as np\nfrom scipy.io import loadmat,savemat\nfrom scipy.signal import find_peaks,peak_prominences,peak_widths,butter,sosfiltfilt\noperation,inputfile,outputfile=sys.argv[1:]\nd=loadmat(inputfile,squeeze_me=True)\nif operation=='findpeaks':\n x=np.asarray(d['data']).ravel(); kwargs={}\n if float(d['minprominence'])>=0: kwargs['prominence']=float(d['minprominence'])\n if float(d['mindistance'])>0: kwargs['distance']=float(d['mindistance'])\n peaks,_=find_peaks(x,**kwargs); prominence=peak_prominences(x,peaks)[0] if len(peaks) else np.array([]); widths=peak_widths(x,peaks,rel_height=.5)[0] if len(peaks) else np.array([])\n savemat(outputfile,{'pks':x[peaks][:,None],'locs':(peaks+1)[:,None],'widths':widths[:,None],'proms':prominence[:,None]})\nelif operation=='bandpass':\n x=np.asarray(d['data']); fs=float(d['srate']); order=int(d['prototype_order']); bands=np.asarray(d['frequency']).ravel(); sos=butter(order,bands,btype='bandpass',fs=fs,output='sos')\n savemat(outputfile,{'filtered':sosfiltfilt(sos,x,axis=0),'sos':sos})\nelse: raise ValueError(operation)\n"
def eeg_zapline(op,x,model=None,**p):
    if op!='zapline_plus': raise NotImplementedError(op)
    _args(p,'source_root octave_path picks noise_frequencies chunk_seconds min_chunk_seconds prominence_quantile chunk_filter_order adaptive_sigma fixed_remove sigma min_sigma max_sigma detection_width spectrum_window_seconds timeout_seconds')
    if model is not None: raise ValueError('Zapline-plus 不接受模型')
    data,idx,fs,timeout,runtime,source=_input(x,p)
    if fs!=round(fs) or fs<=120 or len(idx)<5 or data.shape[1]/fs<16: raise ValueError('此 profile 需要整数 sfreq>120、≥5 EEG 通道、≥16秒连续数据')
    freqs=p['noise_frequencies']
    if isinstance(freqs,str):
        if freqs!='line': raise ValueError('频率字符串只能是 line')
    else:
        freqs=np.asarray(freqs)
        if freqs.dtype.kind not in 'fiu' or freqs.ndim!=1 or not np.isfinite(freqs).all() or len(np.unique(freqs))!=len(freqs) or np.any(freqs<=3) or np.any(freqs>=fs/2-3): raise ValueError('频率必须唯一且扫描窗口位于 (0,Nyquist)；空列表自动检测')
    duration=data.shape[1]/fs;chunk=_integer(p['chunk_seconds'],'chunk_seconds',0,int(duration));minimum=_integer(p['min_chunk_seconds'],'min_chunk_seconds',2,int(duration/2));quant=_number(p['prominence_quantile'],'prominence_quantile',0,1)
    order=_integer(p['chunk_filter_order'],'chunk_filter_order',1,12);fixed=_integer(p['fixed_remove'],'fixed_remove',0,max(1,len(idx)//5));sigma=_number(p['sigma'],'sigma',.1,20);minsig=_number(p['min_sigma'],'min_sigma',.1,sigma);maxsig=_number(p['max_sigma'],'max_sigma',sigma,20)
    if type(p['adaptive_sigma']) is not bool: raise ValueError('adaptive_sigma 需要布尔值')
    width=_number(p['detection_width'],'detection_width',1,min(20,fs/4));window=_integer(p['spectrum_window_seconds'],'spectrum_window_seconds',1,int(duration/8))
    if isinstance(freqs,str) and 60+width/2>=fs/2: raise ValueError('line 模式需让 50/60 Hz 两个检测窗口都低于 Nyquist')
    if not isinstance(freqs,str) and len(freqs) and (np.any(freqs-width/2<=0) or np.any(freqs+width/2>=fs/2)): raise ValueError('检测频带越界')
    if chunk and chunk<minimum: raise ValueError('固定块长须不小于最短块长')
    if not np.any(np.std(data,axis=1)>0): raise ValueError('所有通道均为常量')
    global_nfft=max(256,2**int(np.ceil(np.log2(window*fs))))
    block_nfft=max(256,2**int(np.ceil(np.log2((chunk or minimum)*fs))))
    if not isinstance(freqs,str) and len(freqs):
        nearest_block=np.round(freqs*block_nfft/fs)*fs/block_nfft
        if np.any(np.abs(nearest_block-freqs)>=.05): raise ValueError('最短块 FFT 网格未覆盖线频 ±0.05 Hz；增加块长')
        nearest_global=np.round(freqs*global_nfft/fs)*fs/global_nfft
        if p['adaptive_sigma'] and np.any(np.abs(nearest_global-freqs)>=.05): raise ValueError('完整谱 FFT 网格未覆盖线频 ±0.05 Hz；增加 spectrum_window_seconds')
    elif block_nfft<global_nfft and fs/block_nfft>=.1:
        raise ValueError('自动检测频率的全谱/最短块 FFT 网格不兼容；增加块长')
    cfg=dict(noisefreqs=freqs,adaptiveNremove=1,adaptiveSigma=int(p['adaptive_sigma']),fixedNremove=fixed,noiseCompDetectSigma=sigma,minsigma=minsig,maxsigma=maxsig,chunkLength=chunk,segmentLength=1,minChunkLength=minimum,prominenceQuantile=quant,nkeep=len(idx),plotResults=0,overwritePlot=1,saveSpectra=1,winSizeCompleteSpectrum=window,detectionWinsize=width,minfreq=17,maxfreq=min(99,fs/2-width/2-1),searchIndividualNoise=1)
    cleaned,artifacts=_run(data*1e6,fs,cfg,source,runtime,timeout,'zapline_plus',order=order);cleaned=cleaned*1e-6;out=x.copy().load_data();out._data[idx]=cleaned
    trace=artifacts['trace']; traces=[trace] if isinstance(trace,dict) else list(trace)
    artifacts['chunk_boundaries']=[dict(frequency=float(item['frequency']),samples=(np.asarray(item['chunk_indices']).ravel().astype(int)-1).tolist()) for item in traces]
    for item in artifacts['chunk_boundaries']:
        bounds=item['samples']
        if bounds[0]!=0 or bounds[-1]!=data.shape[1] or any(b-a<minimum*fs for a,b in zip(bounds[:-1],bounds[1:])): raise RuntimeError('作者分块边界未覆盖数据')
    artifacts.update(native_unit='uV',output_unit='V',picks=list(p['picks']),removed=data-cleaned,chunk_filter=dict(design='Butterworth',prototype_order=order,phase='zero',padding='scipy.sosfiltfilt odd/default',band='line frequency +/- detection_width/2'),peak_detector='scipy.signal.find_peaks 1.15.3; half-prominence width',segment_seconds=1)
    return {'data':out,'model':None,'artifacts':artifacts}
