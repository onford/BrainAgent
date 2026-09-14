from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
import platform
import shutil
import tempfile
from typing import Any

from app.preprocessing.storage import canonical, file_hash, write_json

from .schemas import InvasiveExecutionPlan, NeuroDatasetSnapshot


def _dependencies():
    try:
        import h5py
        import numpy as np
    except ImportError as exc:  # pragma: no cover
        raise ImportError("invasive execution requires the 'invasive' extra (h5py and numpy)") from exc
    return h5py, np


def _decode(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value.item() if hasattr(value, "item") else value


def _source_is_unchanged(snapshot: NeuroDatasetSnapshot, path: Path) -> None:
    stat = path.stat()
    source = snapshot.source
    if stat.st_size != source.size_bytes or stat.st_mtime_ns != source.modified_ns:
        raise ValueError("NWB source size or modification time changed after Survey")
    if source.sha256 and file_hash(path) != source.sha256:
        raise ValueError("NWB source hash changed after Survey")


def _time_values(group, count: int):
    _, np = _dependencies()
    timestamps = group.get("timestamps")
    if timestamps is not None:
        return np.asarray(timestamps[:], dtype=np.float64)
    starting = group.get("starting_time")
    if starting is None or starting.attrs.get("rate") is None:
        raise ValueError(f"TimeSeries {group.name} has neither timestamps nor starting_time/rate")
    return float(starting[()]) + np.arange(count, dtype=np.float64) / float(starting.attrs["rate"])


def _check_time(name: str, values) -> dict[str, Any]:
    _, np = _dependencies()
    values = np.asarray(values, dtype=np.float64)
    finite = np.isfinite(values)
    differences = np.diff(values[finite])
    monotonic = bool(np.all(differences > 0))
    nondecreasing = bool(np.all(differences >= 0))
    gaps = []
    if differences.size:
        median = float(np.median(differences))
        if median > 0:
            locations = np.flatnonzero(differences > median * 5)
            gaps = [
                {"after_index": int(index), "duration_s": float(differences[index])}
                for index in locations[:100]
            ]
    return {
        "name": name,
        "count": int(values.size),
        "finite_fraction": float(finite.mean()) if values.size else 1.0,
        "strictly_monotonic": monotonic,
        "monotonic_nondecreasing": nondecreasing,
        "start_s": float(values[0]) if values.size and finite[0] else None,
        "stop_s": float(values[-1]) if values.size and finite[-1] else None,
        "gaps": gaps,
    }


def _read_units(root):
    _, np = _dependencies()
    units = root.get("units")
    if units is None or units.get("spike_times") is None or units.get("spike_times_index") is None:
        raise ValueError("execution requires NWB Units/spike_times and spike_times_index")
    flat = np.asarray(units["spike_times"][:], dtype=np.float64)
    stops = np.asarray(units["spike_times_index"][:], dtype=np.int64)
    if stops.ndim != 1 or (stops.size and (np.any(np.diff(stops) < 0) or stops[-1] != flat.size)):
        raise ValueError("NWB Units spike_times_index is invalid")
    ids = np.asarray(units["id"][:]) if units.get("id") is not None else np.arange(stops.size)
    if ids.size != stops.size or len({_decode(value) for value in ids}) != ids.size:
        raise ValueError("NWB unit ids must be present, stable and unique")
    quality = None
    if units.get("quality") is not None and units["quality"].shape == ids.shape:
        quality = [_decode(value) for value in units["quality"][:]]
    starts = np.concatenate(([0], stops[:-1]))
    spikes = [flat[start:stop] for start, stop in zip(starts, stops, strict=True)]
    return ids, spikes, quality


def _unit_qc(ids, spikes, quality, plan: InvasiveExecutionPlan, start_s: float, stop_s: float):
    _, np = _dependencies()
    p = plan.qc
    duration = max(stop_s - start_s, np.finfo(float).eps)
    rows = []
    retained = []
    cleaned = []
    accepted_quality = {value.casefold() for value in p.accepted_upstream_quality}
    threshold_crossings = plan.input_representation == "threshold_crossings"
    edges = np.linspace(start_s, stop_s, p.stability_bins + 1)
    for index, (unit_id, raw) in enumerate(zip(ids, spikes, strict=True)):
        finite = np.isfinite(raw)
        values = np.sort(raw[finite])
        differences = np.diff(values)
        firing_rate = float(values.size / duration)
        isi_ratio = float(np.mean(differences < p.isi_refractory_period_s)) if differences.size else 0.0
        counts = np.histogram(values, bins=edges)[0] if stop_s > start_s else np.zeros(p.stability_bins)
        presence = float(np.mean(counts > 0))
        mean_count = float(counts.mean())
        stability_cv = float(counts.std() / mean_count) if mean_count else None
        reasons = []
        if firing_rate < p.min_firing_rate_hz:
            reasons.append(f"firing_rate<{p.min_firing_rate_hz:g}Hz")
        if not threshold_crossings and isi_ratio > p.max_isi_violation_ratio:
            reasons.append(f"isi_violation_ratio>{p.max_isi_violation_ratio:g}")
        if presence < p.min_presence_ratio:
            reasons.append(f"presence_ratio<{p.min_presence_ratio:g}")
        upstream = quality[index] if quality is not None else None
        if p.use_upstream_quality and upstream is not None and str(upstream).casefold() not in accepted_quality:
            reasons.append(f"upstream_quality={upstream}")
        if not finite.all():
            reasons.append("nonfinite_spike_times")
        monotonic = bool(np.all(np.diff(raw[finite]) >= 0))
        if not threshold_crossings and not monotonic:
            reasons.append("nonmonotonic_spike_times")
        keep = not reasons
        rows.append(
            {
                "unit_id": _decode(unit_id),
                "source_index": index,
                "spike_count": int(values.size),
                "firing_rate_hz": firing_rate,
                "isi_violation_ratio": isi_ratio,
                "isi_metric_applicable": not threshold_crossings,
                "presence_ratio": presence,
                "stability_cv": stability_cv,
                "upstream_quality": upstream,
                "source_order_normalized": bool(threshold_crossings and not monotonic),
                "retained": keep,
                "reasons": reasons or ["passed_configured_qc"],
            }
        )
        if keep:
            retained.append(index)
            cleaned.append(values)
    return rows, retained, cleaned


def _choose_bounds(spikes, trials, target_times):
    _, np = _dependencies()
    candidates = [values for values in spikes if values.size]
    if trials is not None and trials[0].size:
        return float(np.min(trials[0])), float(np.max(trials[1]))
    if target_times is not None and target_times.size:
        return float(target_times[0]), float(target_times[-1])
    if candidates:
        return float(min(values[0] for values in candidates)), float(max(values[-1] for values in candidates))
    raise ValueError("cannot determine a finite processing interval")


def _read_trials(root):
    _, np = _dependencies()
    group = root.get("intervals/trials")
    if group is None or group.get("start_time") is None or group.get("stop_time") is None:
        return None
    starts = np.asarray(group["start_time"][:], dtype=np.float64)
    stops = np.asarray(group["stop_time"][:], dtype=np.float64)
    if starts.shape != stops.shape or not np.isfinite(starts).all() or not np.isfinite(stops).all() or np.any(stops <= starts):
        raise ValueError("trial start/stop times are invalid")
    return starts, stops


def _select_target(root, snapshot: NeuroDatasetSnapshot, requested: str | None):
    _, np = _dependencies()
    candidates = [item for item in snapshot.collections if item.representation in {"behavior", "stimulus"}]
    if requested:
        selected = [
            item
            for item in candidates
            if item.path == requested
            or item.path.startswith(requested.rstrip("/") + "/")
        ]
    else:
        emg = [item for item in candidates if "/preprocessed_emg/" in item.path.lower()]
        selected = emg if emg else candidates[:1]
    if not selected:
        return None, None, None
    arrays = []
    reference_times = None
    used_paths = []
    for collection in selected:
        data = root.get(collection.path)
        if data is None or not np.issubdtype(data.dtype, np.number):
            continue
        values = np.asarray(data[:], dtype=np.float64)
        if values.ndim == 1:
            values = values[:, None]
        elif values.ndim > 2:
            continue
        times = _time_values(data.parent, values.shape[0])
        if reference_times is None:
            reference_times = times
        elif times.shape != reference_times.shape or not np.allclose(times, reference_times, rtol=0, atol=1e-9):
            raise ValueError("selected target TimeSeries do not share an aligned timebase")
        arrays.append(values)
        used_paths.append(collection.path)
    if not arrays:
        return requested or selected[0].path, None, None
    label = requested or (
        "/acquisition/preprocessed_emg"
        if len(used_paths) > 1 and all("/preprocessed_emg/" in path.lower() for path in used_paths)
        else used_paths[0]
    )
    return label, reference_times, np.concatenate(arrays, axis=1)


def _evaluation_mask(root, snapshot: NeuroDatasetSnapshot, centers):
    _, np = _dependencies()
    collection = next(
        (item for item in snapshot.collections if item.representation == "mask"),
        None,
    )
    if collection is None:
        return None, None
    data = root.get(collection.path)
    if data is None or data.ndim != 1:
        return None, None
    values = np.asarray(data[:], dtype=bool)
    times = _time_values(data.parent, values.size)
    check = _check_time(collection.path, times)
    if not check["strictly_monotonic"] or check["finite_fraction"] != 1.0:
        raise ValueError("evaluation mask timestamps must be finite and strictly monotonic")
    indices = np.searchsorted(times, centers)
    indices = np.clip(indices, 0, times.size - 1)
    prior = np.maximum(indices - 1, 0)
    choose_prior = np.abs(centers - times[prior]) <= np.abs(times[indices] - centers)
    indices[choose_prior] = prior[choose_prior]
    covered = (centers >= times[0]) & (centers <= times[-1])
    aligned = np.zeros(centers.size, dtype=bool)
    aligned[covered] = values[indices[covered]]
    check["true_count_aligned"] = int(aligned.sum())
    check["false_count_aligned"] = int((~aligned & covered).sum())
    check["covered_fraction"] = float(covered.mean())
    return aligned, check


def _bin_spikes(spikes, start_s: float, stop_s: float, bin_size_s: float, max_bytes: int):
    _, np = _dependencies()
    bins = int(math.ceil((stop_s - start_s) / bin_size_s))
    if bins <= 0:
        raise ValueError("processing interval produces no bins")
    required = bins * len(spikes) * 4
    if required > max_bytes:
        raise ValueError(f"requested T×N matrix needs {required} bytes, above max_matrix_bytes={max_bytes}")
    edges = start_s + np.arange(bins + 1, dtype=np.float64) * bin_size_s
    matrix = np.empty((bins, len(spikes)), dtype=np.float32)
    for column, values in enumerate(spikes):
        matrix[:, column] = np.histogram(values, bins=edges)[0]
    centers = edges[:-1] + bin_size_s / 2
    return centers, matrix


def _smooth(matrix, sigma_s: float | None, bin_size_s: float):
    _, np = _dependencies()
    if sigma_s is None or matrix.shape[1] == 0:
        return matrix
    sigma = sigma_s / bin_size_s
    radius = max(1, int(math.ceil(4 * sigma)))
    grid = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (grid / sigma) ** 2)
    kernel /= kernel.sum()
    return np.stack([np.convolve(matrix[:, i], kernel, mode="same") for i in range(matrix.shape[1])], axis=1).astype(np.float32)


