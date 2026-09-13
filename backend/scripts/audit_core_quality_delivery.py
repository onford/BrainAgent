"""Audit completed candidate quality coverage and saved physical differences.

May run while later candidates execute. Only the selected completed candidate
projection of live search state is compared; mutable usage/time fields are not
mistaken for immutable evidence. No signal processing, training or fitting.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

import numpy as np


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def audit(candidate, output):
    candidate = candidate.resolve(strict=True)
    search = candidate.parent.parent
    require(candidate.parent.name == 'candidates', 'Expected a candidate directory')
    require(not output.exists(), 'Preserve existing audit receipt')
    start = time.perf_counter()
    bound = {}

    def load(path, expected=None, size=None):
        path = path.resolve(strict=True)
        require(path.is_relative_to(search), 'Evidence escapes search root')
        checksum = sha(path)
        require(expected is None or checksum == expected, 'Evidence hash mismatch')
        require(size is None or path.stat().st_size == size, 'Evidence size mismatch')
        bound[path] = checksum
        return read(path)

    state = read(search / 'search.json')
    original_candidate = next(c for c in state['candidates'] if c['id'] == candidate.name)
    require(original_candidate['status'] == 'evaluated', 'Candidate is not completed')
    receipt = load(candidate / 'receipt.json')
    require(receipt == original_candidate['receipt'], 'Completed candidate receipt mismatch')
    assessment_root = candidate / receipt['assessment_path']
    assessment = load(assessment_root / 'assessment.json')
    require(assessment == receipt['assessment'] and assessment['selection_ready'], 'Assessment not ready or mismatched')
    input_data = load(search / 'input.json')
    collection = input_data['collection']
    records = {r['id']: r for r in collection['records'] if r['id'] in collection['selected_record_ids']}
    quality_ref = assessment['quality']['receipt_artifact']
    quality_path = (assessment_root / quality_ref['path']).resolve(strict=True)
    quality = load(quality_path, quality_ref['sha256'], quality_ref['bytes'])
    quality_root = quality_path.parent
    require(quality['candidate_id'] == candidate.name, 'Quality candidate identity mismatch')
    require(quality['composite_score'] is None, 'Proxy observations must not become a composite score')
    require(len(quality['detail_artifacts']) == len(records) == 327, 'Full target record coverage missing')
    require(not quality['unexpected_plan_records'] and not quality['unexpected_result_records'], 'Unexpected execution records')
    report = {'status': 'failed', 'candidate_id': candidate.name, 'scope': 'Full target record quality coverage and exact saved signed differences',
              'new_model_fits': 0, 'signal_processing_reexecuted': False, 'neural_preservation_validated': False,
              'final_core_acceptance': False, 'record_results': [], 'read_file_hashes': {}}
    try:
        seen, expected_trials, paired_trials = set(), 0, 0
        unavailable = Counter()
        for ref in quality['detail_artifacts']:
            identity = ref['record_id']
            require(identity in records and identity not in seen, 'Unexpected/duplicate quality record')
            seen.add(identity)
            detail = load(quality_root / ref['path'], ref['sha256'], ref['bytes'])
            require(detail['record_id'] == identity and detail['subject'] == identity[:4], 'Quality record/subject mismatch')
            require(detail['source_read_only'] and detail['source_unchanged_verified'], 'Source integrity evidence missing')
            coverage = detail['coverage']
            require(coverage['available_trials'] == coverage['eligible_trials'] == coverage['original_trials']
                    and coverage['missing_trials'] == coverage['common_invalid_trials'] == 0, 'Target trial coverage differs')
            contrast = detail['physical_contrast']
            require(contrast['expected_trials'] == coverage['eligible_trials'], 'Contrast denominator differs')
            expected_trials += coverage['eligible_trials']
            row = {'record_id': identity, 'source_sfreq': records[identity]['sfreq'], 'trials': coverage['eligible_trials'],
                   'contrast_status': contrast['status'], 'reason': contrast.get('reason')}
            if contrast['status'] == 'not_comparable':
                require(records[identity]['sfreq'] == 128 and contrast['reason'] == 'source_and_processed_sample_rates_differ'
                        and contrast['paired_trials'] == 0 and not contrast.get('artifacts'), 'Unexpected incomparable case')
                unavailable[contrast['reason']] += 1
            else:
                require(contrast['status'] == 'evaluated' and records[identity]['sfreq'] == 160, 'Unexpected contrast status')
                contract = contrast['contract']
                require(contract['fit_scope'] == 'not_fitted' and contract['selection_role'] == 'descriptive_only'
                        and contract['neural_preservation'] == 'not_established', 'Contrast claim/scope differs')
                require(contract['original_trial_ids'] == detail['epoch_order_original_trial_ids'], 'Trial ordering differs')
                require(contrast['paired_trials'] == coverage['eligible_trials'] and contrast['unit'] == 'V', 'Contrast coverage/unit differs')
                arrays = {}
                try:
                    for artifact in contrast['artifacts']:
                        path = (quality_root / artifact['path']).resolve(strict=True)
                        require(path.is_relative_to(quality_root), 'Contrast array escapes quality root')
                        require(artifact['record_id'] == identity and artifact['unit'] == 'V', 'Array provenance/unit differs')
                        checksum = sha(path)
                        require(checksum == artifact['sha256'] and path.stat().st_size == artifact['bytes'], 'Array integrity mismatch')
                        bound[path] = checksum
                        require(artifact['view'] not in arrays, 'Duplicate array view')
                        values = np.load(path, mmap_mode='r', allow_pickle=False)
                        arrays[artifact['view']] = values
                        require(list(values.shape) == artifact['shape'] == [coverage['eligible_trials'], 64, 321]
                                and np.isfinite(values).all(), 'Array geometry/nonfinite mismatch')
                    require(set(arrays) == {'source', 'processed', 'difference'}, 'Missing physical view')
                    require(np.array_equal(arrays['source'] - arrays['processed'], arrays['difference']), 'Saved signed difference is incorrect')
                    row['exact_signed_difference_verified'] = True
                    paired_trials += contrast['paired_trials']
                finally:
                    for values in arrays.values():
                        if getattr(values, '_mmap', None) is not None:
                            values._mmap.close()
            report['record_results'].append(row)
        require(expected_trials == 4918 and len(seen) == 327, 'Final target denominator differs')
        require(paired_trials == quality['physical_contrast']['paired_trials'] == 4768, 'Final paired denominator differs')
        require(sum(unavailable.values()) == 9, 'Unexpected unavailable contrast count')
        latest = read(search / 'search.json')
        require(next(c for c in latest['candidates'] if c['id'] == candidate.name) == original_candidate,
                'Completed candidate state changed during audit')
        report.update(status='passed', records=327, subjects=109, eligible_trials=expected_trials,
                      paired_records=318, paired_trials=paired_trials, unavailable_contrasts=dict(unavailable),
                      completed_candidate_state_unchanged=True,
                      missing_summary_metrics={k: {'status': v['status'], 'reason': v['reason']}
                          for k, v in quality['metrics'].items() if v['status'] != 'ok'})
    except Exception as exc:
        report.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    finally:
        report['read_files_unchanged'] = all(sha(path) == checksum for path, checksum in bound.items())
        if not report['read_files_unchanged']:
            report['status'] = 'failed'
        report['read_file_hashes'] = {str(path.relative_to(search)): checksum for path, checksum in bound.items()}
        report['wall_seconds'] = time.perf_counter() - start
        report['driver_sha256'] = sha(Path(__file__))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.candidate, args.output)
    print(result['status'], result.get('error', ''), flush=True)
    raise SystemExit(0 if result['status'] == 'passed' else 1)
