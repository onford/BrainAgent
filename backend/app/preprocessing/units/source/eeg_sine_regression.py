from app.preprocessing.native_process import run as native_run
# Python 3.12 | MNE 1.10.2 | NumPy 1.26.4 | SciPy 1.15.3
import numpy as np
import mne
from numbers import Integral, Real
import warnings as _core_warnings
from pathlib import Path
import tempfile, subprocess, shutil, hashlib
from scipy.io import savemat, loadmat
from numbers import Real, Integral
SOURCE_HASHES = {'cleanLineNoise.m': 'c7f94884ebc66f91c17bf32e871c8a9a7a9b2770423e0357a53c1e36e596442a', 'removeLinesMovingWindow.m': '34044dd4ef1a6a49be6bf876763c07039e54f7c432b5ec2ac811194a840b3596', 'getStructureParameters.m': '8d891a09018903db08765fa7b238d5f1a8535c612fb3ce765bbcaff4eee1a698', 'calculateSegmentSpectrum.m': 'd140806f99585771f5f1409d94ed5780d287d1915ff8ce5d727170f62d0fe9fc', 'testSignificantFrequencies.m': '9837be68fb892c80f631649ccfc387548828f9e4117939929a3561ddacae979b', 'fitSignificantFrequencies.m': '084271e64d98fd01ad91989301c7d988bb540f14ecf74d42d08ffa031c58effc', 'private/checkTapers.m': '6194476fd4102c923d2cc561f6e5e9e8ab460c35240acf9e6b15f055aec378e8', 'license.txt': '4acae006f7c8812165245451ab91ac370173b52fd610ecb0abcded304d25b429', 'external/chronux_2_modified/spectral_analysis/continuous/mtfftc.m': 'f9fcb6ca3d75d69736509ebeb00523c82807583c21b63edcc8cec4db9c44d43f', 'external/chronux_2_modified/spectral_analysis/continuous/createdatamatc.m': 'd77c9cf0e9be418a571c0effa32602cc9220412aac0cb1aba9804bd1d49996c9', 'external/chronux_2_modified/spectral_analysis/helper/change_row_to_column.m': 'd0cc8b13577bbbe92ae1ae6c68cb8a288415f7563aade31e95afc359c3263436', 'external/chronux_2_modified/spectral_analysis/helper/getfgrid.m': '666d2b9e48142747ca8aa35cac0a83d49a23fbf41f18ae89efb117a7560ba2c5'}
SOURCE_COMMIT = '117bffa6e1fbc6d042a7e75cec9e289e1aa5be72'

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

def _operation_spectrum_fit(op, x, model=None, **p):
    if model is not None:
        raise ValueError('spectrum_fit does not accept model')
    p = _core_kwargs(p, {'freqs': None, 'picks': None, 'mt_bandwidth': 2.0, 'p_value': 0.01, 'filter_length': '10s', 'annotation_policy': 'array', 'nonfinite': 'reject'}, ('freqs', 'picks'))
    if p['annotation_policy'] != 'array':
        raise ValueError('spectrum_fit profile uses explicit full-array policy')
    y = _core_raw(x, allow_nan=_core_nonfinite_policy(p['nonfinite']))
    idx = _core_names(y, p['picks'])
    freqs = np.asarray(p['freqs'])
    if freqs.ndim != 1 or not freqs.size or freqs.dtype.kind not in 'fiu' or any((isinstance(v, (bool, np.bool_)) for v in p['freqs'])) or (not np.isfinite(freqs).all()) or np.any(freqs <= 0) or np.any(freqs >= y.info['sfreq'] / 2) or (len(np.unique(freqs)) != len(freqs)):
        raise ValueError('freqs must be unique positive real sub-Nyquist frequencies')
    _core_real(p['mt_bandwidth'], 'mt_bandwidth', 0, strict=True)
    _core_real(p['p_value'], 'p_value', 0, 1, True)
    if p['p_value'] != 0.01:
        raise ValueError('specified-frequency spectrum_fit fixes p_value=0.01; it does not control frequency selection')
    if isinstance(p['filter_length'], (bool, np.bool_)):
        raise ValueError('invalid spectral-fit parameters')
    before = y.get_data().copy()
    with _core_warnings.catch_warnings(record=True) as caught:
        _core_warnings.simplefilter('always')
        y._data[idx] = mne.filter.notch_filter(before[idx], Fs=y.info['sfreq'], freqs=freqs, method='spectrum_fit', mt_bandwidth=p['mt_bandwidth'], p_value=p['p_value'], filter_length=p['filter_length'], copy=True)
    return _core_out(y, parameters=p, removed=before - y.get_data(), warnings=[str(w.message) for w in caught])