def _align_target(times, values, centers):
    _, np = _dependencies()
    if times is None or values is None:
        return None
    if times.shape[0] != values.shape[0]:
        raise ValueError("target data length differs from its timebase")
    report = _check_time("target", times)
    if not report["strictly_monotonic"] or report["finite_fraction"] != 1.0:
        raise ValueError("target timestamps must be finite and strictly monotonic")
    aligned = np.full((centers.size, values.shape[1]), np.nan, dtype=np.float64)
    covered = (centers >= times[0]) & (centers <= times[-1])
    for column in range(values.shape[1]):
        finite = np.isfinite(values[:, column])
        if finite.sum() >= 2:
            aligned[covered, column] = np.interp(centers[covered], times[finite], values[finite, column])
    return aligned


def _ridge_baseline(matrix, target, evaluation_mask=None):
    _, np = _dependencies()
    if target is None or matrix.shape[0] < 20 or matrix.shape[1] == 0:
        return {"status": "skipped", "reason": "numeric aligned target and at least 20 bins/one retained unit are required"}
    valid = np.isfinite(target).all(axis=1) & np.isfinite(matrix).all(axis=1)
    if valid.sum() < 20:
        return {"status": "skipped", "reason": "fewer than 20 jointly finite aligned bins"}
    if evaluation_mask is not None and evaluation_mask.shape == valid.shape:
        train_rows = valid & ~evaluation_mask
        test_rows = valid & evaluation_mask
    else:
        valid_indices = np.flatnonzero(valid)
        split = max(1, min(valid_indices.size - 1, int(valid_indices.size * 0.8)))
        train_rows = np.zeros(valid.shape, dtype=bool)
        test_rows = np.zeros(valid.shape, dtype=bool)
        train_rows[valid_indices[:split]] = True
        test_rows[valid_indices[split:]] = True
    if train_rows.sum() < 10 or test_rows.sum() < 2:
        return {"status": "skipped", "reason": "configured train/evaluation split has insufficient jointly finite bins"}
    x_train, x_test = matrix[train_rows].astype(np.float64), matrix[test_rows].astype(np.float64)
    y_train, y_test = target[train_rows], target[test_rows]
    mean, scale = x_train.mean(axis=0), x_train.std(axis=0)
    scale[scale == 0] = 1
    x_train = (x_train - mean) / scale
    x_test = (x_test - mean) / scale
    x_train = np.column_stack([np.ones(x_train.shape[0]), x_train])
    x_test = np.column_stack([np.ones(x_test.shape[0]), x_test])
    penalty = np.eye(x_train.shape[1]); penalty[0, 0] = 0
    weights = np.linalg.pinv(x_train.T @ x_train + penalty) @ x_train.T @ y_train
    prediction = x_test @ weights
    denominator = np.sum((y_test - y_test.mean(axis=0)) ** 2, axis=0)
    r2 = np.where(denominator > 0, 1 - np.sum((y_test - prediction) ** 2, axis=0) / denominator, np.nan)
    return {
        "status": "completed",
        "model": "ridge",
        "alpha": 1.0,
        "split": "nwb_eval_mask" if evaluation_mask is not None else "chronological_80_20",
        "train_rows": int(x_train.shape[0]),
        "test_rows": int(x_test.shape[0]),
        "r2": [None if not np.isfinite(value) else float(value) for value in r2],
        "interpretation": "Diagnostic only; a positive score is not proof of scientific validity or absence of leakage outside this split.",
    }


