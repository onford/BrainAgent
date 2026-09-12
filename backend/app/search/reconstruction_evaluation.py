"""Dataset reconstruction probes of shared physical preprocessing.

Public API: freeze_probe_panel(panel, *, design="balanced") -> dict;
evaluate_dataset_reconstruction(...) -> {summary, details, artifacts}.

One complete, first-by-record-id MI recording per subject is a reconstruction
probe ONLY: the primary learner still uses its entire frozen panel. By default
every subject receives one of ten conditions, balanced by hash-sorted rotation.
Explicit design="full_factorial" assigns all ten conditions to every subject.
Source Raw is read once, clean P is replayed once and verified against existing
signal_V.npy before scoring. Each corrupted P is fitted independently through
units.invoke; no runner/evaluator internals or learned representation are used.
Explicit adjacent detect/mark branches bind the diagnostic to the original
signal input; mark alone applies bads and its existing max_fraction cap.

All comparison signals receive the SAME continuous CAR and 1--70 Hz projection
before extracting every eligible frozen trial. These are cleanproxy fidelity
measurements, not neural ground truth.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time

import mne
import numpy as np

from app.preprocessing import inputs, units
from app.preprocessing.schemas import RecordSpec
from app.preprocessing.storage import canonical, digest, file_hash, within, write_json
from .panel import validate_panel
from .reconstruction import (
    ARRAY_NAMES,
    KINDS,
    align_fair_targets,
    evaluate_negative_controls,
    evaluate_reconstruction,
    generate_contamination,
)


VERSION = "dataset-reconstruction-v4"
METRICS = (
    "input_nrmse",
    "paired_nrmse",
    "paired_error_cleanproxy_ratio",
    "reconstruction_nrmse",
    "paired_ser_improvement_db",
    "reconstruction_ser_improvement_db",
    "paired_correlation",
    "reconstruction_correlation",
    "artifact_residual_coefficient",
    "artifact_residual_rms_ratio",
    "clean_retention_nrmse",
    "clean_retention_rms_ratio",
    "clean_retention_correlation",
    "clean_retention_gain",
)
SUPPORTED = {
    "filter": "EEG-FILTER",
    "notch": "EEG-FILTER",
    "detrend": "EEG-DETREND",
    "reference": "EEG-REREFERENCE",
    "resample": "EEG-RESAMPLE",
    "epoch": "EEG-EPOCH",
    "detect_bad_channels": "EEG-AUTO-BAD-CHANNEL",
    "mark_channels": "EEG-BAD-CHANNEL-MARK",
    "interpolate_bad_channels": "EEG-AUTO-BAD-CHANNEL",
    "asr_clean": "EEG-ASR-AUTO",
}
SCOPE = "physical_preprocessing_before_parent_EA_only"


class ProbeError(ValueError):
    def __init__(self, code, message, *, status="failed"):
        super().__init__(message)
        self.code, self.status = code, status


def _require(condition, code, message):
    if not condition:
        raise ProbeError(code, message)


def _dump(value):
    return (
        value.model_dump(mode="json")
        if hasattr(value, "model_dump")
        else deepcopy(value)
    )


def _array_hash(array):
    array = np.ascontiguousarray(array, dtype="<f8")
    h = hashlib.sha256(canonical({"shape": list(array.shape), "dtype": "<f8"}).encode())
    if array.size:
        h.update(memoryview(array).cast("B"))
    return h.hexdigest()


def freeze_probe_panel(panel, *, design="balanced") -> dict:
    """Freeze score-independent records/cases; does not read EEG or change panel.

    Balanced design sorts ALL subjects by SHA256(seed, subject) then assigns the
    ten conditions cyclically, guaranteeing counts differ by at most one. Each
    subject participates once, without candidate scores or replacement after
    failures. Full factorial explicitly assigns ten conditions to each subject.
    Reuse this exact probe across candidates; changing design is a separate run.

    A record with MI trials is selected even if all its trials are ineligible;
    that subject remains unevaluable instead of falling back to a better record.
    EOG/EMG probes use fixed two-second blocks throughout the continuous record
    (one isolated blink/burst per record would miss most eligible trials).
    Other probes are continuous record-wide waveforms. Strength is normalized
    to the full source EEG record RMS, before the common comparison projection.
    """
    panel = _dump(panel)
    validate_panel(panel)
    if design not in ("balanced", "full_factorial"):
        raise ValueError("probe design must be balanced or full_factorial")
    conditions = [
        {"id": f"{kind}-{suffix}", "kind": kind, "rms_ratio": ratio}
        for kind in KINDS
        for suffix, ratio in (("r05", 0.5), ("r10", 1.0))
    ]
    subject_order = sorted(
        {r["subject"] for r in panel["records"].values()},
        key=lambda subject: (
            digest([VERSION, "assignment", panel["seed"], subject]),
            subject,
        ),
    )
    assigned = {
        subject: [conditions[i % len(conditions)]]
        if design == "balanced"
        else conditions
        for i, subject in enumerate(subject_order)
    }
    subjects = {}
    for subject in sorted(subject_order):
        records = sorted(
            r for r, v in panel["records"].items() if v["subject"] == subject
        )
        mi_records = [
            r for r in records if any(t["record_id"] == r for t in panel["trials"])
        ]
        record_id = mi_records[0] if mi_records else None
        trials = sorted(
            (
                t
                for t in panel["trials"]
                if t["record_id"] == record_id and t["eligible"]
            ),
            key=lambda t: t["source_row"],
        )
        subjects[subject] = {
            "record_id": record_id,
            "trial_ids": [t["event_id"] for t in trials],
            "cases": [
                {
                    **condition,
                    "seed": int(
                        digest([VERSION, panel["seed"], subject, condition["kind"]])[
                            :16
                        ],
                        16,
                    ),
                }
                for condition in assigned[subject]
            ],
        }
    condition_manifest = {}
    for condition in conditions:
        members = sorted(s for s in subjects if condition in assigned[s])
        condition_manifest[condition["id"]] = {
            **condition,
            "subjects": members,
            "subjects_expected": len(members),
            "trial_cases_expected": sum(len(subjects[s]["trial_ids"]) for s in members),
        }
    result = {
        "schema_version": VERSION,
        "design": design,
        "assignment": {
            "algorithm": "sha256_sorted_subjects_round_robin"
            if design == "balanced"
            else "all_subjects_all_conditions",
            "subject_order": subject_order,
            "condition_order": [c["id"] for c in conditions],
        },
        "conditions": condition_manifest,
        "panel_hash": panel["panel_hash"],
        "input_hash": panel["input_hash"],
        "seed": panel["seed"],
        "scope": SCOPE,
        "selection": "first_sorted_complete_MI_record_per_subject_probe_only",
        "primary_evaluation_record_count": len(panel["records"]),
        "primary_evaluation_subject_count": len(subjects),
        "primary_evaluation_panel_unchanged": True,
        "comparison": {
            "representation": "completed_physical_epochs_then_common_reference_band",
            "reference": "average",
            "unit": "V",
            "band_hz": [1.0, 70.0],
            "output_contract": deepcopy(panel["output_contract"]),
        },
        "injection": {
            "eog_emg_block_seconds": 2.0,
            "line_frequency": 50.0,
            "strength_scope": "whole_source_EEG_record_RMS_ratio",
            "model": "engineering_probes_not_physiological_head_model",
        },
        "replay_tolerance": {"rtol": 1e-8, "atol_V": 1e-15},
        "applicability_min_input_nrmse": 1e-12,
        "subjects": subjects,
    }
    return {**result, "probe_hash": digest(result)}


def _lineage(config):
    """Only a data chain with adjacent detect/mark side branches is executable."""
    if any(s.get('implementation_version')=='2' for s in config['steps']):
        from app.preprocessing.schemas import Step
        from app.preprocessing.ports import sources
        seen={'raw'}
        for value in config['steps']:
            step=Step.model_validate(value)
            dependencies=[step.input,step.model_from,step.decision_from]
            dependencies += [p.step for p in step.artifact_inputs.values()]
            dependencies += [p.step for e in step.parameter_inputs.values() for p in sources(e)]
            _require(step.implementation_version=='2' and step.id not in seen and all(d is None or d in seen for d in dependencies),
                'GRAPH_DEPENDENCY_MISMATCH','graph probe requires a closed topological graph')
            seen.add(step.id)
        _require(config['output'] in seen,'GRAPH_OUTPUT_MISSING','graph output is missing')
        return
    previous, pending, ended, seen = "raw", None, False, {"raw"}
    for step in config["steps"]:
        if (
            SUPPORTED.get(step["op"]) != step["unit_id"]
            or step["input"] != previous
            or (ended and step["op"] != "reference")
            or step["id"] in seen
            or any(step.get(k) is not None for k in ("model_from", "fit_scope"))
            or (step["op"] != "mark_channels" and step.get("decision_from") is not None)
            or (pending is not None and step["op"] != "mark_channels")
            or (
                step["op"] == "mark_channels"
                and (
                    pending is None
                    or step.get("decision_from") != pending["id"]
                    or step["input"] != pending["input"]
                    or "bads" in step["params"]
                )
            )
        ):
            raise ProbeError(
                "UNSUPPORTED_RECIPE",
                "requires a data chain with adjacent detect/mark bound to the same input; arbitrary model/decision DAGs are not applicable",
                status="not_applicable",
            )
        seen.add(step["id"])
        if step["op"] == "detect_bad_channels":
            pending = step
            continue  # Diagnostic output is not the next data node.
        pending, previous = None, step["id"]
        ended = ended or step["op"] == "epoch"
    if pending is not None:
        raise ProbeError(
            "UNSUPPORTED_RECIPE",
            "detector requires an explicit mark on its original input",
            status="not_applicable",
        )


def _supported(config, contract, event_codes):
    _lineage(config)
    chain = set()
    by_id = {s['id']: s for s in config['steps']}
    cursor = config['output']
    while cursor != 'raw':
        _require(cursor in by_id and cursor not in chain, 'GRID_MISMATCH', 'invalid output dependency')
        chain.add(cursor)
        cursor = by_id[cursor]['input']
    epoch_count = 0
    for step in config["steps"]:
        if step['id'] in chain and step["op"] in ('epoch', 'epoch_with_nonfinite'):
            epoch_count += 1
            _require(
                all((config.get('evaluation_window') or step["params"]).get(k) == contract[k] for k in ("tmin", "tmax"))
                and step["params"].get("picks") == contract["channels"]
                and step["params"].get("event_id") == event_codes,
                "GRID_MISMATCH",
                "candidate epoch contract differs from frozen panel",
            )
    _require(
        epoch_count == 1 and (config["output"] == config["steps"][-1]["id"] or all(s.get('implementation_version')=='2' for s in config['steps'])),
        "GRID_MISMATCH",
            "one frozen epoch grid followed only by reference operations required",
    )


def _decision_input_hash(raw, events, *, bads=None):
    """Bind diagnostics to signal, event grid and decision-relevant Raw state.

    Independent of runner internals; no comparison to runner's hash algorithm.
    An explicit bads override verifies that mark changed only the bad-channel set.
    """
    info = raw.info
    return digest(
        {
            "signal": _array_hash(raw._data),
            "events": _array_hash(events),
            "channels": raw.ch_names,
            "types": raw.get_channel_types(),
            "sfreq": float(info["sfreq"]),
            "first_samp": int(raw.first_samp),
            "bads": list(info["bads"]) if bads is None else list(bads),
            "highpass": float(info["highpass"]),
            "lowpass": float(info["lowpass"]),
            "custom_ref_applied": int(info["custom_ref_applied"]),
            "channel_state": [
                {
                    "loc": _array_hash(ch["loc"]),
                    "unit": int(ch["unit"]),
                    "coord_frame": int(ch["coord_frame"]),
                    "cal": float(ch["cal"]),
                    "range": float(ch["range"]),
                }
                for ch in info["chs"]
            ],
            "dig": [
                {
                    "kind": int(d["kind"]),
                    "ident": int(d["ident"]),
                    "coord_frame": int(d["coord_frame"]),
                    "r": _array_hash(d["r"]),
                }
                for d in (info["dig"] or [])
            ],
            "projs": [
                {
                    "desc": p["desc"],
                    "active": bool(p["active"]),
                    "columns": p["data"]["col_names"],
                    "data": _array_hash(p["data"]["data"]),
                }
                for p in info["projs"]
            ],
            "annotations": {
                "onset": _array_hash(raw.annotations.onset),
                "duration": _array_hash(raw.annotations.duration),
                "description": raw.annotations.description.tolist(),
                "channels": [list(v) for v in raw.annotations.ch_names],
                "orig_time": str(raw.annotations.orig_time),
            },
        }
    )


def _replay(raw, events, config):
    """Replay fresh model=None, retaining the data node across detect/mark."""
    _lineage(config)
    if any(s.get('implementation_version')=='2' for s in config['steps']):
        from .graph_replay import replay
        return replay(raw, events, config)
    x, current = raw.copy(), events.copy()
    continuous, trace = None, []
    decision = None
    for step in config["steps"]:
        params = deepcopy(step["params"])
        decision_op = step["op"] in ("detect_bad_channels", "mark_channels")
        before_hash = _decision_input_hash(x, current) if decision_op else None
        if step["op"] == "mark_channels":
            _require(
                decision is not None
                and decision["input_hash"] == before_hash
                and decision["source_step"] == step["decision_from"]
                and decision["input_node"] == step["input"],
                "DECISION_BINDING_MISMATCH",
                "decision is bound to a different signal version",
            )
            params["bads"] = list(decision["candidates"])
        if step["op"] in ("resample", "epoch"):
            params["events"] = current.copy()
        if step["op"] == "epoch":
            continuous = x
        result = units.invoke(step["unit_id"], step["op"], x, model=None, **params)
        y = result["data"]
        if decision_op:
            _require(
                _decision_input_hash(x, current) == before_hash,
                "DECISION_INPUT_MUTATED",
                "diagnosis/mark mutated its input signal or metadata",
            )
        _require(
            result.get("model") is None,
            "UNEXPECTED_MODEL",
            "data chain returned a model port",
        )
        if step["op"] == "resample":
            mapped = np.asarray(result["artifacts"]["events"])
            _require(
                mapped.shape == current.shape
                and np.array_equal(mapped[:, 1:], current[:, 1:]),
                "EVENT_IDENTITY_CHANGED",
                "resample did not preserve event identity",
            )
            current = mapped.copy()
        if step["op"] == "detect_bad_channels":
            candidates = result["artifacts"]["candidates"]
            _require(
                isinstance(candidates, list)
                and all(isinstance(c, str) for c in candidates)
                and len(candidates) == len(set(candidates))
                and set(candidates)
                <= {
                    n
                    for n, kind in zip(x.ch_names, x.get_channel_types(), strict=True)
                    if kind == "eeg"
                },
                "INVALID_BAD_CHANNELS",
                "detector returned unknown channel names",
            )
            _require(
                _decision_input_hash(y, current) == before_hash,
                "DIAGNOSTIC_OUTPUT_CHANGED",
                "detector must not change the signal or mark channels implicitly",
            )
            decision = {
                "source_step": step["id"],
                "input_node": step["input"],
                "input_hash": before_hash,
                "candidates": list(candidates),
            }
        elif step["op"] == "mark_channels":
            expected_bads = sorted(set(x.info["bads"]) | set(params["bads"]))
            _require(
                _decision_input_hash(y, current)
                == _decision_input_hash(x, current, bads=expected_bads),
                "MARK_OUTPUT_CHANGED",
                "mark must only apply the detector's bad-channel set",
            )
        if step["op"] != "epoch" and isinstance(x, mne.BaseEpochs):
            _require(
                isinstance(y, mne.BaseEpochs) and y.ch_names == x.ch_names
                and y.info["sfreq"] == x.info["sfreq"]
                and np.array_equal(y.events, x.events)
                and np.array_equal(y.selection, x.selection)
                and np.array_equal(y.times, x.times)
                and y.get_data().shape == x.get_data().shape,
                "GRID_MISMATCH", "post-epoch reference changed the frozen epoch grid",
            )
        elif step["op"] != "epoch":
            _require(
                isinstance(y, mne.io.BaseRaw),
                "CONTINUOUS_REQUIRED",
                "data operation must return Raw",
            )
            _require(
                y.ch_names == x.ch_names,
                "CHANNELS_CHANGED",
                "continuous channel removal/reordering is unsupported",
            )
            if step["op"] != "resample":
                _require(
                    y.n_times == x.n_times
                    and y.first_samp == x.first_samp
                    and y.info["sfreq"] == x.info["sfreq"],
                    "GRID_MISMATCH",
                    "data operation changed time grid",
                )
        _require(
            np.isfinite(y.get_data()).all(),
            "NONFINITE_OUTPUT",
            "processor returned nonfinite output",
        )
        artifacts = result.get("artifacts", {})
        trace.append(
            {
                "step_id": step["id"],
                "unit_id": step["unit_id"],
                "op": step["op"],
                "parameters": deepcopy(params)
                if step["op"] == "mark_channels"
                else deepcopy(step["params"]),
                "bads": list(y.info["bads"]),
                "decision_binding": deepcopy(decision) if decision_op else None,
                "fit_artifact_hashes": {
                    k: _array_hash(artifacts[k])
                    for k in (
                        "mixing_matrix",
                        "threshold_matrix",
                        "calibration_sample_mask",
                    )
                    if isinstance(artifacts.get(k), np.ndarray)
                },
            }
        )
        if step["op"] != "detect_bad_channels":
            x = y
            decision = None
        # No persisted Raw or fitted objects; next invocation independently fits.
    return x, x.copy(), current, trace


def _aligned_epoch_ids(epochs, current, mapping, trials, contract):
    _require(
        isinstance(epochs, mne.BaseEpochs),
        "GRID_MISMATCH",
        "terminal result is not epochs",
    )
    indices = epochs.selection.tolist()
    _require(
        len(indices) == len(set(indices))
        and all(0 <= i < len(mapping) for i in indices),
        "TRIAL_IDENTITY_CHANGED",
        "invalid epoch selection",
    )
    ids = [mapping[i]["event_id"] for i in indices]
    expected = [t["event_id"] for t in trials]
    _require(
        set(ids) == set(expected),
        "TRIAL_IDENTITY_CHANGED",
        "replay must retain every and only eligible probe trial",
    )
    times = (
        np.arange(contract["epoch_start_offset"], contract["epoch_end_offset"] + 1)
        / contract["sfreq"]
    )
    _require(
        epochs.ch_names == contract["channels"]
        and epochs.info["sfreq"] == contract["sfreq"]
        and epochs.times.shape == times.shape
        and np.allclose(epochs.times, times, atol=1e-12, rtol=0),
        "GRID_MISMATCH",
        "replay channel/rate/time grid differs",
    )
    _require(
        np.array_equal(epochs.events, current[indices]),
        "TRIAL_IDENTITY_CHANGED",
        "epoch events do not match synchronized events",
    )
    positions = {identity: i for i, identity in enumerate(ids)}
    return epochs.get_data()[[positions[t] for t in expected]]


def _artifact_signal(store_root, item, config, plan, trials, contract):
    _require(
        item["status"] == "completed",
        "CANDIDATE_RECORD_FAILED",
        "existing candidate recording did not complete",
    )
    paths = {}
    required = {"signal_V.npy", "events.json", "delta.json", "provenance.json"}
    for entry in item["result"]["artifacts"]:
        if entry["name"] in required:
            _require(
                entry["name"] not in paths,
                "ARTIFACT_MISMATCH",
                "duplicate artifact name",
            )
            path = within(store_root, entry["path"])
            _require(
                file_hash(path) == entry["sha256"],
                "ARTIFACT_MISMATCH",
                "artifact checksum differs",
            )
            paths[entry["name"]] = path
    _require(set(paths) == required, "ARTIFACT_MISMATCH", "required artifact missing")
    rows = json.loads(paths["events.json"].read_text(encoding="utf-8"))
    delta = json.loads(paths["delta.json"].read_text(encoding="utf-8"))
    provenance = json.loads(paths["provenance.json"].read_text(encoding="utf-8"))
    _require(
        provenance["method_ref"] == config["method_ref"]
        and provenance["input_ref"] == plan["request"]["input_ref"]
        and provenance["engine_sha256"] == plan["engine_sha256"],
        "ARTIFACT_MISMATCH",
        "artifact provenance differs from plan",
    )
    logs = [s for s in provenance["steps"] if s["branch"] == "main"]
    _require(
        len(logs) == len(config["steps"]),
        "ARTIFACT_MISMATCH",
        "artifact recipe length differs",
    )
    for log, step in zip(logs, config["steps"], strict=True):
        from .graph_evaluation import check_log
        from app.preprocessing.schemas import Step
        _require(
            all(log[k] == step[k] for k in ("unit_id", "op"))
            and log["step_id"] == step["id"]
            and check_log(log, Step.model_validate(step)),
            "ARTIFACT_MISMATCH",
            "artifact executed recipe differs",
        )
    after = delta["after"]
    _require(
        after["unit"] == "V"
        and after["kind"] == "epochs"
        and after["channels"] == contract["channels"]
        and after["sfreq"] == contract["sfreq"]
        and after["types"] == ["eeg"] * len(contract["channels"]),
        "ARTIFACT_MISMATCH",
        "artifact is not matching physical voltage epochs",
    )
    retained = [r for r in rows if r["retained"]]
    _require(
        len({r["event_id"] for r in rows}) == len(rows)
        and {r["event_id"] for r in retained} == {t["event_id"] for t in trials}
        and sorted(r["epoch_index"] for r in retained) == list(range(len(trials))),
        "ARTIFACT_MISMATCH",
        "artifact missing/duplicate eligible trial IDs",
    )
    lookup = {r["event_id"]: r for r in retained}
    for trial in trials:
        row = lookup[trial["event_id"]]
        _require(
            row["original_sample"] == trial["source_sample"]
            and row["output_sample"] == trial["output_sample"]
            and row["output_sfreq"] == contract["sfreq"]
            and row["label"] == trial["label"],
            "ARTIFACT_MISMATCH",
            "artifact trial samples/labels differ",
        )
    values = np.load(paths["signal_V.npy"], mmap_mode="r", allow_pickle=False)
    try:
        _require(
            values.shape
            == (len(trials), len(contract["channels"]), contract["n_times"])
            and np.isfinite(values).all(),
            "ARTIFACT_MISMATCH",
            "artifact signal shape/values differ",
        )
        signal = np.array(
            values[[lookup[t["event_id"]]["epoch_index"] for t in trials]]
        )
    finally:
        values._mmap.close()
    return signal, file_hash(paths["signal_V.npy"]), logs


def _reference_raw(raw, events, contract):
    if raw.info["sfreq"] == contract["sfreq"]:
        return raw, events.copy()
    result = units.invoke(
        "EEG-RESAMPLE",
        "resample",
        raw,
        model=None,
        sfreq=contract["sfreq"],
        events=events.copy(),
    )
    mapped = np.asarray(result["artifacts"]["events"])
    _require(
        mapped.shape == events.shape and np.array_equal(mapped[:, 1:], events[:, 1:]),
        "EVENT_IDENTITY_CHANGED",
        "reference resample lost event identity",
    )
    return result["data"], mapped


def _comparison(raw, events, mapping, trials, probe):
    contract = probe["comparison"]["output_contract"]
    _require(
        raw.info["sfreq"] == contract["sfreq"],
        "GRID_MISMATCH",
        "physical output rate differs",
    )
    channels = contract["channels"]
    _require(
        all(raw.get_channel_types(picks=[n]) == ["eeg"] for n in channels),
        "PHYSICAL_V_REQUIRED",
        "comparison channels must be EEG",
    )
    _require(
        all(
            int(raw.info["chs"][raw.ch_names.index(n)]["unit"]) == 107 for n in channels
        ),
        "PHYSICAL_V_REQUIRED",
        "EEG must be physical SI voltage",
    )
    positions = {row["event_id"]: i for i, row in enumerate(mapping)}
    if isinstance(raw,mne.BaseEpochs):
        selected={int(v):i for i,v in enumerate(raw.selection)}
        requested=[positions[t['event_id']] for t in trials]
        _require(all(i in selected for i in requested),'GRID_MISMATCH','completed graph output dropped a frozen trial')
        data=raw.get_data(picks=channels)[[selected[i] for i in requested]]
    else:
        segments=[]
        for trial in trials:
            sample=int(events[positions[trial['event_id']],0])-raw.first_samp
            _require(sample==trial['output_sample'],'GRID_MISMATCH','resampled event differs from frozen grid')
            start,stop=sample+contract['epoch_start_offset'],sample+contract['epoch_end_offset']+1
            _require(0<=start<stop<=raw.n_times,'GRID_MISMATCH','frozen trial outside comparison input')
            segments.append(raw.get_data(picks=channels,start=start,stop=stop))
        data=np.stack(segments)
    values, space = align_fair_targets(
        {"data": data},
        contract["sfreq"],
        channels=channels,
        input_unit="V",
        output_unit="V",
        source_reference="physical_candidate_reference",
        reference="average",
        band_hz=tuple(probe["comparison"]["band_hz"]),
    )
    space['comparison_representation']='completed_physical_epochs_then_common_reference_band'
    return values['data'], space


def _noise(raw, case, subject, record_id, probe):
    picks = mne.pick_types(raw.info, eeg=True, exclude=[])
    _require(
        len(picks) >= 2, "NO_EEG", "at least two EEG channels required for common CAR"
    )
    x = raw.get_data(picks=picks)
    sfreq = float(raw.info["sfreq"])
    key = canonical([subject, record_id])
    block_manifests = []
    if case["kind"] in ("eog", "emg"):
        block = max(2, round(probe["injection"]["eog_emg_block_seconds"] * sfreq))
        # Some readers expose a NumPy scalar; block boundaries enter strict JSON.
        n_times = int(raw.n_times)
        template = np.empty_like(x)
        for start in range(0, n_times, block):
            stop = min(start + block, n_times)
            # Include one preceding sample for a one-sample tail, without dropping it.
            origin = start if stop - start >= 2 else start - 1
            _, a, manifest = generate_contamination(
                x[None, :, origin:stop],
                sfreq,
                kind=case["kind"],
                seed=case["seed"],
                rms_ratio=1.0,
                window_keys=[canonical([subject, record_id, origin])],
            )
            template[:, start:stop] = a[0, :, start - origin :]
            block_manifests.append(
                {"start": origin, "stop": stop, "manifest": manifest}
            )
    else:
        template = None
    _, noise, manifest = generate_contamination(
        x[None],
        sfreq,
        kind=case["kind"],
        seed=case["seed"],
        rms_ratio=case["rms_ratio"],
        window_keys=[key],
        line_frequency=probe["injection"]["line_frequency"],
        template=None if template is None else template[None],
    )
    manifest.update(
        model="engineering_continuous_record_probe",
        blocks=block_manifests,
        strength_scope=probe["injection"]["strength_scope"],
        source_eeg_hash=_array_hash(x),
        contamination_hash=_array_hash(noise[0]),
        eeg_channels=[raw.ch_names[i] for i in picks],
    )
    corrupted = raw.copy().load_data()
    corrupted._data[picks] += noise[0]
    return corrupted, manifest


def _aggregate(rows):
    metrics = {}
    for metric in METRICS:
        if not rows:
            metrics[metric] = {
                "value": None,
                "status": "not_assigned",
                "n_valid": 0,
                "n_total": 0,
            }
            continue
        values = [row.get(metric, {}).get("value") for row in rows]
        valid = [v for v in values if v is not None and math.isfinite(v)]
        metrics[metric] = {
            "value": math.fsum(v / len(rows) for v in valid)
            if len(valid) == len(rows)
            else None,
            "status": "ok" if len(valid) == len(rows) else "incomplete",
            "n_valid": len(valid),
            "n_total": len(rows),
        }
    return metrics


def _controls_valid(controls):
    targets = {
        "identity": {
            "artifact_residual_coefficient": 1.0,
            "paired_ser_improvement_db": 0.0,
        },
        "zero": {"clean_retention_nrmse": 1.0, "clean_retention_rms_ratio": 0.0},
        "scaling": {"clean_retention_nrmse": 0.5, "clean_retention_gain": 0.5},
    }
    for name, expected in targets.items():
        for metric, value in expected.items():
            actual = controls[name]["summary"][metric]["value"]
            if actual is None or not math.isclose(
                actual, value, rel_tol=1e-8, abs_tol=1e-8
            ):
                return False
    return True


def _failure(exc):
    return {
        "status": getattr(exc, "status", "failed"),
        "reason_code": getattr(exc, "code", type(exc).__name__),
        "reason": str(exc),
    }


def _subject(
    subject, frozen, config, item, record, plan, source, store, panel, probe, resources
):
    contract = panel["output_contract"]
    config = {**config, '_record':record.model_dump(mode='json'), '_storage_root':str(store)}
    _supported(config, contract, panel["event_codes"])
    trials = sorted(
        (t for t in panel["trials"] if t["event_id"] in set(frozen["trial_ids"])),
        key=lambda t: t["source_row"],
    )
    if not trials:
        raise ProbeError(
            "NO_ELIGIBLE_TRIALS",
            "first MI probe record has no eligible trials",
            status="not_applicable",
        )
    inputs.validate_record_files(source, record)
    raw, events, mapping = inputs.read_record(
        source,
        record,
        plan["input_snapshot"]["survey"]["event_id"],
        plan["input_snapshot"]["survey"].get("context_event_id"),
    )
    resources["source_records_read"] += 1
    resources["largest_source_array_bytes"] = max(
        resources["largest_source_array_bytes"], raw._data.nbytes
    )
    _require(
        raw.first_samp == 0,
        "GRID_MISMATCH",
        "frozen source sample coordinates require uncropped zero-origin Raw",
    )
    raw_hash = _array_hash(raw._data)
    frozen_trials = {
        t["event_id"]: t for t in panel["trials"] if t["record_id"] == record.id
    }
    _require(
        len(mapping) == len(frozen_trials)
        and {r["event_id"] for r in mapping} == set(frozen_trials),
        "TRIAL_IDENTITY_CHANGED",
        "source MI trial inventory differs",
    )
    for row in mapping:
        t = frozen_trials[row["event_id"]]
        _require(
            row["original_sample"] == t["source_sample"]
            and row["label"] == t["label"]
            and row["code"] == panel["event_codes"][t["label"]],
            "TRIAL_IDENTITY_CHANGED",
            "source event identity differs",
        )
    saved, saved_hash, saved_logs = _artifact_signal(
        store, item, config, plan, trials, contract
    )
    resources["clean_replays"] += 1
    epochs, clean_continuous, clean_events, trace = _replay(raw, events, config)
    logs_by_id = {log["step_id"]: log for log in saved_logs}
    for replayed in trace:
        if replayed["op"] == "mark_channels" and replayed.get('implementation_version') != '2':
            log = logs_by_id[replayed["step_id"]]
            detection = logs_by_id[replayed["decision_binding"]["source_step"]]
            _require(
                log["parameters"].get("bads") == replayed["parameters"]["bads"]
                and isinstance(log.get("input_hash"), str)
                and log["input_hash"] == detection.get("input_hash"),
                "DECISION_PROVENANCE_MISMATCH",
                "saved mark decision differs from replay or diagnostic input binding",
            )
    reproduced = _aligned_epoch_ids(epochs, clean_events, mapping, trials, contract)
    tolerance = probe["replay_tolerance"]
    _require(
        np.allclose(
            reproduced, saved, rtol=tolerance["rtol"], atol=tolerance["atol_V"]
        ),
        "CLEAN_REPLAY_MISMATCH",
        "P(cleanproxy) does not reproduce saved signal_V.npy",
    )
    verification = {
        "status": "verified",
        "saved_signal_sha256": saved_hash,
        "replayed_array_hash": _array_hash(reproduced),
        "max_abs_error_V": float(np.max(np.abs(saved - reproduced))),
        "trial_ids": frozen["trial_ids"],
        "tolerance": tolerance,
        "steps": trace,
    }
    del saved, epochs, reproduced
    q, space = _comparison(clean_continuous, clean_events, mapping, trials, probe)
    del clean_continuous
    reference, reference_events = _reference_raw(raw, events, contract)
    x, _ = _comparison(reference, reference_events, mapping, trials, probe)
    del reference
    base = {
        "subject": subject,
        "record_id": record.id,
        "verification": verification,
        "source_array_hash": raw_hash,
        "comparison_space": space,
    }
    for case in frozen["cases"]:
        detail = {**base, "case": case, "scope": SCOPE, "expected_trials": len(trials)}
        try:
            corrupted, injection = _noise(raw, case, subject, record.id, probe)
            detail["injection"] = injection
            linear, linear_events = _reference_raw(corrupted, events, contract)
            y, _ = _comparison(linear, linear_events, mapping, trials, probe)
            del linear
            a = y - x
            detail["array_hashes"] = {
                "reference": _array_hash(x),
                "contaminated": _array_hash(y),
                "contamination": _array_hash(a),
                "processed_reference": _array_hash(q),
            }
            input_rms = np.sqrt(np.mean(x * x, axis=(1, 2)))
            noise_rms = np.sqrt(np.mean(a * a, axis=(1, 2)))
            applicable = (input_rms > 0) & (
                noise_rms > probe["applicability_min_input_nrmse"] * input_rms
            )
            detail["inapplicable_trials"] = [
                t["event_id"]
                for t, ok in zip(trials, applicable, strict=True)
                if not ok
            ]
            if not applicable.all():
                raise ProbeError(
                    "NO_APPLICABLE_CONTAMINATION",
                    "some frozen trials have zero cleanproxy or negligible injected artifact in the common band; denominator retained",
                    status="not_applicable",
                )
            # The numerical helper expects one manifest key per evaluated window.
            metric_injection = {**case, "window_keys": frozen["trial_ids"]}
            metadata = {
                "reference_kind": "real_eeg_cleanproxy",
                "reference_provenance": f"source:{record.id}:{raw_hash}",
                "processor": {
                    "id": config["method_ref"]["id"],
                    "implemented": True,
                    "paired_execution": True,
                },
                "windows": [
                    {"subject_id": subject, "window_id": t["event_id"]} for t in trials
                ],
                "expected_windows": {subject: frozen["trial_ids"]},
                "spaces": {name: space for name in ARRAY_NAMES},
                "injection": metric_injection,
            }
            controls = evaluate_negative_controls(x, y, contract["sfreq"], a, metadata)
            valid = _controls_valid(controls)
            _require(
                valid,
                "NEGATIVE_CONTROL_FAILED",
                "shared-case controls failed analytical checks",
            )
            # Controls describe the same frozen input even if this processor fails.
            detail.update(negative_controls=controls, negative_controls_verified=valid)
            resources["corrupted_replays"] += 1
            epochs, physical, synchronized, trace = _replay(corrupted, events, config)
            _aligned_epoch_ids(epochs, synchronized, mapping, trials, contract)
            z, _ = _comparison(physical, synchronized, mapping, trials, probe)
            del epochs, physical, corrupted
            detail["array_hashes"]["cleaned"] = _array_hash(z)
            detail["corrupted_steps"] = trace
            receipt = evaluate_reconstruction(
                x, y, z, contract["sfreq"], a, metadata, processed_reference=q
            )
            _require(
                receipt["status"] == "evaluated",
                "METRIC_EVALUATION_FAILED",
                receipt.get("reason", "metrics failed"),
            )
            detail.update(
                status="evaluated",
                metrics=receipt["summary"],
                receipt=receipt,
                negative_controls=controls,
                negative_controls_verified=valid,
            )
            resources["largest_metric_input_arrays_bytes"] = max(
                resources["largest_metric_input_arrays_bytes"],
                sum(v.nbytes for v in (x, y, z, a, q)),
            )
        except Exception as exc:
            detail.update(_failure(exc), metrics=_aggregate([{}]))
        _require(
            _array_hash(raw._data) == raw_hash,
            "SOURCE_RAW_MUTATED",
            "replay mutated the source Raw in memory",
        )
        yield detail


def evaluate_dataset_reconstruction(
    plan, result, store_root, panel, candidate_entry, probe_panel, output_dir
) -> dict:
    """Stream per-subject cases to NEW output_dir; return summary/details/artifacts.

    plan/result accept existing ExecutionPlan/RunResult instances or JSON dicts.
    probe_panel must exactly match freeze_probe_panel(panel, design=its_design).
    Default balanced probes use every subject once, full_factorial is explicit.
    Source/candidate
    artifacts are read-only. Output must not overlap source or candidate artifact
    directories and must not already exist. Case files contain metrics, controls,
    recipe traces, injection manifests and hashes, never Raw or signal arrays.
    Failures remain in the condition's assigned-subject denominator with null
    metrics; unassigned conditions have null/not_assigned, never a zero score.
    Invalid top-level bindings/output paths raise ValueError before writing.
    For assessment orchestration, use a fresh output_dir / "reconstruction".
    Returned artifacts list every written JSON as name/path relative to that
    directory, sha256 and bytes, including the saved summary/details index.
    The inventory is returned outside that index to avoid a self-hash cycle.
    """
    started = time.perf_counter()
    plan, result, panel = _dump(plan), _dump(result), _dump(panel)
    candidate_entry, probe = _dump(candidate_entry), _dump(probe_panel)
    _require(
        probe == freeze_probe_panel(panel, design=probe.get("design")),
        "PROBE_PANEL_CHANGED",
        "probe panel differs from deterministic frozen policy",
    )
    _require(
        result["plan_ref"]["id"] == result["plan_ref"]["sha256"] == digest(plan),
        "PLAN_MISMATCH",
        "result is not bound to this plan",
    )
    _require(
        digest(plan["input_snapshot"]) == panel["input_hash"]
        and plan["request"]["input_ref"]["id"]
        == plan["request"]["input_ref"]["sha256"]
        == panel["input_hash"],
        "PLAN_MISMATCH",
        "plan input differs from frozen panel",
    )
    _require(
        isinstance(candidate_entry.get("id"), str) and candidate_entry["id"],
        "CANDIDATE_MISMATCH",
        "candidate ID required",
    )
    source = Path(plan["input_snapshot"]["collection"]["root"]).resolve(strict=True)
    store, output = Path(store_root).resolve(), Path(output_dir).resolve()
    protected = [source]
    protected.extend(
        within(store, a["path"]).parent
        for item in result["records"]
        for a in (item.get("result") or {}).get("artifacts", [])
    )
    _require(
        not any(
            output.is_relative_to(p) or p.is_relative_to(output) for p in protected
        ),
        "UNSAFE_OUTPUT",
        "output must not overlap source or candidate artifact directories",
    )
    _require(
        not output.exists(),
        "OUTPUT_EXISTS",
        "use a fresh output directory; existing runs are read-only",
    )
    _require(
        len({r["method_ref"]["id"] for r in plan["records"]}) == 1,
        "PLAN_MISMATCH",
        "one physical candidate per reconstruction evaluation",
    )
    output.mkdir(parents=True)
    write_json(output / "probe_panel.json", probe)
    resources = {
        "source_records_read": 0,
        "clean_replays": 0,
        "corrupted_replays": 0,
        "largest_source_array_bytes": 0,
        "largest_metric_input_arrays_bytes": 0,
        "persisted_signal_array_count": 0,
    }
    configs = {r["record_id"]: r for r in plan["records"]}
    records = {r["id"]: r for r in plan["input_snapshot"]["collection"]["records"]}
    items = {r["record_id"]: r for r in result["records"]}
    details, by_case = {}, {}
    for subject, frozen in probe["subjects"].items():
        indices = []
        try:
            rid = frozen["record_id"]
            _require(
                rid in configs and rid in records and rid in items,
                "MISSING_RECORD",
                "selected probe record missing from plan/result/input",
            )
            _require(
                sum(r["record_id"] == rid for r in plan["records"]) == 1
                and sum(r["record_id"] == rid for r in result["records"]) == 1,
                "DUPLICATE_RECORD",
                "duplicate probe record",
            )
            generated = _subject(
                subject,
                frozen,
                configs[rid],
                items[rid],
                RecordSpec.model_validate(records[rid]),
                plan,
                source,
                store,
                panel,
                probe,
                resources,
            )
            for detail in generated:
                _save_case(detail, subject, output, indices, by_case)
        except Exception as exc:
            finished = {item["case_id"] for item in indices}
            for case in frozen["cases"]:
                if case["id"] not in finished:
                    _save_case(
                        {
                            "subject": subject,
                            "record_id": frozen["record_id"],
                            "case": case,
                            "scope": SCOPE,
                            "expected_trials": len(frozen["trial_ids"]),
                            **_failure(exc),
                            "metrics": _aggregate([{}]),
                        },
                        subject,
                        output,
                        indices,
                        by_case,
                    )
        details[subject] = {
            "record_id": frozen["record_id"],
            "expected_trials": len(frozen["trial_ids"]),
            "cases": indices,
        }
    case_summary = {}
    for case_id, condition in probe["conditions"].items():
        rows = by_case.get(case_id, [])
        _require(
            sorted(row["subject"] for row in rows) == condition["subjects"],
            "CONDITION_COVERAGE_MISMATCH",
            "case results differ from frozen condition membership",
        )
        statuses = Counter(row["status"] for row in rows)
        case_summary[case_id] = {
            "status": "not_assigned"
            if not rows
            else "evaluated"
            if statuses.get("evaluated", 0) == len(rows)
            else "incomplete",
            "subjects_assigned": condition["subjects"],
            "subjects_expected": condition["subjects_expected"],
            "subjects_not_assigned": len(probe["subjects"])
            - condition["subjects_expected"],
            "trial_cases_expected": condition["trial_cases_expected"],
            "status_counts": dict(statuses),
            "metrics": _aggregate([row["metrics"] for row in rows]),
        }
    statuses = Counter(c["status"] for s in details.values() for c in s["cases"])
    resources.update(
        wall_seconds=time.perf_counter() - started,
        detail_bytes=sum(p.stat().st_size for p in output.rglob("*.json")),
    )
    summary = {
        "schema_version": VERSION,
        "design": probe["design"],
        "scope": SCOPE,
        "probe_hash": probe["probe_hash"],
        "candidate_id": candidate_entry["id"],
        "physical_method_ref": plan["records"][0]["method_ref"],
        "candidate_entry_hash": digest(candidate_entry),
        "plan_hash": digest(plan),
        "status": "evaluated"
        if statuses.get("evaluated", 0) == sum(statuses.values())
        else "incomplete",
        "subjects_expected": len(probe["subjects"]),
        "cases_expected": sum(len(s["cases"]) for s in probe["subjects"].values()),
        "trial_cases_expected": sum(
            len(s["cases"]) * len(s["trial_ids"]) for s in probe["subjects"].values()
        ),
        "status_counts": dict(statuses),
        "by_case": case_summary,
        "aggregation": "equal_windows_within_subject_then_equal_assigned_subjects_per_frozen_condition",
        "primary_evaluation_record_count": len(panel["records"]),
        "primary_evaluation_subject_count": len(probe["subjects"]),
        "resources": resources,
        "limitations": [
            "Real EEG cleanproxy, not neural truth.",
            "One complete recording per subject is a reconstruction probe; primary evaluation retains all records.",
            "Balanced partial stress test: each subject receives one condition only; each condition covers its assigned subset, not all subjects. Between-condition contrasts also involve different subjects."
            if probe["design"] == "balanced"
            else "Full-factorial stress test: every subject is assigned every condition; failed/undefined cases remain in the declared denominator.",
            "Conclusions concern shared physical voltage preprocessing under the declared synthetic contamination cases.",
            "Engineering injection cases do not reproduce all natural artifacts.",
            "Whole-record independent unlabeled fitting is offline/transductive.",
            "Undefined and failed observations remain in the denominator; no weighted total score.",
        ],
    }
    payload = {
        "summary": summary,
        "details": {"probe_panel_path": "probe_panel.json", "subjects": details},
    }
    write_json(output / "reconstruction_evaluation.json", payload)
    # Inventory is returned outside the saved index to avoid a self-hash cycle.
    payload["artifacts"] = [
        {
            "name": p.relative_to(output).as_posix(),
            "path": p.relative_to(output).as_posix(),
            "sha256": file_hash(p),
            "bytes": p.stat().st_size,
        }
        for p in sorted(output.rglob("*.json"))
    ]
    return payload


def _save_case(detail, subject, output, indices, by_case):
    relative = f"cases/{digest(subject)[:16]}/{detail['case']['id']}.json"
    path = within(output, relative)
    write_json(path, detail)
    indices.append(
        {
            "case_id": detail["case"]["id"],
            "status": detail["status"],
            "reason_code": detail.get("reason_code"),
            "path": relative,
            "sha256": file_hash(path),
        }
    )
    by_case.setdefault(detail["case"]["id"], []).append(
        {"subject": subject, "status": detail["status"], "metrics": detail["metrics"]}
    )
