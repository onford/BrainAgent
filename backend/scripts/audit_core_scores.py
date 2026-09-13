"""Recompute saved grouped development scores without refitting any model."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path


def require(value, message):
    if not value:
        raise ValueError(message)


def same(value, expected, message):
    require(isinstance(value, (int, float)) and math.isfinite(value)
            and math.isclose(value, expected, rel_tol=0, abs_tol=1e-12), message)


def subject_scores(rows, frozen, folds, seed=None):
    require(Counter(row['event_id'] for row in rows) == Counter({key: 1 for key in frozen}),
            'Missing or duplicated development predictions')
    grouped = defaultdict(lambda: defaultdict(list))
    for row in rows:
        truth = frozen[row['event_id']]
        require(all(row[key] == truth[key] for key in ('record_id', 'subject', 'label')), 'Prediction identity or label changed')
        fold = folds[row['fold_id']]
        require(row['subject'] in fold['development_subjects'] and row['subject'] not in fold['train_subjects'],
                'Prediction uses a training subject')
        require(row['prediction'] in {'left_hand', 'right_hand'}, 'Unknown predicted class')
        if seed is not None:
            require(row['seed'] == seed, 'Unexpected seed')
            left, right = row['proba_left'], row['proba_right']
            require(all(isinstance(p, (int, float)) and math.isfinite(p) and 0 <= p <= 1 for p in (left, right)),
                    'Invalid class probabilities')
            same(left + right, 1, 'Class probabilities do not sum to one')
            require(row['prediction'] == ('right_hand' if right > left else 'left_hand'), 'Prediction disagrees with probabilities')
        grouped[row['subject']][row['label']].append(row['prediction'] == row['label'])
    scores = {}
    for subject, classes in grouped.items():
        require(set(classes) == {'left_hand', 'right_hand'}, 'A subject lacks one true class')
        scores[subject] = sum(sum(values) / len(values) for values in classes.values()) / 2
    return scores, math.fsum(scores.values()) / len(scores)


def audit(search, output, allow_partial=False):
    search = search.resolve(strict=True)
    output = output.resolve()
    require(not output.exists() and not output.is_relative_to(search.parent.parent), 'Use a new external receipt')
    hashes = {}

    def read(path, expected=None, stable=True):
        path = Path(path).resolve(strict=True)
        require(path.is_relative_to(search), 'Evidence path escapes search')
        raw = path.read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        require(expected is None or checksum == expected, 'Evidence checksum mismatch')
        if stable:
            require(str(path) not in hashes or hashes[str(path)] == checksum, 'Read evidence changed')
            hashes[str(path)] = checksum
        return json.loads(raw)

    def ref(value):
        return read(value['path'], value['sha256'])

    state = read(search / 'search.json', stable=False)
    require(allow_partial or state['status'] == 'completed', 'Full search has not completed')
    panel = read(search / 'panel.json')
    frozen = {row['event_id']: row for row in panel['trials'] if row['eligible']}
    folds = {fold['id']: fold for fold in panel['folds']}
    require(len(folds) == 5 and len(frozen) == 4918 and len({r['subject'] for r in frozen.values()}) == 109,
            'Unexpected core panel scope')
    completed = [row for row in state['candidates'] if row['status'] == 'evaluated']
    require(bool(completed), 'No completed candidate to audit')
    if not allow_partial:
        require([row['id'] for row in completed] == [state['protocol']['baseline_id'], *state['recommendation']['candidate_ids']],
                'Some frozen candidates have not completed')
    results = []
    for candidate in completed:
        root = search / 'candidates' / candidate['id']
        receipt = read(root / 'receipt.json')
        require(receipt == candidate['receipt'], 'Search and candidate receipt differ')
        summary = receipt['assessment']['utility']
        require(summary['status'] == 'evaluated', 'Incomplete utility receipt')
        utility_ref = summary['receipt_artifact']
        utility = read(root / receipt['assessment_path'] / utility_ref['path'], utility_ref['sha256'])
        require(utility['candidate_id'] == candidate['id'] and utility['panel_hash'] == panel['panel_hash'],
                'Utility belongs to another candidate or panel')
        require(utility['primary_suite'] == ['eegnet']
                and set(utility['learners']['eegnet']['seeds']) == {'17', '42', '2026'}, 'Primary model or seeds differ')
        scores = {}
        runs = [('csp_lda', utility['learners']['csp_lda'], None)] + [
            ('eegnet-' + str(seed), utility['learners']['eegnet']['seeds'][str(seed)], seed)
            for seed in (17, 42, 2026)]
        for name, run, seed in runs:
            require(run['status'] == 'evaluated' and len(run['folds']) == 5, 'Incomplete learner folds')
            require(Counter(f['fold_id'] for f in run['folds']) == Counter({key: 1 for key in folds}), 'Duplicate or missing learner fold')
            combined = ref(run['predictions'])
            constituent = []
            for fold in run['folds']:
                require(set(fold['train_subjects']) == set(folds[fold['fold_id']]['train_subjects'])
                        and set(fold['development_subjects']) == set(folds[fold['fold_id']]['development_subjects']),
                        'Learner fold membership changed')
                rows = ref(fold['predictions'])
                require(all(row['fold_id'] == fold['fold_id'] for row in rows), 'Wrong fold prediction file')
                constituent.extend(rows)
            require(combined == constituent, 'Combined predictions differ from fold files')
            subjects, score = subject_scores(combined, frozen, folds, seed)
            require(set(subjects) == set(run['subjects']), 'Saved subject coverage differs')
            for subject, value in subjects.items():
                same(value, run['subjects'][subject]['ba'], 'Subject balanced accuracy differs')
            same(score, run['summary']['ba']['mean'], 'Subject-macro score differs')
            scores[name] = score
        primary = math.fsum(scores['eegnet-' + str(seed)] for seed in (17, 42, 2026)) / 3
        same(primary, utility['selection_score'], 'Selection score is not the equal-seed subject macro mean')
        require(receipt['assessment']['selection_ready'] is True, 'Candidate is not eligible for selection')
        same(primary, receipt['assessment']['selection_score'], 'Selection-facing assessment score differs')
        same(primary, summary['learner_scores']['eegnet'], 'Assessment EEGNet score differs')
        same(primary, utility['learner_scores']['eegnet'], 'EEGNet score differs')
        same(scores['csp_lda'], utility['learner_scores']['csp_lda'], 'CSP control score differs')
        results.append({'candidate_id': candidate['id'], 'selection_score': primary, 'scores': scores,
                        'subjects': 109, 'trials_per_learner_seed': 4918, 'folds': 5,
                        'prediction_rows_checked': 4 * len(frozen)})
    final = read(search / 'search.json', stable=False)
    require([c for c in final['candidates'] if c['id'] in {r['id'] for r in completed}] == completed,
            'Completed candidate changed during audit')
    require(all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in hashes.items()), 'Evidence changed during audit')
    selected = None
    if not allow_partial:
        registry = {row['id']: row for row in state['registry']}
        ranked = sorted(completed, key=lambda row: (-row['receipt']['assessment']['selection_score'],
                        row['id'] != state['protocol']['baseline_id'], registry[row['id']]['operator_count'], row['id']))
        selected = ranked[0]['id']
        require(selected == state['selected_candidate_id'] == final['selected_candidate_id'], 'Final selection differs from the frozen ranking')
    report = {'status': 'passed', 'search_id': state['id'], 'search_status_observed': state['status'],
              'candidates': results, 'selected_candidate_verified': selected, 'new_model_fits': 0, 'evidence_sha256': hashes,
              'scope': 'Arithmetic, trial identity and grouped development coverage; this does not reload models or provide an independent test set.',
              'final_core_acceptance': False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--search', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-partial', action='store_true')
    args = parser.parse_args()
    report = audit(args.search, args.output, args.allow_partial)
    print(report['status'], len(report['candidates']), 'completed candidate scores checked')
