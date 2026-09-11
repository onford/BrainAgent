"""Read-only, unit-aware signal observations; never a composite quality score.

The reconstruction worker owns filtering, resampling and source/precue reads.
This module measures supplied views, records their provenance, and refuses to
recover missing bandwidth or physical voltage from transformed coordinates.
See docs/preprocessing-evaluation.md for measurement and selection boundaries.
Numerical rank here deliberately differs from evaluation_numeric's gate rank.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from scipy.signal import welch

VERSION = "quality-metrics-1.0"
OHA_THRESHOLDS_UV = (30.0, 50.0, 100.0, 150.0)
SD_THRESHOLDS_UV = (15.0, 30.0, 50.0)
_VOLTAGE_FACTORS = {"V": 1e6, "physvolts": 1e6, "uV": 1.0, "µV": 1.0}


@dataclass(frozen=True)
class SignalView:
    """Caller-attested provenance; no unit/coordinate inference from magnitude.

    passband_hz is the *usable* inherited band, including transition losses.
    None means unknown, not full Nyquist. Time origins are event-relative for
    task/precue views. Samples across discontinuities must be separate calls.
    For dimensionless arrays, channel names identify transformed coordinates.
    processing_id identifies the same cleaning recipe/application; transform_id
    identifies the exact fitted adaptation, not just its method name.
    """

    sfreq: float
    unit: str
    channels: tuple[str, ...]
    source_id: str
    processing_id: str
    reference: str
    kind: Literal[
        "native", "common_amplitude", "common_spectrum", "scored_grid",
        "raw_precue", "task_baseline",
    ] = "native"
    passband_hz: tuple[float, float] | None = None
    coordinate_space: Literal["electrodes", "transformed", "unknown"] = "electrodes"
    transform_id: str | None = None
    transform_kind: Literal[
        "none", "scale_only", "channel_scale", "spatial_linear", "unknown"
    ] = "none"
    fit_scope: str = "not_fitted"
    source_sha256: str | None = None
    source_path: str | None = None
    time_origin_seconds: float = 0.0
    notch_bands_hz: tuple[tuple[float, float], ...] = ()
    measurement_id: str | None = None

    def __post_init__(self):
        if not np.isfinite(self.sfreq) or self.sfreq <= 0:
            raise ValueError("sfreq must be finite and positive")
        if not np.isfinite(self.time_origin_seconds):
            raise ValueError("time origin must be finite")
        if self.unit not in {*_VOLTAGE_FACTORS, "dimensionless", "unknown"}:
            raise ValueError("unsupported unit; do not infer physical units")
        if not self.channels or len(set(self.channels)) != len(self.channels):
            raise ValueError("unique nonempty channels required")
        if not all((self.source_id, self.processing_id, self.reference)):
            raise ValueError("source, processing and reference provenance required")
        if self.passband_hz is not None:
            lo, hi = self.passband_hz
            if not (np.isfinite([lo, hi]).all() and 0 <= lo < hi <= self.sfreq / 2):
                raise ValueError("invalid usable passband")
        for lo, hi in self.notch_bands_hz:
            if not (np.isfinite([lo, hi]).all() and 0 <= lo < hi <= self.sfreq / 2):
                raise ValueError("invalid notch band")
        if self.unit == "dimensionless" and self.coordinate_space == "electrodes":
            raise ValueError("dimensionless values are not physical electrodes")
        if self.kind == "common_amplitude" and not (
            self.passband_hz and self.passband_hz[0] <= 0.5
            and self.passband_hz[1] >= 45
        ):
            raise ValueError("common_amplitude requires declared 0.5–45 Hz support")

    @property
    def physical(self):
        return self.unit in _VOLTAGE_FACTORS and self.coordinate_space == "electrodes"

    def supports(self, lo, hi):
        return bool(self.passband_hz and self.passband_hz[0] <= lo
                    and hi <= self.passband_hz[1] and hi <= self.sfreq / 2)


def _json_value(value):
    if isinstance(value, np.ndarray):
        return _json_value(value.tolist())
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def observation(value, unit, formula_id, *, reason=None, role="proxy_observation",
                denominator=None, status=None):
    """JSON-safe values with explicit missingness, never implicit zero fill."""
    finite = np.isfinite(np.asarray(value, dtype=float)) if value is not None else None
    if status is None:
        if finite is None or not finite.size or not finite.any():
            status = "not_computable"
        else:
            status = "ok" if finite.all() else "partial"
    if status in {"partial", "not_computable"} and reason is None:
        reason = "nonfinite_or_empty_value"
    return dict(value=_json_value(value), unit=unit, formula_id=formula_id,
                status=status, reason=reason, selection_role=role,
                globally_monotonic_quality=False, denominator=_json_value(denominator))


def _signal(data, view):
    values = np.asarray(data, dtype=np.float64)
    if values.ndim != 2 or values.shape[0] != len(view.channels) or values.shape[1] < 2:
        raise ValueError("one continuous channels x samples view required")
    # Multiplication/copy never writes to input memmaps or source arrays.
    return values * _VOLTAGE_FACTORS[view.unit] if view.physical else values.copy()


def _windows(n, sfreq):
    length, minimum = max(1, round(4 * sfreq)), max(1, round(2 * sfreq))
    for start in range(0, n, length):
        end = min(start + length, n)
        if end - start >= minimum:
            yield start, end


def _flat_mask(values, sfreq):
    mask = np.zeros(values.shape, dtype=bool)
    minimum = max(1, round(5 * sfreq) - 1)
    for c, row in enumerate(values):
        valid_diff = np.isfinite(row[1:]) & np.isfinite(row[:-1])
        flat = valid_diff & (np.abs(np.diff(row)) <= 0.1)
        edges = np.flatnonzero(np.diff(np.r_[False, flat, False].astype(int)))
        for start, stop in edges.reshape(-1, 2):
            if stop - start >= minimum:
                mask[c, start:stop + 1] = True
    return mask


def _amplitude(values, physical, flat=None):
    channels, samples = values.shape
    valid_channels = np.isfinite(values).all(axis=1)
    sd = np.full(channels, np.nan)
    ptp, mad = sd.copy(), sd.copy()
    if valid_channels.any():
        finite = values[valid_channels]
        sd[valid_channels] = finite.std(axis=1, ddof=0)
        ptp[valid_channels] = np.ptp(finite, axis=1)
        center = np.median(finite, axis=1, keepdims=True)
        mad[valid_channels] = 1.4826 * np.median(np.abs(finite - center), axis=1)
    unit = "µV" if physical else "input_unit"
    out = {
        "peak_to_peak": observation(ptp, unit, "ptp_channel_window", denominator=samples),
        "robust_dispersion": observation(mad, unit, "1.4826_mad", denominator=samples),
    }
    finite_cells = np.isfinite(values)
    if physical:
        # Valid-cell denominator is explicit; THV requires *all* declared channels.
        n_cells = int(finite_cells.sum())
        oha = [np.count_nonzero(finite_cells & (np.abs(values) > t)) / n_cells
               if n_cells else np.nan for t in OHA_THRESHOLDS_UV]
        valid_times = finite_cells.all(axis=0)
        gfp = np.full(samples, np.nan)
        if channels >= 2 and valid_times.any():
            gfp[valid_times] = values[:, valid_times].std(axis=0, ddof=0)
        good_gfp = np.isfinite(gfp)
        thv = [np.mean(gfp[good_gfp] > t) if good_gfp.any() else np.nan
               for t in SD_THRESHOLDS_UV]
        chv = [np.mean(sd[valid_channels] > t) if valid_channels.any() else np.nan
               for t in SD_THRESHOLDS_UV]
        out.update(
            oha=observation(oha, "ratio", "oha_abs_gt_uv",
                            denominator={"valid_cells": n_cells, "total_cells": values.size}),
            thv=observation(thv, "ratio", "thv_ddof0",
                            denominator={"valid_times": int(good_gfp.sum()), "total_times": samples}),
            chv=observation(chv, "ratio", "chv_ddof0",
                            denominator={"valid_channels": int(valid_channels.sum()), "total_channels": channels}),
            gfp=observation(gfp, "µV", "gfp_ddof0", denominator=channels),
        )
        if flat is not None:
            counts = finite_cells.sum(axis=1)
            fractions = np.divide(flat.sum(axis=1), counts,
                                  out=np.full(channels, np.nan), where=counts > 0)
            out["flat_fraction"] = observation(fractions, "ratio", "flat_0.1uv_5seconds",
                                               denominator=counts)
        for key in ("oha", "thv", "chv"):
            metric = out[key]
            if metric["status"] == "ok" and not finite_cells.all():
                metric.update(status="partial", reason="nonfinite_input_excluded_with_denominator")
    else:
        for key in ("oha", "thv", "chv", "flat_fraction", "gfp"):
            out[key] = observation(None, "µV_threshold_or_amplitude", key,
                                   reason="physical_voltage_required", status="not_applicable")
    variable = valid_channels & (sd > 0)
    correlation = np.full(channels, np.nan)
    if variable.sum() >= 2:
        matrix = np.abs(np.corrcoef(values[variable]))
        np.fill_diagonal(matrix, np.nan)
        correlation[variable] = np.nanpercentile(matrix, 98, axis=1)
    good = np.isfinite(correlation)
    out["channel_correlation"] = observation(correlation, "absolute_correlation", "peer_abs_r_q98",
                                             reason=None if good.all() else "constant_or_nonfinite_channel")
    out["low_correlation_fraction"] = observation(
        float(np.mean(correlation[good] < 0.4)) if good.any() else None,
        "ratio", "q98_abs_r_lt_0.4",
        denominator={"valid_channels": int(good.sum()), "total_channels": channels},
        status="partial" if good.any() and not good.all() else None,
        reason=None if good.all() else "constant_or_nonfinite_channel",
    )
    finite_ptp = ptp[np.isfinite(ptp)]
    out["peak_to_peak_quantiles"] = observation(
        np.quantile(finite_ptp, [0.5, 0.9, 0.99]) if finite_ptp.size else None,
        unit, "channel_ptp_q50_q90_q99", denominator=int(finite_ptp.size))
    return out


def _rank_covariance(values, physical):
    units = "µV²" if physical else "input_unit²"
    ids = {"numerical_rank": "dimensions", "covariance_condition": "ratio",
           "covariance_trace": units, "participation_rank": "dimensions"}
    if not np.isfinite(values).all():
        return {k: observation(None, u, k, reason="nonfinite_input") for k, u in ids.items()}
    centered = values - values.mean(axis=1, keepdims=True)
    # Scale first: rank and condition should not depend on volts versus µV.
    scale = float(np.max(np.abs(centered)))
    norm = centered / scale if scale else centered
    singular = np.linalg.svd(norm, compute_uv=False)
    tolerance = singular[0] * max(norm.shape) * np.finfo(np.float64).eps
    rank = int(np.count_nonzero(singular > tolerance))
    eigenvalues = singular**2 / (values.shape[1] - 1)
    trace = float(np.sum(eigenvalues))
    condition = float(eigenvalues[0] / eigenvalues[-1]) if rank == values.shape[0] else None
    out = {
        "numerical_rank": observation(rank, "dimensions", "svd_maxshape_float64_eps",
                                      role="hard_feasibility", denominator=list(values.shape)),
        "covariance_condition": observation(condition, "ratio", "sample_covariance_condition",
                                            reason="singular_covariance" if condition is None else None),
        "covariance_trace": observation(trace * scale**2, units, "covariance_trace_ddof1"),
        "participation_rank": observation(trace**2 / np.sum(eigenvalues**2) if trace else None,
                                          "dimensions", "covariance_participation_rank",
                                          reason="zero_variance" if not trace else None),
    }
    out["numerical_rank"]["normalized_singular_values"] = singular.tolist()
    out["numerical_rank"]["normalized_tolerance"] = float(tolerance)
    return out


def _band_mean(freqs, psd, lower, upper, *, include_upper=True):
    selected = (freqs >= lower) & (freqs <= upper if include_upper else freqs < upper)
    return psd[..., selected].mean(axis=-1) if selected.sum() >= 2 else np.full(psd.shape[:-1], np.nan)


def _db_ratio(numerator, denominator):
    numerator, denominator = np.broadcast_arrays(numerator, denominator)
    result = np.full(numerator.shape, np.nan)
    valid = np.isfinite(numerator) & np.isfinite(denominator) & (numerator > 0) & (denominator > 0)
    result[valid] = 10 * np.log10(numerator[valid] / denominator[valid])
    return result


def _spectral(values, view, line_frequency):
    finite = np.isfinite(values).all(axis=1)
    unit = "µV²/Hz" if view.physical else "dimensionless²/Hz" if view.unit == "dimensionless" else "unknown²/Hz"
    seg = min(round(4 * view.sfreq), values.shape[1])
    if seg < 2 or not finite.any():
        return {"psd": observation(None, unit, "welch_median", reason="no_finite_channel")}
    freqs, valid_psd = welch(values[finite], fs=view.sfreq, window="hamming",
                              nperseg=seg, noverlap=seg // 2, nfft=seg,
                              detrend="constant", scaling="density", average="median", axis=-1)
    psd = np.full((values.shape[0], len(freqs)), np.nan)
    psd[finite] = valid_psd
    out = {"psd": observation(psd, unit, "welch_median_hamming_50pct",
                              denominator={"samples": values.shape[1], "nperseg": seg,
                                           "nfft": seg, "resolution_hz": view.sfreq / seg})}
    out["psd"]["frequencies_hz"] = freqs.tolist()
    for label, bounds in {"mu": (8, 12), "beta": (13, 30)}.items():
        power = _band_mean(freqs, psd, *bounds) if view.supports(*bounds) else None
        out[label + "_mean_psd"] = observation(power, unit, "band_mean_psd_" + label,
                                                reason=None if view.supports(*bounds) else "bandwidth_unavailable_or_unknown")
    hf = (_db_ratio(_band_mean(freqs, psd, 30, 45), _band_mean(freqs, psd, 1, 30))
          if view.supports(1, 45) else None)
    out["hf_noise_ratio"] = observation(hf, "dB", "mean_psd_30_45_over_1_30_closed_bins",
                                         reason=None if hf is not None else "requires_complete_1_45_hz")
    # Frequency selection is allowed only on declared original/native input.
    candidates = [f for f in (50.0, 60.0) if view.supports(f - 3, f + 3)]

    def line(target):
        overlap = any(lo < target + 3 and hi > target - 3 for lo, hi in view.notch_bands_hz)
        if not view.supports(target - 3, target + 3) or overlap:
            return None
        center = _band_mean(freqs, psd, target - 1, target + 1, include_upper=False)
        left = _band_mean(freqs, psd, target - 3, target - 1, include_upper=False)
        right = _band_mean(freqs, psd, target + 1, target + 3, include_upper=False)
        return _db_ratio(center, (left + right) / 2)

    inferred = False
    if line_frequency is None and view.kind in {"native", "raw_precue"} and view.processing_id == "raw":
        options = [(f, line(f)) for f in candidates]
        options = [(f, float(np.median(v[np.isfinite(v)]))) for f, v in options
                   if v is not None and np.isfinite(v).any()]
        if options:
            line_frequency = max(options, key=lambda item: item[1])[0]
            inferred = True
    targets = []
    if line_frequency is not None:
        if not np.isfinite(line_frequency) or line_frequency <= 0:
            raise ValueError("line frequency must be positive and finite")
        targets = [line_frequency * h for h in range(1, int(view.sfreq / 2 / line_frequency) + 1)]
    out["line_noise"] = {
        "frequency_hz": line_frequency, "inferred_from_raw": inferred,
        "status": "ok" if targets else "not_computable",
        "reason": None if targets else "line_frequency_or_bandwidth_unavailable",
        "harmonics": {str(f): observation(line(f), "dB", "local_psd_ratio_disjoint_half_open_bins",
                                            reason=None if line(f) is not None else "notched_or_bandwidth_unavailable")
                      for f in targets},
    }
    return out


def compute_signal_quality(data, view: SignalView, *, line_frequency=None):
    """Measure one continuous view, including windows; does not filter input.

    Use compute_epoch_quality for independent epochs: never concatenate them
    to make artificial 5-second flat segments or falsely fine-resolution PSD.
    Native metrics are labelled native and are not claimed as common-view
    contract metrics merely because their units happen to match.
    """
    values = _signal(data, view)
    flat = (_flat_mask(values, view.sfreq)
            if view.physical and values.shape[1] / view.sfreq >= 5 else None)
    amplitude = _amplitude(values, view.physical, flat)
    if view.physical and flat is None:
        amplitude["flat_fraction"] = observation(
            None, "ratio", "flat_0.1uv_5seconds", status="not_applicable",
            reason="no_contiguous_5_second_record")
    numerical = _rank_covariance(values, view.physical)
    spectrum = _spectral(values, view, line_frequency)
    windows = []
    window_spectra = []
    full_size = round(4 * view.sfreq)
    for start, end in _windows(values.shape[1], view.sfreq):
        part = values[:, start:end]
        item = dict(start_seconds=view.time_origin_seconds + start / view.sfreq,
                    duration_seconds=(end - start) / view.sfreq,
                    metrics=_amplitude(part, view.physical, None if flat is None else flat[:, start:end]))
        item["metrics"].update(_rank_covariance(part, view.physical))
        # Partial tail has lower true resolution. Do not zero-pad and claim 4 s.
        item["spectrum"] = _spectral(part, view, spectrum.get("line_noise", {}).get("frequency_hz"))
        if end - start == full_size and np.isfinite(part).all():
            window_spectra.append(item["spectrum"]["psd"]["value"])
        windows.append(item)
    if window_spectra:
        q = np.quantile(np.median(np.asarray(window_spectra), axis=1), [0.1, 0.5, 0.9], axis=0)
    else:
        q = None
    spectrum["window_psd_quantiles"] = observation(
        q, spectrum["psd"]["unit"], "full_4s_window_psd_q10_q50_q90",
        denominator={"included_full_windows": len(window_spectra), "all_windows": len(windows)},
        reason=None if q is not None else "no_full_finite_4s_window")
    report = dict(
        version=VERSION, status="ok" if np.isfinite(values).all() else "partial",
        view=asdict(view), physical_voltage=view.physical,
        coordinate_interpretation="physical_electrodes" if view.physical else "transformed_or_unknown_coordinates",
        aggregation="one_record; windows retain denominators; no subject pooling",
        oha_thresholds_uv=OHA_THRESHOLDS_UV, sd_thresholds_uv=SD_THRESHOLDS_UV,
        coverage=dict(total_samples=values.shape[1], channels=values.shape[0],
                      finite_cells=int(np.isfinite(values).sum()), total_cells=values.size,
                      window_samples=sum(round(w["duration_seconds"] * view.sfreq) for w in windows)),
        metrics={**amplitude, **numerical}, spectrum=spectrum, windows=windows,
        composite_score=None, scientific_quality_certified=False,
    )
    return _json_value(report)


def compute_epoch_quality(epochs, view: SignalView, *, trial_ids, line_frequency=None):
    values = np.asarray(epochs)
    if values.ndim != 3 or len(trial_ids) != len(values) or len(set(trial_ids)) != len(trial_ids):
        raise ValueError("unique original trial IDs and epochs x channels x samples required")
    return {str(trial): compute_signal_quality(epoch, view, line_frequency=line_frequency)
            for trial, epoch in zip(trial_ids, values)}


def _comparison_problem(task, baseline):
    for field in ("source_id", "processing_id", "reference", "channels", "coordinate_space",
                  "transform_id", "transform_kind", "measurement_id", "sfreq",
                  "passband_hz", "notch_bands_hz", "fit_scope", "source_sha256"):
        if getattr(task, field) != getattr(baseline, field):
            return field + "_mismatch"
    if task.unit != baseline.unit:
        return "unit_mismatch"
    if task.measurement_id is None:
        return "power_measurement_provenance_required"
    if task.unit == "unknown":
        return "unknown_power_scaling"
    if task.unit == "dimensionless" and (
        not task.transform_id or task.transform_kind in {"none", "unknown"}
    ):
        return "shared_time_invariant_transform_required"
    return None


def compute_paired_erds(task_power, baseline_power, *, task_view: SignalView,
                        baseline_view: SignalView, task_trial_ids, baseline_trial_ids,
                        baseline_times, baseline_interval, baseline_valid_mask=None):
    """Baseline-normalize *linear power*, preserving trial-level denominators.

    Arrays have trial x ... x time axes. The upstream source/precue worker must
    provide the baseline with the SAME cleaning/adaptation and TFR measurement.
    A raw precursor alone never authorizes pairing it with a cleaned/adapted grid.
    baseline_valid_mask marks usable convolution support, not post-hoc good trials.
    """
    task = np.asarray(task_power, dtype=float)
    base = np.asarray(baseline_power, dtype=float)
    times = np.asarray(baseline_times, dtype=float)
    if task.ndim < 2 or base.ndim != task.ndim or task.shape[1:-1] != base.shape[1:-1]:
        raise ValueError("power arrays must share non-time, non-trial dimensions")
    if times.ndim != 1 or times.size != base.shape[-1] or not np.isfinite(times).all():
        raise ValueError("baseline times must match power time axis")
    if times.size < 2 or np.any(np.diff(times) <= 0):
        raise ValueError("strictly increasing baseline times required")
    if (len(task_trial_ids) != len(task) or len(baseline_trial_ids) != len(base)
            or len(set(task_trial_ids)) != len(task_trial_ids)
            or len(set(baseline_trial_ids)) != len(baseline_trial_ids)):
        raise ValueError("unique original trial IDs required")
    problem = _comparison_problem(task_view, baseline_view)
    lo, hi = baseline_interval
    if not np.isfinite([lo, hi]).all() or not lo < hi < 0:
        problem = "baseline_must_be_precue_and_nonempty"
    if times[0] > lo or times[-1] < hi:
        problem = "baseline_interval_not_fully_available"
    selected = (times >= lo) & (times <= hi)
    if not problem and selected.sum() < 2:
        problem = "baseline_interval_has_fewer_than_two_samples"
    metric = observation(None, "%", "100_times_task_minus_baseline_over_baseline",
                         reason=problem, status="not_comparable" if problem else "not_computable")
    result = dict(version=VERSION, metric=metric, task_view=asdict(task_view),
                  baseline_view=asdict(baseline_view), original_trial_ids=list(task_trial_ids),
                  baseline_interval_seconds=list(baseline_interval),
                  physical_roi_interpretation=task_view.physical,
                  baseline_power=None, paired_trials=0, missing_baseline_trial_ids=[])
    if problem:
        return _json_value(result)
    support = np.ones(base.shape, dtype=bool)
    if baseline_valid_mask is not None:
        support = np.broadcast_to(np.asarray(baseline_valid_mask, dtype=bool), base.shape)
    indices = {trial: index for index, trial in enumerate(baseline_trial_ids)}
    denominators = np.full(task.shape[:-1] + (1,), np.nan)
    counts = np.zeros(task.shape[:-1] + (1,), dtype=int)
    missing = []
    for i, trial in enumerate(task_trial_ids):
        if trial not in indices:
            missing.append(trial)
            continue
        j = indices[trial]
        # Do not hide a partly unavailable baseline by silently shortening it.
        b = base[j][..., selected]
        available = support[j][..., selected]
        valid = np.isfinite(b).all(axis=-1) & (b >= 0).all(axis=-1) & available.all(axis=-1)
        average = b.mean(axis=-1)
        valid &= np.isfinite(average) & (average > 0)
        denominators[i, ..., 0] = np.where(valid, average, np.nan)
        counts[i, ..., 0] = np.where(valid, selected.sum(), 0)
    valid = np.isfinite(denominators) & (denominators > 0) & np.isfinite(task) & (task >= 0)
    values = np.full(task.shape, np.nan)
    np.divide(task - denominators, denominators, out=values, where=valid)
    values *= 100
    result.update(
        metric=observation(values, "%", "100_times_task_minus_baseline_over_baseline",
                           denominator={"baseline_samples": counts, "total_task_trials": len(task)},
                           reason=None if valid.all() else "missing_trial_invalid_baseline_or_power"),
        baseline_power=denominators, paired_trials=len(task) - len(missing),
        missing_baseline_trial_ids=missing,
    )
    return _json_value(result)


class QualityMetric(BaseModel):
    """One named observation, with no implicit clinical or selection threshold."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    metricID: str
    value: float | int | list | dict | None
    unit: str
    direction: Literal[
        "non_monotonic", "lower_residual_only", "higher_agreement_only",
        "lower_change_only", "feasibility",
    ] = "non_monotonic"
    status: Literal["ok", "partial", "not_applicable", "not_computable"]
    reason: str | None
    formula: str
    denominator: dict = Field(default_factory=dict)
    details: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def finite_and_explained(self):
        def check(value):
            if isinstance(value, dict):
                for child in value.values():
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)
            elif isinstance(value, float) and not np.isfinite(value):
                raise ValueError("nonfinite JSON numbers are forbidden")
        check(self.value)
        check(self.denominator)
        check(self.details)
        if self.status in {"not_applicable", "not_computable"} and self.value is not None:
            raise ValueError("unavailable metrics must have null values")
        if self.status != "ok" and not self.reason:
            raise ValueError("missing/partial metrics require a reason")
        if self.status == "ok" and self.value is None:
            raise ValueError("ok metric requires an observed value")
        return self


