"""Paired, semi-synthetic EEG reconstruction probes (NumPy/SciPy only).

The reference is a real-EEG cleanproxy, never neural ground truth. Read the
integration protocol in docs/preprocessing-evaluation.md. No scalar ranking,
processor execution, filesystem access, or parameter fitting occurs here.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence

import numpy as np
from scipy.signal import butter, sosfiltfilt


ARRAY_NAMES = (
    "reference",
    "contaminated",
    "cleaned",
    "contamination",
    "processed_reference",
)
KINDS = ("eog", "emg", "drift", "line", "pulse")
SCHEMA_VERSION = "reconstruction-v1"
LIMITATIONS = [
    "Real EEG reference is a cleanproxy, not neural ground truth.",
    "Results apply only to the declared injected artifacts and paired windows.",
    "Paired residual includes nonlinear processor interactions, not just artifact.",
    "Correlation and paired reconstruction alone cannot establish preservation.",
    "Caller must verify execution provenance and identical array ordering.",
    "No independent-test or overall cleaning-quality claim is made.",
]


def _array(value):
    raw = np.asarray(value)
    if raw.dtype.kind not in "fiu":
        raise ValueError("arrays must contain real numeric samples")
    result = np.asarray(raw, dtype=np.float64)
    if result.ndim != 3 or min(result.shape) < 1 or result.shape[-1] < 2:
        raise ValueError("arrays must have shape (windows, channels, samples>=2)")
    if not np.isfinite(result).all():
        raise ValueError("arrays must contain finite samples")
    return result


def _sfreq(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("sfreq must be a positive finite number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("sfreq must be a positive finite number")
    return float(value)


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be positive and finite")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return float(value)


def _strings(values, name, *, unique=True):
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError(f"{name} must be a nonempty list")
    if any(not isinstance(v, str) or not v for v in values):
        raise ValueError(f"{name} must contain nonempty strings")
    if unique and len(set(values)) != len(values):
        raise ValueError(f"{name} must not contain duplicates")
    return list(values)


def _rms(value):
    # Callers first divide all arrays by one common window scale.
    return float(np.sqrt(np.mean(np.square(value))))


def _metric(value=None, status="ok", **counts):
    if value is not None:
        value = float(value)
        if not math.isfinite(value):
            value, status = None, "numeric_overflow"
    return {"value": value, "status": status, **counts}


def _ratio(numerator, denominator, reason):
    if denominator == 0:
        return _metric(status=reason)
    return _metric(numerator / denominator)


def _db_improvement(before, after):
    if before == 0:
        return _metric(status="no_contamination")
    if after == 0:
        return _metric(status="zero_error")
    return _metric(20 * (math.log10(before) - math.log10(after)))


def _correlation(left, right):
    values = []
    for a, b in zip(left, right, strict=True):
        a, b = a - a.mean(), b - b.mean()
        ar, br = _rms(a), _rms(b)
        if ar > 0 and br > 0:
            values.append(float(np.clip(np.mean((a / ar) * (b / br)), -1, 1)))
    counts = {"n_valid_channels": len(values), "n_channels": len(left)}
    if len(values) != len(left):
        return _metric(status="constant_channel", **counts)
    return _metric(np.mean(values), **counts)


def _window_metrics(x, y, z, a, q):
    scale = max(float(np.max(np.abs(v))) for v in (x, y, z, a, q))
    if scale:
        x, y, z, a, q = (v / scale for v in (x, y, z, a, q))
    d = z - q
    xr, ar, qr, dr = (_rms(v) for v in (x, a, q, d))
    zr, er = _rms(z), _rms(z - x)
    gain = _ratio(float(np.mean(q * x)), xr * xr, "zero_reference")
    metrics = {
        "input_nrmse": _ratio(ar, xr, "zero_reference"),
        "paired_nrmse": _ratio(dr, qr, "zero_processed_reference"),
        "paired_error_cleanproxy_ratio": _ratio(dr, xr, "zero_reference"),
        "reconstruction_nrmse": _ratio(er, xr, "zero_reference"),
        "paired_ser_improvement_db": _db_improvement(ar, dr),
        "reconstruction_ser_improvement_db": _db_improvement(ar, er),
        "paired_correlation": _correlation(z, q),
        "reconstruction_correlation": _correlation(z, x),
        "artifact_residual_coefficient": _ratio(
            float(np.mean(d * a)), ar * ar, "no_contamination"
        ),
        "artifact_residual_rms_ratio": _ratio(dr, ar, "no_contamination"),
        "clean_retention_nrmse": _ratio(_rms(q - x), xr, "zero_reference"),
        "clean_retention_rms_ratio": _ratio(qr, xr, "zero_reference"),
        "clean_retention_correlation": _correlation(q, x),
        "clean_retention_gain": gain,
    }
    flags = []
    if qr == 0 and zr == 0:
        flags.append("zero_output")
    # These are numerical identities, not scientific quality thresholds.
    tolerance = 1e-10
    if _rms(q - x) <= tolerance * xr and _rms(z - y) <= tolerance * _rms(y):
        flags.append("identity_output")
    g = gain["value"]
    if g is not None and abs(g - 1) > tolerance:
        if _rms(q - g * x) <= tolerance * xr and _rms(z - g * y) <= tolerance * _rms(y):
            flags.append("pure_scaling_output")
    return metrics, flags


def _aggregate(rows):
    result = {}
    for name in rows[0]:
        values = [row[name]["value"] for row in rows]
        valid = [v for v in values if v is not None]
        # Never improve an aggregate by silently excluding undefined observations.
        result[name] = _metric(
            math.fsum(v / len(values) for v in valid)
            if len(valid) == len(values)
            else None,
            "ok" if len(valid) == len(values) else "incomplete",
            n_valid=len(valid),
            n_total=len(values),
        )
    return result


def _validate_space(space, sfreq, channels):
    if not isinstance(space, dict) or space.get("sfreq") != sfreq:
        raise ValueError("every array space must declare the same sfreq")
    if space.get("unit") not in ("V", "mV", "uV", "dimensionless"):
        raise ValueError("every array space must declare a supported common unit")
    if not isinstance(space.get("reference"), str) or not space["reference"]:
        raise ValueError("every array space must declare its EEG reference")
    if len(_strings(space.get("channels"), "channels")) != channels:
        raise ValueError("channel names must match arrays in the declared order")
    if "band_hz" not in space:
        raise ValueError("every array space must declare band_hz (null for unfiltered)")
    band = space["band_hz"]
    if band is not None:
        if not isinstance(band, (list, tuple)) or len(band) != 2:
            raise ValueError("band_hz must be null or [low, high]")
        low, high = (_positive(v, "band cutoff") for v in band)
        if not low < high < sfreq / 2:
            raise ValueError("band must satisfy 0 < low < high < Nyquist")


def _validate_metadata(metadata, arrays, sfreq):
    # Normalize only JSON metadata, never serialize input samples in the receipt.
    meta = json.loads(json.dumps(metadata, allow_nan=False))
    if not isinstance(meta, dict):
        raise ValueError("metadata must be a JSON object")
    if meta.get("reference_kind") != "real_eeg_cleanproxy":
        raise ValueError("reference_kind must be real_eeg_cleanproxy")
    if (
        not isinstance(meta.get("reference_provenance"), str)
        or not meta["reference_provenance"]
    ):
        raise ValueError("reference_provenance is required")
    processor = meta.get("processor", {})
    if (
        not isinstance(processor, dict)
        or not isinstance(processor.get("id"), str)
        or not processor["id"]
    ):
        raise ValueError("processor.id is required")
    if (
        processor.get("implemented") is not True
        or processor.get("paired_execution") is not True
    ):
        raise ValueError(
            "processor must declare implemented=true and paired_execution=true"
        )
    spaces = meta.get("spaces", {})
    if not isinstance(spaces, dict) or set(spaces) != set(ARRAY_NAMES):
        raise ValueError("spaces must describe all five arrays")
    for space in spaces.values():
        _validate_space(space, sfreq, arrays[0].shape[1])
    if any(space != spaces["reference"] for space in spaces.values()):
        raise ValueError(
            "array spaces differ: band, reference, units and channel order must match"
        )
    windows = meta.get("windows")
    expected = meta.get("expected_windows")
    if not isinstance(windows, list) or len(windows) != len(arrays[0]):
        raise ValueError("windows must identify every array row")
    if not isinstance(expected, dict) or not expected:
        raise ValueError(
            "expected_windows must declare all subjects and paired window IDs"
        )
    manifest = set()
    for subject, ids in expected.items():
        if not subject:
            raise ValueError("subject IDs must be nonempty")
        manifest.update((subject, w) for w in _strings(ids, "expected window IDs"))
    pairs = []
    for window in windows:
        if not isinstance(window, dict):
            raise ValueError("window entries must identify subject_id and window_id")
        pair = (window.get("subject_id"), window.get("window_id"))
        if any(not isinstance(v, str) or not v for v in pair):
            raise ValueError("window IDs and subject IDs must be nonempty strings")
        pairs.append(pair)
    if len(set(pairs)) != len(pairs) or set(pairs) != manifest:
        raise ValueError(
            "missing, duplicate or unexpected paired windows; no subset scoring"
        )
    injection = meta.get("injection", {})
    if not isinstance(injection, dict) or injection.get("kind") not in KINDS:
        raise ValueError("injection.kind must identify the known artifact")
    seed = injection.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("injection.seed must be a predeclared nonnegative integer")
    _positive(injection.get("rms_ratio"), "injection.rms_ratio")
    if "window_keys" in injection:
        if len(_strings(injection["window_keys"], "injection.window_keys")) != len(
            windows
        ):
            raise ValueError("injection window_keys must cover the full paired panel")
    if "sfreq" in injection and injection["sfreq"] != sfreq:
        raise ValueError("injection sampling rate differs from the evaluation")
    return meta


def evaluate_reconstruction(
    reference: np.ndarray,
    contaminated: np.ndarray,
    cleaned: np.ndarray,
    sfreq: float,
    contamination: np.ndarray,
    metadata: dict,
    *,
    processed_reference: np.ndarray | None = None,
) -> dict:
    """Measure P(x+a) vs P(x) AND P(x) vs x, on every declared window.

    Inputs share shape (windows, channels, samples), physical comparison space,
    and ordering. ``processed_reference`` is mandatory for scoring. Bad inputs
    return status=invalid_input and no metrics; missing implementation returns
    status=not_implemented. Undefined metric values are null with a reason.
    Metadata and full formulas are documented in reconstruction.md.
    """
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "invalid_input",
        "reference_kind": "real_eeg_cleanproxy",
        "limitations": list(LIMITATIONS),
        "windows": [],
        "subjects": {},
        "summary": {},
    }
    if isinstance(metadata, dict) and isinstance(metadata.get("processor"), dict):
        if metadata["processor"].get("implemented") is False:
            return {
                **receipt,
                "status": "not_implemented",
                "reason": "processor not implemented",
            }
    try:
        sfreq = _sfreq(sfreq)
        if processed_reference is None:
            raise ValueError("processed_reference=P(cleanproxy) is required")
        arrays = [
            _array(v)
            for v in (
                reference,
                contaminated,
                cleaned,
                contamination,
                processed_reference,
            )
        ]
        if any(v.shape != arrays[0].shape for v in arrays):
            raise ValueError(
                "array shapes differ; dropped channels/windows/samples are not aligned"
            )
        meta = _validate_metadata(metadata, arrays, sfreq)
        for i, window in enumerate(meta["windows"]):
            x, y, z, a, q = (v[i] for v in arrays)
            scale = max(float(np.max(np.abs(v))) for v in (x, y, a))
            if scale and np.max(np.abs(y / scale - x / scale - a / scale)) > 1e-10:
                raise ValueError(
                    "contaminated must equal reference + known contamination"
                )
            with np.errstate(
                over="ignore", under="ignore", invalid="ignore", divide="ignore"
            ):
                metrics, flags = _window_metrics(x, y, z, a, q)
            receipt["windows"].append({**window, "metrics": metrics, "flags": flags})
        for subject in meta["expected_windows"]:
            rows = [
                w["metrics"] for w in receipt["windows"] if w["subject_id"] == subject
            ]
            receipt["subjects"][subject] = {
                "n_windows": len(rows),
                "metrics": _aggregate(rows),
            }
        receipt["summary"] = _aggregate(
            [s["metrics"] for s in receipt["subjects"].values()]
        )
        receipt.update(
            status="evaluated",
            metadata=meta,
            n_subjects=len(receipt["subjects"]),
            n_windows=len(receipt["windows"]),
            aggregation="mean_windows_then_equal_subject_mean",
        )
        # Protect the external strict-JSON boundary even on extreme numeric input.
        json.dumps(receipt, allow_nan=False)
        return receipt
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return {
            **receipt,
            "status": "invalid_input",
            "reason": str(exc),
            "windows": [],
            "subjects": {},
            "summary": {},
        }


def align_fair_targets(
    arrays: Mapping[str, np.ndarray],
    sfreq: float,
    *,
    channels: Sequence[str],
    input_unit: str,
    output_unit: str,
    source_reference: str,
    reference: str = "unchanged",
    band_hz: tuple[float, float] | None = None,
    trim_samples: int = 0,
) -> tuple[dict[str, np.ndarray], dict]:
    """Apply ONE predeclared linear transform to all arrays, without fitting.

    Prefer this before running P, on x and a, then form x+a. Input arrays must
    already have the same unit/reference/order. Physical-unit conversion,
    fourth-order Butterworth zero-phase bandpass, common average reference and
    symmetric fixed trimming are supported. No resampling, gain fitting,
    lag search, whitening or voltage-to-dimensionless conversion is allowed.
    Raises ValueError for invalid alignment; returns arrays plus shared space.
    """
    sfreq = _sfreq(sfreq)
    if not isinstance(arrays, Mapping) or not arrays:
        raise ValueError("a nonempty mapping of arrays is required")
    values = {key: _array(value) for key, value in arrays.items()}
    shape = next(iter(values.values())).shape
    if any(v.shape != shape for v in values.values()):
        raise ValueError("alignment requires identical shapes and ordering")
    if reference not in ("unchanged", "average"):
        raise ValueError("reference must be unchanged or average")
    if not isinstance(source_reference, str) or not source_reference:
        raise ValueError("source_reference must identify the shared input reference")
    if reference == "average" and shape[1] < 2:
        raise ValueError("average reference requires at least two channels")
    space = {
        "sfreq": sfreq,
        "unit": output_unit,
        "reference": source_reference if reference == "unchanged" else "average",
        "band_hz": list(band_hz) if band_hz is not None else None,
        "channels": list(channels),
    }
    _validate_space(space, sfreq, shape[1])
    factors = {"V": 1.0, "mV": 1e-3, "uV": 1e-6}
    if input_unit == output_unit == "dimensionless":
        factor = 1.0
    elif input_unit in factors and output_unit in factors:
        factor = factors[input_unit] / factors[output_unit]
    else:
        raise ValueError("cannot mix voltage and dimensionless representations")
    if isinstance(trim_samples, bool) or not isinstance(trim_samples, int):
        raise ValueError("trim_samples must be an integer")
    if trim_samples < 0 or shape[-1] - 2 * trim_samples < 2:
        raise ValueError("trim_samples removes too many samples")
    sos = (
        butter(4, band_hz, btype="bandpass", fs=sfreq, output="sos")
        if band_hz
        else None
    )
    output = {}
    for key, value in values.items():
        value = value.copy() * factor
        if reference == "average":
            value -= value.mean(axis=1, keepdims=True)
        if sos is not None:
            value = sosfiltfilt(sos, value, axis=-1)
        if trim_samples:
            value = value[..., trim_samples:-trim_samples].copy()
        if not np.isfinite(value).all():
            raise ValueError("alignment produced nonfinite values")
        output[key] = value
    space["alignment"] = {
        "filter": "butterworth_4_sosfiltfilt" if sos is not None else None,
        "trim_samples": trim_samples,
        "unit_factor": factor,
    }
    return output, space


def generate_contamination(
    reference: np.ndarray,
    sfreq: float,
    *,
    kind: str,
    seed: int,
    rms_ratio: float,
    window_keys: Sequence[str],
    line_frequency: float = 50.0,
    spatial_weights: Sequence[float] | None = None,
    template: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Return (x+a, a, injection manifest) without changing x or global RNG.

    Strength is RMS(a)/RMS(x) per window, not a paper-specific dB convention.
    Stable unique subject/window keys make synthesis invariant to row ordering.
    A measured artifact template of identical shape can replace engineering
    probes. Neither synthetic EOG nor EMG is a physiological head model.
    """
    x, sfreq = _array(reference), _sfreq(sfreq)
    ratio = _positive(rms_ratio, "rms_ratio")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be an explicit nonnegative integer")
    keys = _strings(window_keys, "window_keys")
    if len(keys) != len(x):
        raise ValueError("window_keys must match array rows")
    if kind == "line":
        line_frequency = _positive(line_frequency, "line_frequency")
        if line_frequency >= sfreq / 2:
            raise ValueError("line frequency must be below Nyquist")
    if kind == "emg" and template is None and sfreq <= 50:
        raise ValueError("synthetic EMG requires sfreq > 50 Hz")
    weights = (
        None if spatial_weights is None else np.asarray(spatial_weights, dtype=float)
    )
    if weights is not None and (
        weights.shape != (x.shape[1],) or not np.isfinite(weights).all()
    ):
        raise ValueError("spatial_weights must give one finite weight per channel")
    measured = None if template is None else _array(template)
    if measured is not None and measured.shape != x.shape:
        raise ValueError("artifact template must have the reference shape")
    contamination = np.empty_like(x)
    t = np.arange(x.shape[-1]) / sfreq
    for i, key in enumerate(keys):
        digest = hashlib.sha256(json.dumps([seed, kind, key]).encode()).digest()
        rng = np.random.Generator(np.random.PCG64(int.from_bytes(digest, "little")))
        w = rng.uniform(0.5, 1.5, x.shape[1]) if weights is None else weights
        if measured is not None:
            noise = measured[i].copy()
        elif kind == "eog":
            center = rng.uniform(0.25, 0.75) * t[-1]
            width = min(0.12, t[-1] / 8)
            noise = w[:, None] * np.exp(-0.5 * ((t - center) / width) ** 2)
        elif kind == "emg":
            sos = butter(
                4, [20, min(90, 0.45 * sfreq)], btype="bandpass", fs=sfreq, output="sos"
            )
            noise = sosfiltfilt(
                sos, rng.normal(size=x.shape[1:]), padlen=min(27, len(t) - 1)
            )
            envelope = 0.1 + np.exp(
                -0.5 * ((t - rng.uniform(0.25, 0.75) * t[-1]) / (t[-1] / 8)) ** 2
            )
            noise *= w[:, None] * envelope
        elif kind == "drift":
            frequency = (
                rng.uniform(0.1, min(0.5, sfreq / 4)) if sfreq > 0.4 else sfreq / 8
            )
            noise = w[:, None] * np.sin(
                2 * np.pi * frequency * t + rng.uniform(0, 2 * np.pi)
            )
        elif kind == "line":
            noise = w[:, None] * np.sin(
                2 * np.pi * line_frequency * t + rng.uniform(0, 2 * np.pi)
            )
        else:
            noise = np.zeros(x.shape[1:])
            indices = rng.choice(len(t), size=max(1, len(t) // 128), replace=False)
            noise[:, indices] = w[:, None] * rng.choice([-1.0, 1.0], len(indices))
        xs, ns = float(np.max(np.abs(x[i]))), float(np.max(np.abs(noise)))
        if xs == 0 or ns == 0:
            raise ValueError(
                "reference and contamination must have nonzero RMS in every window"
            )
        with np.errstate(over="ignore", invalid="ignore"):
            contamination[i] = (
                (noise / ns) * (_rms(x[i] / xs) / _rms(noise / ns)) * xs * ratio
            )
    with np.errstate(over="ignore", invalid="ignore"):
        corrupted = x + contamination
    if not np.isfinite(corrupted).all() or not np.isfinite(contamination).all():
        raise ValueError("contamination exceeds finite numeric range")
    plan = {
        "generator_version": SCHEMA_VERSION,
        "kind": kind,
        "seed": seed,
        "sfreq": sfreq,
        "source_shape": list(x.shape),
        "rng": "PCG64_SHA256_seed_kind_window_key",
        "rms_ratio": ratio,
        "strength_definition": "per_window_RMS_artifact_over_RMS_cleanproxy",
        "model": "recorded_template" if measured is not None else "engineering_probe",
        "window_keys": keys,
        "line_frequency": line_frequency if kind == "line" else None,
        "spatial_weights": weights.tolist() if weights is not None else None,
        "template_sha256": hashlib.sha256(measured.tobytes()).hexdigest()
        if measured is not None
        else None,
    }
    return corrupted, contamination, plan


def evaluate_negative_controls(
    reference: np.ndarray,
    contaminated: np.ndarray,
    sfreq: float,
    contamination: np.ndarray,
    metadata: dict,
    *,
    scale: float = 0.5,
) -> dict:
    """Run identity, zero and pure positive scaling through the same evaluator."""
    scale = _positive(scale, "scale")
    if scale == 1:
        raise ValueError("scaling control must differ from identity")
    x, y = _array(reference), _array(contaminated)
    results = {}
    for name, gain in (("identity", 1.0), ("zero", 0.0), ("scaling", scale)):
        meta = {
            **metadata,
            "processor": {
                "id": f"negative_control:{name}",
                "implemented": True,
                "paired_execution": True,
                "gain": gain,
            },
        }
        with np.errstate(over="ignore", invalid="ignore"):
            cleaned, processed = gain * y, gain * x
        results[name] = evaluate_reconstruction(
            x,
            y,
            cleaned,
            sfreq,
            contamination,
            meta,
            processed_reference=processed,
        )
    return results