def _args(p, keys):
    if set(p) != set(keys.split()):
        raise ValueError('参数缺失或包含未定义参数：' + str(set(p) ^ set(keys.split())))

def _input(x, p):
    import scipy
    if mne.__version__ != '1.10.2' or np.__version__ != '1.26.4' or scipy.__version__ != '1.15.3':
        raise RuntimeError('需要冻结的 MNE 1.10.2 / NumPy 1.26.4 / SciPy 1.15.3 profile')
    if not isinstance(x, mne.io.BaseRaw):
        raise TypeError('输入必须是连续 MNE Raw')
    if any(('boundary' in d.lower() or d.lower().startswith(('bad_acq_skip', 'edge')) for d in x.annotations.description)):
        raise ValueError('请按采集断点拆为连续段后执行')
    picks = p['picks']
    if not isinstance(picks, (list, tuple)) or not picks or len(set(picks)) != len(picks):
        raise ValueError('picks 需要唯一 EEG 通道名')
    types = dict(zip(x.ch_names, x.get_channel_types()))
    if any((c not in types or types[c] != 'eeg' or c in x.info['bads'] for c in picks)):
        raise ValueError('只能选择存在且未标坏的 EEG 通道')
    idx = [x.ch_names.index(c) for c in picks]
    data = np.asarray(x.get_data(picks=idx), dtype=np.float64)
    if not np.isfinite(data).all():
        raise ValueError('输入包含 NaN/Inf')
    sfreq = float(x.info['sfreq'])
    timeout = _number(p['timeout_seconds'], 'timeout_seconds', 1, 3600)
    runtime = Path(p['octave_path']).expanduser().resolve()
    source = Path(p['source_root']).expanduser().resolve()
    if not runtime.is_file():
        raise FileNotFoundError('octave_path 不是可执行文件')
    for (relative, digest) in SOURCE_HASHES.items():
        path = source / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('作者源码缺失/版本不符：' + relative)
    return (data, idx, sfreq, timeout, runtime, source)

def _integer(v, name, lo, hi):
    if isinstance(v, (bool, np.bool_)) or not isinstance(v, Integral) or (not lo <= v <= hi):
        raise ValueError(name + ' 超出整数范围')
    return int(v)

def _number(v, name, lo, hi):
    if isinstance(v, (bool, np.bool_)) or not isinstance(v, Real) or (not np.isfinite(v)) or (not lo <= v <= hi):
        raise ValueError(name + ' 超出有限数值范围')
    return float(v)

def _quote(s):
    return "'" + str(s).replace("'", "''") + "'"

def _replace_once(text, old, new, count=1):
    if count != 1 or text.count(old) != 1:
        raise RuntimeError('作者源码观察器定位不唯一')
    return text.replace(old, new, 1)