class QualityMetrics(BaseModel):
    """One caller-supplied subject/record; parent owns subject-level aggregation."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    version: str = VERSION
    unit: Literal["V", "dimensionless"]
    sfreq: float = Field(gt=0)
    channel_names: list[str]
    n_epochs: int = Field(ge=1)
    n_samples_per_epoch: int = Field(ge=2)
    metrics: list[QualityMetric]
    metadata: dict

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [m.metricID for m in self.metrics]
        if len(set(ids)) != len(ids):
            raise ValueError("metric IDs must be unique")
        return self

    def by_id(self, metric_id: str) -> QualityMetric:
        return next(m for m in self.metrics if m.metricID == metric_id)


def _epochs_input(values, channels, name):
    array = np.asarray(values)
    if array.dtype.kind not in "fiu" or array.ndim != 3:
        raise ValueError(f"{name} must be numeric epochs x channels x samples")
    if array.shape[0] < 1 or array.shape[1] != channels or array.shape[2] < 2:
        raise ValueError(f"{name} has empty or incompatible dimensions")
    return np.asarray(array, dtype=np.float64)


def _metric(metric_id, value, unit, formula, *, reason=None, status=None,
            direction="non_monotonic", denominator=None, details=None):
    observed = observation(value, unit, metric_id, reason=reason, status=status)
    if value is not None and not np.isfinite(np.asarray(value, dtype=float)).any():
        observed.update(value=None, status="not_computable",
                        reason=reason or "no_finite_metric_value")
    if observed["status"] in {"not_applicable", "not_computable"}:
        observed["value"] = None
    return QualityMetric(
        metricID=metric_id, value=observed["value"], unit=unit,
        direction=direction, status=observed["status"], reason=observed["reason"],
        formula=formula, denominator=_json_value(denominator or {}),
        details=_json_value(details or {}),
    )


def evaluate_quality(epochs_V, sfreq, channel_names, *, reference_epochs_V=None,
                     baseline_epochs_V=None, montage_positions=None) -> QualityMetrics:
    """Evaluate genuinely physical-voltage epochs (E,C,T), with no source writes.

    V is an explicit caller contract, never guessed from signal magnitude.
    No filtering or normalization is silently applied. Parent must supply a
    common measurement view for cross-pipeline comparisons and gate metrics
    against inherited acquisition/processing passbands. Spectral ratios below
    are descriptive sampled-band observations, not certified residual noise.

    Optional baseline epochs are real precue data with identical trial/channel
    order, units, processing and representation. Parent obtains them from the
    read-only full-record source; a 0–2 s scored grid is not its own baseline.
    Baseline absence returns not_applicable. reference_epochs_V is a paired
    before-view, not ground truth. No across-subject aggregation is performed.
    """
    return _evaluate_epochs(epochs_V, sfreq, channel_names,
                            reference=reference_epochs_V, baseline=baseline_epochs_V,
                            positions=montage_positions, physical=True)


def evaluate_dimensionless_quality(epochs, sfreq, channel_names, *,
                                    reference_epochs=None) -> QualityMetrics:
    """Adapted-coordinate observations: never µV thresholds or physical ROIs.

    This convenience API deliberately omits baseline pairing, since array
    shape alone cannot prove the same fitted transform. For dimensionless ERDS
    use compute_paired_erds with exact transform/measurement provenance.
    """
    return _evaluate_epochs(epochs, sfreq, channel_names, reference=reference_epochs,
                            baseline=None, positions=None, physical=False)


def _evaluate_epochs(epochs, sfreq, channel_names, *, reference, baseline, positions, physical):
    channels = list(channel_names)
    if (not channels or any(not isinstance(c, str) or not c for c in channels)
            or len(set(channels)) != len(channels)):
        raise ValueError("channel_names must be unique nonempty strings")
    if isinstance(sfreq, bool) or not np.isfinite(sfreq) or sfreq <= 0:
        raise ValueError("sfreq must be finite and positive")
    values = _epochs_input(epochs, len(channels), "epochs_V" if physical else "epochs")
    n, c, t = values.shape
    if reference is not None:
        reference = _epochs_input(reference, c, "reference_epochs_V")
        if reference.shape != values.shape:
            raise ValueError("reference epochs must match task shape and order")
    if baseline is not None:
        baseline = _epochs_input(baseline, c, "baseline_epochs_V")
        if baseline.shape[:2] != values.shape[:2]:
            raise ValueError("baseline must match task trial/channel order")
    # Do not stitch finite samples through missing spans or concatenate epochs.
    valid = np.isfinite(values).all(axis=(1, 2))
    good = values[valid] * (1e6 if physical else 1.0)
    unit = "µV" if physical else "dimensionless"
    power_unit = "µV²" if physical else "dimensionless²"
    denominator = {"total_epochs": n, "finite_epochs": int(valid.sum()),
                   "valid_epoch_indices": np.flatnonzero(valid).tolist(),
                   "excluded_nonfinite_epoch_indices": np.flatnonzero(~valid).tolist(),
                   "channels": c, "samples_per_epoch": t}
    metrics = []

    def add(mid, value, units, formula, **kwargs):
        if not valid.all() and value is not None and kwargs.get("status") is None:
            kwargs.update(status="partial", reason=kwargs.get("reason") or "nonfinite_epochs_excluded")
        metrics.append(_metric(mid, value, units, formula, denominator=denominator, **kwargs))

    duration = t / sfreq
    sample_windows = list(_windows(t, sfreq))
    parts = [epoch[:, start:end] for epoch in good for start, end in sample_windows]
    if parts:
        weights = np.array([part.shape[-1] for part in parts])
        windows_info = {"count": len(parts), "lengths_samples": weights.tolist(),
                        "minimum_seconds": 2, "target_seconds": 4,
                        "threshold_comparison": "strict_greater_than", "ddof": 0,
                        "windows": [
                            {"epoch_index": int(i), "start_sample": start, "stop_sample": end,
                             "start_seconds_in_epoch": start / sfreq,
                             "stop_seconds_in_epoch": end / sfreq}
                            for i in np.flatnonzero(valid) for start, end in sample_windows
                        ],
                        "excluded_tail_samples_per_epoch": t - sum(b-a for a, b in sample_windows)}
        measures = [_amplitude(p, physical) for p in parts]
        for key, formula in {
            "peak_to_peak": "max_t(x)-min_t(x), per epoch/window/channel",
            "robust_dispersion": "1.4826*median_t(abs(x-median_t(x)))",
            "channel_correlation": "Q98_j(abs(Pearson(x_c,x_j))), j!=c",
        }.items():
            array = np.array([m[key]["value"] for m in measures], dtype=float)
            add(key, array, "absolute_correlation" if key == "channel_correlation" else unit,
                formula, details=windows_info,
                reason="constant_or_invalid_channel" if not np.isfinite(array).all() else None)
        correlations = np.array([m["channel_correlation"]["value"] for m in measures], dtype=float)
        valid_corr = np.isfinite(correlations)
        low = float(np.mean(correlations[valid_corr] < 0.4)) if valid_corr.any() else None
        add("low_correlation_fraction", low, "ratio", "count(q98_abs_r<0.4)/finite_channel_windows",
            status="partial" if valid_corr.any() and not valid_corr.all() else None,
            reason=None if valid_corr.all() else "constant_or_invalid_channel",
            details={**windows_info, "valid_channel_windows": int(valid_corr.sum()),
                     "total_channel_windows": int(correlations.size), "threshold_is_descriptive": True})
        if physical:
            for key, thresholds, formula in (
                ("oha", OHA_THRESHOLDS_UV, "sum(abs(x)>threshold)/(channels*samples)"),
                ("thv", SD_THRESHOLDS_UV, "count_t(std_c(x,ddof=0)>threshold)/samples"),
                ("chv", SD_THRESHOLDS_UV, "count_c(std_t(x,ddof=0)>threshold)/channels"),
            ):
                curves = np.asarray([m[key]["value"] for m in measures], dtype=float)
                add(key, np.average(curves, axis=0, weights=weights), "ratio", formula,
                    details={**windows_info, "thresholds_uv": list(thresholds),
                             "window_curves": curves.tolist(),
                             "aggregation": "duration_weighted_window_curve; not_whole_record_CHV"})
    else:
        for key in ("peak_to_peak", "robust_dispersion", "channel_correlation", "low_correlation_fraction"):
            add(key, None, unit if key in {"peak_to_peak", "robust_dispersion"} else "ratio",
                "requires_valid_quality_window", reason="no_finite_window_of_at_least_2_seconds",
                status="not_applicable")
        if physical:
            for key in ("oha", "thv", "chv"):
                add(key, None, "ratio", key, reason="no_finite_window_of_at_least_2_seconds", status="not_applicable")
    if not physical:
        for key in ("oha", "thv", "chv"):
            add(key, None, "ratio", key + "_uv_threshold_curve",
                reason="physical_voltage_required", status="not_applicable")
    if physical and duration >= 5 and len(good):
        flat = np.array([_flat_mask(e, sfreq).mean(axis=1) for e in good])
        add("flat_fraction", flat, "ratio", "marked_samples(abs(diff)<=0.1uV continuously >=5s)/samples",
            details={"epochs_are_never_concatenated": True})
    else:
        add("flat_fraction", None, "ratio", "flat_0.1uv_5seconds",
            reason="physical_voltage_required" if not physical else "no_contiguous_5_second_epoch",
            status="not_applicable")
    for mid, units in (("numerical_rank", "dimensions"), ("covariance_condition", "ratio"),
                       ("covariance_trace", power_unit), ("participation_rank", "dimensions")):
        observations = [_rank_covariance(e, physical)[mid] for e in good]
        vals = [o["value"] for o in observations]
        add(mid, vals if vals else None, units,
            {"numerical_rank": "count(svd(X-mean_t(X))>smax*max(C,T)*eps_float64)",
             "covariance_condition": "lambda_max/lambda_min; singular -> null",
             "covariance_trace": "trace((X-mean_t(X))@(X-mean_t(X)).T/(T-1))",
             "participation_rank": "sum(lambda)^2/sum(lambda^2)"}[mid],
            direction="feasibility" if mid == "numerical_rank" else "non_monotonic",
            reason=next((o["reason"] for o in observations if o["reason"]), None),
            details={"valid_epoch_indices": np.flatnonzero(valid).tolist(), "covariance_ddof": 1})

    psd = None
    if duration >= 2 and len(good):
        seg = min(round(4 * sfreq), t)
        freqs, psd = welch(good, fs=sfreq, window="hamming", nperseg=seg,
                            noverlap=seg // 2, nfft=seg, detrend="constant",
                            scaling="density", average="median", axis=-1)
        details = {"frequencies_hz": freqs.tolist(), "nperseg": seg,
                   "nfft": seg, "resolution_hz": sfreq / seg,
                   "inherited_filter_history": "caller_must_check",
                   "aggregation": "per_epoch_per_channel_linear_PSD"}
        add("psd", psd, power_unit + "/Hz", "median_bias_corrected_Welch_Hamming_50pct", details=details)
        full_windows = [epoch[:, start:end] for epoch in good for start, end in sample_windows
                        if end - start == round(4 * sfreq)]
        if full_windows:
            wf, wp = welch(np.asarray(full_windows), fs=sfreq, window="hamming",
                           nperseg=round(4 * sfreq), noverlap=0, nfft=round(4 * sfreq),
                           detrend="constant", scaling="density", average="mean", axis=-1)
            quantiles = np.quantile(np.median(wp, axis=1), [0.1, 0.5, 0.9], axis=0)
            add("psd_window_quantiles", quantiles, power_unit + "/Hz",
                "Q10/Q50/Q90_over_full_4s_windows(channel_median_PSD)",
                details={"frequencies_hz": wf.tolist(), "full_windows": len(full_windows),
                         "excluded_short_tail_windows": len(parts) - len(full_windows),
                         "window_channel_median_psd": np.median(wp, axis=1).tolist(),
                         "windows": [{"epoch_index": int(i), "start_seconds_in_epoch": start / sfreq,
                                      "stop_seconds_in_epoch": end / sfreq}
                                     for i in np.flatnonzero(valid) for start, end in sample_windows
                                     if end - start == round(4 * sfreq)]})
        else:
            add("psd_window_quantiles", None, power_unit + "/Hz", "full_4s_window_PSD_quantiles",
                reason="no_complete_4_second_window; shorter_epoch_PSD_is_reported_separately",
                status="not_applicable")
        for label, lo, hi in (("mu", 8., 12.), ("beta", 13., 30.)):
            bp = _band_mean(freqs, psd, lo, hi) if sfreq / 2 > hi else None
            add(label + "_mean_psd", bp, power_unit + "/Hz", f"mean_f(PSD), {lo}-{hi}Hz",
                reason=None if bp is not None else "complete_band_below_nyquist_required",
                status=None if bp is not None else "not_applicable")
        hf = _db_ratio(_band_mean(freqs, psd, 30, 45), _band_mean(freqs, psd, 1, 30)) if sfreq / 2 > 45 else None
        add("emg_hf_proxy", hf, "dB", "10log10(meanPSD[30,45]/meanPSD[1,30]);closed_bins",
            direction="lower_residual_only", reason=None if hf is not None else "requires_45_hz_bandwidth",
            status=None if hf is not None else "not_applicable",
            details={"specific_to_emg": False, "lowpass_can_mechanically_reduce": True})
        for f0 in (50., 60.):
            if sfreq / 2 > f0 + 3:
                center = _band_mean(freqs, psd, f0 - 1, f0 + 1, include_upper=False)
                left = _band_mean(freqs, psd, f0 - 3, f0 - 1, include_upper=False)
                right = _band_mean(freqs, psd, f0 + 1, f0 + 3, include_upper=False)
                ratio = _db_ratio(center, (left + right) / 2)
            else:
                ratio = None
            add(f"line_ratio_{int(f0)}hz", ratio, "dB", "10log10(meanPSD[target+-1]/mean(two_2Hz_sidebands))",
                direction="lower_residual_only", reason=None if ratio is not None else "target_and_both_sidebands_unavailable",
                status=None if ratio is not None else "not_applicable",
                details={"disjoint_half_open_bins": True, "mains_frequency_not_inferred": True,
                         "previous_notch_requires_parent_not_applicable_override": True})
    else:
        for key in ("psd", "psd_window_quantiles", "mu_mean_psd", "beta_mean_psd", "emg_hf_proxy", "line_ratio_50hz", "line_ratio_60hz"):
            add(key, None, power_unit + "/Hz" if "psd" in key else "dB", key,
                reason="no_finite_epoch_of_at_least_2_seconds", status="not_applicable")
    if duration >= 30 and len(good):
        time = np.arange(t, dtype=float) / sfreq
        time -= time.mean()
        slopes = np.sum((good - good.mean(axis=-1, keepdims=True)) * time, axis=-1) / np.sum(time**2)
        add("drift_slope", slopes, unit + "/s", "OLS_slope(time_seconds,voltage),minimum30s",
            details={"nonlinear_drift_not_captured": True})
        if sfreq / 2 > 30:
            df, dp = welch(good, fs=sfreq, window="hamming", nperseg=round(30*sfreq),
                           noverlap=round(30*sfreq)//2, nfft=round(30*sfreq),
                           detrend="constant", scaling="density", average="median", axis=-1)
            def integral(lo, hi):
                mask = (df >= lo) & (df <= hi)
                return np.trapz(dp[..., mask], x=df[mask], axis=-1)
            drift = _db_ratio(integral(0.1, 0.5), integral(1, 30))
            add("drift_power_ratio", drift, "dB", "10log10(integralPSD[0.1,0.5]/integralPSD[1,30])",
                direction="lower_residual_only", details={"requires_inherited_highpass_below_0.1Hz": True})
        else:
            add("drift_power_ratio", None, "dB", "low_frequency_integrated_power_ratio",
                reason="requires_complete_0.1_30_hz_band", status="not_applicable")
    else:
        add("drift_slope", None, unit + "/s", "OLS_slope_minimum30s",
            reason="no_contiguous_30_second_epoch", status="not_applicable")
        add("drift_power_ratio", None, "dB", "low_frequency_integrated_power_ratio",
            reason="no_contiguous_30_second_epoch", status="not_applicable")
    if physical and positions is not None:
        if isinstance(positions, dict):
            if not all(name in positions for name in channels):
                raise ValueError("montage requires every declared channel")
            positions = np.asarray([positions[name] for name in channels], dtype=float)
        else:
            positions = np.asarray(positions, dtype=float)
        if positions.shape != (c, 3) or not np.isfinite(positions).all():
            raise ValueError("montage_positions requires finite channel x 3 coordinates")
        distances = np.linalg.norm(positions[:, None] - positions[None, :], axis=-1)
        pairs = [(i, j) for i in range(c) for j in range(i + 1, c)]
        ed = np.array([[np.var(e[i] - e[j], ddof=0) for i, j in pairs] for e in good])
        add("electrical_distance", ed if pairs and len(good) else None, "µV²", "Var_t(x_i-x_j),ddof0",
            details={"channel_pairs": [[channels[i], channels[j]] for i, j in pairs],
                     "montage_distances_input_units": [float(distances[i, j]) for i, j in pairs],
                     "bridge_diagnosis": False})
    else:
        add("electrical_distance", None, "µV²", "Var_t(x_i-x_j)",
            reason="physical_montage_unavailable", status="not_applicable")
    if reference is not None:
        valid_pair = valid & np.isfinite(reference).all(axis=(1, 2))
        a, b = reference[valid_pair], values[valid_pair]
        rms = np.sqrt(np.mean(a**2, axis=-1))
        err = np.sqrt(np.mean((b-a)**2, axis=-1))
        nrmse = np.divide(err, rms, out=np.full(rms.shape, np.nan), where=rms > 0)
        add("reference_nrmse", nrmse if len(a) else None, "ratio", "RMS(after-before)/RMS(before)",
            direction="lower_change_only", details={"reference_is_not_clean_ground_truth": True,
                                                    "paired_epoch_indices": np.flatnonzero(valid_pair).tolist()})
    else:
        add("reference_nrmse", None, "ratio", "RMS(after-before)/RMS(before)",
            reason="reference_epochs_unavailable", status="not_applicable")
    for label, lo, hi in (("mu", 8., 12.), ("beta", 13., 30.)):
        erds = None
        reason, status = "baseline_epochs_unavailable", "not_applicable"
        extra = {"positive_is_ers": True, "negative_is_erd": True,
                 "definition": "band_mean_Welch_power_ERDS; not a multitaper TFR",
                 "baseline_source": "parent_supplied_real_precue" if baseline is not None else None}
        if baseline is not None:
            if baseline.shape[-1] / sfreq < 2 or duration < 2 or sfreq / 2 <= hi:
                reason = "insufficient_baseline_duration_or_bandwidth"
            else:
                # Same window duration and spectral grid in both periods.
                segment = min(round(4 * sfreq), t, baseline.shape[-1])
                both = valid & np.isfinite(baseline).all(axis=(1, 2))
                erds = np.full((n, c), np.nan)
                bp_full = np.full((n, c), np.nan)
                if both.any():
                    def powers(x):
                        f, p = welch(x, fs=sfreq, window="hamming", nperseg=segment,
                                     noverlap=segment // 2, nfft=segment, detrend="constant",
                                     scaling="density", average="median", axis=-1)
                        return _band_mean(f, p, lo, hi)
                    task_bp = powers(values[both])
                    base_bp = powers(baseline[both])
                    normalized = np.full(base_bp.shape, np.nan)
                    np.divide(task_bp-base_bp, base_bp, out=normalized,
                              where=np.isfinite(base_bp) & (base_bp > 0))
                    erds[both] = 100 * normalized
                    bp_full[both] = base_bp * 1e12
                reason = None if np.isfinite(erds).all() else "nonpositive_or_nonfinite_baseline"
                status = None
                extra.update(baseline_power_uv2_per_hz=_json_value(bp_full), nperseg=segment,
                             baseline_n_samples=baseline.shape[-1])
        add("erds_" + label, erds, "%", "100*(task_band_linear_power-baseline_band_linear_power)/baseline_band_linear_power",
            reason=reason, status=status, details=extra)
    return QualityMetrics(unit="V" if physical else "dimensionless", sfreq=float(sfreq),
                          channel_names=channels, n_epochs=n, n_samples_per_epoch=t,
                          metrics=metrics, metadata={
                              "aggregation_scope": "one_subject_or_record; parent_aggregates_subjects",
                              "input_unit_contract": "genuine_physical_volts" if physical else "dimensionless_transformed_coordinates",
                              "no_unit_inference": True, "measurement_filter_applied": False,
                              "spectral_passband_history": "not_in_signature; parent_must_gate_inherited_filters",
                              "amplitude_view": "supplied_view; caller_prepares_common_0.5_45Hz_if_required",
                              "baseline_alignment_contract": "same_trials_channels_reference_processing; real_precue",
                              "scored_grid_is_not_baseline": True, "composite_score": None,
                              "source_arrays_modified": False, "scientific_quality_certified": False,
                          })
