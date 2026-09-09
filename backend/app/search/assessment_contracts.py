"""Compact, fixed assessment schema; full evaluator receipts stay in artifacts."""

from __future__ import annotations

import math
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .utility_contracts import Distribution, LEARNER_SUITE, PRIMARY_SUITE


Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Count = Annotated[int, Field(ge=0)]
Score = Annotated[float, Field(ge=0, le=1)]
Component = Literal["utility", "quality", "reconstruction", "assessment"]
METRIC_NAMES = {"ba", "accuracy", "f1", "kappa", "auc", "brier", "logloss"}


class StrictAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    @model_validator(mode="after")
    def finite_json(self):
        def visit(v):
            if isinstance(v, dict):
                for child in v.values():
                    visit(child)
            elif isinstance(v, (list, tuple)):
                for child in v:
                    visit(child)
            elif isinstance(v, float) and not math.isfinite(v):
                raise ValueError("NaN/Infinity are forbidden throughout assessment JSON")
        visit(self.model_dump(mode="python"))
        return self


class ArtifactRef(StrictAssessment):
    path: str = Field(min_length=1)
    sha256: Hash
    bytes: Count

    @model_validator(mode="after")
    def relative_path(self):
        p = PurePosixPath(self.path)
        if p.is_absolute() or ".." in p.parts or "\\" in self.path or ":" in self.path or self.path != p.as_posix() or not p.parts:
            raise ValueError("artifact path must be canonical and relative to assessment output_dir")
        return self


class ArtifactEntry(ArtifactRef):
    component: Component


class Bindings(StrictAssessment):
    candidate_hash: Hash
    plan_hash: Hash
    result_hash: Hash
    input_hash: Hash
    panel_hash: Hash
    core_receipt_hash: Hash
    probe_panel_hash: Hash | None


class AssessmentCoverage(StrictAssessment):
    subjects_expected: Count
    records_expected: Count
    original_trials: Count
    eligible_trials: Count
    common_invalid_trials: Count

    @model_validator(mode="after")
    def trials(self):
        if self.eligible_trials + self.common_invalid_trials != self.original_trials:
            raise ValueError("frozen trial denominator does not add up")
        return self


class LearnerCoverage(StrictAssessment):
    subjects_expected: Count
    subjects_available: Count
    eligible_trials_expected: Count
    trials_available: Count

    @model_validator(mode="after")
    def subset(self):
        if self.subjects_available > self.subjects_expected or self.trials_available > self.eligible_trials_expected:
            raise ValueError("learner coverage exceeds frozen panel")
        return self


class UtilitySummary(StrictAssessment):
    denominator_scope: Literal["frozen_development_subjects_and_eligible_development_trials"] = "frozen_development_subjects_and_eligible_development_trials"
    evaluation_mode: Literal["group_cross_validation", "subject_holdout"]
    status: Literal["evaluated", "incomplete", "failed"]
    reason: str | None
    primary_suite: list[str]
    learner_scores: dict[str, Score | None]
    learner_statuses: dict[str, Literal["evaluated", "failed", "not_applicable"]]
    learner_statistics: dict[str, dict[str, Distribution | None]]
    learner_coverage: dict[str, LearnerCoverage]
    summary: Distribution | None
    primary_models_expected: Literal[3] = 3
    primary_models_available: Count
    primary_trial_predictions_expected: Count
    primary_trial_predictions_available: Count
    receipt_artifact: ArtifactRef | None
    failure_artifact: ArtifactRef | None
    failure_reasons: list[str]
    warnings: list[str]

    @model_validator(mode="after")
    def full_suite(self):
        if self.primary_suite != list(PRIMARY_SUITE):
            raise ValueError("three primary models are fixed")
        for mapping in (self.learner_scores, self.learner_statuses, self.learner_statistics, self.learner_coverage):
            if set(mapping) != set(LEARNER_SUITE):
                raise ValueError("complete six-model summary inventory required")
        complete = 0
        for name in LEARNER_SUITE:
            score, state = self.learner_scores[name], self.learner_statuses[name]
            statistics = self.learner_statistics[name]
            if set(statistics) != METRIC_NAMES:
                raise ValueError("utility statistic inventory is fixed")
            if (score is not None) != (state == "evaluated"):
                raise ValueError("unevaluated model cannot supply a score")
            if state == "evaluated":
                coverage = self.learner_coverage[name]
                if coverage.subjects_available != coverage.subjects_expected or coverage.trials_available != coverage.eligible_trials_expected:
                    raise ValueError("evaluated model requires the entire frozen denominator")
                if statistics["ba"] is None or statistics["ba"].mean != score:
                    raise ValueError("BA score/statistics differ")
                complete += name in PRIMARY_SUITE
            elif any(v is not None for v in statistics.values()):
                raise ValueError("failed models cannot retain partial summary statistics")
        if self.primary_models_available != complete:
            raise ValueError("primary model denominator differs")
        if (self.status == "evaluated") != (complete == 3):
            raise ValueError("utility status must require all three complete primary models")
        if self.primary_trial_predictions_expected != sum(self.learner_coverage[n].eligible_trials_expected for n in PRIMARY_SUITE):
            raise ValueError("primary prediction denominator differs")
        if self.primary_trial_predictions_available != sum(self.learner_coverage[n].trials_available for n in PRIMARY_SUITE):
            raise ValueError("primary prediction coverage differs")
        if self.status == "evaluated":
            if complete != 3 or self.summary is None or self.receipt_artifact is None or self.reason or self.failure_reasons:
                raise ValueError("complete utility requires all three primaries and verified receipt")
        elif self.summary is not None or not self.reason or not self.failure_reasons:
            raise ValueError("incomplete utility has no aggregate utility statistic")
        if self.status == "failed" and self.failure_artifact is None:
            raise ValueError("failed utility requires a failure artifact")
        return self