def _run(data, fs, cfg, source, runtime, timeout, mode, order=4):
    from scipy.signal.windows import dpss
    with tempfile.TemporaryDirectory(prefix='eeg_line_') as temp:
        work = Path(temp)
        native = work / 'native'
        compat = work / 'compat'
        native.mkdir()
        compat.mkdir()
        for relative in SOURCE_HASHES:
            target = native / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, target)
        traces = ''
        fp = native / 'removeLinesMovingWindow.m'
        s = fp.read_text()
        s = _replace_once(s, 'Fs = getStructureParameters', 'global BA_TRACE BA_CALL; BA_CALL=BA_CALL+1;\nFs = getStructureParameters', 1)
        s = _replace_once(s, 'for iteration = 1:lineNoise.maximumIterations', 'for iteration = 1:lineNoise.maximumIterations\n    BA_TESTED_FREQS=f0; BA_LAST_REDUCTION=[];', 1)
        s = _replace_once(s, '        dBReduction = initialSpectrum - cleanedSpectrum;', '        dBReduction = initialSpectrum - cleanedSpectrum; BA_LAST_REDUCTION=dBReduction(fidx);', 1)
        s = _replace_once(s, '    if isempty(f0)', '    BA_TRACE(end+1).call=BA_CALL; BA_TRACE(end).iteration=iteration; BA_TRACE(end).remaining_frequencies=f0; BA_TRACE(end).significant=f0Mask; BA_TRACE(end).tested_frequencies=BA_TESTED_FREQS; BA_TRACE(end).line_db_reduction=BA_LAST_REDUCTION;\n    if isempty(f0)', 1)
        fp.write_text(s)
        nwin = int(round(fs * cfg['taperWindowSize']))
        nw = cfg['taperBandWidth'] * cfg['taperWindowSize'] / 2
        k = int(np.floor(2 * nw - 1))
        (tapers, ratios) = dpss(nwin, nw, k, sym=True, norm=2, return_ratios=True)
        savemat(work / 'tapers.mat', dict(tapers=tapers.T, eigenvalues=ratios, N=nwin, NW=nw, K=k))
        (compat / 'dpss.m').write_text('function [tapers,eigenvalues]=dpss(N,NW,K)\n d=load(' + _quote(work / 'tapers.mat') + "); if N~=d.N || NW~=d.NW || K~=d.K; error('DPSS profile mismatch'); end; tapers=d.tapers; eigenvalues=d.eigenvalues(:);\nend\n")
        invocation = "signal=struct('data',data,'srate',srate); [signal,effective]=cleanLineNoise(signal,cfg); cleaned=signal.data; [F,A,f,sig]=testSignificantFrequencies(data(1,1:size(effective.tapers,1)),effective); analytics=struct('first_window_F',F,'first_window_amplitude',A,'frequencies',f,'F_threshold',sig);"
        matcfg = {key: np.asarray(value, dtype=float) if isinstance(value, (int, float, bool, np.number, np.ndarray, list, tuple)) else value for (key, value) in cfg.items()}
        savemat(work / 'input.mat', dict(data=data, srate=float(fs), cfg=matcfg))
        script = "warning('off','Octave:shadowed-function'); pkg load signal; pkg load statistics; if ~strncmp(version,'11.3.',5);error('Octave 11.3.x required');end; if ~strcmp(ver('signal').Version,'1.4.8') || ~strcmp(ver('statistics').Version,'1.7.7');error('Package version mismatch');end; addpath(genpath(" + _quote(native) + '));addpath(' + _quote(compat) + ",'-begin'); load(" + _quote(work / 'input.mat') + '); global BA_TRACE BA_CALL; BA_TRACE=struct([]);BA_CALL=0; ' + invocation + " trace=BA_TRACE; save('-mat7-binary'," + _quote(work / 'output.mat') + ",'cleaned','effective','analytics','trace');"
        (work / 'run.m').write_text(script)
        result = native_run([str(runtime), '--quiet', '--no-gui', str(work / 'run.m')], capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0 or not (work / 'output.mat').exists():
            raise RuntimeError('Octave 作者算法执行失败：' + (result.stdout + result.stderr)[-6000:])
        out = loadmat(work / 'output.mat', simplify_cells=True)
        value = np.asarray(out['cleaned'])
        if np.iscomplexobj(value) and np.max(np.abs(value.imag)) > 1e-12 * max(1.0, np.max(np.abs(value.real))):
            raise RuntimeError('作者输出含复信号')
        if value.size != data.size:
            raise RuntimeError('作者输出样点数量错误')
        cleaned = np.asarray(value.real, dtype=float).reshape(data.shape)
        if cleaned.shape != data.shape or not np.isfinite(cleaned).all():
            raise RuntimeError('作者算法输出形状/有限性错误')
        return (cleaned, dict(effective_parameters=out['effective'], analytics=out['analytics'], trace=out['trace'], runtime_log=result.stdout + result.stderr, source_commit=SOURCE_COMMIT, source_sha256=SOURCE_HASHES, profile=mode + '-octave-11.3-scipy-1.15.3', compatibility_patches=['DPSS from scipy.signal.windows.dpss norm=2 sym=True', 'numeric config encoded as MATLAB double', 'iteration observer']))

def _operation_cleanline(op, x, model=None, **p):
    if op != 'cleanline':
        raise NotImplementedError(op)
    _args(p, 'source_root octave_path picks line_frequencies bandwidth scan_bandwidth window_seconds step_seconds alpha pad smoothing max_iterations timeout_seconds tail_policy')
    if model is not None:
        raise ValueError('CleanLine 不接受模型')
    (data, idx, fs, timeout, runtime, source) = _input(x, p)
    n = data.shape[-1]
    lines = np.asarray(p['line_frequencies'])
    if lines.dtype.kind not in 'fiu' or lines.ndim != 1 or (not len(lines)) or (not np.isfinite(lines).all()) or np.any(lines <= 0) or np.any(lines >= fs / 2) or (len(np.unique(lines)) != len(lines)):
        raise ValueError('line_frequencies 须唯一且严格位于 (0,Nyquist)')
    win = _number(p['window_seconds'], 'window_seconds', 1 / fs, n / fs)
    step = _number(p['step_seconds'], 'step_seconds', 1 / fs, win)
    if abs(win * fs - round(win * fs)) > 1e-08 or abs(step * fs - round(step * fs)) > 1e-08:
        raise ValueError('窗口/步长须对应整数样点')
    bandwidth = _number(p['bandwidth'], 'bandwidth', np.finfo(float).tiny, fs)
    k = int(np.floor(win * bandwidth - 1))
    if k < 2 or k >= round(win * fs):
        raise ValueError('DPSS 数量 floor(window_seconds*bandwidth-1) 须在[2,Nwin-1]')
    scan = p['scan_bandwidth']
    if scan is None:
        scan = np.array([])
    else:
        scan = _number(scan, 'scan_bandwidth', 0, fs)
        if np.any(lines - scan / 2 <= 0) or np.any(lines + scan / 2 >= fs / 2):
            raise ValueError('扫描窗口越过 0/Nyquist')
    if p['tail_policy'] != 'preserve':
        raise ValueError('此作者 profile 的尾段策略为 preserve')
    cfg = dict(Fs=fs, fPassBand=np.array([0.0, fs / 2]), lineFrequencies=lines.astype(float), lineNoiseChannels=np.arange(1, len(idx) + 1), maximumIterations=_integer(p['max_iterations'], 'max_iterations', 1, 100), p=_number(p['alpha'], 'alpha', 1e-12, 1 - 1e-12), pad=_integer(p['pad'], 'pad', -1, 6), taperBandWidth=bandwidth, taperWindowSize=win, taperWindowStep=step, fScanBandWidth=scan, tau=_number(p['smoothing'], 'smoothing', 1, 1000000.0))
    (cleaned, artifacts) = _run(data * 1000000.0, fs, cfg, source, runtime, timeout, 'cleanline')
    cleaned = cleaned * 1e-06
    out = x.copy().load_data()
    out._data[idx] = cleaned
    nw = int(round(win * fs))
    ns = int(round(step * fs))
    covered = (n - nw) // ns * ns + nw
    cleaned[:, covered:] = data[:, covered:]
    out._data[idx] = cleaned
    artifacts.update(native_unit='uV', output_unit='V', picks=list(p['picks']), covered_samples=covered, untouched_tail_samples=n - covered, dpss_NW=win * bandwidth / 2, dpss_K=k, removed=data - cleaned)
    return {'data': out, 'model': None, 'artifacts': artifacts}

def eeg_sine_regression(op, x, model=None, **p):
    if model is not None:
        raise ValueError('operation does not accept model')
    if op == 'spectrum_fit':
        return _operation_spectrum_fit(op, x, model=None, **p)
    if op == 'cleanline':
        return _operation_cleanline(op, x, model=None, **p)
    raise NotImplementedError(op)
