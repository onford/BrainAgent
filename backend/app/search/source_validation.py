"""Run and save a reproducible known-source validation matrix; no search scoring."""
import argparse
from copy import deepcopy
from pathlib import Path
import time

import numpy as np

from app.preprocessing import units
from app.preprocessing.storage import digest, file_hash
from .io import write, read
from .source_simulation import simulate_sources, save_probe, evaluate_known_sources
from .catalog import search_engine_hash
from .reconstruction import generate_contamination, KINDS


def filter_probe(values, probe, upper):
    import mne
    parameters = dict(l_freq=1., h_freq=float(upper), method='iir', phase='zero', picks=probe.manifest['channels'])
    outputs = []
    for row in values:
        raw = mne.io.RawArray(row.copy(), mne.create_info(probe.manifest['channels'], probe.manifest['sfreq'], 'eeg'), verbose=False)
        result = units.invoke('EEG-FILTER', 'filter', raw, **parameters)['data']
        outputs.append(result.get_data())
    return np.stack(outputs), dict(id=f'registered_filter_1_{upper}',
        provenance={'unit_id': 'EEG-FILTER', 'op': 'filter', 'parameters': parameters,
            'unit_source': units.specification('EEG-FILTER').source,
            'processing': 'same fixed filter for every synthetic case; no parameter fitting'})


def load_template(path, probe):
    """Explicit local provenance and sample grid; no inferred units or resampling."""
    path = Path(path)
    manifest = read(path.with_suffix('.json'))
    if file_hash(path) != manifest.get('sha256') or manifest.get('sfreq') != probe.manifest['sfreq']:
        raise ValueError('recorded template hash or sampling grid differs')
    if manifest.get('unit') != 'V' or not manifest.get('source_url') or not manifest.get('source_file_sha256') or not manifest.get('sample_selection'):
        raise ValueError('recorded template requires explicit source, units and sample selection')
    if manifest.get('channels') != probe.manifest['channels']:
        raise ValueError('recorded template channel order differs')
    if path.stat().st_size > probe.sensor_V.size * 8 + 4096:
        raise ValueError('recorded template exceeds the declared array size')
    template = np.load(path, allow_pickle=False, mmap_mode='r')
    if not isinstance(template, np.ndarray) or template.dtype.kind != 'f' or template.shape != probe.sensor_V.shape or not np.isfinite(template).all():
        raise ValueError('recorded template must cover every declared case/channel/sample')
    return template, manifest


def run_validation(output, *, sfreq=160., seed=42, template_path=None):
    template_path = Path(template_path) if template_path is not None else None
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    probe = simulate_sources(sfreq=sfreq, seed=seed)
    save_probe(probe, root / 'truth')
    engine = units.engine_hash()
    search_engine = search_engine_hash()
    template, template_provenance = load_template(template_path, probe) if template_path else (None, None)
    design = dict(schema_version='known-source-validation-1', probe_sha256=probe.manifest['sha256'],
        engine_sha256=engine, search_engine_sha256=search_engine,
        conditions=[{'kind': k, 'rms_ratio': ratio} for k in KINDS for ratio in (.5, 1.)],
        controls=['oracle', 'identity', 'zero', 'scale_0.1', 'circular_shift_4_samples'],
        registered_processors=['filter_1_40', 'filter_1_8'], template_provenance=template_provenance,
        interpretation='Finite validation matrix, not full method coverage or selection on real EEG.')
    if template is not None:
        design['conditions'] += [{'kind': 'recorded_eog_template', 'rms_ratio': ratio} for ratio in (.5, 1.)]
    write(root / 'design.json', design)
    x = probe.sensor_V
    clean_runs = {upper: filter_probe(x, probe, upper) for upper in (40, 8)}
    summaries = []
    for condition in design['conditions']:
        kind, ratio = condition['kind'], condition['rms_ratio']
        y, a, injection = generate_contamination(x, sfreq, kind='eog' if kind == 'recorded_eog_template' else kind,
            seed=seed, rms_ratio=ratio, window_keys=probe.manifest['cases'],
            template=template if kind == 'recorded_eog_template' else None)
        folder = root / (kind + '-' + str(ratio))
        folder.mkdir()
        np.save(folder / 'artifact_V.npy', a, allow_pickle=False)
        write(folder / 'injection.json', {'injection': injection, 'artifact_sha256': file_hash(folder / 'artifact_V.npy')})
        runs = [('oracle', x, x), ('identity', x, y), ('zero', x * 0, y * 0),
                ('scale_0.1', x * .1, y * .1),
                ('circular_shift_4_samples', np.roll(x, 4, axis=-1), np.roll(y, 4, axis=-1))]
        for name, q, z in runs:
            processor = dict(id=name, provenance='Declared analytic control; oracle uses the known injection and is not deployable.')
            report = evaluate_known_sources(probe, a, q, z, processor=processor)
            write(folder / (name + '.json'), report)
            summaries.append(dict(condition=condition, processor=name, metrics=report['summary']))
        for upper in (40, 8):
            q, processor = clean_runs[upper]
            z, applied = filter_probe(y, probe, upper)
            assert processor == applied
            report = evaluate_known_sources(probe, a, q, z, processor=processor)
            for label, array in [('processed_clean_V', q), ('processed_contaminated_V', z)]:
                np.save(folder / (processor['id'] + '-' + label + '.npy'), array, allow_pickle=False)
            write(folder / (processor['id'] + '.json'), report)
            summaries.append(dict(condition=condition, processor=processor['id'], metrics=report['summary']))
    probe.verify()
    if units.engine_hash() != engine or search_engine_hash() != search_engine:
        raise ValueError('numeric implementation changed during source validation')
    if template_path and file_hash(template_path) != template_provenance['sha256']:
        raise ValueError('recorded template changed during validation')
    artifacts = [{'path': p.relative_to(root).as_posix(), 'sha256': file_hash(p), 'bytes': p.stat().st_size}
                 for p in sorted(root.rglob('*')) if p.is_file()]
    result = dict(schema_version='known-source-validation-1', status='completed', design_sha256=digest(design),
        engine_sha256=engine, search_engine_sha256=search_engine,
        probe_sha256=probe.manifest['sha256'], elapsed_seconds=time.monotonic() - started,
        original_probe_unchanged=True, template_unchanged=True if template_path else None,
        runs=summaries, artifacts=artifacts, limitations=deepcopy(probe.manifest['limitations']))
    write(root / 'validation.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--sfreq', type=float, default=160.)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--recorded-template', type=Path)
    args = parser.parse_args()
    result = run_validation(args.output, sfreq=args.sfreq, seed=args.seed, template_path=args.recorded_template)
    print({'status': result['status'], 'runs': len(result['runs']), 'seconds': result['elapsed_seconds']})
