"""RELAX v2.0.1 formula adapter. Copyright Neil Bailey et al.; GPL-3.0-or-later. Source commit 318300217bdb7ed47a19a892fed16690c5bb77b4."""
import numpy as np
import mne
from scipy.signal import butter, filtfilt
import hashlib, json
from numbers import Real

def _round(a):
    return np.floor(np.asarray(a) + 0.5).astype(int)

def _profile(p):
    if p not in ('relax_2_0_1', 'repaired_units_indices'):
        raise ValueError('profile=relax_2_0_1|repaired_units_indices')

def _real(a, name, ndim=None, finite=True):
    a = np.asarray(a)
    if a.dtype.kind not in 'iuf' or np.iscomplexobj(a):
        raise TypeError(name + ' needs real numeric array')
    a = np.asarray(a, float)
    if ndim is not None and a.ndim != ndim or (finite and (not np.isfinite(a).all())):
        raise ValueError(name + ' shape/finite')
    return a

def _bool(a, shape, name):
    a = np.asarray(a)
    if a.dtype.kind != 'b' or a.shape != shape:
        raise ValueError(name + ' requires boolean array ' + str(shape))
    return a

def _copy(x):
    if not isinstance(x, (mne.io.BaseRaw, mne.BaseEpochs)):
        raise TypeError('Raw/Epochs in V required')
    y = x.copy().load_data()
    a = y.get_data()
    if not a.size or not np.isfinite(a).all():
        raise ValueError('finite nonempty data required')
    return y

def _params(p, required, defaults):
    missing = set(required) - set(p)
    extra = set(p) - set(required) - set(defaults)
    if missing or extra:
        raise ValueError('missing=' + str(missing) + ' extra=' + str(extra))
    return {**defaults, **p}

def _out(x, **a):
    return {'data': x.copy(), 'model': None, 'artifacts': a}

def _runs(mask):
    d = np.diff(np.r_[False, np.asarray(mask, bool), False].astype(int))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))

def _mean_shrink(a, h):
    c = np.r_[0.0, np.cumsum(a)]
    pos = np.arange(len(a))
    lo = np.maximum(0, pos - h)
    hi = np.minimum(len(a), pos + h + 1)
    return (c[hi] - c[lo]) / (hi - lo)

def _eye_weights_numeric(S, fs, eyes, raw_mask, profile):
    _profile(profile)
    S = _real(S, 'sources', 2)
    eyes = _bool(eyes, (len(S),), 'eyes')
    raw_mask = _bool(raw_mask, (S.shape[1],), 'raw_blink_mask')
    if not np.isfinite(fs) or fs <= 50:
        raise ValueError('fs must support 25Hz filter')
    b, a = butter(2, [0.5, 25], btype='bandpass', fs=fs)
    padlen = 3 * (max(len(a), len(b)) - 1)
    if S.shape[1] <= padlen:
        raise ValueError('insufficient samples for source filtfilt')
    h = int(_round(0.2 * fs))
    min_run = int(_round(_round(0.1 * fs) / (1000 / fs))) if profile == 'relax_2_0_1' else int(_round(0.1 * fs))
    weights = np.zeros_like(S)
    filtered = np.zeros_like(S)
    initial = np.zeros_like(S, dtype=bool)
    combined = initial.copy()
    for k in np.flatnonzero(eyes):
        q = filtfilt(b, a, S[k], padtype='odd', padlen=padlen)
        filtered[k] = q
        med = np.median(q)
        scaled_mad = 1.482602218505602 * np.median(abs(q - med))
        mask = abs(q - med) > 2 * scaled_mad
        initial[k] = mask
        starts = np.flatnonzero(np.diff(mask.astype(int)) == 1) + 1
        ends = np.flatnonzero(np.diff(mask.astype(int)) == -1)
        mask = mask | raw_mask
        if profile == 'relax_2_0_1':
            if len(starts):
                if not len(ends):
                    raise ValueError('author profile has unclosed initial IC blink run')
                if ends[0] < starts[0]:
                    ends = ends[1:]
                if not len(ends):
                    raise ValueError('author profile has no end after initial IC blink run')
                if ends[-1] < starts[-1]:
                    starts = starts[:-1]
                if len(starts) != len(ends):
                    raise ValueError('author IC blink endpoint mismatch')
                for st, en in zip(starts, ends):
                    if en - st < min_run:
                        mask[st:en + 1] = False
        else:
            for st, en in _runs(mask):
                if en - st < min_run:
                    mask[st:en] = False
        combined[k] = mask
        padded = mask.astype(float)
        for c in range(len(padded) - h - 2, -1, -1):
            if padded[c] == 1:
                padded[c:c + h + 1] = 1
        for c in range(h, len(padded)):
            if padded[c] == 1:
                padded[c - h:c + 1] = 1
        weights[k] = _mean_shrink(padded, h)
    return dict(eye_weights=weights, filtered_sources=filtered, ic_outlier_masks=initial, combined_masks=combined, minimum_run_samples=min_run, moving_mean_half_samples=h, profile=profile)

