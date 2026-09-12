"""Fixed, bounded continuous measurement snapshots; no data-driven selection."""
from copy import deepcopy
import math

import numpy as np

from app.preprocessing.storage import digest, file_hash


def save_window(values, *, output, record_id, stage, sfreq, channels, history):
    x = np.asarray(values)
    if stage not in ('source_raw', 'processed_continuous') or x.ndim != 3 or x.shape[0] != 1:
        raise ValueError('continuous single-record diagnostic window required')
    if x.dtype.kind != 'f' or len(channels) != x.shape[1] or not math.isfinite(sfreq) or sfreq <= 0:
        raise ValueError('diagnostic window geometry invalid')
    # Selection is fixed before observing values. A short record stays short.
    stop = min(x.shape[-1], int(math.floor(16 * sfreq)))
    if stop * x.shape[1] * 8 > 4 * 1024**2:
        return dict(status='unavailable', reason='fixed_window_exceeds_4MiB_payload_limit')
    selected = np.array(x[..., :stop], dtype=np.float64, copy=True)
    if not stop or not np.isfinite(selected).all():
        return dict(status='unavailable', reason='empty_or_nonfinite_fixed_window')
    directory = output / 'diagnostic-windows' / digest(record_id)[:20]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (stage + '.npy')
    with path.open('xb') as stream:
        np.save(stream, selected, allow_pickle=False)
    artifact = dict(kind='continuous_diagnostic_window', path=path.relative_to(output).as_posix(),
        sha256=file_hash(path), bytes=path.stat().st_size, shape=list(selected.shape), unit='V',
        record_id=record_id, stage=stage)
    contract = dict(schema_version='continuous-diagnostic-window-1', record_id=record_id, stage=stage,
        sfreq=float(sfreq), channels=list(channels), unit='V', history=deepcopy(history),
        selection='first_up_to_16_seconds_of_verified_stage_without_signal_or_label_selection',
        start_sample=0, stop_sample_exclusive=stop, stage_samples=x.shape[-1],
        time_origin='start_of_this_stage; no cross-stage alignment asserted',
        window_ids=[f'{record_id}:{stage}:0:{stop}'], artifact=artifact)
    return dict(status='verified', contract=contract, sha256=digest(contract))


def verified_windows(quality, stage, context):
    records = [r for s in quality.get('bysubject', {}).values() for r in s.get('records', [])]
    ids = [r['record_id'] for r in records]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate diagnostic record identity')
    coverage = quality.get('coverage', {})
    complete = bool(records) and coverage.get('records_expected') == coverage.get('records_visited') == len(records)
    for record in records:
        context['check']()
        window = record.get('diagnostic_windows', {}).get(stage, {})
        frame = record.get('measurement_frames', {}).get(stage, {})
        if window.get('status') != 'verified' or frame.get('status') != 'verified':
            yield record['record_id'], None, None, 'verified_fixed_window_unavailable', complete
            continue
        if not frame.get('sha256') or window.get('measurement_frame_sha256') != frame['sha256']:
            raise ValueError('diagnostic window measurement frame binding mismatch')
        c = window['contract']
        if digest(c) != window.get('sha256') or c.get('schema_version') != 'continuous-diagnostic-window-1':
            raise ValueError('diagnostic window contract hash or version mismatch')
        a = c['artifact']
        if (c.get('record_id') != record['record_id'] or c.get('stage') != stage
                or a.get('record_id') != record['record_id'] or a.get('stage') != stage
                or c.get('unit') != 'V' or a.get('unit') != 'V'
                or c.get('selection') != 'first_up_to_16_seconds_of_verified_stage_without_signal_or_label_selection'):
            raise ValueError('diagnostic window identity or selection mismatch')
        fs = c['sfreq']
        if type(fs) not in (int, float) or not math.isfinite(fs) or fs <= 0:
            raise ValueError('invalid diagnostic window sampling rate')
        stop = c['stop_sample_exclusive']
        if (c['start_sample'] != 0 or type(c['stage_samples']) is not int or c['stage_samples'] <= 0
                or stop != min(c['stage_samples'], math.floor(16 * fs))
                or c['window_ids'] != [f"{record['record_id']}:{stage}:0:{stop}"]):
            raise ValueError('diagnostic window sample support mismatch')
        x = context['read_array'](a)
        if x.shape != (1, len(c['channels']), stop) or list(x.shape) != a.get('shape'):
            raise ValueError('diagnostic window array geometry mismatch')
        yield record['record_id'], x, c, None, complete
