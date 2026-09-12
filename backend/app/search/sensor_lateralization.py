"""Fixed C3-minus-C4 sensor ERDS contrast, with descriptive sensitivity only."""
import math

import numpy as np


def _sensitivity(values):
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < 2:
        return dict(status='unavailable', reason='at_least_two_members_required', member_count=n)
    # Delete-one sensitivity is not a confidence interval, especially for trials
    # sharing time, a record or a person. Never resample them as independent people.
    means = (math.fsum(values.tolist()) - values) / (n - 1)
    return dict(status='evaluated', minimum=float(means.min()), maximum=float(means.max()),
        member_count=n, interpretation='delete_one_member_mean_range; sensitivity, not a confidence interval')


def extract_record(report, trial_ids):
    result = dict(schema_version='sensor-erds-contrast-1', channels=['C3', 'C4'],
        direction='C3_minus_C4', unit='percentage_points', expected_trials=len(trial_ids), bands={},
        original_trial_ids=list(trial_ids),
        limitations=['Fixed sensor contrast, not contralateral/ipsilateral classification or source localization.',
            'No labels and no expected ERD/ERS direction or preprocessing target.',
            'Baseline power and delete-one sensitivity are descriptive; temporal dependence and preprocessing leakage remain possible.'])
    channels = report.get('channel_names', [])
    valid_geometry = (len(set(channels)) == len(channels) and all(c in channels for c in ('C3', 'C4'))
        and report.get('unit') == 'V' and len(set(trial_ids)) == len(trial_ids) and bool(trial_ids)
        and report.get('n_epochs') == len(trial_ids))
    metrics = {r['metricID']: r for r in report.get('metrics', [])}
    for band, bounds in [('mu', [8., 12.]), ('beta', [13., 30.])]:
        row = metrics.get('erds_' + band, {})
        detail = row.get('details', {})
        answer = dict(status='unavailable', reason='complete_paired_sensor_baseline_measurement_required',
            band_hz=bounds, expected_trials=len(trial_ids), available_trials=0, value=None,
            missing_trial_ids=list(trial_ids), trials=[])
        result['bands'][band] = answer
        if not valid_geometry:
            answer['reason'] = 'unique_C3_C4_voltage_and_original_trial_axes_required'
            continue
        if row.get('status') != 'ok':
            answer['reason'] = row.get('reason') or 'complete_erds_metric_required'
            continue
        if (row.get('denominator', {}).get('original_trial_ids') != trial_ids
                or detail.get('paired_original_trial_ids') != trial_ids
                or detail.get('baseline_interval_seconds') != [-2.5, -.5]
                or detail.get('baseline_stop_exclusive') is not True):
            answer['reason'] = 'precue_pairing_and_original_trial_identity_required'
            continue
        audit = detail.get('baseline_audit', [])
        if ([r.get('event_id') for r in audit] != trial_ids
                or [r.get('epoch_index') for r in audit] != list(range(len(trial_ids)))
                or any(r.get('status') != 'ok' for r in audit)):
            answer['reason'] = 'all_precue_windows_require_verified_support'
            continue
        erds = np.asarray(row.get('value'), dtype=float)
        baseline = np.asarray(detail.get('baseline_power_uv2_per_hz'), dtype=float)
        shape = (len(trial_ids), len(channels))
        if erds.shape != shape or baseline.shape != shape:
            raise ValueError('sensor ERDS and baseline arrays do not match declared axes')
        indices = [channels.index(c) for c in ('C3', 'C4')]
        e, b = erds[:, indices], baseline[:, indices]
        if not np.isfinite(e).all() or not np.isfinite(b).all() or (b <= 0).any():
            answer['reason'] = 'nonfinite_erds_or_nonpositive_baseline'
            continue
        differences = e[:, 0] - e[:, 1]
        if not np.isfinite(differences).all():
            answer['reason'] = 'nonfinite_sensor_difference'
            continue
        answer.update(status='ok', reason=None, available_trials=len(trial_ids), missing_trial_ids=[],
            value=math.fsum(differences.tolist()) / len(trial_ids),
            trials=[dict(trial_id=t, baseline_C3_uv2_per_hz=float(bp[0]), baseline_C4_uv2_per_hz=float(bp[1]),
                erds_C3_percent=float(ep[0]), erds_C4_percent=float(ep[1]), difference_percentage_points=float(d))
                for t, bp, ep, d in zip(trial_ids, b, e, differences)],
            baseline_power_summary={c: dict(minimum=float(b[:,i].min()), median=float(np.median(b[:,i])),
                maximum=float(b[:,i].max()), unit='uV^2/Hz') for i,c in enumerate(('C3','C4'))},
            baseline_interval_seconds=detail['baseline_interval_seconds'],
            delete_one_trial_sensitivity=_sensitivity(differences))
    return result