def _write_event_file(path: Path, ids, spikes):
    _, np = _dependencies()
    stops = np.cumsum([len(values) for values in spikes], dtype=np.int64)
    flat = np.concatenate(spikes) if spikes and stops[-1] else np.empty(0, dtype=np.float64)
    np.savez_compressed(path, unit_ids=np.asarray([str(_decode(value)) for value in ids]), spike_times=flat, spike_times_index=stops)


def _trial_tensor(matrix, centers, trials, bin_size_s: float, pre_s: float, post_s: float, max_bytes: int):
    _, np = _dependencies()
    if trials is None or not trials[0].size:
        return None, None
    starts, stops = trials
    span = float(np.max(stops - starts)) + pre_s + post_s
    width = max(1, int(math.ceil(span / bin_size_s)))
    required = starts.size * width * matrix.shape[1] * 4
    if required > max_bytes:
        raise ValueError(f"trial tensor needs {required} bytes, above max_matrix_bytes={max_bytes}")
    relative = -pre_s + np.arange(width) * bin_size_s + bin_size_s / 2
    tensor = np.full((starts.size, width, matrix.shape[1]), np.nan, dtype=np.float32)
    for index, (start, stop) in enumerate(zip(starts, stops, strict=True)):
        target_times = start + relative
        valid = (target_times >= centers[0]) & (target_times <= centers[-1]) & (target_times <= stop + post_s)
        source = np.searchsorted(centers, target_times[valid])
        source = np.clip(source, 0, centers.size - 1)
        tensor[index, np.flatnonzero(valid), :] = matrix[source, :]
    return relative, tensor


