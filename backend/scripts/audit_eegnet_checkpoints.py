"""Read-only reconstruction of saved development predictions, with no training.

Uses the registered network architecture but independently checks event/array
assembly, inner-fit normalization, split membership, inference and score means.
This is an artifact audit, not an independent generalization experiment.
"""
import argparse
import hashlib
import math
from collections import Counter, defaultdict
from contextlib import contextmanager
import json
from pathlib import Path
import time

import numpy as np
import torch
from threadpoolctl import threadpool_limits

from app.preprocessing.storage import digest, file_hash, write_json
from app.search.eegnet import build_model


def require(condition, message):
    if not condition:
        raise ValueError(message)


@contextmanager
def mapped(path):
    values = np.load(path, mmap_mode='r', allow_pickle=False)
    try:
        yield values
    finally:
        if getattr(values, '_mmap', None) is not None:
            values._mmap.close()


class Evidence:
    def __init__(self, root):
        self.root = root.resolve(strict=True)
        self.files = {}

    def path(self, value, expected=None):
        path = Path(value)
        if not path.is_absolute():
            path = self.root / path
        path = path.resolve(strict=True)
        require(path.is_relative_to(self.root), 'Evidence path outside the search tree')
        checksum = file_hash(path)
        require(expected is None or checksum == expected, f'Checksum mismatch: {path}')
        require(path not in self.files or self.files[path] == checksum, f'Evidence changed during audit: {path}')
        self.files[path] = checksum
        return path

    def ref(self, value):
        path = self.path(value['path'], value['sha256'])
        if 'bytes' in value:
            require(path.stat().st_size == value['bytes'], 'Artifact size mismatch')
        return path

    def read(self, value):
        return json.loads(self.path(value).read_text(encoding='utf-8'))

    def read_ref(self, value):
        return json.loads(self.ref(value).read_text(encoding='utf-8'))

    def finish(self):
        require(all(file_hash(path) == checksum for path, checksum in self.files.items()), 'Read evidence changed')
        return {path.relative_to(self.root).as_posix(): checksum for path, checksum in self.files.items()}


