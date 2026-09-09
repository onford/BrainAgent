"""BrainAgent engineering adapters, NOT reproductions of PREP or clean_rawdata.

Detection: PREP-inspired amplitude/correlation diagnostics, explicitly simplified.
Interpolation: MNE 1.10.2 Raw.interpolate_bads, EEG spherical splines.
ASR: ASRpy 0.0.8 kernels with explicit complete-block covariance adaptation.
See catalog references and .local/research/ordering.* for evidence and limitations.
"""
from importlib import metadata
from pathlib import Path
import hashlib
import warnings
from types import FunctionType

import mne
import numpy as np


class CleaningError(ValueError):
    def __init__(self, code, message, **details):
        self.code, self.details = code, details
        super().__init__(f"{code}: {message}")


def _require(condition, code, message, **details):
    if not condition:
        raise CleaningError(code, message, **details)


def _input(x):
    _require(isinstance(x, mne.io.BaseRaw), "CONTINUOUS_REQUIRED", "Raw input required")
    values = x.get_data()
    _require(values.size and np.isfinite(values).all(), "NONFINITE_INPUT", "finite physical V required")
    picks = mne.pick_types(x.info, eeg=True, exclude=[])
    _require(len(picks) >= 4, "TOO_FEW_EEG", "at least four EEG channels required")
    _require(all(int(x.info["chs"][i]["unit"]) == 107 for i in picks),
             "PHYSICAL_V_REQUIRED", "EEG must have MNE SI volt units")
    # Joins need segment-local calibration/filter state. Do not cross them silently.
    boundaries = [str(d) for d in x.annotations.description
                  if str(d).lower().startswith(("edge", "bad_acq_skip", "boundary"))]
    return values, picks, boundaries


def _out(x, y, **artifacts):
    _require(y.ch_names == x.ch_names and y.n_times == x.n_times
             and y.first_samp == x.first_samp and y.info["sfreq"] == x.info["sfreq"],
             "GRID_CHANGED", "cleaning must preserve the channel and sample grid")
    _require(y.annotations == x.annotations and y.get_channel_types() == x.get_channel_types(),
             "EVENT_METADATA_CHANGED", "cleaning must preserve annotations and channel types")
    _require(np.isfinite(y.get_data()).all(), "NONFINITE_OUTPUT", "cleaning output must be finite")
    return {"data": y, "model": None, "artifacts": {
        "units": "V", "shape_preserving": True, "trial_rejection": False,
        "implementation_kind": "brainagent_engineering_adapter", **artifacts}}


