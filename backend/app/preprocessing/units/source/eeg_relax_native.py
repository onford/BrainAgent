"""Pinned complete RELAX, with explicit native excision and event provenance."""
from pathlib import Path
import json
import tempfile

import mne
import numpy as np
from scipy.io import loadmat, savemat

from app.preprocessing.artifact_codec import fingerprint
from app.preprocessing.native_process import run, preserve_partial_files
from app.preprocessing.storage import file_hash
from .eeg_classic_native import quote, native_roots as classic_roots


def native_roots(params):
    roots = dict(classic_roots('prep_native', {
        'source_root': params['prep_root'], 'eeglab_root': params['eeglab_root']}))
    pins = json.loads((Path(__file__).parents[2] / 'relax_source_pins.json').read_text(encoding='utf8'))
    for name, key in [('relax', 'source_root'), ('picard', 'picard_root'),
                      ('fieldtrip', 'fieldtrip_root'), ('mwf', 'mwf_root')]:
        root = Path(params[key]).resolve()
        for relative, expected in pins[name].items():
            if file_hash(root / relative) != expected:
                raise ValueError('RELAX dependency differs from pinned source: ' + name + '/' + relative)
        roots[name] = root
    return list(roots.items())


def event_markers(raw, events):
    events = np.asarray(events)
    if events.ndim != 2 or events.shape[1] != 3 or events.dtype.kind not in 'iu':
        raise ValueError('RELAX requires integer event rows')
    if len(events) and np.any(np.diff(events[:, 0]) <= 0):
        raise ValueError('RELAX event samples must be unique and ordered')
    samples = np.rint((raw.annotations.onset - raw.first_time) * raw.info['sfreq']).astype(int) + raw.first_samp
    markers = np.zeros(len(samples), dtype=int)
    for index, sample in enumerate(events[:, 0]):
        positions = np.flatnonzero(samples == sample)
        if len(positions) != 1:
            raise ValueError('RELAX event cannot be bound to exactly one input annotation')
        markers[positions[0]] = index + 1
    return markers


def mapped_events(native_events, original, markers, labels, n_samples):
    rows, kept = [], []
    for event in native_events:
        marker = np.asarray(event.get('ba_index', [])).reshape(-1)
        if not marker.size or marker.size == 1 and marker[0] == 0:
            continue
        if marker.size != 1 or not np.isfinite(marker[0]) or marker[0] != int(marker[0]):
            raise ValueError('RELAX emitted an invalid event marker')
        index = int(marker[0]) - 1
        position = np.flatnonzero(markers == index + 1)
        if not 0 <= index < len(original) or len(position) != 1 or index in kept:
            raise ValueError('RELAX duplicated or invented event identity')
        if str(event['type']) != labels[int(position[0])]:
            raise ValueError('RELAX changed a retained task event label')
        latency = float(event['latency']) - 1
        if not np.isfinite(latency) or abs(latency - round(latency)) > 1e-6 or not 0 <= latency < n_samples:
            raise ValueError('RELAX retained task event is off its new sample grid')
        row = original[index].copy()
        row[0] = round(latency)
        rows.append(row)
        kept.append(index)
    if kept != sorted(kept) or len(rows) > 1 and np.any(np.diff(np.asarray(rows)[:, 0]) <= 0):
        raise ValueError('RELAX reordered retained task events')
    return np.asarray(rows, dtype=int).reshape(-1, 3), np.asarray(kept, dtype=int)