def _model_signature(x):
    projs = tuple(((p['desc'], int(p['kind']), bool(p['active']), tuple(p['data']['col_names']), hashlib.sha256(np.asarray(p['data']['data']).tobytes()).hexdigest()) for p in x.info['projs']))
    return (tuple(x.ch_names), tuple(x.get_channel_types()), tuple(x.info['bads']), int(x.info['custom_ref_applied']), projs)

def eeg_relax_eye_weights(op, x, model=None, **p):
    if op != 'eye_weights':
        raise ValueError('op=eye_weights')
    p = _params(p, ['eye_components', 'raw_blink_mask', 'component_id', 'reference_id'], {'profile': 'relax_2_0_1'})
    y = _copy(x)
    if not isinstance(y, mne.io.BaseRaw) or not isinstance(model, dict) or model.get('kind') != 'ica':
        raise TypeError('Raw and fitted ICA model required')
    ic = model['estimator']
    if model.get('signature') != _model_signature(y):
        raise ValueError('ICA channel/type/bads/reference/projector signature mismatch')
    if model.get('reference_id') != p['reference_id'] or model.get('sfreq') != y.info['sfreq'] or list(ic.ch_names) != [n for n, t in zip(y.ch_names, y.get_channel_types()) if t == 'eeg' and n not in y.info['bads']]:
        raise ValueError('ICA channel/reference/sampling mismatch')
    if p['component_id'] != _component_id(ic):
        raise ValueError('component identity mismatch')
    if ic.noise_cov is not None:
        raise ValueError('noise_cov=None required')
    S = ic.unmixing_matrix_ @ ic.pca_components_[:ic.n_components_] @ (y.get_data(picks=ic.ch_names) / ic.pre_whitener_)
    result = _eye_weights_numeric(S, y.info['sfreq'], p['eye_components'], p['raw_blink_mask'], p['profile'])
    return _out(y, **result, component_id=p['component_id'], reference_id=p['reference_id'])

def _identity_value(value):
    if isinstance(value, np.ndarray):
        if value.dtype.hasobject:
            raise TypeError('ICA identity cannot encode object arrays')
        if value.dtype.kind in 'fc' and (not np.isfinite(value).all()):
            raise ValueError('ICA identity parameters must be finite')
        return {'__ndarray__': {'dtype': value.dtype.str, 'shape': list(value.shape), 'sha256': hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()}}
    if isinstance(value, np.generic):
        return _identity_value(value.item())
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not np.isfinite(value):
            raise ValueError('ICA identity parameters must be finite')
        return value
    if isinstance(value, (list, tuple)):
        return [_identity_value(v) for v in value]
    if isinstance(value, dict):
        if any((not isinstance(k, str) for k in value)):
            raise TypeError('ICA identity dictionary keys must be strings')
        return {k: _identity_value(value[k]) for k in sorted(value)}
    raise TypeError('Unsupported ICA identity parameter type: ' + type(value).__name__)

def _component_id(ic):
    metadata = dict(method=ic.method, n_components=int(ic.n_components_), fit_params=ic.fit_params, ch_names=ic.ch_names)
    h = hashlib.sha256(json.dumps(_identity_value(metadata), sort_keys=True, allow_nan=False).encode())
    for a in (ic.unmixing_matrix_, ic.mixing_matrix_, ic.pca_components_, ic.pre_whitener_, ic.pca_mean_):
        h.update(str(np.shape(a)).encode())
        h.update(np.asarray(a, dtype='<f8').tobytes())
    h.update('\x00'.join(ic.ch_names).encode())
    return h.hexdigest()