def _detect(x, p):
    values, picks, boundaries = _input(x)
    _require(not boundaries, "DISCONTINUOUS_INPUT", "split acquisition joins before detection", boundaries=boundaries)
    eeg = values[picks]
    sfreq = float(x.info["sfreq"])
    width = int(round(p["window_s"] * sfreq))
    count = eeg.shape[1] // width
    _require(count >= 5, "INSUFFICIENT_WINDOWS", "at least five complete diagnostic windows required")
    windows = eeg[:, :count * width].reshape(len(picks), count, width)
    ptp = np.ptp(windows, axis=-1)
    from scipy.ndimage import maximum_filter1d, minimum_filter1d
    flat_n = int(round(p["flat_duration_s"] * sfreq))
    _require(eeg.shape[1] >= flat_n, "INSUFFICIENT_FLAT_DURATION", "record shorter than flatness window")
    # Evaluate every valid duration window without allocating a sliding-window tensor.
    left = flat_n // 2
    stop = eeg.shape[1] - (flat_n - 1) // 2
    rolling_ptp = (maximum_filter1d(eeg, flat_n, axis=-1, mode="nearest")
                   - minimum_filter1d(eeg, flat_n, axis=-1, mode="nearest"))[:, left:stop]
    flat_windows = rolling_ptp <= p["flat_ptp_V"]
    flat = flat_windows.any(axis=1)
    first_flat = [int(np.argmax(row)) if flag else None for row, flag in zip(flat_windows, flat)]
    del rolling_ptp, flat_windows
    amplitude = np.median(np.std(windows, axis=-1), axis=1)
    eligible = np.array([x.ch_names[i] not in x.info["bads"] for i in picks]) & ~flat
    _require(eligible.sum() >= 3, "TOO_FEW_DONORS", "fewer than three nonflat unmarked channels")
    center = np.median(amplitude[eligible])
    spread = 1.4826 * np.median(np.abs(amplitude[eligible] - center))
    # A numerical floor prevents equal-amplitude channels producing infinite scores.
    spread = max(float(spread), np.finfo(float).eps * max(float(center), 1e-12))
    z = (amplitude - center) / spread
    high = z > p["deviation_z"]
    donors = eligible & ~high
    _require(donors.sum() >= 3, "TOO_FEW_DONORS", "amplitude diagnostics left fewer than three donors")
    correlations = np.zeros((len(picks), count))
    for w in range(count):
        block = windows[:, w] - windows[:, w].mean(axis=1, keepdims=True)
        norm = np.linalg.norm(block, axis=1)
        normalized = block / np.maximum(norm[:, None], np.finfo(float).tiny)
        corr = np.abs(normalized @ normalized.T)
        np.fill_diagonal(corr, 0)
        # Max peer correlation (not PREP's 98th percentile / filtered RANSAC).
        correlations[:, w] = np.max(corr[:, donors], axis=1)
    fraction = np.mean(correlations < p["correlation_threshold"], axis=1)
    lowcorr = fraction >= p["bad_window_fraction"]
    median_corr = np.median(correlations, axis=1)
    longest = np.zeros(len(picks), dtype=int)
    current = np.zeros(len(picks), dtype=int)
    for low in (correlations < p["correlation_threshold"]).T:
        current = np.where(low, current + 1, 0)
        longest = np.maximum(longest, current)
    longest_seconds = longest * width / sfreq
    coherent = high & (median_corr >= p["shared_correlation_threshold"])
    joint = high & lowcorr & ~coherent
    persistent = ((fraction >= p["persistent_low_corr_fraction"])
                  & (longest_seconds >= p["persistent_low_corr_seconds"]))
    selected = flat | joint | persistent
    names = [x.ch_names[i] for i in picks]
    evidence_masks = (("flat", flat), ("amplitude_deviation", high),
                      ("low_peer_correlation", lowcorr))
    selection_masks = (("flat", flat), ("joint_amplitude_low_correlation", joint),
                       ("persistent_low_correlation", persistent))
    reasons = {n: [k for k, mask in selection_masks if mask[i]] for i, n in enumerate(names)}
    diagnostics = {}
    for i, name in enumerate(names):
        classes = list(reasons[name])
        if coherent[i]:
            classes.append("suspected_correlated_artifact")
        elif high[i] and not selected[i]:
            classes.append("amplitude_outlier_uncertain")
        if lowcorr[i] and not selected[i]:
            classes.append("intermittent_low_correlation")
        diagnostics[name] = {
            "classes": classes or ["no_criterion_triggered"], "auto_mark": bool(selected[i]),
            "recommended_action": ("mark_then_spatial_interpolation" if selected[i] else
                "asr_and_quality_review" if coherent[i] else "quality_review" if classes else "retain"),
            "amplitude_robust_z": float(z[i]), "amplitude_std_V": float(amplitude[i]),
            "median_window_ptp_V": float(np.median(ptp[i])),
            "p95_window_ptp_V": float(np.quantile(ptp[i], .95)),
            "low_correlation_fraction": float(fraction[i]),
            "median_max_peer_correlation": float(median_corr[i]),
            "longest_low_correlation_seconds": float(longest_seconds[i]),
            "first_flat_sample_interval": ([first_flat[i], first_flat[i] + flat_n]
                                            if first_flat[i] is not None else None)}
    return _out(x, x.copy(), candidates=[n for i, n in enumerate(names) if selected[i]],
                diagnostic_schema_version="2", algorithm_version="brainagent-channel-consensus-2",
                selection_policy=p["selection_policy"], effective_parameters=p,
                threshold_evidence="engineering_priors_not_PREP_reproduction_or_validated_optima",
                reasons=reasons, diagnostic_flags={n: [k for k, m in evidence_masks if m[i]]
                                                  for i, n in enumerate(names)},
                channel_diagnostics=diagnostics, correlation_donors=[n for i, n in enumerate(names) if donors[i]],
                channel_names=names, amplitude_std_V=amplitude,
                amplitude_robust_z=z, max_peer_correlation=correlations,
                low_correlation_window_fraction=fraction, window_ptp_V=ptp,
                diagnostic_tail_samples=int(eeg.shape[1] - count * width),
                adaptation_scope=p["adaptation_scope"], labels_used=False,
                fit_sample_interval=[0, x.n_times],
                limitation="Engineering consensus: no RANSAC, robust-reference iteration or line-noise criterion. High correlation is not proof of normality; shared artifacts and bridged electrodes may remain. No EOG classification.")