def execute_invasive(
    snapshot: NeuroDatasetSnapshot,
    plan: InvasiveExecutionPlan,
    output_dir: Path,
) -> dict[str, Any]:
    h5py, np = _dependencies()
    if not plan.executable or plan.strategy != "consume_released_derivative":
        raise ValueError("plan is not executable; resolve its blocked method/evidence steps")
    source = Path(snapshot.source.path).resolve(strict=True)
    _source_is_unchanged(snapshot, source)
    output_dir = output_dir.resolve()
    if output_dir.exists():
        summary_path = output_dir / "result.json"
        if summary_path.is_file():
            return json.loads(summary_path.read_text(encoding="utf-8"))
        raise ValueError("invasive output directory already exists without a complete result")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".invasive-", dir=output_dir.parent))
    try:
        with h5py.File(source, "r", swmr=True) as root:
            ids, raw_spikes, quality = _read_units(root)
            trials = _read_trials(root)
            target_path, target_times, target_values = _select_target(root, snapshot, plan.transform.target_series_path)
            provisional_start, provisional_stop = _choose_bounds(raw_spikes, trials, target_times)
            qc_rows, retained_indices, spikes = _unit_qc(ids, raw_spikes, quality, plan, provisional_start, provisional_stop)
            retained_ids = ids[retained_indices]
            start_s, stop_s = (
                _choose_bounds(spikes, trials, target_times)
                if any(values.size for values in spikes)
                else (provisional_start, provisional_stop)
            )
            neural_checks = [_check_time(f"unit:{_decode(ids[index])}", raw_spikes[index]) for index in range(len(ids))]
            invalid_neural = [
                row["name"]
                for row in neural_checks
                if row["finite_fraction"] != 1.0
                or (
                    plan.input_representation != "threshold_crossings"
                    and not row["strictly_monotonic"]
                )
            ]
            normalized_event_channels = [
                row["unit_id"] for row in qc_rows if row["source_order_normalized"]
            ]
            alignment = {
                "neural": {
                    "unit_count": len(neural_checks),
                    "invalid_timebases": invalid_neural,
                    "coverage_s": [start_s, stop_s],
                },
                "trials": None if trials is None else {
                    "count": int(trials[0].size),
                    "strictly_monotonic": bool(np.all(np.diff(trials[0]) >= 0)),
                    "coverage_s": [float(trials[0].min()), float(trials[1].max())] if trials[0].size else None,
                },
                "target": None if target_times is None else _check_time(target_path or "target", target_times),
            }
            if target_times is not None and target_times.size:
                overlap = max(0.0, min(stop_s, float(target_times[-1])) - max(start_s, float(target_times[0])))
                alignment["target"]["start_offset_from_neural_s"] = float(target_times[0]) - start_s
                alignment["target"]["stop_offset_from_neural_s"] = float(target_times[-1]) - stop_s
                alignment["target"]["neural_coverage_overlap_ratio"] = overlap / max(stop_s - start_s, np.finfo(float).eps)
                alignment["target"]["data_finite_fraction"] = float(np.isfinite(target_values).mean()) if target_values is not None and target_values.size else None

            artifacts: dict[str, Any] = {}
            matrix = None
            centers = None
            if plan.transform.representation in {"events", "both"}:
                _write_event_file(temp / "spike-events.npz", retained_ids, spikes)
                artifacts["spike_events"] = {"path": "spike-events.npz", "shape": [sum(len(v) for v in spikes), len(spikes)]}
            if plan.transform.representation in {"binned", "both"}:
                centers, matrix = _bin_spikes(spikes, start_s, stop_s, plan.transform.bin_size_s, plan.transform.max_matrix_bytes)
                matrix = _smooth(matrix, plan.transform.smoothing_sigma_s, plan.transform.bin_size_s)
                np.save(temp / "neural-matrix.npy", matrix, allow_pickle=False)
                np.save(temp / "time.npy", centers, allow_pickle=False)
                np.save(temp / "unit-ids.npy", np.asarray([str(_decode(value)) for value in retained_ids]), allow_pickle=False)
                artifacts["neural_matrix"] = {"path": "neural-matrix.npy", "shape": list(matrix.shape), "axes": ["time", "unit"], "dtype": str(matrix.dtype)}
                target = _align_target(target_times, target_values, centers)
                if target is not None:
                    np.save(temp / "aligned-target.npy", target, allow_pickle=False)
                    artifacts["aligned_target"] = {"path": "aligned-target.npy", "shape": list(target.shape), "source": target_path}
                evaluation_mask, mask_check = _evaluation_mask(root, snapshot, centers)
                alignment["evaluation_mask"] = mask_check
                if evaluation_mask is not None:
                    np.save(temp / "evaluation-mask.npy", evaluation_mask, allow_pickle=False)
                    artifacts["evaluation_mask"] = {
                        "path": "evaluation-mask.npy",
                        "shape": list(evaluation_mask.shape),
                        "axes": ["time"],
                    }
                relative, tensor = _trial_tensor(matrix, centers, trials, plan.transform.bin_size_s, plan.transform.trial_pre_s, plan.transform.trial_post_s, plan.transform.max_matrix_bytes)
                if tensor is not None:
                    np.save(temp / "trial-aligned.npy", tensor, allow_pickle=False)
                    np.save(temp / "trial-time.npy", relative, allow_pickle=False)
                    artifacts["trial_aligned"] = {"path": "trial-aligned.npy", "shape": list(tensor.shape), "axes": ["trial", "time_from_trial_start", "unit"]}
                baseline = _ridge_baseline(matrix, target, evaluation_mask) if plan.transform.run_baseline else {"status": "skipped", "reason": "disabled by configuration"}
            else:
                baseline = {"status": "skipped", "reason": "event-only output has no dense design matrix"}

        retention = len(retained_indices) / len(ids) if len(ids) else 0.0
        validation = {
            "source_unchanged": True,
            "unit_count_input": int(len(ids)),
            "unit_count_retained": len(retained_indices),
            "unit_retention_ratio": retention,
            "all_retained_spike_times_finite": all(np.isfinite(values).all() for values in spikes),
            "all_retained_spike_times_monotonic": all(np.all(np.diff(values) >= 0) for values in spikes),
            "signal_distribution": None if matrix is None or not matrix.size else {
                "mean": float(np.mean(matrix)),
                "standard_deviation": float(np.std(matrix)),
                "nonzero_fraction": float(np.mean(matrix != 0)),
                "finite_fraction": float(np.mean(np.isfinite(matrix))),
            },
            "baseline": baseline,
        }
        config = {
            "schema_version": "1",
            "task": plan.task,
            "strategy": plan.strategy,
            "method_profile": plan.method_profile,
            "literature_evidence_refs": [ref.model_dump(mode="json") for ref in plan.literature_evidence_refs],
            "code_evidence_refs": [ref.model_dump(mode="json") for ref in plan.code_evidence_refs],
            "source": snapshot.source.model_dump(mode="json"),
            "snapshot": snapshot.model_dump(mode="json"),
            "qc": plan.qc.model_dump(mode="json"),
            "transform": plan.transform.model_dump(mode="json"),
            "steps": [step.model_dump(mode="json") for step in plan.steps],
        }
        warnings = list(plan.warnings)
        if not retained_indices:
            warnings.append("All units were removed by the configured QC policy.")
        if invalid_neural:
            warnings.append("Some source units had invalid timestamps and were excluded; see qc-decisions.json.")
        if normalized_event_channels:
            warnings.append(
                f"Normalized source event order for {len(normalized_event_channels)} threshold-crossing channels; no events were removed for single-unit ISI criteria."
            )
        if not snapshot.source.sha256:
            warnings.append("Source identity uses size and modification time only; repeat Survey with hash_source=true for a content digest.")
        implementation_files = [Path(__file__), Path(__file__).with_name("nwb.py"), Path(__file__).with_name("planner.py"), Path(__file__).with_name("schemas.py")]
        provenance = {
            "implementation": "brainagent-invasive-nwb-v1",
            "implementation_sha256": {
                file.name: file_hash(file) for file in implementation_files
            },
            "environment": {
                "python": platform.python_version(),
                "numpy": np.__version__,
                "h5py": h5py.__version__,
            },
            "upstream_processing_modules": snapshot.processing_history,
            "source_identity_policy": "sha256" if snapshot.source.sha256 else "size_and_modified_ns",
        }
        write_json(temp / "preprocessing-config.json", config)
        write_json(temp / "qc-decisions.json", qc_rows)
        write_json(temp / "alignment.json", alignment)
        write_json(temp / "validation.json", validation)
        write_json(temp / "provenance.json", provenance)
        manifest = {
            "source": snapshot.source.model_dump(mode="json"),
            "dataset_id": snapshot.dataset_id,
            "session_id": snapshot.session_id,
            "modality": snapshot.modality,
            "input_representation": plan.input_representation,
            "strategy": plan.strategy,
            "artifacts": artifacts,
            "warnings": warnings,
        }
        write_json(temp / "manifest.json", manifest)
        report_lines = [
            f"# Invasive preprocessing report: {snapshot.dataset_id}",
            "",
            f"- Session: `{snapshot.session_id}`",
            f"- Modality: `{snapshot.modality}`",
            f"- Strategy: `{plan.strategy}`",
            f"- Input units: {len(ids)}",
            f"- Retained units: {len(retained_indices)} ({retention:.1%})",
            f"- Processing interval: {start_s:g}–{stop_s:g} s",
            f"- Baseline: `{baseline['status']}`",
            f"- Baseline details: `{canonical(baseline)}`",
            "",
            "## Original data overview",
            "",
            *[
                f"- `{item.path}`: representation=`{item.representation}`, shape={item.shape}, dtype=`{item.dtype}`, units=`{item.physical_units or 'unspecified'}`"
                for item in snapshot.collections
            ],
            "",
            "## Final data shapes",
            "",
            *(
                [f"- `{name}`: {value.get('shape')}" for name, value in artifacts.items()]
                or ["- No numerical derivative was materialized."]
            ),
            "",
            "## Unit retention decisions",
            "",
            f"- Retained source unit IDs: {[row['unit_id'] for row in qc_rows if row['retained']]}",
            f"- Removed units and reasons: {[(row['unit_id'], row['reasons']) for row in qc_rows if not row['retained']]}",
            "",
            "## Parameters",
            "",
            f"- QC: `{canonical(plan.qc.model_dump(mode='json'))}`",
            f"- Transform: `{canonical(plan.transform.model_dump(mode='json'))}`",
            "",
            "## Executed and skipped steps",
            "",
            *[f"- `{step.id}` — {step.status}: {step.reason}" for step in plan.steps],
            "",
            "## Warnings",
            "",
            *([f"- {warning}" for warning in warnings] or ["- None"]),
            "",
            "Detailed parameters and per-unit decisions are stored in `preprocessing-config.json` and `qc-decisions.json`.",
        ]
        (temp / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        files = {}
        for artifact in sorted(temp.iterdir()):
            if artifact.is_file() and artifact.name not in {"manifest.json", "result.json"}:
                files[artifact.name] = {"sha256": file_hash(artifact), "size_bytes": artifact.stat().st_size}
        manifest["files"] = files
        write_json(temp / "manifest.json", manifest)
        result = {
            "status": "completed",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "output_dir": str(output_dir),
            "report": str(output_dir / "report.md"),
            "manifest": str(output_dir / "manifest.json"),
            "final_shapes": {name: value.get("shape") for name, value in artifacts.items()},
            "unit_retention_ratio": retention,
            "alignment": alignment,
            "validation": validation,
            "warnings": warnings,
        }
        write_json(temp / "result.json", result)
        os.replace(temp, output_dir)
        return result
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
