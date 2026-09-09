"""Only explicitly enabled, statically imported operations can be executed."""

from importlib import import_module, metadata
import json
from pathlib import Path
import platform
from typing import Literal

from pydantic import Field
from ..schemas import Contract, UnitSpec
from ..storage import file_hash, digest

ROOT = Path(__file__).parent
PINNED = {
    "mne": "1.10.2",
    "mne-bids": "0.17.0",
    "numpy": "1.26.4",
    "scipy": "1.15.3",
    "scikit-learn": "1.6.1",
    "pandas": "2.2.3",
    "h5io": "0.2.5",
    "h5py": "3.13.0",
    "pybv": "0.7.6",
}


class FilterParams(Contract):
    l_freq: float | None
    h_freq: float | None
    method: Literal["iir"]
    phase: Literal["zero"]
    picks: list[str] = Field(min_length=1)


class DetrendParams(Contract):
    type: Literal["constant", "linear"]
    picks: list[str] = Field(min_length=1)


class ReferenceParams(Contract):
    ref_channels: Literal["average"] | list[str]


class EpochParams(Contract):
    events: Literal["$events"] = "$events"
    event_id: dict[str, int]
    tmin: float
    tmax: float
    picks: list[str] = Field(min_length=1)


class BaselineParams(Contract):
    baseline: tuple[float | None, float | None]


class ResampleParams(Contract):
    sfreq: float = Field(gt=0)
    events: Literal["$events"] = "$events"


class EogFitParams(Contract):
    picks: list[str] = Field(min_length=1)
    picks_artifact: list[str] = Field(min_length=1)
    reference_id: str = Field(min_length=1)


class EogApplyParams(Contract):
    reference_id: str = Field(min_length=1)


class AmplitudeParams(Contract):
    window_s: float = Field(default=1, gt=0)
    stride_s: float = Field(default=0.5, gt=0)
    tail: Literal["drop"] = "drop"
    valid_intervals: None = None
    min_windows: int = Field(default=1, ge=1, strict=True)
    peak_to_peak_limit_V: float = Field(default=1e-4, gt=0)
    frac_bad: float = Field(default=0.25, ge=0, le=1)


class MarkParams(Contract):
    max_fraction: float = Field(ge=0, lt=1)


# Each enabled operation has a deliberately bounded integrated parameter domain.
# Other ops remain discoverable in the catalog without silently widening support.
OPERATIONS = {
    ("EEG-DETREND", "detrend"): DetrendParams,
    ("EEG-FILTER", "filter"): FilterParams,
    ("EEG-RESAMPLE", "resample"): ResampleParams,
    ("EEG-REREFERENCE", "reference"): ReferenceParams,
    ("EEG-EPOCH", "epoch"): EpochParams,
    ("EEG-BASELINE", "baseline"): BaselineParams,
    ("EEG-EOG-REGRESSION", "eog_fit"): EogFitParams,
    ("EEG-EOG-REGRESSION", "eog_apply"): EogApplyParams,
    ("EEG-AMPLITUDE-THRESHOLD", "amplitude_windows"): AmplitudeParams,
    ("EEG-BAD-CHANNEL-MARK", "mark_channels"): MarkParams,
}


def catalog() -> list[UnitSpec]:
    rows = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
    for row in rows:
        supported = {
            op: schema.model_json_schema()
            for (unit, op), schema in OPERATIONS.items()
            if unit == row["id"]
        }
        row["implementation"].update(
            version="1",
            profile="source",
            enabled_ops=supported,
            dependencies=PINNED if supported else {},
            nonfinite_policy="reject" if supported else "op_specific_not_integrated",
        )
        row["validation"]["integration"] = (
            "enabled_bounded_domain" if supported else "not_enabled"
        )
        if supported:
            row["validation"]["evidence"] = (
                "tests/preprocessing; see acceptance report for executed coverage"
            )
    return [UnitSpec.model_validate(r) for r in rows]


def specification(unit_id: str) -> UnitSpec:
    return next((r for r in catalog() if r.id == unit_id), None) or _unknown(unit_id)


def _unknown(unit_id):
    raise ValueError(f"unknown unit id (no legacy remapping): {unit_id}")


def validate_params(unit: str, op: str, params: dict) -> dict:
    schema = OPERATIONS.get((unit, op))
    if schema is None:
        raise ValueError(f"operation not integrated: {unit}/{op}")

    # Prevent Pydantic from coercing bools into numeric scientific parameters.
    def reject_bool(value):
        if isinstance(value, bool):
            raise ValueError("boolean cannot substitute for a scientific parameter")
        if isinstance(value, dict):
            for v in value.values():
                reject_bool(v)
        if isinstance(value, (list, tuple)):
            for v in value:
                reject_bool(v)

    reject_bool(params)
    return schema.model_validate(params).model_dump(mode="json")


def environment() -> dict[str, str]:
    versions = {name: metadata.version(name) for name in PINNED}
    if versions != PINNED or platform.python_version_tuple()[:2] != ("3", "12"):
        raise ValueError(
            "EEG worker requires Python 3.12 and locked EEG dependencies; use uv sync --extra eeg --extra dev"
        )
    return {**versions, "python": platform.python_version()}


def engine_hash() -> str:
    root = ROOT.parent
    files = [*root.rglob("*.py"), ROOT / "catalog.json"]
    hashes = {p.relative_to(root).as_posix(): file_hash(p) for p in sorted(files)}
    hashes["../file_publish.py"] = file_hash(root.parent / "file_publish.py")
    return digest(hashes)


def invoke(unit_id: str, op: str, x, model=None, **params):
    if (unit_id, op) not in OPERATIONS:
        raise ValueError("operation not enabled")
    spec = specification(unit_id)
    module = spec.implementation["module"]
    if file_hash(ROOT / f"source/{module}.py") != spec.source["code_sha256"]:
        raise ValueError("source implementation checksum changed")
    entry = getattr(
        import_module(f"app.preprocessing.units.source.{module}"),
        spec.implementation["entry"],
    )
    return entry(op, x, model=model, **params)
