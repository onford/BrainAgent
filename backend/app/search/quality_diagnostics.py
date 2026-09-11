"""Small deterministic signal previews, separate from all scoring metrics."""

import numpy as np


def diagnostic_views(values, sfreq, channels, positions=None, trial_ids=None):
    """First finite epoch, first <=4 seconds, at native samples (no decimation).

    This is an explicitly limited preview, not selection of the best/worst EEG.
    A per-channel overview uses min/max buckets to preserve short transients.
    No concatenation across epochs, no data-dependent trial/channel selection.
    """
    finite = np.flatnonzero(np.isfinite(values).all(axis=(1, 2)))
    if not len(finite):
        return {"status": "not_applicable", "reason": "no_finite_epoch"}
    index = int(finite[0])
    preferred = [c for c in ("C3", "Cz", "C4") if c in channels]
    names = preferred or list(channels[:3])
    data = np.asarray(values[index, [channels.index(c) for c in names]], dtype=float) * 1e6
    stop = min(data.shape[1], round(4 * sfreq))
    width = max(1, int(np.ceil(data.shape[1] / 256)))
    starts = list(range(0, data.shape[1], width))
    result = {
        "schema_version": "signal-preview-1", "status": "ok", "unit": "µV",
        "epoch_index": index, "trial_id": trial_ids[index] if trial_ids else None,
        "selection": "first_finite_epoch; C3/Cz/C4_if_present_else_first_three_channels",
        "channels": names, "sfreq": float(sfreq), "sample_count": int(data.shape[1]),
        "time_axis": "seconds_relative_to_supplied_epoch_start; not_inferred_cue_time",
        "waveform": {"times_seconds": (np.arange(stop)/sfreq).tolist(),
                     "values_uv": data[:, :stop].tolist(), "display_filter": None},
        "overview": {"start_seconds": [s/sfreq for s in starts],
                     "stop_seconds": [min(s+width, data.shape[1])/sfreq for s in starts],
                     "minimum_uv": [[float(row[s:s+width].min()) for s in starts] for row in data],
                     "maximum_uv": [[float(row[s:s+width].max()) for s in starts] for row in data]},
        "limitations": ["Preview does not cover all epochs or channels; full metrics retain their original denominator.",
                        "No display filtering, smoothing or resampling; overview envelopes are not a waveform."],
    }
    if positions is not None:
        p = np.asarray([positions[c] for c in channels] if isinstance(positions, dict) else positions)
        if p.shape == (len(channels), 3) and np.isfinite(p).all():
            result["sensor_layout"] = {"channels": list(channels), "positions_m": p.tolist(),
                                       "projection": "head_xy_no_interpolation",
                                       "provenance": "input_FIFF_channel_locations; may_be_standard_montage_not_individual_digitization"}
    return result