def _interpolate(x, p):
    values, picks, _ = _input(x)
    names = [x.ch_names[i] for i in picks]
    bads = [n for n in names if n in x.info["bads"]]
    _require(len(bads) <= p["max_fraction"] * len(picks), "BAD_FRACTION_EXCEEDED",
             "marked EEG fraction exceeds interpolation cap", bads=bads, eeg_count=len(picks))
    y = x.copy().load_data()
    if not bads:
        return _out(x, y, repaired_channels=[], status="no_marked_eeg")
    _require(len(picks) - len(bads) >= 4, "TOO_FEW_DONORS", "spherical splines require at least four good EEG donors")
    positions = np.array([x.info["chs"][i]["loc"][:3] for i in picks])
    _require(np.isfinite(positions).all() and (np.linalg.norm(positions, axis=1) > 0).all(),
             "MISSING_GEOMETRY", "all EEG channels need finite nonzero head positions")
    _require(len(np.unique(positions, axis=0)) == len(picks), "DUPLICATE_GEOMETRY", "EEG positions must be distinct")
    _require(all(int(x.info["chs"][i]["coord_frame"]) == 4 for i in picks),
             "GEOMETRY_FRAME", "MNE head coordinates required")
    # Limit interpolation to EEG; do not clear/repair unrelated auxiliary bads.
    y.info["bads"] = bads
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        y.interpolate_bads(reset_bads=False, method={"eeg": "spline"}, verbose="ERROR")
    y.info["bads"] = [n for n in x.info["bads"] if n not in bads]
    unmodified = [i for i, n in enumerate(x.ch_names) if n not in bads]
    _require(np.array_equal(values[unmodified], y.get_data(picks=unmodified)),
             "DONOR_CHANGED", "interpolation changed a donor or auxiliary channel")
    return _out(x, y, repaired_channels=bads, donors=[n for n in names if n not in bads],
                bads_before=list(x.info["bads"]), bads_after=list(y.info["bads"]),
                positions_head_m=positions, method="MNE spherical spline", origin="auto",
                mne_version=metadata.version("mne"), warnings=[str(w.message) for w in caught])


def _complete_block_covariance(data, window=128):
    """SCCN asr_calibrate block indexing, including replicated final sample.

    Source: github.com/sccn/clean_rawdata/blob/master/asr_calibrate.m,
    'calculate the sample covariance matrices U', range=min(S,k:blocksize:S+k-1).
    ASRpy 0.0.8 subtracts different endpoints for allocation and indexing.
    """
    channels, samples = data.shape
    starts = np.arange(0, samples, window)
    covariance = np.zeros((len(starts), channels * channels))
    for offset in range(window):
        block = data[:, np.minimum(starts + offset, samples - 1)].T
        covariance += (block[:, None, :] * block[:, :, None]).reshape(covariance.shape)
    return covariance


def _calibration_kernel(source):
    """Bind one reviewed dependency locally; never mutate upstream module globals."""
    kernel = source.asr_calibrate
    scope = {**kernel.__globals__, "block_covariance": _complete_block_covariance}
    return FunctionType(kernel.__code__, scope, kernel.__name__, kernel.__defaults__, kernel.__closure__)


def _calibration_shortage(x, p, picks, rank, clean_seconds, mask=None, caught=()):
    from asrpy import asr as source
    message = ("record shorter than calibration requirement" if clean_seconds is None else
               "insufficient samples selected for calibration; output was not truncated")
    details = {"clean_seconds": clean_seconds, "required": p["min_clean_seconds"],
               "calibration_selection_performed": mask is not None,
               "available_record_seconds": x.n_times / x.info["sfreq"]}
    if p["on_insufficient_calibration"] == "error":
        raise CleaningError("ASR_CALIBRATION_TOO_SHORT", message, **details)
    source_files = [Path(source.__file__), Path(source.__file__).with_name("asr_utils.py")]
    return _out(x, x.copy(), algorithm_version="brainagent-asrpy-complete-blocks-3",
        on_insufficient_calibration=p["on_insufficient_calibration"],
        status="not_applicable", asr_applied=False, model_created=False, data_action="identity",
        not_applicable_code="ASR_CALIBRATION_TOO_SHORT", not_applicable_reason=message,
        actual_calibration_seconds=clean_seconds, minimum_calibration_seconds=p["min_clean_seconds"],
        clean_seconds=clean_seconds, calibration_selection_performed=mask is not None,
        available_record_seconds=x.n_times / x.info["sfreq"], calibration_sample_mask=mask,
        calibration_rank=None, input_rank=rank, channels=[x.ch_names[i] for i in picks],
        excluded_bads=list(x.info["bads"]), adaptation_scope=p["adaptation_scope"], labels_used=False,
        fit_sample_interval=[0, x.n_times], warnings=[str(w.message) for w in caught],
        source_version=metadata.version("asrpy"),
        source_hashes={f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in source_files},
        limitations=["ASR was not applied: explicitly declared identity on insufficient calibration.",
                     "The complete step input is retained; its artifacts may remain.",
                     "Downstream declared operations still execute; cohort ASR application is incomplete."])


