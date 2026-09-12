"""Dataset quality orchestration, independent of decoding and reconstruction.

Inputs and all signal files are read-only. One record's arrays are resident at a
time. Large curves stay in record JSON artifacts; only reduced observations are
kept for record-within-subject, then subject-equal aggregation. No quality score.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path

import numpy as np

from app.preprocessing.inputs import read_record, validate_record_files
from app.preprocessing.schemas import ExecutionPlan, RunResult
from app.preprocessing.storage import digest, file_hash, within, write_json
from .panel import validate_panel
from .quality import evaluate_quality


VERSION = "dataset-quality-1.0"
# Fixed engineering measurement window, not a claim that every paradigm has rest
# here. Each trial additionally requires no overlap with ANY original MI event.
PRECUE_SECONDS = (-2.5, -0.5)  # half-open; two actual seconds, no padding
STAGES = ("source_raw", "source_task", "source_precue", "processed_task",
          "processed_continuous", "processed_precue")
_SPECS = {
    "peak_to_peak": ("µV", "max_t(x)-min_t(x)"),
    "robust_dispersion": ("µV", "1.4826*median_t(abs(x-median_t(x)))"),
    "channel_correlation": ("absolute_correlation", "Q98_j(abs(Pearson(x_c,x_j))),j!=c"),
    "low_correlation_fraction": ("ratio", "count(q98_abs_r<0.4)/finite_channel_windows"),
    "oha": ("ratio", "count(abs(x)>threshold)/(channels*samples)"),
    "thv": ("ratio", "count_t(std_c(x,ddof0)>threshold)/samples"),
    "chv": ("ratio", "count_c(std_t(x,ddof0)>threshold)/channels"),
    "flat_fraction": ("ratio", "marked_samples(abs(diff)<=0.1uV continuously>=5s)/samples"),
    "numerical_rank": ("dimensions", "count(s>max(s)*max(C,T)*eps_float64)"),
    "covariance_condition": ("ratio", "lambda_max/lambda_min;singular->null"),
    "covariance_trace": ("µV²", "trace(sample_covariance_ddof1)"),
    "participation_rank": ("dimensions", "sum(lambda)^2/sum(lambda^2)"),
    "psd": ("µV²/Hz", "median_bias_corrected_Welch_Hamming_50pct"),
    "psd_window_quantiles": ("µV²/Hz", "Q10/Q50/Q90_over_full_4s_windows(channel_median_PSD)"),
    "mu_mean_psd": ("µV²/Hz", "mean_f(PSD[8,12])"),
    "beta_mean_psd": ("µV²/Hz", "mean_f(PSD[13,30])"),
    "emg_hf_proxy": ("dB", "10log10(meanPSD[30,45]/meanPSD[1,30])"),
    "line_ratio_50hz": ("dB", "10log10(meanPSD[49,51)/mean(two_2Hz_sidebands))"),
    "line_ratio_60hz": ("dB", "10log10(meanPSD[59,61)/mean(two_2Hz_sidebands))"),
    "drift_slope": ("µV/s", "OLS_slope_minimum30s"),
    "drift_power_ratio": ("dB", "10log10(integralPSD[0.1,0.5]/integralPSD[1,30])"),
    "electrical_distance": ("µV²", "Var_t(x_i-x_j),ddof0"),
    "reference_nrmse": ("ratio", "RMS(after-before)/RMS(before)"),
    "erds_mu": ("%", "100*(task_mu_linear_power-baseline_mu_linear_power)/baseline_mu_linear_power"),
    "erds_beta": ("%", "100*(task_beta_linear_power-baseline_beta_linear_power)/baseline_beta_linear_power"),
}
METRIC_IDS = tuple(_SPECS)
_RESIDUAL = {"emg_hf_proxy", "line_ratio_50hz", "line_ratio_60hz", "drift_power_ratio"}
_CURVES = {"oha", "thv", "chv", "psd", "psd_window_quantiles"}
_OP_NAMES = {"bandpass": ("EEG-FILTER", "filter"),
             "notch": ("EEG-FILTER", "notch"),
             "highpass": ("EEG-FILTER", "filter"),
             "detect_bad_channels": ("EEG-AUTO-BAD-CHANNEL", "detect_bad_channels"),
             "interpolate_bad_channels": ("EEG-AUTO-BAD-CHANNEL", "interpolate_bad_channels"),
             "asr": ("EEG-ASR-AUTO", "asr_clean"),
             "average_reference": ("EEG-REREFERENCE", "reference"),
             "resample": ("EEG-RESAMPLE", "resample"),
             "epoch": ("EEG-EPOCH", "epoch"), "detrend": ("EEG-DETREND", "detrend")}
_LIMITATIONS = [
    "Proxy observations are not a quality score or validated selection thresholds.",
    "Native stages retain their reference and passband; they are not common 0.5-45Hz views.",
    "Filtering can mechanically lower amplitude, drift and high-frequency power.",
    "ERDS is Welch band-mean power change, not a complete time-frequency analysis.",
    "Zero-phase continuous processing can mix time across a cue; same processing does not prove causal isolation.",
    "Record means are averaged within subject, then subjects equally; records are not inferred sessions.",
    "Original task labels are descriptive only; no supervised fitting or held-out quality-based selection occurs here.",
]


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


@contextmanager
def _mapped(path):
    value = np.load(path, mmap_mode="r", allow_pickle=False)
    try:
        yield value
    finally:
        if getattr(value, "_mmap", None) is not None:
            value._mmap.close()


def _json(value):
    if isinstance(value, np.ndarray):
        return _json(value.tolist())
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def _empty(reason, *, status="not_applicable"):
    return {"metrics": [
        {"metricID": mid, "value": None, "unit": unit,
         "direction": "lower_residual_only" if mid in _RESIDUAL else "non_monotonic",
         "status": status, "reason": reason, "formula": formula,
         "denominator": {}, "details": {}, "applicability": "unavailable",
         "selection_role": "proxy_observation", "limitations": []}
        for mid, (unit, formula) in _SPECS.items()
    ], "metadata": {"reason": reason}}


def _unavailable(metric, reason):
    metric.update(value=None, status="not_applicable", reason=reason, applicability="unavailable")


def _recipe_steps(config, entry):
    """Explicit compiler contract: detection expands to decision + signal mark."""
    nodes = entry["recipe"]["nodes"]
    from .graph_evaluation import graph_method
    if graph_method(config.steps):
        _require(len(nodes)==len(config.steps), 'graph_recipe_step_count_mismatch')
        mapped=[]
        for node, step in zip(nodes, config.steps, strict=True):
            graph=node.get('graph')
            if graph:
                _require((graph['unit_id'],graph['op'],graph['profile'])==(step.unit_id,step.op,step.profile),'graph_recipe_operation_mismatch')
            else:
                _require(_OP_NAMES.get(node['operator'])==(step.unit_id,step.op),'graph_promoted_operation_mismatch')
            _require(all(step.params.get(k)==v for k,v in node.get('parameters',{}).items()),'graph_recipe_parameter_mismatch')
            mapped.append((node,step))
        return mapped
    previous, index, mapped = "raw", 0, []
    _require(len({s.id for s in config.steps}) == len(config.steps), "duplicate_candidate_step_id")
    for node in nodes:
        _require(index < len(config.steps), "candidate_recipe_step_count_mismatch")
        step = config.steps[index]
        index += 1
        _require(step.input == previous, "candidate_is_not_a_single_continuous_chain")
        _require(node["operator"] in _OP_NAMES and (step.unit_id, step.op) == _OP_NAMES[node["operator"]],
                 "candidate_recipe_operation_mismatch")
        _require(all(step.params.get(k) == v for k, v in node.get("parameters", {}).items()),
                 "candidate_recipe_frozen_parameters_mismatch")
        mapped.append((node, step))
        if node["operator"] == "detect_bad_channels":
            _require(index < len(config.steps), "candidate_diagnostic_mark_missing")
            mark = config.steps[index]
            index += 1
            cap = next((n["parameters"]["max_fraction"] for n in nodes
                        if n["operator"] == "interpolate_bad_channels"), 0.25)
            _require(mark.id == step.id + "m" and mark.input == previous
                     and mark.decision_from == step.id
                     and (mark.unit_id, mark.op) == ("EEG-BAD-CHANNEL-MARK", "mark_channels")
                     and mark.params == {"max_fraction": cap}, "candidate_diagnostic_mark_mismatch")
            mapped.append((node, mark))
            previous = mark.id
        else:
            previous = step.id
    _require(index == len(config.steps), "candidate_recipe_step_count_mismatch")
    _require(config.output == previous, "candidate_output_chain_mismatch")
    return mapped


def _data_chain(config):
    steps = {s.id: s for s in config.steps}
    chain, current = [], config.output
    while current != "raw":
        _require(current in steps and current not in {s.id for s in chain}, "invalid_candidate_data_chain")
        chain.append(steps[current])
        current = steps[current].input
    return list(reversed(chain))


def _recipe(config, entry):
    """Bind frozen user parameters to actual executed steps, not signal spectra."""
    _recipe_steps(config, entry)
    epochs = [i for i, s in enumerate(config.steps) if s.op == "epoch"]
    _require(len(epochs) == 1, "unique_epoch_boundary_required")
    return epochs[0]


def _artifacts(root, item, config, plan, panel, entry):
    _require(item["status"] == "completed", "record_not_completed")
    _require(item["method_id"] == config.method_ref.id, "record_method_mismatch")
    entries = item["result"]["artifacts"]
    _require(len({a["name"] for a in entries}) == len(entries), "duplicate_artifact_name")
    _require(len({a["path"] for a in entries}) == len(entries), "duplicate_artifact_path")
    paths = {}
    # Hash all declared artifacts, including continuous FIFF split parts and logs.
    for artifact in entries:
        path = within(root, artifact["path"])
        _require(file_hash(path) == artifact["sha256"], "artifact_checksum_mismatch")
        paths[artifact["name"]] = path
    _require({"signal_V.npy", "events.json", "delta.json", "provenance.json", "data-epo.fif"} <= paths.keys(),
             "required_quality_artifact_missing")
    provenance, delta, rows = (_read(paths[k]) for k in ("provenance.json", "delta.json", "events.json"))
    _require(delta == item["result"]["delta"], "delta_result_mismatch")
    for key, expected in (("input_ref", plan.request.input_ref.model_dump()),
                          ("method_ref", config.method_ref.model_dump()),
                          ("engine_sha256", plan.engine_sha256)):
        _require(provenance[key] == expected, "provenance_" + key + "_mismatch")
    boundary = _recipe(config, entry)
    logs = [log for log in provenance["steps"] if log["branch"] == "main"]
    _require(len(logs) == len(config.steps), "provenance_steps_mismatch")
    for log, step in zip(logs, config.steps):
        _require((log["step_id"], log["unit_id"], log["op"]) == (step.id, step.unit_id, step.op),
                 "provenance_operation_mismatch")
        from .graph_evaluation import check_log
        _require(check_log(log, step),
                 "provenance_parameters_mismatch")
    contract, after = panel["output_contract"], delta["after"]
    _require(after["kind"] == "epochs" and after["unit"] == "V", "genuine_physical_voltage_epochs_required")
    _require(after["channels"] == contract["channels"] and after["sfreq"] == contract["sfreq"]
             and after["types"] == ["eeg"] * len(contract["channels"]), "output_channel_rate_contract_mismatch")
    _require(not any(s.op in {"csd", "surface_laplacian"} for s in config.steps),
             "voltage_to_csd_unit_change_not_supported")
    epoch = config.steps[boundary]
    window=config.evaluation_window.model_dump() if config.evaluation_window else epoch.params
    _require(all(window[k] == contract[k] for k in ("tmin", "tmax"))
             and epoch.params["picks"] == contract["channels"]
             and epoch.params["event_id"] == panel["event_codes"], "frozen_epoch_contract_mismatch")
    frozen = {t["event_id"]: t for t in panel["trials"] if t["record_id"] == config.record_id}
    _require(len({r["event_id"] for r in rows}) == len(rows), "duplicate_original_trial_id")
    _require({r["event_id"] for r in rows} == set(frozen), "original_event_inventory_mismatch")
    kept = []
    for row in rows:
        trial = frozen[row["event_id"]]
        _require(row["label"] == trial["label"] and row["code"] == panel["event_codes"][trial["label"]]
                 and row["original_sample"] == trial["source_sample"]
                 and row["output_sample"] == trial["output_sample"]
                 and row["output_sfreq"] == contract["sfreq"], "original_event_identity_mismatch")
        _require(type(row["retained"]) is bool, "retention_must_be_boolean")
        # All eligible trials are fixed; dropping one invalidates this record.
        _require(row["retained"] == trial["eligible"], "eligible_trial_retention_mismatch")
        if row["retained"]:
            _require(type(row["epoch_index"]) is int, "epoch_index_must_be_integer")
            kept.append(row)
        else:
            _require(row["epoch_index"] is None, "dropped_trial_has_epoch_index")
    kept.sort(key=lambda r: r["epoch_index"])
    _require([r["epoch_index"] for r in kept] == list(range(len(kept))), "epoch_index_inventory_mismatch")
    _require(delta["events_before"] == len(rows) and delta["events_retained"] == len(kept),
             "event_denominator_mismatch")
    shape = (len(kept), len(contract["channels"]), contract["n_times"])
    _require(after["shape"] == list(shape), "signal_declared_shape_mismatch")
    return paths, provenance, delta, kept, shape, boundary


def _check_signal_fiff(paths, kept, shape, panel, delta):
    """Check actual NPY rows against FIFF events and physical data in small batches."""
    import mne
    from mne._fiff.constants import FIFF
    contract = panel["output_contract"]
    epochs = mne.read_epochs(paths["data-epo.fif"], preload=False, verbose="ERROR")
    try:
        times = np.arange(contract["epoch_start_offset"], contract["epoch_end_offset"]+1) / contract["sfreq"]
        _require(epochs.ch_names == contract["channels"]
                 and epochs.info["sfreq"] == contract["sfreq"]
                 and epochs.get_channel_types() == ["eeg"]*len(contract["channels"])
                 and all(ch["unit"] == FIFF.FIFF_UNIT_V for ch in epochs.info["chs"])
                 and epochs.times.shape == times.shape
                 and np.allclose(epochs.times, times, rtol=0, atol=1e-12),
                 "fiff_output_grid_mismatch")
        _require(np.array_equal(epochs.events, [[r["output_sample"], 0, r["code"]] for r in kept])
                 and epochs.selection.tolist() == delta["after"]["epoch_selection"],
                 "fiff_epoch_identity_mismatch")
        with _mapped(paths["signal_V.npy"]) as values:
            _require(values.dtype.kind in "fiu" and values.shape == shape, "signal_shape_or_dtype_mismatch")
            for start in range(0, len(kept), 16):
                part = epochs[start:start+16].get_data()
                _require(np.allclose(values[start:start+16], part,
                                     rtol=2*np.finfo(np.float32).eps, atol=1e-18, equal_nan=True),
                         "signal_V_does_not_match_fiff_epoch_rows")
    finally:
        for backing in getattr(epochs, "_raw", []) or []:
            backing.fid.close()


def _source(plan, record, panel):
    """Use the existing BIDS unit/event-validated reader; no writes or fitting."""
    root = Path(plan.input_snapshot.collection.root)
    validate_record_files(root, record)
    raw, events, mapping = read_record(root, record, plan.input_snapshot.survey.event_id,
                                       plan.input_snapshot.survey.context_event_id)
    try:
        _require(raw.first_samp == 0, "panel_requires_uncropped_zero_origin_source")
        frozen = {t["event_id"]: t for t in panel["trials"] if t["record_id"] == record.id}
        _require(len(mapping) == len(frozen) and {r["event_id"] for r in mapping} == set(frozen),
                 "source_event_inventory_mismatch")
        for row in mapping:
            t = frozen[row["event_id"]]
            _require(row["original_sample"] == t["source_sample"] and row["label"] == t["label"],
                     "source_event_panel_mismatch")
        metadata = _read(within(root, record.bids_path).with_suffix(".json"))
        return raw, mapping, metadata
    except Exception:
        raw.close()
        raise


def _history(raw, metadata, config=None, entry=None):
    """Acquisition metadata and frozen operations, never a PSD-based estimate."""
    lo, hi = float(raw.info["highpass"]), float(raw.info["lowpass"])
    source_unknown = any(metadata.get(key, "n/a") == "n/a"
                         for key in ("SoftwareFilters", "HardwareFilters"))
    notches, operations = [], []
    if config is not None:
        for node, step in _recipe_steps(config, entry):
            operations.append({"operator": node["operator"], "step_id": step.id,
                               "unit_id": step.unit_id, "op": step.op,
                               "frozen_parameters": deepcopy(step.params)})
            if step.op in {"filter", "butter"}:
                if step.params.get("l_freq") is not None:
                    lo = max(lo, float(step.params["l_freq"]))
                if step.params.get("h_freq") is not None:
                    hi = min(hi, float(step.params["h_freq"]))
            if step.op == "resample":
                hi = min(hi, float(step.params["sfreq"]) / 2)
            if step.op in {"notch", "sine_regression", "zapline"}:
                frequencies = step.params.get("freqs", step.params.get("line_freq", []))
                if isinstance(frequencies, (float, int)):
                    frequencies = [frequencies]
                notches.extend(float(f) for f in frequencies)
    return {"nominal_band_hz": [lo, hi], "notch_centers_hz": notches,
            "source_filter_metadata_incomplete": source_unknown,
            "raw_reader_info_is_not_hardware_calibration": True,
            "source_software_filters": metadata.get("SoftwareFilters"),
            "source_hardware_filters": metadata.get("HardwareFilters"),
            "mains_hz": metadata.get("PowerLineFrequency"), "operations": operations,
            "candidate_recipe_hash": digest(entry["recipe"]) if entry else None,
            "reference": metadata.get("EEGReference"), "bandwidth_inferred_from_signal": False}


def _gate(report, history, trial_ids=None):
    bounds = history.get("nominal_band_hz") if history else None
    notches = history.get("notch_centers_hz", []) if history else []
    bands = {"mu_mean_psd": (8, 12), "beta_mean_psd": (13, 30),
             "erds_mu": (8, 12), "erds_beta": (13, 30), "emg_hf_proxy": (1, 45),
             "line_ratio_50hz": (47, 53), "line_ratio_60hz": (57, 63),
             "drift_power_ratio": (0.1, 30)}
    for m in report["metrics"]:
        mid = m["metricID"]
        m.update(selection_role="proxy_observation", limitations=list(_LIMITATIONS[:3]),
                 applicability="available" if m["status"] in {"ok", "partial"} else "unavailable")
        m["details"]["history"] = history
        if trial_ids is not None:
            m["denominator"]["original_trial_ids"] = trial_ids
        if mid in bands:
            lo, hi = bands[mid]
            if bounds is None:
                _unavailable(m, "filter_history_unavailable")
            elif bounds[0] > lo or bounds[1] < hi:
                _unavailable(m, "frozen_filter_history_does_not_cover_metric_band")
            elif any(lo <= f <= hi for f in notches):
                _unavailable(m, "prior_line_suppression_intersects_metric_band")
        if mid == "drift_slope" and bounds and bounds[0] > 0.1:
            _unavailable(m, "prior_highpass_prevents_native_drift_assessment")
        if mid in _RESIDUAL and history and history["source_filter_metadata_incomplete"]:
            _unavailable(m, "acquisition_filter_history_incomplete_for_residual_proxy")
        if history and history["source_filter_metadata_incomplete"]:
            m["limitations"].append("Acquisition filters incomplete; sampled-band power/ERDS is descriptive, not recovered bandwidth.")
    report["metadata"].update(history=history, measurement_view="native_not_common_filtered",
                              subject_selection_constraint=False)
    return report


def _positions(raw, channels):
    montage = raw.get_montage()
    if montage is None:
        return None
    p = montage.get_positions()["ch_pos"]
    if not all(name in p and np.isfinite(p[name]).all() for name in channels):
        return None
    return {name: p[name] for name in channels}


def _bad_overlap(raw, start, stop):
    lo, hi = start / raw.info["sfreq"], stop / raw.info["sfreq"]
    for a in raw.annotations:
        if a["description"].lower().startswith(("bad", "edge", "boundary")):
            onset = float(a["onset"]) - raw.first_time
            end = onset + float(a["duration"])
            if (onset < hi and end > lo) or (onset == end and lo <= onset < hi):
                return True
    return False


def _segments(raw, rows, channels, offsets, *, sample_key, original_mapping=None,
              task_tmax=0.0, baseline=False):
    fs = float(raw.info["sfreq"])
    a, b = offsets
    _require(b > a, "invalid_extraction_window")
    values = np.full((len(rows), len(channels), b-a), np.nan)
    audit = []
    for i, row in enumerate(rows):
        sample = row[sample_key]
        start, stop = sample - raw.first_samp + a, sample - raw.first_samp + b
        reason = None
        if start < 0 or stop > raw.n_times:
            reason = "precue_outside_record" if baseline else "task_outside_source_record"
        elif _bad_overlap(raw, start, stop):
            reason = "annotation_intersects_measurement_window"
        if baseline and original_mapping is not None and reason is None:
            # Task exclusions use original native event time/duration, including
            # common-invalid events. The preceding task cannot become "rest".
            # Use actual quantized output samples, not an unrounded source cue.
            lo, hi = (sample+a)/fs, (sample+b)/fs
            for event in original_mapping:
                task_start = event["original_onset_s"]
                event_duration = float(event.get("duration_s", 0))
                if task_start < hi and event_duration <= 0:
                    reason = "precue_rest_unverified_zero_duration_prior_task"
                    break
                task_end = task_start + max(event_duration, task_tmax, 0)
                if (task_start < hi and task_end > lo) or (lo <= task_start < hi):
                    reason = "precue_overlaps_original_task_event"
                    break
        if reason is None:
            data = raw.get_data(picks=channels, start=start, stop=stop)
            if np.isfinite(data).all():
                values[i] = data
            else:
                reason = "nonfinite_measurement_window"
        audit.append({"event_id": row["event_id"], "epoch_index": i,
                      "start_sample_in_raw": start, "stop_sample_in_raw": stop,
                      "absolute_sample_time_seconds": [(sample+a)/fs, (sample+b)/fs],
                      "status": "ok" if reason is None else "not_applicable", "reason": reason})
    return values, audit


def _post_reference(data, raw, channels, steps):
    """Replay ONLY MNE average reference on the epoch-selected EEG set."""
    if not steps:
        return data
    import mne
    for step in steps:
        _require(step.op == "reference" and step.unit_id == "EEG-REREFERENCE"
                 and step.params == {"ref_channels": "average"}, "unsupported_postepoch_operation")
    good = np.isfinite(data).all(axis=(1, 2))
    out = data.copy()
    if good.any():
        info = mne.pick_info(raw.info, [raw.ch_names.index(n) for n in channels], copy=True)
        epochs = mne.EpochsArray(data[good], info, baseline=None, proj=False, verbose="ERROR")
        for _ in steps:
            epochs.set_eeg_reference(ref_channels="average", projection=False, verbose="ERROR")
        out[good] = epochs.get_data()
    return out


def _post_epoch_windows(task, baseline, context, times, raw, channels, steps):
    """Apply each source epoch offset to both scoring and cue-paired rest.

    Baseline means come from the complete source epoch, never the cropped
    scoring window or the independent pre-cue measurement window.
    """
    for step in steps:
        if step.op == "reference":
            task, baseline, context = (
                _post_reference(values, raw, channels, [step])
                for values in (task, baseline, context))
        else:
            _require(step.op == "baseline" and step.unit_id == "EEG-BASELINE",
                     "unsupported_postepoch_operation")
            window = step.params.get("baseline")
            if window is None:
                continue
            _require(isinstance(window, (list, tuple)) and len(window) == 2,
                     "invalid_source_baseline_window")
            lo, hi = window
            lo = times[0] if lo is None else float(lo)
            hi = times[-1] if hi is None else float(hi)
            _require(times[0] - 1e-12 <= lo <= hi <= times[-1] + 1e-12,
                     "source_baseline_outside_context")
            mask = (times >= lo - 1e-12) & (times <= hi + 1e-12)
            _require(mask.any(), "empty_source_baseline_window")
            offset = context[:, :, mask].mean(axis=-1, keepdims=True)
            task, baseline, context = (values - offset for values in (task, baseline, context))
    return task, baseline


def _measure(values, fs, channels, history, *, baseline=None, trial_ids=None, positions=None,
             baseline_audit=None):
    from .quality_diagnostics import diagnostic_views
    if not len(values) or not np.isfinite(values).all(axis=(1, 2)).any():
        return _gate(_empty("no_available_measurement_epochs"), history, trial_ids)
    report = evaluate_quality(values, fs, channels, baseline_epochs_V=baseline,
                              montage_positions=positions).model_dump(mode="json")
    report["metadata"]["diagnostic_views"] = diagnostic_views(values, fs, channels, positions, trial_ids)
    from .neural_signal import task_tfr
    report["metadata"]["neural_tfr"] = task_tfr(values, baseline, fs, channels, trial_ids, history)
    if baseline_audit is not None:
        for m in report["metrics"]:
            if m["metricID"].startswith("erds_"):
                m["details"].update(baseline_interval_seconds=list(PRECUE_SECONDS),
                                     baseline_stop_exclusive=True, baseline_audit=baseline_audit,
                                     paired_original_trial_ids=trial_ids)
                if not any(a["status"] == "ok" for a in baseline_audit):
                    _unavailable(m, "no_precue_with_valid_support_and_matching_processing")
    return _gate(report, history, trial_ids)


def _continuous(paths, provenance, config, boundary, shape, kept, panel, mapping):
    """Verify saved pre-epoch state and verify post-ref task against exact NPY."""
    import mne
    _require("continuous-raw.fif" in paths, "same_processed_continuous_artifact_unavailable")
    meta = provenance.get("continuous_raw")
    _require(isinstance(meta, dict), "continuous_raw_provenance_unavailable")
    epoch = config.steps[boundary]
    _require(meta.get("before_epoch_step_id") == epoch.id
             and meta.get("source_node_id") == epoch.input and meta.get("unit") == "V",
             "continuous_epoch_provenance_mismatch")
    _require(meta.get("file") == "continuous-raw.fif"
             and meta.get("sha256") == file_hash(paths["continuous-raw.fif"])
             and meta.get("bytes") == paths["continuous-raw.fif"].stat().st_size,
             "continuous_snapshot_hash_binding_mismatch")
    chain = _data_chain(config)
    position = next(i for i, step in enumerate(chain) if step.id == epoch.id)
    post = chain[position+1:]
    _require(meta.get("pre_epoch_step_ids") == [s.id for s in chain[:position]]
             and meta.get("post_epoch_step_ids") == [s.id for s in post]
             and meta.get("post_epoch_steps") == [s.model_dump(mode="json") for s in post]
             and meta.get("post_epoch_operations_applied") is False,
             "continuous_snapshot_pipeline_mismatch")
    log = next(s for s in provenance["steps"] if s["branch"] == "main" and s["step_id"] == epoch.id)
    _require(meta.get("source_data_hash") == log.get("input_hash") and bool(meta.get("source_data_hash")),
             "continuous_snapshot_input_hash_mismatch")
    frozen = sorted((t for t in panel["trials"] if t["record_id"] == config.record_id),
                    key=lambda t: t["source_row"])
    _require(meta.get("target_events") == [[t["output_sample"], 0, panel["event_codes"][t["label"]]] for t in frozen],
             "continuous_snapshot_event_inventory_mismatch")
    _require(all((s.op == "reference" and s.unit_id == "EEG-REREFERENCE"
                 and s.params == {"ref_channels": "average"})
                 or (s.op == "baseline" and s.unit_id == "EEG-BASELINE") for s in post),
             "unsupported_postepoch_operation")
    raw = mne.io.read_raw_fif(paths["continuous-raw.fif"], preload=False, verbose="ERROR")
    try:
        contract, channels = panel["output_contract"], panel["output_contract"]["channels"]
        _require(raw.info["sfreq"] == contract["sfreq"]
                 and all(n in raw.ch_names for n in channels) and not raw.info["projs"],
                 "continuous_channel_rate_projection_mismatch")
        _require(raw.first_samp == meta.get("first_sample")
                 and raw.info["sfreq"] == meta.get("sfreq")
                 and raw.ch_names == meta.get("channels"), "continuous_state_metadata_mismatch")
        task, task_audit = _segments(raw, kept, channels,
                                     (contract["epoch_start_offset"], contract["epoch_end_offset"]+1),
                                     sample_key="output_sample")
        baseline, audit = _segments(raw, kept, channels,
                                    tuple(round(t*contract["sfreq"]) for t in PRECUE_SECONDS),
                                    sample_key="output_sample", original_mapping=mapping,
                                    task_tmax=max(0, contract["tmax"]), baseline=True)
        start, stop = (round(float(epoch.params[key]) * contract["sfreq"])
                       for key in ("tmin", "tmax"))
        context, _ = _segments(raw, kept, channels, (start, stop + 1), sample_key="output_sample")
        times = np.arange(start, stop + 1) / contract["sfreq"]
        task, baseline = _post_epoch_windows(task, baseline, context, times, raw, channels, post)
        with _mapped(paths["signal_V.npy"]) as observed:
            _require(task.shape == shape and np.isfinite(task).all()
                     and np.allclose(task, observed, rtol=2*np.finfo(np.float32).eps, atol=1e-18),
                     "continuous_reextracted_task_does_not_match_signal_V")
        return raw, baseline, audit, post
    except Exception:
        raw.close()
        raise


def _reduce(report):
    """Full curves remain in detail. Aggregate each metric on its named axes."""
    out = {}
    for m in report["metrics"]:
        mid = m["metricID"]
        r = {k: deepcopy(m[k]) for k in ("metricID", "unit", "direction", "status", "reason", "formula")}
        r.update(value=None, axes={}, denominator=deepcopy(m["denominator"]),
                 selection_role="proxy_observation", limitations=deepcopy(m.get("limitations", [])))
        if m["value"] is not None:
            a = np.asarray(m["value"], dtype=float)
            r["denominator"]["finite_values_before_reduction"] = int(np.isfinite(a).sum())
            r["denominator"]["total_values_before_reduction"] = a.size
            if mid == "psd":
                # All included epochs are finite in quality.py. Keep frequency.
                a = np.mean(np.median(a, axis=1), axis=0)
            elif mid not in _CURVES:
                a = np.mean(a[np.isfinite(a)]) if np.isfinite(a).any() else None
            r["value"] = _json(a)
        if mid in {"psd", "psd_window_quantiles"}:
            r["axes"] = {"frequencies_hz": m["details"].get("frequencies_hz")}
            if mid == "psd_window_quantiles":
                r["axes"]["quantiles"] = [0.1, 0.5, 0.9]
        if mid in {"oha", "thv", "chv"}:
            r["axes"] = {"thresholds_uv": m["details"].get("thresholds_uv")}
        out[mid] = r
    return out


def _aggregate(members, level):
    """A missing member is visible in the fixed denominator, never a zero."""
    output = {}
    for mid in METRIC_IDS:
        rows = [(key, values[mid]) for key, values in members.items()]
        good = [(key, m) for key, m in rows if m["value"] is not None]
        first = (good or rows)[0][1]
        statuses = Counter(m["status"] for _, m in rows)
        value, reason, status = None, "no_available_members", "not_applicable"
        counts = None
        if good:
            compatible = all(m["unit"] == first["unit"] and m.get("axes", {}) == first.get("axes", {})
                             and np.shape(m["value"]) == np.shape(first["value"]) for _, m in good)
            if not compatible:
                reason, status = "measurement_axes_differ_no_interpolation_or_scalar_fallback", "not_comparable"
            else:
                a = np.asarray([m["value"] for _, m in good], dtype=float)
                counts = np.isfinite(a).sum(axis=0)
                value = np.divide(np.where(np.isfinite(a), a, 0).sum(axis=0), counts,
                                  out=np.full(a.shape[1:], np.nan), where=counts > 0)
                full = len(good) == len(rows) and all(m["status"] == "ok" for _, m in good)
                status, reason = ("ok", None) if full else ("partial", "incomplete_member_or_metric_coverage")
        elif any(m["status"] in {"not_computable", "failed"} for _, m in rows):
            status = "not_computable"
        output[mid] = {"metricID": mid, "value": _json(value), "unit": first["unit"],
                       "direction": first["direction"], "status": status, "reason": reason,
                       "formula": first["formula"], "axes": first.get("axes", {}),
                       "aggregation": "equal_" + level + "_mean",
                       "applicability": "available" if status == "ok" else "partial" if value is not None else "unavailable",
                       "selection_role": "proxy_observation", "limitations": list(_LIMITATIONS),
                       "denominator": {"expected_" + level: len(rows), "available_" + level: len(good),
                                       "expected_ids": [key for key, _ in rows],
                                       "available_ids": [key for key, _ in good],
                                       "finite_members_per_value": _json(counts),
                                       "status_counts": dict(statuses),
                                       "missing_reasons": {key: m["reason"] for key, m in rows if m["status"] != "ok"}}}
        if mid == "psd_window_quantiles":
            output[mid]["limitations"].append("Mean of record quantile curves; not quantiles of pooled windows.")
    return output


def _coverage(trials, *, available=0):
    eligible = sum(t["eligible"] for t in trials)
    return {"original_trials": len(trials), "eligible_trials": eligible,
            "available_trials": available, "missing_trials": eligible-available,
            "common_invalid_trials": len(trials)-eligible}


def evaluate_dataset_quality(plan, result, store_root, panel, candidate_entry, output_dir):
    """Return {summary, detail_artifacts, artifacts}; summary has all 25 metrics.

    Invalid frozen/global identities raise ValueError before output. Record-local
    failures are explicit artifacts and do not skip remaining records/subjects.
    Output data-quality.json contains the summary plus indexed record details.
    Baseline support comes only from verified same-processed continuous FIFF;
    its metadata contract is provenance.continuous_raw (see _continuous).
    """
    plan = plan if isinstance(plan, ExecutionPlan) else ExecutionPlan.model_validate(plan)
    result = result if isinstance(result, RunResult) else RunResult.model_validate(result)
    panel = panel.model_dump(mode="json") if hasattr(panel, "model_dump") else deepcopy(panel)
    entry = candidate_entry.model_dump(mode="json") if hasattr(candidate_entry, "model_dump") else deepcopy(candidate_entry)
    validate_panel(panel)
    _require(digest(plan.input_snapshot.model_dump(mode="json")) == panel["input_hash"], "plan_panel_input_hash_mismatch")
    _require(plan.request.input_ref.id == plan.request.input_ref.sha256 == panel["input_hash"],
             "plan_input_reference_hash_mismatch")
    _require(result.plan_ref.id == result.plan_ref.sha256 == digest(plan.model_dump(mode="json")), "result_plan_hash_mismatch")
    _require(isinstance(entry.get("recipe", {}).get("nodes"), list), "frozen_candidate_recipe_required")
    root, output = Path(store_root).resolve(), Path(output_dir).resolve()
    source_root = Path(plan.input_snapshot.collection.root).resolve()
    _require(not output.is_relative_to(source_root) and not source_root.is_relative_to(output),
             "quality_output_must_be_disjoint_from_source")
    # Prevent overwriting any existing candidate input artifacts, even when the
    # caller intentionally puts its evaluation output under the store root.
    input_paths = [within(root, a["path"]) for r in result.records
                   for a in r.get("result", {}).get("artifacts", [])]
    _require(not any(p.is_relative_to(output) for p in input_paths), "quality_output_contains_input_artifacts")
    records = {r.id: r for r in plan.input_snapshot.collection.records}
    config_groups = {}
    result_groups = {}
    for c in plan.records:
        config_groups.setdefault(c.record_id, []).append(c)
    for item in result.records:
        result_groups.setdefault(item["record_id"], []).append(item)
    subjects = sorted({r["subject"] for r in panel["records"].values()})
    bysubject, detail_artifacts = {}, []
    record_summaries = []
    for subject in subjects:
        reduced = {stage: {} for stage in STAGES}
        subject_records = []
        for rid in sorted(k for k, r in panel["records"].items() if r["subject"] == subject):
            trials = [t for t in panel["trials"] if t["record_id"] == rid]
            detail = {"schema_version": VERSION, "record_id": rid, "subject": subject,
                      "role": panel["records"][rid]["role"], "coverage": _coverage(trials),
                      "original_trials": trials, "stages": {s: _empty("stage_not_available") for s in STAGES},
                      "errors": {}, "limitations": list(_LIMITATIONS), "source_read_only": True,
                      "source_unchanged_verified": False}
            raw, continuous = None, None
            mapping, source_history, metadata = None, None, None
            paths, config, history = None, None, None
            channels, contract = panel["output_contract"]["channels"], panel["output_contract"]
            try:
                try:
                    _require(rid in records, "source_record_missing_from_snapshot")
                    raw, mapping, metadata = _source(plan, records[rid], panel)
                    source_history = _history(raw, metadata)
                    positions = _positions(raw, channels)
                    detail["source_files"] = records[rid].files
                    detail["stages"]["source_raw"] = _measure(raw.get_data(picks=channels)[None],
                                                                raw.info["sfreq"], channels, source_history,
                                                                positions=positions)
                    original = {r["event_id"]: r for r in mapping}
                    source_rows = [original[t["event_id"]] for t in trials if t["eligible"]]
                    ids = [r["event_id"] for r in source_rows]
                    fs = float(raw.info["sfreq"])
                    task, _ = _segments(raw, source_rows, channels,
                                         (round(contract["tmin"]*fs), round(contract["tmax"]*fs)+1),
                                         sample_key="original_sample")
                    base, audit = _segments(raw, source_rows, channels,
                                            tuple(round(t*fs) for t in PRECUE_SECONDS),
                                            sample_key="original_sample", original_mapping=mapping,
                                            task_tmax=max(0, contract["tmax"]), baseline=True)
                    detail["source_precue_audit"] = audit
                    detail["stages"]["source_task"] = _measure(task, fs, channels, source_history,
                                                                 baseline=base, trial_ids=ids,
                                                                 positions=positions, baseline_audit=audit)
                    detail["stages"]["source_precue"] = _measure(base, fs, channels, source_history,
                                                                   trial_ids=ids, positions=positions)
                    del task, base
                except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                    detail["errors"]["source"] = str(exc)
                    for s in ("source_raw", "source_task", "source_precue"):
                        detail["stages"][s] = _empty("source_validation_or_read_failed:" + str(exc))
                try:
                    _require(len(config_groups.get(rid, [])) == 1, "plan_record_missing_or_duplicate")
                    _require(len(result_groups.get(rid, [])) == 1, "result_record_missing_or_duplicate")
                    config, item = config_groups[rid][0], result_groups[rid][0]
                    paths, provenance, delta, kept, shape, boundary = _artifacts(root, item, config, plan, panel, entry)
                    _check_signal_fiff(paths, kept, shape, panel, delta)
                    history = _history(raw, metadata, config, entry) if raw is not None and metadata is not None else None
                    ids = [r["event_id"] for r in kept]
                    detail["epoch_order_original_trial_ids"] = ids
                    baseline, audit = None, None
                    try:
                        _require(mapping is not None and "source" not in detail["errors"], "original_source_event_lineage_unavailable")
                        continuous, baseline, audit, post = _continuous(paths, provenance, config, boundary,
                                                                         shape, kept, panel, mapping)
                        detail["processed_precue_audit"] = audit
                        detail["baseline_provenance"] = {"artifact": "continuous-raw.fif",
                                                         "sha256": file_hash(paths["continuous-raw.fif"]),
                                                         "same_task_reextraction_verified": True,
                                                         "postepoch_reference_steps": [s.id for s in post if s.op == "reference"],
                                                         "postepoch_baseline_steps": [s.model_dump(mode="json") for s in post if s.op == "baseline"],
                                                         "baseline_offset_source": "complete_source_epoch_paired_to_same_cue",
                                                         "precue_seconds": list(PRECUE_SECONDS),
                                                         "raw_source_precue_was_not_substituted": True}
                        positions = _positions(continuous, channels)
                        if any(s.op == "baseline" for s in post):
                            detail["stages"]["processed_continuous"] = _empty(
                                "trial_specific_baseline_has_no_unique_continuous_representation")
                        else:
                            full = _post_reference(continuous.get_data(picks=channels)[None], continuous, channels, post)
                            detail["stages"]["processed_continuous"] = _measure(full, contract["sfreq"], channels,
                                                                                 history, positions=positions)
                            del full
                        detail["stages"]["processed_precue"] = _measure(baseline, contract["sfreq"], channels,
                                                                         history, trial_ids=ids, positions=positions)
                    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                        detail["errors"]["processed_baseline"] = str(exc)
                        baseline, audit = None, None
                        for s in ("processed_continuous", "processed_precue"):
                            detail["stages"][s] = _empty(str(exc))
                    with _mapped(paths["signal_V.npy"]) as values:
                        _require(values.dtype.kind in "fiu" and values.shape == shape, "signal_shape_or_dtype_mismatch")
                        report = _measure(values, contract["sfreq"], channels, history, baseline=baseline,
                                          trial_ids=ids, positions=_positions(raw, channels) if raw is not None else None,
                                          baseline_audit=audit)
                        if baseline is None:
                            for m in report["metrics"]:
                                if m["metricID"].startswith("erds_"):
                                    _unavailable(m, detail["errors"].get("processed_baseline", "same_processed_baseline_unavailable"))
                        detail["stages"]["processed_task"] = report
                        detail["coverage"].update(_coverage(trials, available=len(kept)))
                        detail["coverage"]["finite_processed_trials"] = int(np.isfinite(values).all(axis=(1, 2)).sum())
                    detail["verified_artifacts"] = item["result"]["artifacts"]
                    del baseline
                except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                    detail["errors"]["processed"] = str(exc)
                    detail["stages"]["processed_task"] = _empty(str(exc), status="not_computable")
                if raw is not None:
                    try:
                        validate_record_files(source_root, records[rid])
                        detail["source_unchanged_verified"] = "source" not in detail["errors"]
                    except (OSError, ValueError) as exc:
                        detail["errors"]["source_postcheck"] = str(exc)
                        detail["stages"] = {s: _empty("source_changed_during_quality", status="not_computable") for s in STAGES}
                        detail["source_unchanged_verified"] = False
            finally:
                if raw is not None:
                    raw.close()
                if continuous is not None:
                    continuous.close()
            for stage in STAGES:
                report = detail["stages"][stage]
                _require({m["metricID"] for m in report["metrics"]} == set(METRIC_IDS), "quality_metric_inventory_mismatch")
                reduced[stage][rid] = _reduce(report)
            detail["status"] = "failed" if "processed" in detail["errors"] else "partial" if detail["errors"] else "evaluated"
            path = output / "quality-details" / (digest([subject, rid])[:20] + ".json")
            write_json(path, _json(detail))
            artifact = {"kind": "quality_record_detail", "path": path.relative_to(output).as_posix(),
                        "sha256": file_hash(path), "bytes": path.stat().st_size,
                        "record_id": rid, "subject": subject}
            detail_artifacts.append(artifact)
            record_summary = {k: deepcopy(detail[k]) for k in ("record_id", "subject", "role", "coverage", "status", "errors")}
            record_summary["detail_artifact"] = artifact
            record_summaries.append(record_summary)
            subject_records.append(record_summary)
            del detail
        stage_means = {stage: _aggregate(members, "records") for stage, members in reduced.items()}
        bysubject[subject] = {"subject": subject, "records": subject_records,
                              "coverage": {key: sum(r["coverage"].get(key, 0) for r in subject_records)
                                           for key in _coverage([])},
                              "metrics": stage_means["processed_task"], "stages": stage_means}
    stages = {stage: _aggregate({s: bysubject[s]["stages"][stage] for s in subjects}, "subjects") for stage in STAGES}
    summary = {"schema_version": VERSION, "candidate_id": entry.get("id"),
               "candidate_recipe_hash": digest(entry["recipe"]), "panel_hash": panel["panel_hash"],
               "input_hash": panel["input_hash"], "plan_hash": result.plan_ref.sha256,
               "status": "evaluated" if all(r["status"] == "evaluated" for r in record_summaries) else "partial",
               "metrics": stages["processed_task"], "bysubject": bysubject, "stages": stages,
               "coverage": {"subjects_expected": len(subjects), "subjects_visited": len(bysubject),
                            "records_expected": len(panel["records"]), "records_visited": len(record_summaries),
                            "records_verified": sum("processed" not in r["errors"] for r in record_summaries),
                            **{k: sum(r["coverage"].get(k, 0) for r in record_summaries) for k in _coverage([])}},
               "unexpected_result_records": sorted(set(result_groups)-set(panel["records"])),
               "unexpected_plan_records": sorted(set(config_groups)-set(panel["records"])),
               "run_status": result.status,
               "aggregation": "native_record_means_then_equal_subject_means; missing members explicit",
               "metric_count": len(METRIC_IDS), "composite_score": None,
               "limitations": list(_LIMITATIONS), "precue_seconds": list(PRECUE_SECONDS),
               "detail_artifacts": detail_artifacts,
               "memory_policy": "one_record_arrays; reduced_subject_metrics; no all_subject_signal_stack"}
    path = output / "data-quality.json"
    write_json(path, _json(summary))
    artifact = {"kind": "quality_summary", "path": path.name, "sha256": file_hash(path), "bytes": path.stat().st_size}
    return {"summary": summary, "detail_artifacts": detail_artifacts, "artifacts": [artifact, *detail_artifacts]}
