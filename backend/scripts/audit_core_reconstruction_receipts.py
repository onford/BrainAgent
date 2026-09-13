"""Audit frozen probe membership and saved metric aggregation, without rerunning EEG.

This checks receipt arithmetic and control identities. It does not reconstruct
unsaved arrays or independently establish neural preservation.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def same(actual, expected):
    require(isinstance(actual, (float, int)) and not isinstance(actual, bool)
            and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12),
            f'Metric differs: {actual!r} != {expected!r}')


def aggregate(rows, saved):
    require(bool(rows) and all(set(row) == set(saved) for row in rows), 'Metric membership differs')
    for name, target in saved.items():
        values = [row[name]['value'] for row in rows]
        valid = [v for v in values if v is not None]
        require(all(isinstance(v, (int, float)) and math.isfinite(v) for v in valid), 'Nonfinite metric')
        require(target['n_total'] == len(rows) and target['n_valid'] == len(valid), 'Metric denominator differs')
        if len(valid) != len(rows):
            require(target['value'] is None and target['status'] == 'incomplete', 'Missing metric was dropped or filled')
        else:
            require(target['status'] == 'ok', 'Complete metric has wrong status')
            same(target['value'], math.fsum(valid) / len(rows))


def receipt_check(receipt, subject, trial_ids):
    require(receipt['reference_kind'] == 'real_eeg_cleanproxy' and receipt['status'] == 'evaluated',
            'Wrong reference interpretation or incomplete receipt')
    windows = receipt['windows']
    require(Counter((w['subject_id'], w['window_id']) for w in windows)
            == Counter((subject, trial) for trial in trial_ids), 'Frozen probe windows differ')
    require(receipt['n_windows'] == len(trial_ids) and receipt['n_subjects'] == 1
            and set(receipt['subjects']) == {subject}, 'Receipt coverage differs')
    require(receipt['metadata']['expected_windows'] == {subject: trial_ids}, 'Expected windows changed')
    subject_metrics = receipt['subjects'][subject]
    require(subject_metrics['n_windows'] == len(trial_ids), 'Subject window denominator differs')
    aggregate([w['metrics'] for w in windows], subject_metrics['metrics'])
    aggregate([subject_metrics['metrics']], receipt['summary'])


def audit(candidate, output):
    candidate = candidate.resolve(strict=True)
    search = candidate.parent.parent
    output = output.resolve()
    require(not output.exists() and not output.is_relative_to(search.parent.parent), 'Use a new external receipt')
    hashes = {}

    def read(path, expected=None):
        path = path.resolve(strict=True)
        require(path.is_relative_to(search), 'Evidence path escapes search')
        raw = path.read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        require(expected is None or checksum == expected, 'Evidence hash differs')
        hashes[str(path)] = checksum
        return json.loads(raw)

    saved = read(candidate / 'receipt.json')
    require(saved['status'] == 'evaluated' and saved['assessment']['status'] == 'complete',
            'Candidate has not completed')
    root = candidate / saved['assessment_path']
    assessment = read(root / 'assessment.json')
    ref = assessment['reconstruction']['receipt_artifact']
    data = read(root / ref['path'], ref['sha256'])
    probe_root = (root / ref['path']).parent
    probe = read(probe_root / data['details']['probe_panel_path'])
    summary = data['summary']
    require(summary['status'] == 'evaluated' and summary['candidate_id'] == candidate.name,
            'Reconstruction candidate or completion differs')
    require(probe['design'] == summary['design'] == 'balanced' and len(probe['subjects']) == 109,
            'Unexpected core probe design')
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                         ensure_ascii=False, allow_nan=False).encode()).hexdigest()

    require(probe == read(search / 'probe-panel.json'), 'Candidate probe differs from frozen search probe')
    require(probe['probe_hash'] == summary['probe_hash']
            == digest({k: v for k, v in probe.items() if k != 'probe_hash'})
            and digest(probe) == assessment['bindings']['probe_panel_hash'], 'Probe hash binding differs')
    require(set(data['details']['subjects']) == set(probe['subjects']), 'Probe subject membership differs')
    by_case = defaultdict(list)
    total_windows = 0
    for subject, frozen in probe['subjects'].items():
        entry = data['details']['subjects'][subject]
        require(entry['record_id'] == frozen['record_id'] and entry['expected_trials'] == len(frozen['trial_ids']),
                'Probe record or trial count differs')
        require(Counter(c['case_id'] for c in entry['cases']) == Counter(c['id'] for c in frozen['cases']),
                'Frozen condition assignment differs')
        for case in entry['cases']:
            detail = read(probe_root / case['path'], case['sha256'])
            require(detail['status'] == case['status'] == 'evaluated' and detail['subject'] == subject
                    and detail['record_id'] == frozen['record_id'], 'Case identity or status differs')
            require(detail['case'] == next(c for c in frozen['cases'] if c['id'] == case['case_id']),
                    'Case injection changed')
            require(detail['expected_trials'] == len(frozen['trial_ids']) and not detail['inapplicable_trials'],
                    'Incomplete case trials')
            require(detail['verification']['status'] == 'verified', 'Original paired replay was not verified')
            for step in detail['verification']['steps'] + detail['corrupted_steps']:
                require(not step.get('fit_artifact_hashes') and not step.get('decision_binding'),
                        'Unexpected fitting or record-specific decision')
            receipt_check(detail['receipt'], subject, frozen['trial_ids'])
            require(detail['metrics'] == detail['receipt']['summary'], 'Case summary differs from receipt')
            controls = detail['negative_controls']
            require(set(controls) == {'identity', 'zero', 'scaling'} and detail['negative_controls_verified'] is True,
                    'Missing analytical controls')
            for control in controls.values():
                receipt_check(control, subject, frozen['trial_ids'])
            for control, metric, expected in [
                ('identity', 'artifact_residual_coefficient', 1),
                ('identity', 'paired_ser_improvement_db', 0),
                ('zero', 'clean_retention_nrmse', 1),
                ('zero', 'clean_retention_rms_ratio', 0),
                ('scaling', 'clean_retention_nrmse', .5),
                ('scaling', 'clean_retention_gain', .5),
            ]:
                same(controls[control]['summary'][metric]['value'], expected)
            by_case[case['case_id']].append((subject, detail['metrics']))
            total_windows += len(frozen['trial_ids'])
    require(set(by_case) == set(probe['conditions']) == set(summary['by_case']), 'Condition set differs')
    for name, rows in by_case.items():
        expected, reported = probe['conditions'][name], summary['by_case'][name]
        require(sorted(s for s, _ in rows) == expected['subjects'] == reported['subjects_assigned'],
                'Condition subject membership differs')
        require(reported['status'] == 'evaluated' and reported['status_counts'] == {'evaluated': len(rows)},
                'Condition completion differs')
        require(reported['subjects_expected'] == expected['subjects_expected'] == len(rows)
                and reported['subjects_not_assigned'] == 109 - len(rows), 'Condition denominator differs')
        require(reported['trial_cases_expected'] == expected['trial_cases_expected']
                == sum(len(probe['subjects'][subject]['trial_ids']) for subject, _ in rows), 'Trial case total differs')
        aggregate([metrics for _, metrics in rows], reported['metrics'])
        # Selection-facing summary intentionally omits the repeated subject list.
        projected = {k: v for k, v in reported.items() if k != 'subjects_assigned'}
        require(assessment['reconstruction']['summary']['by_case'][name] == projected,
                'Assessment condition summary differs')
    require(summary['subjects_expected'] == summary['cases_expected'] == 109
            and summary['trial_cases_expected'] == total_windows, 'Overall probe coverage differs')
    require(all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == checksum for p, checksum in hashes.items()),
            'Audited source changed')
    report = {'status': 'passed', 'candidate_id': candidate.name, 'subjects': 109,
              'conditions': len(by_case), 'trial_cases': total_windows,
              'control_receipts': 327, 'source_unchanged': True, 'files': hashes,
              'scope': 'Frozen membership, saved window-to-subject-to-condition arithmetic, control identities and assessment projection.',
              'limitations': ['No saved physical probe arrays were independently reloaded by this audit.',
                              'Paired execution evidence comes from the original frozen run.',
                              'Balanced conditions cover assigned subsets; cleanproxy is not neural truth.']}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.candidate, args.output)
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}, ensure_ascii=False))
