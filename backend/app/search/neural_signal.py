"""Label-free ROI time-frequency descriptions with explicit baseline/edge support."""

import numpy as np


def task_tfr(values, baseline, sfreq, channels, trial_ids, history):
    result = {"schema_version": "neural-tfr-1", "status": "not_applicable",
              "reason": "verified_baseline_and_trial_ids_required", "unit": "%",
              "limitations": ["Descriptive sensor-space ROI; not source localization or neural preservation certification.",
                              "No labels or mandatory ERD direction; time is relative to the supplied epoch start.",
                              "Zero-phase preprocessing can spread activity across time; wavelet edges are masked."],
              "history": history, "channels": [], "selection_role": "descriptive_only"}
    if baseline is None or trial_ids is None:
        return result
    x, b = np.asarray(values), np.asarray(baseline)
    if x.ndim != 3 or b.ndim != 3 or x.shape[:2] != b.shape[:2] or len(trial_ids) != len(x):
        raise ValueError("TFR task/baseline/trial axes differ")
    roi = [i for i, c in enumerate(channels) if c.lower() in {"c3", "cz", "c4"}]
    if not roi:
        result["reason"] = "sensorimotor_roi_missing"
        return result
    valid = np.isfinite(x).all(axis=(1, 2)) & np.isfinite(b).all(axis=(1, 2))
    result.update(channels=[channels[i] for i in roi], expected_trials=len(x), paired_trials=int(valid.sum()),
                  missing_trial_ids=[t for t, ok in zip(trial_ids, valid) if not ok])
    band = history.get("nominal_band_hz")
    if not valid.any() or not band or None in band:
        result["reason"] = "no_finite_pairs_or_unknown_passband"
        return result
    freqs = np.array([f for f in range(8, 31, 2) if band[0] <= f <= band[1] and f < sfreq / 2])
    if not len(freqs):
        result["reason"] = "roi_frequencies_outside_passband"
        return result
    cycles, decim = 3.0, max(1, int(sfreq // 40))
    edges = np.ceil(5 * cycles * sfreq / (2 * np.pi * freqs)).astype(int)
    if 2 * max(edges) + 1 >= min(x.shape[-1], b.shape[-1]):
        result["reason"] = "insufficient_wavelet_support"
        return result
    from mne.time_frequency import tfr_array_morlet
    options = dict(sfreq=sfreq, freqs=freqs, n_cycles=cycles, zero_mean=True, use_fft=True,
                   decim=decim, output="power", n_jobs=1, verbose=False)
    power = tfr_array_morlet(x[valid][:, roi] * 1e6, **options)
    base = tfr_array_morlet(b[valid][:, roi] * 1e6, **options)
    ticks, bticks = np.arange(0, x.shape[-1], decim), np.arange(0, b.shape[-1], decim)
    base_mean = np.stack([base[:, :, i, :][..., (bticks >= e) & (bticks < b.shape[-1] - e)].mean(-1)
                          for i, e in enumerate(edges)], axis=-1)
    if not np.isfinite(base_mean).all() or (base_mean <= 0).any():
        result["reason"] = "nonpositive_or_nonfinite_baseline_power"
        return result
    change = (100 * (power / base_mean[..., None] - 1)).mean(axis=0)
    support = (ticks[None, :] >= edges[:, None]) & (ticks[None, :] < x.shape[-1] - edges[:, None])
    change[:, ~support] = np.nan
    result.update(status="ok" if valid.all() else "partial", reason=None if valid.all() else "missing_paired_trials",
                  frequencies_hz=freqs.tolist(), times_seconds=(ticks / sfreq).tolist(),
                  erds_percent=[[[float(v) if np.isfinite(v) else None for v in row] for row in ch] for ch in change],
                  baseline_mean_uv2=base_mean.mean(0).tolist(), support_mask=support.tolist(),
                  parameters={"n_cycles": cycles, "decim": decim, "zero_mean": True,
                              "aggregation": "equal_trial_mean_of_within_trial_percent_change"})
    return result
