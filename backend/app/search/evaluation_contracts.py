"""Version 2 panel/evaluator contracts with optional worker metadata.

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
EvaluationMode = Literal["group_cross_validation", "subject_holdout"]
Adaptation = Literal[
    "none", "subject_scale", "euclidean_alignment", "conditional_alignment"
]


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


class EvaluationFold(EvaluationContract):
    id: str = Field(min_length=1)
    train_subjects: list[str] = Field(min_length=1)
    development_subjects: list[str] = Field(min_length=1)


class FrozenPanel(EvaluationContract):
    evaluator_version: Literal[2]
    evaluation_mode: EvaluationMode
    folds: list[EvaluationFold] = Field(min_length=1, max_length=5)
    seed: int
    input_hash: Hash
    panel_hash: Hash
    train_subjects: list[str]
    development_subjects: list[str] = Field(min_length=1)
    class_labels: ClassLabels
    event_codes: dict[str, Annotated[int, Field(gt=0)]]
    records: dict[str, FrozenRecord] = Field(min_length=1)
    trials: list[FrozenTrial] = Field(min_length=1)
    output_contract: OutputContract

    @model_validator(mode="after")
    def subject_folds(self):
        subjects = {r.subject for r in self.records.values()}
        train, dev = self.train_subjects, self.development_subjects
        if (
            len(train + dev) != len(set(train + dev))
            or set(train + dev) != subjects
            or len(subjects) < 2
        ):
            raise ValueError(
                "subject groups must be unique and cover selected subjects"
            )
        if len({f.id for f in self.folds}) != len(self.folds):
            raise ValueError("duplicate fold id")
        held_out = []
        for fold in self.folds:
            combined = fold.train_subjects + fold.development_subjects
            if len(combined) != len(set(combined)) or set(combined) != subjects:
                raise ValueError(
                    "fold subjects must be disjoint, unique and cover all subjects"
                )
            held_out.extend(fold.development_subjects)
        if self.evaluation_mode == "group_cross_validation":
            if (
                train
                or set(dev) != subjects
                or len(self.folds) != min(5, len(subjects))
                or len(held_out) != len(subjects)
                or set(held_out) != subjects
            ):
                raise ValueError("CV requires every subject out of fold exactly once")
        elif (
            not train
            or len(self.folds) != 1
            or set(self.folds[0].train_subjects) != set(train)
            or set(held_out) != set(dev)
        ):
            raise ValueError("holdout fold must match explicit subject groups")
        for key, record in self.records.items():
            if (
                key != record.record_id
                or not record.subject.strip()
                or record.role
                != ("train" if record.subject in train else "development")
            ):
                raise ValueError("record identity/role differs from subject groups")
        return self


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


class NumericSubjectDiagnostics(EvaluationContract):
    channel_variance: list[Annotated[float, Field(ge=0)]]
    channel_flat_fraction: list[Score]
    covariance_condition: float = Field(ge=1)
    covariance_condition_before: float = Field(ge=1)
    covariance_condition_after: float = Field(ge=1)
    mean_channel_variance_before: float = Field(ge=0)
    mean_channel_variance_after: float = Field(ge=0)
    effective_rank_before: Count
    effective_rank_after: Count

    @model_validator(mode="after")
    def dimensions(self):
        if (
            not self.channel_variance
            or len(self.channel_variance) != len(self.channel_flat_fraction)
            or max(self.effective_rank_before, self.effective_rank_after)
            > len(self.channel_variance)
            or self.covariance_condition != self.covariance_condition_before
        ):
            raise ValueError("inconsistent numeric diagnostic dimensions/rank")
        return self


class NumericDiagnosticsSummary(EvaluationContract):
    mean_condition_before: float = Field(ge=1)
    mean_condition_after: float = Field(ge=1)
    mean_variance_before: float = Field(ge=0)
    mean_variance_after: float = Field(ge=0)
    gate_fraction: Score | None
    mean_effective_rank: float = Field(
        ge=0, description="Subject mean of effective_rank_before"
    )
    mean_anisotropy: float = Field(
        ge=1, description="Subject mean of normalized shrunk spectrum Q90/Q10"
    )


class EvaluationDiagnostics(EvaluationContract):
    floor_fraction: Score | None = None
    converged: bool | None = None
    warnings: list[str] = Field(default_factory=list)
    subjects: dict[str, NumericSubjectDiagnostics] = Field(default_factory=dict)
    summary: NumericDiagnosticsSummary | None = None

    @model_validator(mode="after")
    def subject_means(self):
        if self.summary is not None:
            if not self.subjects:
                raise ValueError("numeric summary requires subject diagnostics")
            for summary_key, subject_key in {
                "mean_condition_before": "covariance_condition_before",
                "mean_condition_after": "covariance_condition_after",
                "mean_variance_before": "mean_channel_variance_before",
                "mean_variance_after": "mean_channel_variance_after",
                "mean_effective_rank": "effective_rank_before",
            }.items():
                expected = sum(
                    getattr(s, subject_key) for s in self.subjects.values()
                ) / len(self.subjects)
                if not math.isclose(
                    getattr(self.summary, summary_key),
                    expected,
                    rel_tol=1e-12,
                    abs_tol=0,
                ):
                    raise ValueError("numeric summary must equal actual subject means")
        return self


class AlignmentPolicy(EvaluationContract):
    adaptation: Adaptation = "none"
    alignment_threshold: float = Field(default=10.0, ge=1)


class SubjectRepresentation(EvaluationContract):
    applied_adaptation: Literal["none", "scale_only", "euclidean_alignment"]
    gate_passed: bool
    fallback_reason: str | None = None
    covariance_anisotropy: float = Field(ge=1)
    gate_metric_value: float = Field(ge=1)
    fit_trials: Count
    transform_path: str | None = None
    transform_sha256: Hash | None = None
    unit: Literal["V", "dimensionless"]


class RecordRepresentation(EvaluationContract):
    subject: str
    array_path: str
    array_sha256: Hash
    shape: list[Count]
    unit: Literal["V", "dimensionless"]


class GateMetricMetadata(EvaluationContract):
    name: Literal["normalized_shrunk_spectrum_q90_q10"] = (
        "normalized_shrunk_spectrum_q90_q10"
    )
    normalization: Literal["covariance_divided_by_mean_channel_variance"] = (
        "covariance_divided_by_mean_channel_variance"
    )
    shrinkage: Literal[0.1] = 0.1
    lower_quantile: Literal[0.1] = 0.1
    upper_quantile: Literal[0.9] = 0.9
    quantile_method: Literal["linear"] = "linear"
    comparison: Literal["greater_than_or_equal"] = "greater_than_or_equal"
    threshold_origin: Literal["predeclared_engineering_parameter"] = (
        "predeclared_engineering_parameter"
    )
    fraction_denominator: Literal["all_selected_subjects"] = "all_selected_subjects"
    zero_covariance_value: Literal[1.0] = 1.0


class LearnerMetadata(EvaluationContract):
    covariance_temporal_centering: Literal[True] = True
    covariance_ddof: Literal[0] = 0
    covariance_pooling: Literal[
        "equal_epoch_weight_within_subject_or_training_class"
    ] = "equal_epoch_weight_within_subject_or_training_class"
    covariance_symmetry: Literal["signed_cross_covariances_preserved"] = (
        "signed_cross_covariances_preserved"
    )
    variance_floor: Literal[1e-20] = 1e-20
    covariance_scale_floor: Literal[1e-20] = 1e-20
    spectral_normalization: Literal["covariance_divided_by_mean_channel_variance"] = (
        "covariance_divided_by_mean_channel_variance"
    )
    condition_relative_floor: Literal[1e-12] = 1e-12
    effective_rank_relative_tolerance: Literal[1e-8] = 1e-8
    effective_rank_rule: Literal["eigenvalue_gt_largest_times_tolerance"] = (
        "eigenvalue_gt_largest_times_tolerance"
    )
    zero_covariance_condition: Literal[1.0] = 1.0
    zero_covariance_rank: Literal[0] = 0
    csp_components: int = Field(ge=1, le=4)
    csp_regularization: Literal[0.1] = 0.1
    covariance_shrinkage_target: Literal["mean_channel_variance_times_identity"] = (
        "mean_channel_variance_times_identity"
    )
    csp_eigenproblem: Literal["class0_vs_class0_plus_class1"] = (
        "class0_vs_class0_plus_class1"
    )
    csp_order: Literal["descending_abs_eigenvalue_minus_half_stable"] = (
        "descending_abs_eigenvalue_minus_half_stable"
    )
    csp_feature: Literal["log_projected_temporally_centered_population_variance"] = (
        "log_projected_temporally_centered_population_variance"
    )
    lda_solver: Literal["lsqr"] = "lsqr"
    lda_covariance_estimator: Literal["LedoitWolf_within_training_class"] = (
        "LedoitWolf_within_training_class"
    )
    lda_priors: Literal["empirical_training_class_frequency"] = (
        "empirical_training_class_frequency"
    )
    lda_ridge: Literal[1e-12] = 1e-12
    lda_ridge_scale: Literal["max_mean_covariance_diagonal_or_one"] = (
        "max_mean_covariance_diagonal_or_one"
    )
    secondary_feature: Literal["log_channel_population_variance"] = (
        "log_channel_population_variance"
    )
    standardizer_with_mean: Literal[True] = True
    standardizer_with_std: Literal[True] = True
    logistic_solver: Literal["lbfgs"] = "lbfgs"
    logistic_penalty: Literal["l2"] = "l2"
    logistic_c: Literal[1.0] = 1.0
    logistic_tolerance: Literal[1e-4] = 1e-4
    logistic_max_iter: Literal[1000] = 1000
    logistic_fit_intercept: Literal[True] = True
    logistic_class_weight: Literal["none"] = "none"
    logistic_random_state: int = Field(ge=0, lt=2**32)
    supervised_fit_scope: Literal["fold_train_subjects_only"] = (
        "fold_train_subjects_only"
    )


class EvaluationRepresentation(EvaluationContract):
    policy: AlignmentPolicy
    unit: Literal["V", "dimensionless"]
    transductive: bool
    channels: list[str]
    covariance_regularization: Literal[0.1] = 0.1
    gate_metric: GateMetricMetadata = Field(default_factory=GateMetricMetadata)
    gate_subject_count: Count
    gate_passed_subject_count: Count
    gate_fraction: Score | None
    fit_scope: Literal["subject_whole_batch_label_free"] = (
        "subject_whole_batch_label_free"
    )
    subjects: dict[str, SubjectRepresentation]
    records: dict[str, RecordRepresentation]

    @model_validator(mode="after")
    def common_unit(self):
        conditional = self.policy.adaptation == "conditional_alignment"
        count = len(self.subjects) if conditional else 0
        passed = (
            sum(s.gate_passed for s in self.subjects.values()) if conditional else 0
        )
        if (
            not self.subjects
            or self.gate_subject_count != count
            or self.gate_passed_subject_count != passed
            or (
                conditional
                and (
                    self.gate_fraction is None
                    or not math.isclose(
                        self.gate_fraction, passed / count, abs_tol=1e-12
                    )
                )
            )
            or (not conditional and self.gate_fraction is not None)
        ):
            raise ValueError(
                "gate fraction must use actual conditional decisions over all selected subjects"
            )
        for subject in self.subjects.values():
            expected_gate = self.policy.adaptation == "euclidean_alignment" or (
                conditional
                and subject.gate_metric_value >= self.policy.alignment_threshold
            )
            expected_adaptation = (
                "euclidean_alignment"
                if expected_gate
                else ("none" if self.policy.adaptation == "none" else "scale_only")
            )
            if (
                subject.gate_passed != expected_gate
                or subject.applied_adaptation != expected_adaptation
            ):
                raise ValueError(
                    "subject gate must use the predeclared spectrum metric and threshold"
                )
        expected = "V" if self.policy.adaptation == "none" else "dimensionless"
        if (
            self.unit != expected
            or self.transductive != (self.policy.adaptation != "none")
            or any(s.unit != expected for s in self.subjects.values())
            or any(
                r.unit != expected or r.subject not in self.subjects
                for r in self.records.values()
            )
        ):
            raise ValueError(
                "all delivered records must share the policy's declared unit"
            )
        if self.policy.adaptation != "none" and any(
            not s.transform_path
            or not s.transform_sha256
            or s.applied_adaptation == "none"
            for s in self.subjects.values()
        ):
            raise ValueError("adapted subjects require fitted transform provenance")
        return self


class PairedSubjectCI(EvaluationContract):
    low: Delta
    high: Delta
    confidence: float = 0.95
    n_subjects: int = Field(ge=1)
    n_resamples: int = 2000
    seed: int
    method: Literal["paired_subject_percentile_bootstrap"] = (
        "paired_subject_percentile_bootstrap"
    )
    interpretation: Literal["descriptive_development_only_not_independent_test"] = (
        "descriptive_development_only_not_independent_test"
    )

    @model_validator(mode="after")
    def ordered(self):
        if self.low > self.high:
            raise ValueError("confidence interval bounds must be ordered")
        return self


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
    evaluator_version: Literal[2] = 2
    evaluation_mode: EvaluationMode | None = None
    folds: list[EvaluationFold] = Field(default_factory=list)
    primary_learner: Literal["csp4_reg0.1_shrinkage_lda"] = "csp4_reg0.1_shrinkage_lda"
    secondary_learner: Literal["logvariance_standardizer_logistic_regression"] = (
        "logvariance_standardizer_logistic_regression"
    )
    secondary_macro_ba: Score | None = None
    secondary_subjects: dict[str, Score] = Field(default_factory=dict)
    paired_subject_ci: PairedSubjectCI | None = None
    representation: EvaluationRepresentation | None = None
    learner_metadata: LearnerMetadata | None = None
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
                or self.evaluation_mode is None
                or not self.folds
                or self.representation is None
                or self.learner_metadata is None
                or self.diagnostics.summary is None
                or self.secondary_macro_ba is None
            ):
                raise ValueError(
                    "evaluated receipt requires complete development metrics"
                )
            if self.learner_metadata.csp_components != min(
                4, len(self.representation.channels)
            ):
                raise ValueError("CSP component metadata must match common channel cap")
            if set(self.secondary_subjects) != set(self.subjects) or not math.isclose(
                self.secondary_macro_ba,
                sum(self.secondary_subjects.values()) / len(self.subjects),
                abs_tol=1e-12,
            ):
                raise ValueError(
                    "secondary metrics require the same subject denominator"
                )
            held_out = [s for f in self.folds for s in f.development_subjects]
            if (
                len(held_out) != len(set(held_out))
                or set(held_out) != set(self.subjects)
                or any(
                    set(f.train_subjects) & set(f.development_subjects)
                    for f in self.folds
                )
                or self.coverage.missing
                or self.coverage.train.missing
                or self.coverage.predicted != self.coverage.eligible
            ):
                raise ValueError("evaluated receipt requires complete fold coverage")
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
                if (
                    any(d is not None for d in deltas)
                    or self.paired_subject_ci is not None
                ):
                    raise ValueError("paired deltas require mean_delta")
            elif any(d is None for d in deltas) or not math.isclose(
                self.mean_delta, sum(deltas) / len(deltas), abs_tol=1e-12
            ):
                raise ValueError("mean_delta must be the paired subject mean")
            elif (
                self.paired_subject_ci is None
                or self.paired_subject_ci.n_subjects != len(self.subjects)
            ):
                raise ValueError("paired deltas require a descriptive subject interval")
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
        if self.diagnostics.summary is not None:
            if self.representation is None or set(self.diagnostics.subjects) != set(
                self.representation.subjects
            ):
                raise ValueError(
                    "numeric summary requires complete representation subject coverage"
                )
            expected = sum(
                s.gate_metric_value for s in self.representation.subjects.values()
            ) / len(self.representation.subjects)
            if (
                self.diagnostics.summary.gate_fraction
                != self.representation.gate_fraction
                or not math.isclose(
                    self.diagnostics.summary.mean_anisotropy,
                    expected,
                    rel_tol=1e-12,
                    abs_tol=0,
                )
            ):
                raise ValueError(
                    "numeric summary gate values must match actual subject decisions"
                )
        return self