def eeg_relax_native(op, x, model=None, **params):
    required = set('source_root eeglab_root prep_root picard_root fieldtrip_root mwf_root matlab_path line_freq h_freq seed timeout_seconds adaptation_scope compatibility_policy events'.split())
    if op != 'relax_native' or model is not None or set(params) != required:
        raise ValueError('closed complete RELAX configuration required')
    if params['adaptation_scope'] != 'record_unlabeled' or params['compatibility_policy'] != 'eegrej_scalar_row_bound':
        raise ValueError('RELAX requires explicit shared record-local and compatibility policies')
    if not isinstance(x, mne.io.BaseRaw) or any(t != 'eeg' for t in x.get_channel_types()):
        raise ValueError('RELAX requires continuous EEG-only Raw in V')
    fs = float(x.info['sfreq'])
    if not (75 <= params['h_freq'] < fs / 2 and 0 < params['line_freq'] - 3 < params['line_freq'] + 3 < fs / 2):
        raise ValueError('RELAX native muscle diagnostics require at least 75 Hz and filters below Nyquist')
    if type(params['seed']) is not int or not 0 <= params['seed'] < 2**32 or not np.isfinite(params['timeout_seconds']) or params['timeout_seconds'] <= 0:
        raise ValueError('invalid RELAX seed or execution timeout')
    roots = dict(native_roots(params))
    data = x.get_data()
    positions = np.array([c['loc'][:3] for c in x.info['chs']])
    if not np.isfinite(data).all() or not np.isfinite(positions).all() or np.any(np.linalg.norm(positions, axis=1) == 0):
        raise ValueError('RELAX requires finite signal and electrode coordinates')
    original_events = np.asarray(params['events'], dtype=int)
    markers = event_markers(x, params['events'])
    labels = list(x.annotations.description)
    author = roots['relax'] / 'RELAX_SET_PARAMETERS_AND_RUN.m'
    source = author.read_text(encoding='utf8')
    config = source[source.index('RELAX_cfg.Perform_targeted_wICA=1;'):source.index('%% Check for dependencies:')]
    with tempfile.TemporaryDirectory(prefix='ba-relax-') as temporary:
        work = Path(temporary)
        compat = work / 'compatibility'
        compat.mkdir()
        origin = roots['eeglab'] / 'functions/sigprocfunc/eegrej.m'
        original = origin.read_bytes()
        old = b'for iRegion2=iRegion1+1:size(regions)'
        if original.count(old) != 1:
            raise ValueError('explicit RELAX compatibility policy requires the registered EEGLAB call site')
        patched = compat / 'eegrej.m'
        patched.write_bytes(original.replace(old, b'for iRegion2=iRegion1+1:size(regions,1)'))
        adaptations = [dict(file='eegrej.m', source_sha256=file_hash(origin), derived_sha256=file_hash(patched),
            change='Explicit scalar row-count bound; original dependency unchanged')]
        savemat(work / 'input.mat', dict(signal_V=data, sfreq=fs, positions=positions,
            channels=np.array(x.ch_names, dtype=object), labels=np.array(labels, dtype=object), markers=markers,
            latencies=(x.annotations.onset - x.first_time) * fs + 1,
            durations=x.annotations.duration * fs))
        setup = ''.join(f'addpath(genpath({quote(roots[k])}));\n' for k in ('relax', 'prep', 'picard', 'mwf'))
        script = f"""
work={quote(work)}; mkdir(fullfile(work,'profile')); setenv('USERPROFILE',fullfile(work,'profile'));
set(0,'DefaultFigureVisible','off'); eeglab_root={quote(roots['eeglab'])}; addpath(eeglab_root);
addpath(genpath(fullfile(eeglab_root,'functions'))); addpath(genpath(fullfile(eeglab_root,'plugins','firfilt')));
addpath(genpath(fullfile(eeglab_root,'plugins','ICLabel1.6'))); addpath(fullfile(eeglab_root,'plugins','dipfit'));
addpath({quote(roots['fieldtrip'])}); ft_defaults; {setup} addpath({quote(compat)},'-begin');
input=load(fullfile(work,'input.mat')); EEG=eeg_emptyset;
EEG.data=input.signal_V*1e6; EEG.srate=input.sfreq; EEG.nbchan=size(EEG.data,1); EEG.pnts=size(EEG.data,2);
EEG.trials=1; EEG.xmin=0; EEG.xmax=(EEG.pnts-1)/EEG.srate; EEG.ref='unknown'; EEG.setname='Shared RELAX recipe';
for i=1:EEG.nbchan
 EEG.chanlocs(i).labels=strtrim(input.channels{{i}}); EEG.chanlocs(i).type='EEG';
 EEG.chanlocs(i).X=input.positions(i,2); EEG.chanlocs(i).Y=-input.positions(i,1); EEG.chanlocs(i).Z=input.positions(i,3);
end
EEG.chanlocs=convertlocs(EEG.chanlocs,'cart2all');
for i=1:numel(input.latencies)
 EEG.event(i).type=input.labels{{i}}; EEG.event(i).latency=input.latencies(i);
 EEG.event(i).duration=input.durations(i); EEG.event(i).ba_index=input.markers(i);
end
EEG=eeg_checkset(EEG); EEG=pop_saveset(EEG,'filename','record.set','filepath',work);
RELAX_cfg=struct; {config}
RELAX_cfg.myPath=work; RELAX_cfg.filename=[]; RELAX_cfg.caploc=[];
RELAX_cfg.all_data_in_1_folder_or_BIDS_format='folder'; RELAX_cfg.files={{'record.set'}}; RELAX_cfg.FilesToProcess=1;
RELAX_cfg.LineNoiseFrequency={params['line_freq']}; RELAX_cfg.LowPassFilter={params['h_freq']};
RELAX_cfg.LowPassFilter_aux_elecs={params['h_freq']}; RELAX_cfg.ElectrodesToDelete={{}};
requested_configuration=RELAX_cfg; rng({params['seed']},'twister'); RELAX_Wrapper(RELAX_cfg);
output=pop_loadset('filename','record_RELAX.set','filepath',fullfile(work,'RELAXProcessed','Cleaned_Data'));
runtime=struct('version',version,'toolboxes',ver);
save(fullfile(work,'native-output.mat'),'output','requested_configuration','runtime','-v7'); close all;
"""
        driver = work / 'driver.m'
        driver.write_text(script, encoding='utf8', newline='\n')
        try:
            completed = run([params['matlab_path'], '-batch', f'run({quote(driver)})'], timeout=params['timeout_seconds'])
            completed.check_returncode()
            result = loadmat(work / 'native-output.mat', simplify_cells=True)
            native = result['output']
            channels = [str(c['labels']) for c in np.atleast_1d(native['chanlocs'])]
            if len(set(channels)) != len(channels) or not set(channels) <= set(x.ch_names):
                raise ValueError('RELAX output channel identity changed unexpectedly')
            signal = np.asarray(native['data'], dtype=float) * 1e-6
            if signal.ndim != 2 or signal.shape[0] != len(channels) or not signal.size or not np.isfinite(signal).all() or native['srate'] != fs:
                raise ValueError('RELAX output violates physical signal/grid contract')
            native_events = list(np.atleast_1d(native['event']))
            events, kept = mapped_events(native_events, original_events, markers, labels, signal.shape[1])
            intervals = np.asarray(native['RELAX']['ExtremelyBadPeriodsForDeletion'], dtype=float).reshape(-1, 2)
            if not np.isfinite(intervals).all():
                raise ValueError('RELAX excision intervals are nonfinite')
            removed = np.zeros(x.n_times, dtype=bool)
            for start, stop in np.clip(np.floor(intervals + .5).astype(int), 1, x.n_times):
                if start > stop:
                    raise ValueError('RELAX excision interval is reversed')
                removed[start-1:stop] = True
            source_samples = np.flatnonzero(~removed)
            if len(source_samples) != signal.shape[1] or len(events) and not np.array_equal(
                    source_samples[events[:, 0]], original_events[kept, 0] - x.first_samp):
                raise ValueError('RELAX output grid/events do not match declared original sample excisions')
            info = mne.pick_info(x.info.copy(), [x.ch_names.index(c) for c in channels])
            cleaned = mne.io.RawArray(signal, info, verbose='ERROR')
            from mne._fiff.constants import FIFF
            with cleaned.info._unlock():
                cleaned.info['custom_ref_applied'] = FIFF.FIFFV_MNE_CUSTOM_REF_ON
                cleaned.info['highpass'], cleaned.info['lowpass'] = .5, params['h_freq']
            annotations, annotation_projection = [], []
            for index, e in enumerate(native_events):
                onset = max(0., float(e['latency']) - 1) / fs
                value = np.asarray(e.get('duration', [])).reshape(-1)
                duration = float(value[0]) / fs if len(value) == 1 else 0.
                if str(e['type']) == 'boundary':
                    projected, description = 0., 'BAD boundary'
                else:
                    projected, description = min(duration, max(0., signal.shape[1] / fs - onset)), str(e['type'])
                annotations.append((onset, projected, description))
                if projected != duration or description != str(e['type']):
                    annotation_projection.append(dict(native_event_index=index, native_duration_seconds=duration,
                        output_duration_seconds=projected, output_description=description,
                        reason='native excised gap becomes a zero-duration BAD boundary; retained durations are bounded by actual output support'))
            if annotations:
                cleaned.set_annotations(mne.Annotations(*zip(*annotations)))
            artifacts = dict(events=events, kept_event_indices=kept, reference_id='relax_native',
                native_events=native_events, native_qc=native.get('RELAX_issues_to_check', {}),
                annotation_projection=annotation_projection,
                removed_native_intervals=native['RELAX']['ExtremelyBadPeriodsForDeletion'],
                native_interval_frame='one_based_inclusive_input_samples', source_sample_indices=source_samples,
                removed_channels=[c for c in x.ch_names if c not in channels],
                input_sha256=fingerprint(x), physical_unit='V', native_unit='uV',
                random_seed=params['seed'], requested_configuration=result['requested_configuration'],
                runtime=result['runtime'], native_adaptations=adaptations,
                identity_kind='project_derived', source_configuration_sha256=file_hash(author),
                input_event_markers=markers, original_events=original_events,
                native_output_sha256=file_hash(work / 'native-output.mat'),
                native_output_mat=np.frombuffer((work / 'native-output.mat').read_bytes(), dtype=np.uint8).copy())
            return dict(data=cleaned, model=None, artifacts=artifacts)
        except BaseException:
            preserve_partial_files(work)
            raise
