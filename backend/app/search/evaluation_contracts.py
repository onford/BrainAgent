"""Version 1 panel/evaluator contracts with optional worker metadata.

Early worker failures and invalid panels have coverage=None (unknown, not zero).
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Count = Annotated[int, Field(ge=0)]
Score = Annotated[float, Field(ge=0, le=1)]
Delta = Annotated[float, Field(ge=-1, le=1)]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Role = Literal["train", "development"]


class EvaluationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class OutputContract(EvaluationContract):
    channels: list[str] = Field(min_length=1)
    sfreq: float = Field(ge=160, le=160)
    tmin: float
    tmax: float
    epoch_start_offset: int
    epoch_end_offset: int
    n_times: int = Field(ge=2)

    @model_validator(mode="after")
    def sample_grid(self):
        if (
            self.tmin >= self.tmax
            or len(self.channels) != len(set(self.channels))
            or self.epoch_start_offset != round(self.tmin * self.sfreq)
            or self.epoch_end_offset != round(self.tmax * self.sfreq)
            or self.n_times != self.epoch_end_offset - self.epoch_start_offset + 1
        ):
            raise ValueError("inconsistent frozen EEG epoch grid")
        return self


class FrozenRecord(EvaluationContract):
    record_id: str
    subject: str
    role: Role
    n_samples: int = Field(gt=0)
    sfreq: float = Field(gt=0)
    resampled_n_samples: int = Field(gt=0)


class FrozenTrial(EvaluationContract):
    event_id: str
    record_id: str
    subject: str
    role: Role
    label: str
    source_sample: Count
    source_row: int = Field(ge=2)
    output_sample: Count
    epoch_start: int
    epoch_stop: int
    eligible: bool
    reason: Literal["NO_DATA", "TOO_SHORT", "RESAMPLE_EVENT_COLLISION"] | None

    @model_validator(mode="after")
    def original_identity(self):
        if (
            self.event_id != f"{self.record_id}:event:{self.source_row - 2}"
            or self.eligible != (self.reason is None)
            or self.epoch_stop <= self.epoch_start
        ):
            raise ValueError("inconsistent original trial identity/window")
        return self


class ClassLabels(EvaluationContract):
    left: Literal["left", "left_hand"]
    right: Literal["right", "right_hand"]


class FrozenPanel(EvaluationContract):
    evaluator_version: Literal[1]
    seed: int
    input_hash: Hash
    panel_hash: Hash
    train_subjects: list[str] = Field(min_length=1)
    development_subjects: list[str] = Field(min_length=1)
    class_labels: ClassLabels
    event_codes: dict[str, Annotated[int, Field(gt=0)]]
    records: dict[str, FrozenRecord] = Field(min_length=1)
    trials: list[FrozenTrial] = Field(min_length=1)
    output_contract: OutputContract


class GroupCoverage(EvaluationContract):
    original: Count
    eligible: Count
    available: Count
    predicted: Count
    missing: Count = Field(
        description="Eligible trials absent from the inspected candidate; eligible - available, not eligible - predicted."
    )
    common_invalid: Count
    common_invalid_reasons: dict[str, Count]

    @model_validator(mode="after")
    def denominator(self):
        if (
            not 0 <= self.predicted <= self.available <= self.eligible <= self.original
            or self.missing != self.eligible - self.available
            or self.common_invalid != self.original - self.eligible
            or sum(self.common_invalid_reasons.values()) != self.common_invalid
        ):
            raise ValueError("inconsistent coverage denominator")
        return self


class Coverage(GroupCoverage):
    """Every inherited top-level count is an alias of development coverage."""

    train: GroupCoverage
    development: GroupCoverage

    @model_validator(mode="after")
    def development_alias(self):
        if any(
            getattr(self, key) != getattr(self.development, key)
            for key in GroupCoverage.model_fields
        ):
            raise ValueError("top-level coverage must use the development denominator")
        if self.train.predicted != 0:
            raise ValueError("evaluator does not predict training trials")
        return self


class Recalls(EvaluationContract):
    left: Score | None
    right: Score | None


class SubjectEvaluation(EvaluationContract):
    """Value in receipt.subjects[development_subject_id]."""

    recalls: Recalls
    recall_left: Score | None
    recall_right: Score | None
    ba: Score | None
    delta: Delta | None
    original_trials: Count
    eligible_trials: Count
    available_trials: Count
    predicted_trials: Count
    missing: Count

    @model_validator(mode="after")
    def summary(self):
        if (
            not self.predicted_trials
            <= self.available_trials
            <= self.eligible_trials
            <= self.original_trials
            or self.missing != self.eligible_trials - self.available_trials
            or self.recall_left != self.recalls.left
            or self.recall_right != self.recalls.right
        ):
            raise ValueError("inconsistent subject summary")
        if self.ba is not None and (
            self.recall_left is None
            or self.recall_right is None
            or not math.isclose(
                self.ba, (self.recall_left + self.recall_right) / 2, abs_tol=1e-12
            )
        ):
            raise ValueError("subject BA must average the two recalls")
        return self


class EvaluationDiagnostics(EvaluationContract):
    floor_fraction: Score | None = None
    converged: bool | None = None
    warnings: list[str] = Field(default_factory=list)


class EvaluationTimings(EvaluationContract):
    feature: float | None = Field(default=None, ge=0)
    train: float | None = Field(default=None, ge=0)
    predict: float | None = Field(default=None, ge=0)
    preprocessing_seconds: float | None = Field(default=None, ge=0)
    evaluation_seconds: float | None = Field(default=None, ge=0)
    total_seconds: float | None = Field(default=None, ge=0)


class PlanReference(EvaluationContract):
    id: Hash
    sha256: Hash


class EvaluationVersions(EvaluationContract):
    worker_version: int = Field(ge=1)
    search_engine_sha256: Hash | None = None
    engine_sha256: Hash | None = None
    environment_sha256: Hash | None = None
    panel_hash: Hash | None = None
    input_hash: Hash | None = None
    method_hash: Hash | None = None


class EvaluationReceipt(EvaluationContract):
    evaluator_version: Literal[1] = 1
    status: Literal[
        "evaluated",
        "candidate_invalid",
        "data_unevaluable",
        "execution_failure",
        "resource_failure",
    ]
    panel_hash: str | None = None
    macro_ba: Score | None = None
    mean_delta: Delta | None = None
    subjects: dict[str, SubjectEvaluation] = Field(default_factory=dict)
    coverage: Coverage | None = None
    diagnostics: EvaluationDiagnostics = Field(default_factory=EvaluationDiagnostics)
    timings: EvaluationTimings = Field(default_factory=EvaluationTimings)
    attribution: str | None = None
    error_code: str | None = None
    error: str | None = None
    stop_search: bool = False
    predictions_path: str | None = None
    # Legacy evaluated receipts remain readable. New evaluate() always writes
    # this hash; the worker must require and verify it before cached reuse.
    predictions_sha256: Hash | None = None
    candidate_id: str | None = None
    job_id: str | None = None
    plan_ref: PlanReference | None = None
    preprocessing_seconds: float | None = Field(default=None, ge=0)
    evaluation_seconds: float | None = Field(default=None, ge=0)
    versions: EvaluationVersions | None = None

    @model_validator(mode="before")
    @classmethod
    def early_worker_stop(cls, value):
        # A worker may fail before evaluate() and have only status/error. Never
        # interpret its data_unevaluable receipt as permission to keep searching.
        if (
            isinstance(value, dict)
            and value.get("status") == "data_unevaluable"
            and "stop_search" not in value
        ):
            return {**value, "stop_search": True}
        return value

    @model_validator(mode="after")
    def outcome(self):
        if self.status == "data_unevaluable" and not self.stop_search:
            raise ValueError("data_unevaluable must stop the search")
        if self.status == "evaluated":
            if (
                self.macro_ba is None
                or not self.subjects
                or self.coverage is None
                or self.error is not None
                or self.error_code is not None
                or self.stop_search
                or not self.predictions_path
            ):
                raise ValueError(
                    "evaluated receipt requires complete development metrics"
                )
            if any(
                s.ba is None or s.missing or s.predicted_trials != s.eligible_trials
                for s in self.subjects.values()
            ):
                raise ValueError(
                    "evaluated subjects require complete frozen denominators"
                )
            if not math.isclose(
                self.macro_ba,
                sum(s.ba for s in self.subjects.values()) / len(self.subjects),
                abs_tol=1e-12,
            ):
                raise ValueError("macro BA must be the subject mean")
            deltas = [s.delta for s in self.subjects.values()]
            if self.mean_delta is None:
                if any(d is not None for d in deltas):
                    raise ValueError("paired deltas require mean_delta")
            elif any(d is None for d in deltas) or not math.isclose(
                self.mean_delta, sum(deltas) / len(deltas), abs_tol=1e-12
            ):
                raise ValueError("mean_delta must be the paired subject mean")
        elif self.macro_ba is not None or self.mean_delta is not None or not self.error:
            raise ValueError("failed receipt requires readable error and null scores")
        elif self.predictions_sha256 is not None:
            raise ValueError("failed receipt requires predictions_sha256=None")
        if self.coverage is not None:
            for key, field in {
                "original": "original_trials",
                "eligible": "eligible_trials",
                "available": "available_trials",
                "predicted": "predicted_trials",
                "missing": "missing",
            }.items():
                if getattr(self.coverage, key) != sum(
                    getattr(s, field) for s in self.subjects.values()
                ):
                    raise ValueError("development coverage must equal subject totals")
        return self