def lateralization_diagnostic(quality, stage, context):
    records = []
    seen = set()
    for group, subject in quality.get('bysubject', {}).items():
        for record in subject.get('records', []):
            context['check']()
            rid = record['record_id']
            if rid in seen:
                raise ValueError('duplicate lateralization record identity')
            seen.add(rid)
            frame = record.get('measurement_frames', {}).get(stage, {})
            measurement = record.get('sensor_lateralization', {}).get(stage, {})
            available = frame.get('status') == 'verified' and measurement.get('measurement_frame_sha256') == frame.get('sha256')
            if (measurement and measurement.get('measurement_frame_sha256') is not None
                    and frame.get('status') == 'verified' and not available):
                raise ValueError('sensor contrast frame binding mismatch')
            if available and (measurement.get('schema_version') != 'sensor-erds-contrast-1'
                    or measurement.get('direction') != 'C3_minus_C4' or measurement.get('channels') != ['C3','C4']
                    or measurement.get('unit') != 'percentage_points'):
                raise ValueError('sensor contrast measurement contract mismatch')
            records.append(dict(record_id=rid, subject=group, status='evaluated' if available else 'unavailable',
                measurement=measurement if available else {}, expected_trials=record.get('coverage', {}).get('eligible_trials')))
    coverage = quality.get('coverage', {})
    inventory_complete = bool(records) and coverage.get('records_expected') == coverage.get('records_visited') == len(records)
    inventory_complete = inventory_complete and (coverage.get('subjects_expected') == coverage.get('subjects_visited')
        == len(quality.get('bysubject', {})) == len({r['subject'] for r in records}))
    summary = {}
    for band in ('mu', 'beta'):
        groups, good_records = {}, 0
        for record in records:
            r = record['measurement'].get('bands', {}).get(band, {})
            value = r.get('value')
            rows = r.get('trials', [])
            ids = [t.get('trial_id') for t in rows]
            valid = (r.get('status') == 'ok' and type(value) in (int,float) and math.isfinite(value)
                and record['expected_trials'] == r.get('expected_trials') == r.get('available_trials') == len(rows)
                and bool(rows) and len(set(ids)) == len(rows)
                and ids == record['measurement'].get('original_trial_ids'))
            if valid:
                differences = []
                for t in rows:
                    fields = [t.get(k) for k in ('baseline_C3_uv2_per_hz','baseline_C4_uv2_per_hz',
                        'erds_C3_percent','erds_C4_percent','difference_percentage_points')]
                    if not all(type(v) in (int,float) and math.isfinite(v) for v in fields) or min(fields[:2]) <= 0:
                        raise ValueError('saved sensor contrast has invalid baseline or ERDS values')
                    if not math.isclose(fields[2]-fields[3], fields[4], rel_tol=1e-12, abs_tol=1e-10):
                        raise ValueError('saved sensor difference does not match its paired ERDS')
                    differences.append(fields[4])
                if not math.isclose(math.fsum(differences)/len(rows), value, rel_tol=1e-12, abs_tol=1e-10):
                    raise ValueError('saved sensor mean does not match all original paired trials')
            groups.setdefault(record['subject'], []).append(value if valid else None)
            good_records += int(valid)
        group_means = {g: math.fsum(v)/len(v) for g,v in groups.items() if all(x is not None for x in v)}
        complete = inventory_complete and good_records == len(records)
        summary[band] = dict(status='ok' if complete else 'unavailable',
            value=math.fsum(group_means.values()) / len(groups) if complete else None,
            unit='percentage_points', expected_records=coverage.get('records_expected'), available_records=good_records,
            expected_subjects=len(groups), available_subjects=len(group_means), subject_means=group_means,
            delete_one_subject_sensitivity=_sensitivity(list(group_means.values())) if complete else
                dict(status='unavailable',reason='complete_groups_required'))
    return dict(status='evaluated' if all(r['status']=='ok' for r in summary.values()) else 'unavailable',
        sensor_lateralization=dict(status='ok' if all(r['status']=='ok' for r in summary.values()) else 'unavailable',
            summary=summary, records=records, aggregation='equal_trials_then_equal_records_within_subject_then_equal_subjects',
            interpretation='C3 minus C4 percentage-point ERDS contrast; descriptive sensitivity is not an inferential interval or neural protection certificate'))
