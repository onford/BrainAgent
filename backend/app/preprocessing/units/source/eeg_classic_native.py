"""Whole pinned author entrypoints; record-local execution of one shared recipe.

Only the explicitly exposed mains frequency/seed and all-EEG channel policy
are configurable. Native defaults and QC are retained. Automagic's extra REF
is preserved in native artifacts and explicitly projected out of the graph.
"""
from pathlib import Path
import json
import shutil
import tempfile

import mne
import numpy as np
from scipy.io import loadmat, savemat

from app.preprocessing.artifact_codec import fingerprint
from app.preprocessing.classic_pipelines import catalog
from app.preprocessing.native_process import run, preserve_partial_files
from app.preprocessing.storage import file_hash


def quote(path):
    return "'" + Path(path).resolve().as_posix().replace("'", "''") + "'"


def native_roots(op, params):
    pipeline = "prep" if op == "prep_native" else "automagic"
    roots = [(pipeline, Path(params["source_root"]).resolve())]
    if pipeline == "automagic":
        roots.append(("prep", Path(params["prep_root"]).resolve()))
    contracts = {p["id"]: p for p in catalog()["pipelines"]}
    pins = json.loads((Path(__file__).parents[2] / "classic_source_pins.json").read_text(encoding="utf8"))
    for name, root in roots:
        contract = contracts[name]
        if file_hash(root / contract["entrypoint"]) != contract["sha256"]:
            raise ValueError("native author entrypoint differs from registered source: " + name)
        for relative, expected in pins[name].items():
            if file_hash(root / relative) != expected:
                raise ValueError("native author source tree differs from registered snapshot: " + name + '/' + relative)
    return roots + [("eeglab", Path(params["eeglab_root"]).resolve())]