def _asr(x, p):
    values, picks, boundaries = _input(x)
    _require(not boundaries, "DISCONTINUOUS_INPUT", "ASR state must not cross acquisition joins", boundaries=boundaries)
    sfreq = float(x.info["sfreq"])
    _require(sfreq > 82, "ASR_SFREQ_UNSUPPORTED", "ASRpy default spectral knots require sfreq > 82 Hz")
    _require(x.info["highpass"] >= 0.5, "ASR_HIGHPASS_REQUIRED", "high-pass at least 0.5 Hz before calibration")
    _require(p["win_len"] * x.info["highpass"] >= 0.5,
             "ASR_WINDOW_HIGHPASS", "window must span at least half the high-pass cycle")
    _require(0 < p["lookahead"] <= p["win_len"] / 2 and p["stepsize"] <= p["win_len"] * sfreq,
             "ASR_WINDOW_PARAMETERS", "lookahead <= win_len/2 and stepsize <= win_len*sfreq")
    delay = sfreq * p["lookahead"]
    _require(delay >= 1 and np.isclose(delay, round(delay), rtol=0, atol=1e-9),
             "ASR_LOOKAHEAD_GRID", "positive integral lookahead samples prevent ASRpy floor/round mismatch")
    picks = np.array([i for i in picks if x.ch_names[i] not in x.info["bads"]])
    _require(len(picks) >= 4, "TOO_FEW_DONORS", "at least four unmarked EEG channels needed for ASR")
    eeg = values[picks]
    centered = eeg - eeg.mean(axis=1, keepdims=True)
    singular = np.linalg.svd(centered, compute_uv=False)
    rank = int(np.sum(singular > singular[0] * max(centered.shape) * np.finfo(float).eps))
    ratio = float(singular[-1] / singular[0]) if singular[0] else 0
    _require(rank == len(picks) and ratio > 1e-8 and not x.info["custom_ref_applied"], "ASR_FULL_RANK_REQUIRED",
             "ASR adapter requires numerically full-rank good EEG before CAR/interpolation",
             rank=rank, channels=len(picks), singular_ratio=ratio, minimum_ratio=1e-8,
             custom_ref_applied=int(x.info["custom_ref_applied"]))
    try:
        version = metadata.version("asrpy")
    except metadata.PackageNotFoundError as exc:
        raise CleaningError("ASR_DEPENDENCY", "install asrpy==0.0.8 with --no-deps in the EEG environment") from exc
    _require(version == "0.0.8", "ASR_DEPENDENCY", "asrpy==0.0.8 required", installed=version)
    if x.n_times / sfreq < p["min_clean_seconds"]:
        return _calibration_shortage(x, p, picks, rank, None)
    from asrpy import asr as source
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        estimator = source.ASR(sfreq=sfreq, cutoff=p["cutoff"], win_len=p["win_len"],
                               win_overlap=p["win_overlap"], method="euclid")
        # The same calls as ASR.fit, with guards BEFORE calibrating the selected data.
        clean, mask = source.clean_windows(eeg, sfreq=sfreq, win_len=p["win_len"],
            win_overlap=p["win_overlap"], max_bad_chans=estimator.max_bad_chans,
            min_clean_fraction=estimator.min_clean_fraction,
            max_dropout_fraction=estimator.max_dropout_fraction)
        clean_seconds = clean.shape[1] / sfreq
        if clean_seconds < p["min_clean_seconds"]:
            return _calibration_shortage(x, p, picks, rank, clean_seconds, mask, caught)
        clean_rank = int(np.linalg.matrix_rank(clean - clean.mean(axis=1, keepdims=True)))
        _require(clean_rank == len(picks), "ASR_CALIBRATION_RANK", "selected calibration is rank deficient", rank=clean_rank)
        estimator.M, estimator.T = _calibration_kernel(source)(clean, sfreq=sfreq,
            cutoff=p["cutoff"], blocksize=estimator.blocksize, win_len=p["win_len"],
            win_overlap=p["win_overlap"], max_dropout_fraction=estimator.max_dropout_fraction,
            min_clean_fraction=estimator.min_clean_fraction, ab=(estimator.A, estimator.B), method="euclid")
        for matrix in (estimator.M, estimator.T):
            _require(np.isrealobj(matrix) and np.isfinite(matrix).all(), "ASR_INVALID_CALIBRATION", "nonfinite or complex calibration matrix")
        _require(np.linalg.matrix_rank(estimator.M) == len(picks), "ASR_CALIBRATION_RANK", "mixing matrix is singular")
        y = estimator.transform(x.copy().load_data(), picks=picks.tolist(),
            lookahead=p["lookahead"], stepsize=p["stepsize"], maxdims=p["maxdims"],
            mem_splits=p["mem_splits"])
    residual = eeg - y.get_data(picks=picks)
    untouched = [i for i in range(len(x.ch_names)) if i not in picks]
    _require(not untouched or np.array_equal(values[untouched], y.get_data(picks=untouched)),
             "UNSELECTED_CHANGED", "ASR changed marked EEG or auxiliary data")
    source_files = [Path(source.__file__), Path(source.__file__).with_name("asr_utils.py")]
    return _out(x, y, adaptation_scope=p["adaptation_scope"], labels_used=False,
        fit_sample_interval=[0, x.n_times], calibration_sample_mask=mask,
        clean_seconds=clean_seconds, calibration_rank=clean_rank, input_rank=rank,
        channels=[x.ch_names[i] for i in picks], excluded_bads=list(x.info["bads"]),
        mixing_matrix=estimator.M, threshold_matrix=estimator.T,
        spectral_filter_A=estimator.A, spectral_filter_B=estimator.B,
        fixed_fit_parameters={"blocksize": estimator.blocksize, "max_bad_chans": estimator.max_bad_chans,
                              "min_clean_fraction": estimator.min_clean_fraction,
                              "max_dropout_fraction": estimator.max_dropout_fraction,
                              "zthresholds": [-3.5, 5], "method": "euclid"},
        correction_rms_V=np.sqrt(np.mean(residual ** 2, axis=1)),
        correction_max_abs_V=np.max(np.abs(residual), axis=1),
        algorithm_version="brainagent-asrpy-complete-blocks-3",
        calibration_covariance={"algorithm": "complete_blocks_repeat_last_sample",
            "upstream_adaptation": "ASRpy 0.0.8 block indexing replaced locally by SCCN complete-block semantics",
            "block_count": int(np.ceil(clean.shape[1] / estimator.blocksize)),
            "last_block_real_samples": int((clean.shape[1] - 1) % estimator.blocksize + 1),
            "upstream_endpoint_affected": clean.shape[1] % estimator.blocksize in (1, 2)},
        status="applied", asr_applied=True, model_created=True, data_action="asr_transform",
        on_insufficient_calibration=p["on_insufficient_calibration"],
        actual_calibration_seconds=clean_seconds, minimum_calibration_seconds=p["min_clean_seconds"],
        calibration_selection_performed=True, available_record_seconds=x.n_times / sfreq,
        not_applicable_code=None, not_applicable_reason=None,
        source_version=version, source_hashes={f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in source_files},
        warnings=[str(w.message) for w in caught],
        limitations=["Record-wide unlabeled/transductive adaptation, not train-only or online evaluation.",
                     "Automatic calibration selection is a statistical heuristic, not proof of artifact-free EEG.",
                     "ASRpy transform zero-pads the tail; final lookahead seconds can have boundary inaccuracies.",
                     "ASRpy 0.0.8 Euclidean implementation, not exact MATLAB clean_rawdata reproduction."])


def automatic_cleaning(op, x, model=None, **params):
    _require(model is None, "UNEXPECTED_MODEL", "record-local adapters do not accept fitted model ports")
    # Validate direct invocation too; internal functions never infer fit permission.
    from .. import validate_params
    unit = "EEG-ASR-AUTO" if op == "asr_clean" else "EEG-AUTO-BAD-CHANNEL"
    p = validate_params(unit, op, params)
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1, user_api="blas"):
        try:
            return {"detect_bad_channels": _detect, "interpolate_bad_channels": _interpolate,
                    "asr_clean": _asr}[op](x, p)
        except CleaningError:
            raise
        except (ValueError, RuntimeError, np.linalg.LinAlgError, IndexError, AssertionError) as exc:
            raise CleaningError("CLEANING_NUMERICAL_FAILURE", str(exc), operation=op) from exc
