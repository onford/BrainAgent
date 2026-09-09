"""Stable utility.json v1: fixed model suite, complete subject denominators."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PRIMARY_SUITE = ("csp_lda", "fbcsp", "ts_lr")
LEARNER_SUITE = PRIMARY_SUITE + ("fgmdm", "ea_fbcsp", "logvar_lr")
Score = Annotated[float, Field(ge=0, le=1)]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class StrictUtility(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Artifact(StrictUtility):
    path: str
    sha256: Hash


class Distribution(StrictUtility):
    mean: float
    lower_quartile: float
    subject_sd: float = Field(ge=0)
    n_subjects: int = Field(gt=0)


class SubjectMetrics(StrictUtility):
    n_trials: int = Field(gt=0)
    ba: Score
    accuracy: Score
    f1: Score
    kappa: float = Field(ge=-1, le=1)
    auc: Score | None
    brier: Score | None
    logloss: float | None = Field(ge=0)
    probability_status: Literal["available", "not_available_in_core_predictions"]

    @model_validator(mode="after")
    def probabilities(self):
        if any(v is None for v in (self.auc, self.brier, self.logloss)) != (
            self.probability_status == "not_available_in_core_predictions"
        ):
            raise ValueError("probability metrics must all be present or explicitly N/A")
        if self.probability_status != "available" and any(
            v is not None for v in (self.auc, self.brier, self.logloss)
        ):
            raise ValueError("core hard predictions do not supply probability metrics")
        return self


class FoldOutput(StrictUtility):
    fold_id: str
    train_subjects: list[str]
    development_subjects: list[str]
    model: Artifact
    metadata: Artifact
    predictions: Artifact

    @model_validator(mode="after")
    def disjoint(self):
        if not self.train_subjects or not self.development_subjects or set(self.train_subjects) & set(self.development_subjects):
            raise ValueError("utility fold must have disjoint training and development subjects")
        return self


class LearnerOutput(StrictUtility):
    role: Literal["primary", "benchmark", "diagnostic"]
    status: Literal["evaluated", "failed", "not_applicable"]
    input_representation: Literal["candidate_representation", "pre_adaptation_phys_V"]
    error: str | None = None
    predictions: Artifact | None = None
    metadata: Artifact | None = None
    folds: list[FoldOutput] = Field(default_factory=list)
    subjects: dict[str, SubjectMetrics] = Field(default_factory=dict)
    summary: dict[str, Distribution | None] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def complete(self):
        if self.status == "evaluated":
            if self.error or not self.predictions or not self.metadata or not self.folds or not self.subjects:
                raise ValueError("evaluated learner needs complete artifacts and subject metrics")
            held_out = [s for f in self.folds for s in f.development_subjects]
            if len(held_out) != len(set(held_out)) or set(held_out) != set(self.subjects):
                raise ValueError("every subject must be OOF in exactly one fold")
            if set(self.summary) != {"ba", "accuracy", "f1", "kappa", "auc", "brier", "logloss"}:
                raise ValueError("learner summary metric inventory differs")
            for metric, distribution in self.summary.items():
                values = [getattr(s, metric) for s in self.subjects.values()]
                if distribution is None:
                    if any(v is not None for v in values):
                        raise ValueError("missing distribution for present metrics")
                elif any(v is None for v in values) or distribution.n_subjects != len(values) or not math.isclose(
                    distribution.mean, sum(values) / len(values), abs_tol=1e-12
                ):
                    raise ValueError("learner distribution must use all subjects equally")
        elif not self.error or self.subjects or self.summary or self.predictions:
            raise ValueError("failed learner needs an error and no partial aggregate score")
        return self


class UtilitySubject(StrictUtility):
    eligible_trials: int = Field(gt=0)
    mean_ba: Score | None
    learner_ba: dict[str, Score | None]


class UtilityReceipt(StrictUtility):
    utility_version: Literal[1] = 1
    candidate_id: str
    candidate_hash: Hash
    panel_hash: Hash | None
    core_receipt_hash: Hash
    evaluation_mode: Literal["group_cross_validation", "subject_holdout"] | None
    protocol: Artifact
    inputs: Artifact | None
    execution: Artifact | None = None
    status: Literal["evaluated", "incomplete"]
    selection_score: Score | None
    primary_suite: list[str]
    learner_scores: dict[str, Score | None]
    subjects: dict[str, UtilitySubject]
    learners: dict[str, LearnerOutput]
    summary: Distribution | None
    failure_reasons: list[str]
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def fixed_utility(self):
        if self.primary_suite != list(PRIMARY_SUITE) or set(self.learners) != set(LEARNER_SUITE) or set(self.learner_scores) != set(LEARNER_SUITE):
            raise ValueError("utility learner suite is fixed")
        complete = all(self.learners[k].status == "evaluated" for k in PRIMARY_SUITE)
        if (self.status == "evaluated") != complete or (self.selection_score is not None) != complete:
            raise ValueError("all three primary learners are required; no partial averaging")
        for name, learner in self.learners.items():
            expected = learner.summary["ba"].mean if learner.status == "evaluated" else None
            if self.learner_scores[name] != expected:
                raise ValueError("learner score differs from full subject macro BA")
            if learner.status == "evaluated" and set(learner.subjects) != set(self.subjects):
                raise ValueError("learners must have the identical subject denominator")
        for subject, row in self.subjects.items():
            if set(row.learner_ba) != set(LEARNER_SUITE):
                raise ValueError("subject learner inventory differs")
            for name, learner in self.learners.items():
                metric = learner.subjects.get(subject)
                if row.learner_ba[name] != (metric.ba if metric else None) or (metric and metric.n_trials != row.eligible_trials):
                    raise ValueError("subject trial denominator or learner BA differs")
            mean = sum(row.learner_ba[k] for k in PRIMARY_SUITE) / 3 if complete else None
            if row.mean_ba != mean:
                raise ValueError("subject utility must equally average the fixed three models")
        if complete:
            expected = sum(self.learner_scores[k] for k in PRIMARY_SUITE) / 3
            if not self.inputs or not self.subjects or self.failure_reasons or not self.summary or not math.isclose(self.selection_score, expected, abs_tol=1e-12):
                raise ValueError("complete utility requires provenance and fixed equal weights")
            if self.summary.n_subjects != len(self.subjects) or not math.isclose(
                self.summary.mean, self.selection_score, abs_tol=1e-12
            ):
                raise ValueError("utility summary denominator differs")
        elif not self.failure_reasons or self.summary is not None:
            raise ValueError("incomplete utility needs clear reasons and null summary")
        return self