def eeg_classic_native(op, x, model=None, **params):
    if op not in ("prep_native", "automagic_native") or model is not None:
        raise ValueError("unsupported complete native pipeline call")
    required = {"source_root", "eeglab_root", "matlab_path", "line_freq", "seed", "timeout_seconds", "adaptation_scope"}
    if op == "automagic_native":
        required.update(("prep_root", "ica_random_policy"))
    if set(params) != required or params["adaptation_scope"] != "record_unlabeled":
        raise ValueError("explicit closed native configuration and record-local permission required")
    if not isinstance(x, mne.io.BaseRaw) or any(t != "eeg" for t in x.get_channel_types()):
        raise ValueError("native full pipeline requires continuous EEG-only Raw in V")
    if isinstance(params["seed"], bool) or not isinstance(params["seed"], int) or not 0 <= params["seed"] < 2**32:
        raise ValueError("native random seed must be a uint32 integer")
    if not 0 < params["line_freq"] < x.info["sfreq"] / 2 or not np.isfinite(params["timeout_seconds"]) or params["timeout_seconds"] <= 0:
        raise ValueError("native mains frequency/timeout invalid")
    roots = dict(native_roots(op, params))
    if op == "automagic_native" and params['ica_random_policy'] not in ('author_clock', 'fixed_loop_seed_zero'):
        raise ValueError('unknown native ICA random policy')
    if not (roots["eeglab"] / "functions/popfunc/eeg_emptyset.m").is_file():
        raise ValueError("complete EEGLAB dependency root required")
    raw = x.copy().load_data()
    data = raw.get_data()
    positions = np.array([c["loc"][:3] for c in raw.info["chs"]])
    if not np.isfinite(data).all() or not np.isfinite(positions).all() or np.any(np.linalg.norm(positions, axis=1) == 0):
        raise ValueError("native spatial preprocessing requires finite EEG and electrode geometry")
    annotations = list(raw.annotations)
    event_latencies = np.array([(a["onset"] - raw.first_time) * raw.info["sfreq"] + 1 for a in annotations])
    with tempfile.TemporaryDirectory(prefix="ba-native-pipeline-") as work:
        work = Path(work)
        adaptations = []
        if op == 'automagic_native' and params['ica_random_policy'] == 'fixed_loop_seed_zero':
            derived = work / 'author-automagic'
            shutil.copytree(roots['automagic'], derived)
            call = derived / 'preprocessing/performICLabel.m'
            original = call.read_bytes()
            marker = b"''chanind'',EEG.icachansind)"
            if original.count(marker) != 1:
                raise ValueError('pinned Automagic ICA call site changed')
            call.write_bytes(original.replace(marker, b"''chanind'',EEG.icachansind,''rndreset'',''no'')"))
            adaptations.append(dict(file='preprocessing/performICLabel.m',
                source_sha256=file_hash(roots['automagic'] / 'preprocessing/performICLabel.m'),
                derived_sha256=file_hash(call),
                change='Explicit runica rndreset=no: author training loop resets rand state to zero; outer seed still controls preceding initialization.'))
            roots['automagic'] = derived
        savemat(work / "input.mat", dict(signal_V=data, positions=positions,
            channels=np.array(raw.ch_names, dtype=object), sfreq=float(raw.info["sfreq"]),
            event_labels=np.array([a["description"] for a in annotations], dtype=object),
            event_latencies=event_latencies, event_durations=np.array([a["duration"] * raw.info["sfreq"] for a in annotations])))
        setup = f"addpath({quote(roots['eeglab'])}); addpath(genpath(fullfile({quote(roots['eeglab'])},'functions'))); addpath(genpath(fullfile({quote(roots['eeglab'])},'plugins','firfilt')));"
        setup += f"addpath(genpath(fullfile({quote(roots['prep'])},'PrepPipeline')));"
        if op == "prep_native":
            invoke = f"""
params=struct('referenceChannels',1:EEG.nbchan,'evaluationChannels',1:EEG.nbchan, ...
 'rereferencedChannels',1:EEG.nbchan,'lineNoiseChannels',1:EEG.nbchan, ...
 'lineFrequencies',{float(params['line_freq'])!r},'errorMsgs','verbose');
[output, native_times]=prepPipeline(EEG,params);
native_qc=output.etc.noiseDetection;
assert(strcmp(native_qc.errors.status,'good') && native_qc.fullReferenceInfo,'PREP mandatory stage failed');
"""
        else:
            setup += f"addpath(genpath({quote(roots['automagic'])}));"
            invoke = f"""
defaults=DefaultParameters; settings=defaults.Settings;
settings.trackAllSteps=1;
system=defaults.EEGSystem; system.powerLineFreq={float(params['line_freq'])!r};
params=struct('EEGSystem',system,'Settings',settings);
data_root=fullfile(work,'input'); mkdir(data_root); record_root=fullfile(data_root,'record'); mkdir(record_root);
result_root=fullfile(work,'results'); mkdir(result_root);
pop_saveset(EEG,'filename','record.set','filepath',record_root,'savemode','onefile');
project=Project('native-record',data_root,result_root,'.set',params,struct());
assert(project.nBlock==1,'Expected exactly one record in shared native recipe');
rng({params['seed']},'twister'); project.preprocessAll(); project.updateRatingStructures();
assert(numel(project.processedList)==1,'Author preprocessing did not complete');
if project.toBeInterpolatedCount()>0,project.interpolateSelected();end
project.updateRatingStructures(); block=project.blockMap(project.processedList{{1}});
finished=load(block.resultAddress); output=finished.EEG; native_qc=finished.automagic;
params=project.params; serialized=jsonencode(native_qc);
steps_file=fullfile(result_root,'record','allSteps_record.mat');
if isfile(steps_file),copyfile(steps_file,fullfile(work,'all-stages.mat'));end
assert(~contains(serialized,'FAILED'),'Automagic mandatory stage failed');
assert(~isfield(native_qc,'error_msg') || isempty(native_qc.error_msg),'Automagic reported failure');
"""
        script = f"""
work={quote(work)}; mkdir(fullfile(work,'profile')); setenv('USERPROFILE',fullfile(work,'profile'));
set(0,'DefaultFigureVisible','off'); {setup}
input=load(fullfile(work,'input.mat')); EEG=eeg_emptyset;
EEG.data=input.signal_V*1e6; EEG.srate=input.sfreq; EEG.nbchan=size(EEG.data,1);
EEG.pnts=size(EEG.data,2); EEG.trials=1; EEG.xmin=0; EEG.xmax=(EEG.pnts-1)/EEG.srate;
EEG.setname='BrainAgent shared native recipe'; EEG.filename='native-input'; EEG.ref='unknown';
for i=1:EEG.nbchan
 EEG.chanlocs(i).labels=strtrim(input.channels{{i}});
 EEG.chanlocs(i).X=input.positions(i,2); EEG.chanlocs(i).Y=-input.positions(i,1); EEG.chanlocs(i).Z=input.positions(i,3);
 EEG.chanlocs(i).type='EEG';
end
EEG.chanlocs=convertlocs(EEG.chanlocs,'cart2all');
for i=1:numel(input.event_latencies)
 EEG.event(i).type=input.event_labels{{i}}; EEG.event(i).latency=input.event_latencies(i); EEG.event(i).duration=input.event_durations(i);
end
EEG=eeg_checkset(EEG); rng({params['seed']},'twister'); {invoke}
save(fullfile(work,'native-output.mat'),'output','params','native_qc','-v7');
assert(isequal(output.event,EEG.event),'Native event inventory changed');
assert(output.srate==EEG.srate && size(output.data,2)==EEG.pnts,'Native sample grid changed');
native_signal_V=double(output.data)*1e-6; native_channels={{output.chanlocs.labels}}; native_reference=output.ref;
[present,indices]=ismember({{EEG.chanlocs.labels}},native_channels);
assert(all(present) && numel(unique(indices))==EEG.nbchan,'Native required channels lost/duplicated');
signal_V=native_signal_V(indices,:); assert(all(isfinite(signal_V(:))),'Nonfinite native output');
runtime=struct('version',version,'toolboxes',ver); expanded_configuration=params;
save(fullfile(work,'result.mat'),'signal_V','native_signal_V','native_channels','native_reference','native_qc','expanded_configuration','runtime','-v7');
close all;
"""
        (work / "driver.m").write_text(script, encoding="utf-8")
        try:
            completed = run([params["matlab_path"], "-batch", f"run({quote(work / 'driver.m')})"], timeout=params["timeout_seconds"])
        except BaseException:
            preserve_partial_files(work)
            raise
        if completed.returncode != 0 or not (work / "result.mat").is_file():
            preserve_partial_files(work)
            raise RuntimeError("complete native pipeline failed: " + (completed.stdout + completed.stderr)[-6000:])
        result = loadmat(work / "result.mat", simplify_cells=True)
        cleaned = np.asarray(result["signal_V"], dtype=float)
        channels = np.atleast_1d(result["native_channels"]).tolist()
        if cleaned.shape != data.shape or not np.isfinite(cleaned).all():
            raise ValueError("native bridge output violates the original physical grid")
        if op == "prep_native" and channels != raw.ch_names:
            raise ValueError("PREP changed the native channel inventory")
        raw._data = cleaned
        from mne._fiff.constants import FIFF
        with raw.info._unlock():
            raw.info['custom_ref_applied'] = FIFF.FIFFV_MNE_CUSTOM_REF_ON
        artifacts = {name: result[name] for name in ("native_signal_V", "native_channels", "native_reference", "native_qc", "expanded_configuration", "runtime")}
        artifacts.update(reference_id=op, source_commit=next(p['commit'] for p in catalog()['pipelines'] if p['id'] == ('prep' if op == 'prep_native' else 'automagic')),
            input_sha256=fingerprint(x), native_output_sha256=file_hash(work / "native-output.mat"),
            identity_kind="upstream_configured" if channels == raw.ch_names and not adaptations else "project_derived",
            output_projection=dict(policy="original_ordered_EEG_channels", retained=raw.ch_names,
                excluded=[c for c in channels if c not in raw.ch_names]),
            physical_unit="V", native_unit="uV", random_seed=params["seed"])
        if op == 'automagic_native':
            artifacts['shared_decision_policy'] = 'accept_author_autoBadChans_for_native_interpolation'
            artifacts['ica_random_policy'] = params['ica_random_policy']
            artifacts['native_adaptations'] = adaptations
            artifacts['repeatability'] = 'not_guaranteed_clock_reset' if params['ica_random_policy'] == 'author_clock' else 'explicit_loop_seed_zero'
        # Preserve the complete native object and optional per-stage arrays as
        # bytes in the standard artifact codec, including fields not used above.
        artifacts['native_output_mat'] = np.frombuffer((work / 'native-output.mat').read_bytes(), dtype=np.uint8).copy()
        if (work / 'all-stages.mat').exists():
            artifacts['native_all_stages_mat'] = np.frombuffer((work / 'all-stages.mat').read_bytes(), dtype=np.uint8).copy()
        return dict(data=raw, model=None, artifacts=artifacts)
