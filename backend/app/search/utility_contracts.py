"""Versioned utility records with fixed model, seed and subject denominators."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PRIMARY_SUITE = ("eegnet",)
LEARNER_SUITE = ("eegnet", "csp_lda")
EEGNET_SEEDS = (17, 42, 2026)
# Read-only schema vocabulary for already published records.
LEGACY_PRIMARY_SUITE = ("csp_lda", "fbcsp", "ts_lr")
LEGACY_LEARNER_SUITE = LEGACY_PRIMARY_SUITE + ("fgmdm", "ea_fbcsp", "logvar_lr")
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
        if (not self.train_subjects or not self.development_subjects
            or len(set(self.train_subjects)) != len(self.train_subjects)
            or len(set(self.development_subjects)) != len(self.development_subjects)
            or set(self.train_subjects) & set(self.development_subjects)):
            raise ValueError("utility fold must have disjoint training and development subjects")
        return self


class SeedSummary(StrictUtility):
    seeds: list[int]
    mean_ba: Score
    seed_sd: float = Field(ge=0)
    minimum_ba: Score
    maximum_ba: Score

    @model_validator(mode="after")
    def fixed_seeds(self):
        if self.seeds != list(EEGNET_SEEDS) or not self.minimum_ba <= self.mean_ba <= self.maximum_ba:
            raise ValueError("EEGNet seed summary must use the fixed three seeds")
        return self


class PredictionOutput(StrictUtility):
    status: Literal["evaluated", "failed", "not_applicable"]
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
            if self.error or not self.predictions or not self.metadata or not self.subjects:
                raise ValueError("evaluated predictor needs complete artifacts and subject metrics")
            if not getattr(self, "seeds", {}):
                held_out = [s for f in self.folds for s in f.development_subjects]
                if not self.folds or len(held_out) != len(set(held_out)) or set(held_out) != set(self.subjects):
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


class SeedOutput(PredictionOutput):
    seed: int


class LearnerOutput(PredictionOutput):
    role: Literal["primary", "benchmark", "diagnostic"]
    input_representation: Literal["candidate_representation", "pre_adaptation_phys_V"]
    seeds: dict[str, SeedOutput] = Field(default_factory=dict)
    seed_summary: SeedSummary | None = None

    @model_validator(mode="after")
    def seed_aggregation(self):
        if self.seeds and self.status == "evaluated":
            if self.folds or set(self.seeds) != {str(s) for s in EEGNET_SEEDS} or self.seed_summary is None:
                raise ValueError("EEGNet requires three separate complete seeded fold inventories")
            scores = []
            fold_inventory = None
            for seed, run in self.seeds.items():
                if run.seed != int(seed) or run.status != "evaluated" or set(run.subjects) != set(self.subjects):
                    raise ValueError("every fixed seed must cover the identical complete subject set")
                inventory = [(f.fold_id, f.train_subjects, f.development_subjects) for f in run.folds]
                if fold_inventory is not None and inventory != fold_inventory:
                    raise ValueError("all seeds must use identical ordered subject folds")
                fold_inventory = inventory
                scores.append(run.summary["ba"].mean)
            mean = sum(scores) / len(scores)
            sd = math.sqrt(sum((v-mean)**2 for v in scores)/len(scores))
            expected = (mean, sd, min(scores), max(scores))
            actual = (self.seed_summary.mean_ba, self.seed_summary.seed_sd,
                      self.seed_summary.minimum_ba, self.seed_summary.maximum_ba)
            if any(not math.isclose(a, b, abs_tol=1e-12) for a, b in zip(actual, expected)):
                raise ValueError("seed statistics differ from all three seeded results")
            for subject, row in self.subjects.items():
                records = [run.subjects[subject] for run in self.seeds.values()]
                if any(r.n_trials != row.n_trials for r in records):
                    raise ValueError("seed trial denominators differ")
                for metric in self.summary:
                    values = [getattr(r, metric) for r in records]
                    target = getattr(row, metric)
                    if any(v is None for v in values):
                        if target is not None:
                            raise ValueError("partial seed metric cannot be averaged")
                    elif target is None or not math.isclose(target, sum(values)/len(values), abs_tol=1e-12):
                        raise ValueError("subject metrics must average seed metrics, not ensemble predictions")
        elif self.seed_summary is not None:
            raise ValueError("incomplete or unseeded learner cannot supply seed statistics")
        return self


class UtilitySubject(StrictUtility):
    eligible_trials: int = Field(gt=0)
    mean_ba: Score | None
    learner_ba: dict[str, Score | None]


class UtilityReceipt(StrictUtility):
    utility_version: Literal[1, 2] = 2
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
    seed_summary: SeedSummary | None = None
    learner_scores: dict[str, Score | None]
    subjects: dict[str, UtilitySubject]
    learners: dict[str, LearnerOutput]
    summary: Distribution | None
    failure_reasons: list[str]
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def fixed_utility(self):
        primary = PRIMARY_SUITE if self.utility_version == 2 else LEGACY_PRIMARY_SUITE
        suite = LEARNER_SUITE if self.utility_version == 2 else LEGACY_LEARNER_SUITE
        if self.primary_suite != list(primary) or set(self.learners) != set(suite) or set(self.learner_scores) != set(suite):
            raise ValueError("utility learner suite is fixed")
        complete = all(self.learners[k].status == "evaluated" for k in primary)
        if (self.status == "evaluated") != complete or (self.selection_score is not None) != complete:
            raise ValueError("complete primary evaluation is required; no partial averaging")
        for name, learner in self.learners.items():
            expected = learner.summary["ba"].mean if learner.status == "evaluated" else None
            if self.learner_scores[name] != expected:
                raise ValueError("learner score differs from full subject macro BA")
            if learner.status == "evaluated" and set(learner.subjects) != set(self.subjects):
                raise ValueError("learners must have the identical subject denominator")
        for subject, row in self.subjects.items():
            if set(row.learner_ba) != set(suite):
                raise ValueError("subject learner inventory differs")
            for name, learner in self.learners.items():
                metric = learner.subjects.get(subject)
                if row.learner_ba[name] != (metric.ba if metric else None) or (metric and metric.n_trials != row.eligible_trials):
                    raise ValueError("subject trial denominator or learner BA differs")
            mean = sum(row.learner_ba[k] for k in primary) / len(primary) if complete else None
            if row.mean_ba != mean:
                raise ValueError("subject utility must equally average the fixed primary evaluator")
        if self.utility_version == 2:
            eegnet = self.learners["eegnet"]
            if eegnet.role != "primary" or self.learners["csp_lda"].role != "benchmark":
                raise ValueError("model roles are fixed")
            if complete and (not eegnet.seeds or eegnet.seed_summary is None):
                raise ValueError("EEGNet requires all three seeded evaluations")
            if self.learners["csp_lda"].seeds or self.learners["csp_lda"].seed_summary:
                raise ValueError("CSP-LDA is a single deterministic benchmark")
            if any(k not in {str(s) for s in EEGNET_SEEDS} or run.seed != int(k) for k, run in eegnet.seeds.items()):
                raise ValueError("unexpected EEGNet seed identity")
            if any(learner.input_representation != "candidate_representation" for learner in self.learners.values()):
                raise ValueError("both models must evaluate the candidate representation")
            if self.seed_summary != eegnet.seed_summary:
                raise ValueError("utility seed statistics differ from EEGNet")
        if complete:
            expected = sum(self.learner_scores[k] for k in primary) / len(primary)
            if not self.inputs or not self.subjects or self.failure_reasons or not self.summary or not math.isclose(self.selection_score, expected, abs_tol=1e-12):
                raise ValueError("complete utility requires provenance and fixed equal weights")
            if self.summary.n_subjects != len(self.subjects) or not math.isclose(
                self.summary.mean, self.selection_score, abs_tol=1e-12
            ):
                raise ValueError("utility summary denominator differs")
        elif not self.failure_reasons or self.summary is not None:
            raise ValueError("incomplete utility needs clear reasons and null summary")
        return self