def audit(candidate, output):
    candidate = candidate.resolve(strict=True)
    require(candidate.parent.name == 'candidates', 'Expected a search candidate directory')
    search = candidate.parent.parent
    output = output.resolve()
    require(not output.exists() and not output.is_relative_to(search) and not search.is_relative_to(output),
            'Use a new output directory disjoint from the search tree')
    evidence = Evidence(search)
    receipt = evidence.read(candidate / 'receipt.json')
    assessment = receipt.get('assessment') or {}
    require((assessment.get('utility') or {}).get('status') == 'evaluated', 'Utility evaluation must be complete')
    search_state = evidence.read(search / 'search.json')
    bound_candidate = next(c for c in search_state['candidates'] if c['id'] == candidate.name)
    require(bound_candidate['receipt'] == receipt, 'Candidate receipt differs from search snapshot')
    assessment_root = candidate / receipt['assessment_path']
    utility_ref = assessment['utility']['receipt_artifact']
    utility = evidence.read_ref({**utility_ref, 'path': str(assessment_root / utility_ref['path'])})
    protocol = evidence.read_ref(utility['protocol'])
    assembly = evidence.read_ref(utility['inputs'])
    panel = evidence.read(search / 'panel.json')
    result = evidence.read(candidate / 'result.json')
    plan = evidence.read(candidate / 'plan.json')
    require(result['plan_ref']['id'] == result['plan_ref']['sha256'] == digest(plan) and assembly['plan'] == plan, 'Input plan binding mismatch')
    require(assessment['bindings']['plan_hash'] == digest(plan) and assessment['bindings']['result_hash'] == digest(result), 'Assessment plan/result hashes differ')
    require(panel['panel_hash'] == digest({k: v for k, v in panel.items() if k != 'panel_hash'})
        and panel['input_hash'] == digest(plan['input_snapshot']), 'Frozen panel/input checksum mismatch')
    require(utility['panel_hash'] == panel['panel_hash'] and utility['candidate_id'] == candidate.name, 'Candidate/panel mismatch')
    require(panel['evaluation_mode'] == 'group_cross_validation' and len(panel['folds']) == 5, 'Expected five grouped development folds')
    trials = assembly['trials']
    frozen = {t['event_id']: t for t in panel['trials'] if t['eligible']}
    require(Counter(t['event_id'] for t in trials) == Counter({k: 1 for k in frozen}), 'Missing/duplicate eligible trials')
    require([t['array_index'] for t in trials] == list(range(len(trials))), 'Array indices are not contiguous')
    by_record = defaultdict(list)
    for trial in trials:
        original = frozen[trial['event_id']]
        require(all(trial[k] == value for k, value in original.items()), 'Frozen trial metadata changed')
        by_record[trial['record_id']].append(trial)
    records = {r['record_id']: r for r in result['records']}
    require(len(records) == len(result['records']) and set(records) == set(panel['records']), 'Record inventory mismatch')
    array_path = evidence.ref(assembly['arrays']['representation'])
    output.mkdir()
    started = time.perf_counter()
    report = {'status': 'failed', 'candidate_id': candidate.name, 'scope': 'Saved development model/array audit only; no training or independent test set',
        'full_candidate_accepted': False, 'new_model_fits': 0, 'models': [], 'source': str(search),
        'architecture_source_sha256': file_hash(Path(__import__('app.search.eegnet', fromlist=['']).__file__))}
    try:
        require(report['architecture_source_sha256'] == protocol['implementation_sha256']['eegnet.py'], 'Network code differs from frozen protocol')
        require(str(torch.__version__) == protocol['runtime_library_versions']['torch']
            and np.__version__ == protocol['runtime_library_versions']['numpy'], 'Numerical runtime differs from frozen protocol')
        with mapped(array_path) as values, threadpool_limits(limits=1), torch.random.fork_rng(devices=[]):
            torch.set_num_threads(1)
            torch.use_deterministic_algorithms(True)
            require(values.dtype == np.dtype('float64')
                and values.shape == (len(trials), len(panel['output_contract']['channels']), panel['output_contract']['n_times']), 'Wrong input shape/dtype')
            for rid, selected in by_record.items():
                item = records[rid]
                require(item['status'] == 'completed', 'Incomplete physical record')
                refs = {ref['name']: {**ref, 'path': str(search / 'engine' / ref['path'])} for ref in item['result']['artifacts']}
                require(len(refs) == len(item['result']['artifacts']), 'Duplicate physical artifact names')
                events = evidence.read_ref(refs['events.json'])
                events_by_id = {row['event_id']: row for row in events}
                require(len(events_by_id) == len(events), 'Duplicate physical event IDs')
                with mapped(evidence.ref(refs['signal_V.npy'])) as physical:
                    for trial in selected:
                        event = events_by_id[trial['event_id']]
                        require(event['retained'] and event['epoch_index'] == trial['epoch_index']
                            and event['original_sample'] == trial['source_sample'] and event['label'] == trial['label'], 'Physical event mapping mismatch')
                        require(np.isfinite(physical[trial['epoch_index']]).all()
                            and np.array_equal(values[trial['array_index']], physical[trial['epoch_index']]), 'Utility input differs from finite physical volts')
            groups = np.array([t['subject'] for t in trials])
            labels = np.array([t['label'] for t in trials])
            positive = panel['class_labels']['right']
            class_names = np.array([panel['class_labels']['left'], positive])
            folds = {f['id']: f for f in panel['folds']}
            seed_scores = {}
            norm_cache = {}
            require(set(utility['learners']['eegnet']['seeds']) == {'17', '42', '2026'}, 'Three required model seeds are missing')
            for seed in (17, 42, 2026):
                saved_run = utility['learners']['eegnet']['seeds'][str(seed)]
                require(saved_run['status'] == 'evaluated', 'Incomplete model seed')
                require(Counter(f['fold_id'] for f in saved_run['folds']) == Counter({k: 1 for k in folds}), 'Missing/duplicate folds')
                all_predictions = {}
                for fold_result in saved_run['folds']:
                    fold = folds[fold_result['fold_id']]
                    metadata = evidence.read_ref(fold_result['metadata'])
                    predictions = evidence.read_ref(fold_result['predictions'])
                    checkpoint = torch.load(evidence.ref(fold_result['model']), map_location='cpu', weights_only=True)
                    require(checkpoint['format_version'] == 1, 'Unknown checkpoint format')
                    meta = checkpoint['metadata']
                    require(all(metadata[k] == value for k, value in meta.items()) and meta['seed'] == seed, 'Checkpoint metadata mismatch')
                    require(meta['protocol'] == protocol['eegnet'], 'Checkpoint protocol mismatch')
                    fit_groups, validation_groups, held_out = set(meta['fit_subjects']), set(meta['validation_subjects']), set(fold['development_subjects'])
                    require(fit_groups and validation_groups and not fit_groups & validation_groups
                        and fit_groups | validation_groups == set(fold['train_subjects'])
                        and not (fit_groups | validation_groups) & held_out, 'Leakage in model split')
                    require(set(meta['normalization_fit_subjects']) == fit_groups, 'Normalization fit group mismatch')
                    training = meta['protocol']['training']
                    ranked = sorted(fold['train_subjects'], key=lambda s: (hashlib.sha256(f'{training["split_seed"]}:{s}'.encode()).hexdigest(), s))
                    count = min(len(ranked) - 1, math.ceil(len(ranked) * training['validation_fraction']))
                    require(validation_groups == set(ranked[:count]) and fit_groups == set(ranked[count:]), 'Inner split differs from frozen label-independent policy')
                    require(set(metadata['train_subjects']) == set(fold['train_subjects'])
                        and set(metadata['development_subjects']) == held_out, 'External fold metadata differs')
                    fit_indices = np.flatnonzero(np.isin(groups, list(fit_groups)))
                    dev_indices = np.flatnonzero(np.isin(groups, list(held_out)))
                    require(set(metadata['fit_event_ids']) == {trials[i]['event_id'] for i in fit_indices}, 'Inner-fit event IDs differ')
                    require(set(metadata['validation_event_ids']) == {t['event_id'] for t in trials if t['subject'] in validation_groups}
                        and set(metadata['development_event_ids']) == {trials[i]['event_id'] for i in dev_indices}, 'Validation/development event IDs differ')
                    key = tuple(fit_indices.tolist())
                    if key not in norm_cache:
                        fit_values = values[fit_indices].astype(np.float64)
                        mean = fit_values.mean(axis=(0, 2), keepdims=True)
                        std = fit_values.std(axis=(0, 2), keepdims=True)
                        norm_cache[key] = mean, np.where(std == 0, 1, std)
                        del fit_values
                    mean, std = norm_cache[key]
                    require(np.array_equal(mean, checkpoint['normalization']['mean'].numpy())
                        and np.array_equal(std, checkpoint['normalization']['std'].numpy()), 'Normalization differs from actual inner-fit trials')
                    require([row['event_id'] for row in predictions] == [trials[i]['event_id'] for i in dev_indices], 'OOF prediction event order differs')
                    model = build_model(**meta['architecture'], sfreq=meta['sfreq'])
                    model.load_state_dict(checkpoint['state_dict'], strict=True)
                    model.eval()
                    probabilities = []
                    batch_size = meta['protocol']['training']['batch_size']
                    with torch.inference_mode():
                        for start in range(0, len(dev_indices), batch_size):
                            indices = dev_indices[start:start + batch_size]
                            batch = ((values[indices].astype(np.float64) - mean) / std).astype(np.float32)
                            p = model(torch.from_numpy(batch[:, None])).softmax(dim=1).numpy().astype(np.float64)
                            probabilities.append(p / p.sum(axis=1, keepdims=True))
                    probability = np.concatenate(probabilities)
                    saved = np.array([[row['proba_left'], row['proba_right']] for row in predictions])
                    error = float(np.max(np.abs(probability - saved)))
                    require(np.allclose(probability, saved, rtol=0, atol=1e-12), 'Reloaded probabilities differ')
                    predicted = class_names[probability.argmax(axis=1)]
                    require(np.array_equal(predicted, [row['prediction'] for row in predictions]), 'Reloaded labels differ')
                    for i, row in zip(dev_indices, predictions, strict=True):
                        require(row['subject'] == trials[i]['subject'] and row['label'] == labels[i]
                            and row['array_index'] == int(i) and row['fold_id'] == fold['id'], 'Prediction labels or fold binding differ')
                        require(row['event_id'] not in all_predictions, 'OOF trial counted twice')
                        all_predictions[row['event_id']] = row
                    model_audit = {'seed': seed, 'fold': fold['id'], 'trials': len(predictions),
                        'maximum_probability_difference': error, 'normalization_from_inner_fit_verified': True}
                    report['models'].append(model_audit)
                    write_json(output / f'model-{seed}-{len(report["models"])}.json', model_audit)
                    print('VERIFIED', seed, fold['id'], len(predictions), error, flush=True)
                require(set(all_predictions) == set(frozen), 'Seed omits frozen eligible trials')
                subject_scores = []
                for subject in sorted(set(groups)):
                    rows = [all_predictions[t['event_id']] for t in trials if t['subject'] == subject]
                    truth = np.array([row['label'] for row in rows])
                    predicted = np.array([row['prediction'] for row in rows])
                    score = float(np.mean([np.mean(predicted[truth == label] == label) for label in np.unique(truth)]))
                    require(abs(score - saved_run['subjects'][subject]['ba']) <= 1e-12, 'Subject balanced accuracy differs')
                    subject_scores.append(score)
                seed_scores[str(seed)] = float(np.mean(subject_scores))
            score = float(np.mean(list(seed_scores.values())))
            require(abs(score - utility['selection_score']) <= 1e-12, 'Seed/subject macro selection score differs')
            report.update(status='passed', records=len(by_record), trials=len(trials), subjects=len(set(groups)), seed_scores=seed_scores,
                selection_score=score, historical_assessment_status=assessment['status'])
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        try:
            report['verified_read_files'] = evidence.finish()
            report['read_files_unchanged'] = True
        except Exception as exc:
            report.update(status='failed', read_files_unchanged=False, integrity_error=str(exc))
        report['wall_seconds'] = time.perf_counter() - started
        report['driver_sha256'] = file_hash(Path(__file__))
        write_json(output / 'audit.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.candidate, args.output)
    print('AUDIT', result['status'], result.get('error'), flush=True)
    raise SystemExit(0 if result['status'] == 'passed' else 1)
