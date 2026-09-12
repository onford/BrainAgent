"""Descriptive paired timing/shape measurements; never align away observed errors."""
import math

import numpy as np


def measure_pair(source, processed, *, sfreq, channels, trial_ids, tmin=0., max_lag_seconds=.1, check=lambda: None):
    x, y = np.asarray(source, dtype=float), np.asarray(processed, dtype=float)
    if x.ndim != 3 or x.shape != y.shape or len(channels) != x.shape[1] or len(trial_ids) != x.shape[0]:
        raise ValueError('temporal measurements require identical trial/channel/sample axes')
    if len(set(channels)) != len(channels) or len(set(trial_ids)) != len(trial_ids) or not len(trial_ids):
        raise ValueError('temporal measurements require nonempty unique identities')
    if not math.isfinite(sfreq) or sfreq <= 0 or not math.isfinite(tmin) or not 0 < max_lag_seconds <= .25:
        raise ValueError('invalid temporal measurement sampling contract')
    if not np.isfinite(x).all() or not np.isfinite(y).all() or x.shape[-1] < 8:
        raise ValueError('temporal measurements require finite complete windows with at least eight samples')
    radius = min(int(max_lag_seconds * sfreq), (x.shape[-1] - 1) // 4)
    lags = list(range(-radius, radius + 1))
    times = tmin + np.arange(x.shape[-1]) / sfreq
    rows = []
    for trial, a, b in zip(trial_ids, x, y):
        check()
        for channel, left, right in zip(channels, a, b):
            scale = max(float(np.max(np.abs(left))), float(np.max(np.abs(right))))
            u, v = (left / scale, right / scale) if scale else (left, right)
            u2, v2 = float(np.mean(u*u)), float(np.mean(v*v))
            centered_u, centered_v = u - u.mean(), v - v.mean()
            variance_u, variance_v = float(np.mean(centered_u**2)), float(np.mean(centered_v**2))
            correlation = (float(np.clip(np.mean(centered_u * centered_v) / math.sqrt(variance_u * variance_v), -1, 1))
                           if variance_u > 0 and variance_v > 0 else None)
            candidates = []
            for lag in lags:
                # Positive lag means processed follows source. Cropping is used
                # for this diagnostic only; the preservation error stays unshifted.
                aa = u[:len(u)-lag] if lag > 0 else u[-lag:] if lag < 0 else u
                bb = v[lag:] if lag > 0 else v[:len(v)+lag] if lag < 0 else v
                aa, bb = aa - aa.mean(), bb - bb.mean()
                denominator = math.sqrt(float(np.dot(aa, aa)) * float(np.dot(bb, bb)))
                candidates.append(float(np.clip(np.dot(aa, bb) / denominator, -1, 1)) if denominator > 0 else None)
            finite = [value for value in candidates if value is not None]
            best = max(finite) if finite else None
            tied = [lag for lag, value in zip(lags, candidates) if value is not None and abs(value-best) <= 1e-8]
            lag_value = tied[0] * 1000 / sfreq if len(tied) == 1 and abs(tied[0]) < radius else None
            lag_reason = ('undefined_constant_signal' if not tied else 'ambiguous_equal_maxima' if len(tied) > 1
                          else 'maximum_at_search_boundary' if lag_value is None else None)
            metrics = {
                'normalized_change': (math.sqrt(float(np.mean((v-u)**2)) / u2) if u2 > 0 else None, 'ratio'),
                'gain': (float(np.mean(u*v)) / u2 if u2 > 0 else None, 'ratio'),
                'zero_lag_correlation': (correlation, 'correlation'),
                'lag_ms': (lag_value, 'ms'),
                'energy_centroid_shift_ms': ((float(np.dot(times, v*v) / np.sum(v*v) - np.dot(times, u*u) / np.sum(u*u)) * 1000)
                                             if u2 > 0 and v2 > 0 else None, 'ms'),
            }
            rows.append(dict(trial_id=trial, channel=channel,
                metrics={name: dict(value=value, unit=unit, status='ok' if value is not None else 'unavailable',
                    reason=lag_reason if name == 'lag_ms' else 'zero_reference_energy_or_constant_signal' if value is None else None)
                    for name, (value, unit) in metrics.items()},
                lag_search=dict(candidate_lags_samples=lags, correlations=candidates, best_lags_samples=tied,
                    overlap_samples=[len(u)-abs(lag) for lag in lags])))
    summary = {}
    for name in rows[0]['metrics']:
        values = [row['metrics'][name]['value'] for row in rows]
        valid = all(value is not None for value in values)
        summary[name] = dict(value=math.fsum(values) / len(values) if valid else None,
            status='ok' if valid else 'unavailable', unit=rows[0]['metrics'][name]['unit'],
            expected=len(values), available=sum(value is not None for value in values),
            reason=None if valid else 'incomplete_trial_channel_measurements')
    return dict(schema_version='temporal-change-1', status='evaluated', summary=summary, measurements=rows,
        expected_trials=len(trial_ids), paired_trials=len(trial_ids), channels=list(channels),
        parameters=dict(sfreq=sfreq, tmin=tmin, max_lag_seconds=max_lag_seconds,
            actual_max_lag_samples=radius, tie_tolerance=1e-8, amplitude_alignment='none', time_alignment='none'),
        interpretation='Changes between verified common measurement views; not isolated artifacts or proof of neural preservation.',
        limitations=['Lag is a bounded waveform similarity descriptor, not a physiological latency estimate.',
            'Periodic or flat signals can make delay unidentifiable; equal maxima and boundary maxima are unavailable.',
            'Energy centroid changes can reflect amplitude or shape as well as time shifts.',
            'All trial/channel pairs remain in the denominator; no favorable deletion of missing values.',
            'Shared filtering retains its edge and phase effects. These are full supplied-window measurements.'])


def common_view_diagnostic(quality, context):
    from app.preprocessing.storage import digest
    records = [row for group in quality.get('bysubject', {}).values() for row in group.get('records', [])]
    if len({r['record_id'] for r in records}) != len(records):
        raise ValueError('duplicate common-view record identities')
    expected_records = quality.get('coverage', {}).get('records_expected')
    complete_inventory = (type(expected_records) is int and expected_records == len(records)
                          and quality.get('coverage', {}).get('records_visited') == expected_records)
    rows = []
    for record in records:
        context['check']()
        contrast = record.get('physical_contrast') or {}
        contract = contrast.get('contract')
        if contrast.get('status') != 'evaluated' or not contract:
            rows.append(dict(record_id=record['record_id'], status='unavailable', reason='verified_common_view_contract_missing'))
            continue
        if digest(contract) != contrast.get('contract_sha256'):
            raise ValueError('common-view contract hash differs')
        if (contract.get('schema_version') != 'physical-contrast-1'
                or contract.get('geometry') != 'same_original_cues_samples_channels; no_resampling_or_time_warp'):
            raise ValueError('common-view original sample geometry is not verified')
        artifacts = contrast.get('artifacts', [])
        byview = {a['view']: a for a in artifacts}
        if len(byview) != len(artifacts) or not {'source', 'processed'} <= byview.keys():
            raise ValueError('common-view source/processed arrays missing or duplicated')
        if any(a.get('record_id') != record['record_id'] for a in artifacts):
            raise ValueError('common-view array record identity differs')
        trials = contract.get('original_trial_ids', [])
        if (len(trials) != contrast.get('expected_trials') or len(trials) != contrast.get('paired_trials')
                or len(trials) != record.get('coverage', {}).get('eligible_trials')):
            raise ValueError('common-view original trial denominator differs')
        space = contract['space']
        if space.get('unit') != 'V' or contract.get('fit_scope') != 'not_fitted':
            raise ValueError('common-view physical voltage and unfitted projection required')
        source, processed = (context['read_array'](byview[name]) for name in ('source', 'processed'))
        if source.shape[-1] != round((contract['time_window'][1] - contract['time_window'][0]) * space['sfreq']) + 1:
            raise ValueError('common-view time interval does not match the actual sample count')
        measured = measure_pair(source, processed, sfreq=space['sfreq'], channels=space['channels'],
            trial_ids=trials, tmin=contract['time_window'][0], check=context['check'])
        ambiguous = [dict(trial_id=r['trial_id'], channel=r['channel'], lag=r['metrics']['lag_ms'],
                          best_lags_samples=r['lag_search']['best_lags_samples'])
                     for r in measured['measurements'] if r['metrics']['lag_ms']['status'] != 'ok']
        # Complete original arrays + kernel parameters reproduce every pair.
        # Bounded examples are labelled; numerical denominators remain complete.
        rows.append(dict(record_id=record['record_id'], status='evaluated', summary=measured['summary'],
            parameters=measured['parameters'], paired_trials=measured['paired_trials'],
            expected_trial_channel_pairs=len(measured['measurements']), ambiguous_lag_pairs=len(ambiguous),
            ambiguous_examples=ambiguous[:4], examples_truncated=len(ambiguous) > 4,
            comparison_contract_sha256=contrast['contract_sha256']))
    names = ('normalized_change', 'gain', 'zero_lag_correlation', 'lag_ms', 'energy_centroid_shift_ms')
    summary = {}
    for name in names:
        available = [r['summary'][name] for r in rows if r['status'] == 'evaluated' and r['summary'][name]['status'] == 'ok']
        complete = bool(rows) and complete_inventory and len(available) == len(rows)
        summary[name] = dict(value=math.fsum(r['value'] for r in available) / len(rows) if complete else None,
            status='ok' if complete else 'unavailable', expected_records=expected_records, available_records=len(available),
            unit=available[0]['unit'] if available else ('ms' if name.endswith('_ms') else 'correlation' if name == 'zero_lag_correlation' else 'ratio'),
            reason=None if complete else 'incomplete_record_measurements')
    status = 'evaluated' if rows and complete_inventory and all(r['status'] == 'evaluated' for r in rows) else 'unavailable'
    return {'status': status, 'common_view_change': dict(status='ok' if status == 'evaluated' else 'unavailable',
        records=rows, summary=summary, aggregation='equal_records_after_equal_trial_channel_pairs; descriptive only',
        neural_preservation='not_established',
        limitations=['Waveform timing/energy changes do not isolate neural signals or artifacts.',
            'No post-hoc amplitude or time alignment; ambiguous lag remains unavailable.',
            'Historical or unsupported geometry without a complete frozen common-view contract remains unavailable.'])}