class AuxiliarySummary(StrictAssessment):
    status: Literal["evaluated", "partial", "not_applicable", "failed"]
    reason: str | None
    # Module-owned aggregate values retain units/status/denominators. Subject
    # tables, raw curves and reconstruction case details are in receipt_artifact.
    summary: dict[str, JsonValue] | None
    receipt_artifact: ArtifactRef | None
    failure_artifact: ArtifactRef | None

    @model_validator(mode="after")
    def availability(self):
        if self.status in {"evaluated", "partial"} and (self.summary is None or self.receipt_artifact is None):
            raise ValueError("available auxiliary evaluation requires summary and artifact")
        if self.status in {"failed", "not_applicable"} and self.summary is not None:
            raise ValueError("unavailable auxiliary summary must be null")
        if self.status != "evaluated" and not self.reason:
            raise ValueError("partial/unavailable assessment requires a reason")
        if self.status == "failed" and self.failure_artifact is None:
            raise ValueError("failed auxiliary evaluation requires a failure artifact")
        return self


class AssessmentManifest(StrictAssessment):
    schema_version: Literal["assessment-artifacts-v1"] = "assessment-artifacts-v1"
    bindings: Bindings
    scope: Literal["all_component_output_files; manifest_self_hash_in_return"] = "all_component_output_files; manifest_self_hash_in_return"
    artifacts: list[ArtifactEntry]


class AssessmentSnapshot(StrictAssessment):
    schema_version: Literal["assessment-content-v1"] = "assessment-content-v1"
    # Exact non-manifest projection of AssessmentSummary, checked by verifier.
    content: dict[str, JsonValue]


class AssessmentSummary(StrictAssessment):
    schema_version: Literal["assessment-v1"] = "assessment-v1"
    candidate_id: str = Field(min_length=1)
    bindings: Bindings
    coverage: AssessmentCoverage
    status: Literal["complete", "partial", "failed"]
    selection_score: Score | None
    selection_ready: bool
    selection_policy: Literal["utility_only_all_three_primary_models_all_frozen_subjects"] = "utility_only_all_three_primary_models_all_frozen_subjects"
    core_csp_macro_ba: Score | None
    core_status: str
    utility: UtilitySummary
    quality: AuxiliarySummary
    reconstruction: AuxiliarySummary
    artifact_manifest: ArtifactRef
    artifacts: list[ArtifactEntry]

    @model_validator(mode="after")
    def score_and_manifest(self):
        ready = self.utility.status == "evaluated"
        if self.selection_ready != ready or (self.selection_score is not None) != ready:
            raise ValueError("selection requires full utility, independent of auxiliary results")
        if ready:
            expected = sum(self.utility.learner_scores[k] for k in PRIMARY_SUITE)/3
            if not math.isclose(self.selection_score, expected, rel_tol=0, abs_tol=1e-12) or not math.isclose(
                self.selection_score, self.utility.summary.mean, rel_tol=0, abs_tol=1e-12
            ):
                raise ValueError("selection_score must equal validated three-model utility")
        states = (self.utility.status, self.quality.status, self.reconstruction.status)
        expected_status = "complete" if all(s == "evaluated" for s in states) else "failed" if all(s in {"failed", "not_applicable"} for s in states) else "partial"
        if self.status != expected_status:
            raise ValueError("assessment status differs from components")
        paths = [a.path for a in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate manifest artifact path")
        entries = {a.path: a for a in self.artifacts}
        refs = [self.artifact_manifest]
        for component in (self.utility, self.quality, self.reconstruction):
            refs.extend(r for r in (component.receipt_artifact, component.failure_artifact) if r is not None)
        for ref in refs:
            item = entries.get(ref.path)
            if item is None or item.sha256 != ref.sha256 or item.bytes != ref.bytes:
                raise ValueError("summary references an artifact outside the verified manifest")
        return self
