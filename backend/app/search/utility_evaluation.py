"""Fixed-suite, subject-OOF dataset utility independent of search selection.

Public entry point: evaluate_dataset_utility(plan, result, store_root, panel,
candidate_entry, core_receipt, output_dir). Scores are fractions, never percent.
The three primary learners must ALL succeed on every eligible trial. Benchmark
failures do not silently change this denominator or its equal learner weights.
"""

from __future__ import annotations

from collections import Counter
from contextlib import ExitStack
from copy import deepcopy
import csv
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import warnings

import joblib
import numpy as np
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score, cohen_kappa_score, f1_score,
    log_loss, roc_auc_score,
)
from sklearn.preprocessing import StandardScaler
from sklearn.utils.extmath import softmax
from threadpoolctl import threadpool_limits

from app.preprocessing.storage import digest, file_hash, write_json
from . import evaluation
from .evaluation_contracts import EvaluationReceipt
from .evaluation_numeric import (
    StableShrinkageCovariance, VARIANCE_FLOOR, covariance, csp_features, fit_csp,
)
from .learners import LearnerNotApplicable, make_learner
from .panel import validate_panel
from .utility_contracts import LEARNER_SUITE, PRIMARY_SUITE, UtilityReceipt
from .utility_parallel import UtilityExecutionError, check_assembly_resources, run_utility_tasks, utility_execution


# Frozen engineering candidates, not literature-optimal hyperparameters.
FBCSP_GRID = {"C": [0.1, 1.0, 10.0], "n_components": [4, 6], "k_best": [10]}
TS_GRID = {"C": [0.1, 1.0, 10.0]}
METRICS = ("ba", "accuracy", "f1", "kappa", "auc", "brier", "logloss")
MAX_INPUT_BYTES = 8 * 1024**3  # Two disk-backed representations combined.


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _artifact(path):
    return {"path": str(Path(path).resolve()), "sha256": file_hash(Path(path))}


def _save(path, value):
    write_json(path, value)
    return _artifact(path)


def _close_mmap(values):
    mmap = getattr(values, "_mmap", None)
    if mmap is not None:
        mmap.close()


def _distribution(values):
    if not values or any(v is None for v in values):
        return None
    values = np.asarray(values, dtype=float)
    _require(np.isfinite(values).all(), "nonfinite subject metric")
    return {"mean": float(values.mean()), "lower_quartile": float(np.quantile(values, 0.25, method="linear")),
            "subject_sd": float(np.std(values, ddof=0)), "n_subjects": len(values)}


def _metrics(rows, positive):
    truth = np.array([row["label"] == positive for row in rows], dtype=int)
    prediction = np.array([row["prediction"] == positive for row in rows], dtype=int)
    _require(len(np.unique(truth)) == 2, "every subject must have both eligible classes")
    probabilities = [row["proba_right"] for row in rows]
    available = all(value is not None for value in probabilities)
    _require(available or all(value is None for value in probabilities), "partial subject probability coverage")
    result = {"n_trials": len(rows), "ba": float(balanced_accuracy_score(truth, prediction)),
              "accuracy": float(accuracy_score(truth, prediction)), "f1": float(f1_score(truth, prediction, zero_division=0)),
              "kappa": float(cohen_kappa_score(truth, prediction)), "auc": None, "brier": None, "logloss": None,
              "probability_status": "available" if available else "not_available_in_core_predictions"}
    if available:
        p = np.asarray(probabilities)
        score = np.asarray([row["decision_score"] for row in rows])
        _require(np.isfinite(p).all() and np.isfinite(score).all() and ((0 <= p) & (p <= 1)).all(), "invalid probability/decision scores")
        result.update(auc=float(roc_auc_score(truth, score)), brier=float(np.mean((p - truth) ** 2)),
                      logloss=float(log_loss(truth, np.column_stack([1 - p, p]), labels=[0, 1])))
    return result


def _available_band(plan, sfreq):
    """Intersect executed filters; never infer missing spectral support from scores."""
    supports = []
    for record in plan.records:
        low, high = 4.0, min(40.0, sfreq / 2 - 1e-6)
        for step in record.steps:
            if step.op == "filter":
                a, b = step.params.get("l_freq"), step.params.get("h_freq")
                if a is not None:
                    low = max(low, float(a))
                if b is not None:
                    high = min(high, float(b))
        _require(np.isfinite([low, high]).all() and 0 < low < high < sfreq / 2, "no supported 4-40Hz benchmark passband")
        supports.append((low, high))
    _require(len(set(supports)) == 1, "record-specific filter bands cannot share a single utility recipe")
    return supports[0]


def utility_protocol(*, execution=None):
    """Freeze this value (storage.digest) at job creation, not per candidate.

    protocol.sha256 in utility.json equals this canonical dictionary's digest.
    Callers must compare the frozen protocol before dispatching this evaluator.
    No machine-specific absolute paths or scores enter this protocol value.
    """
    folder = Path(__file__).parent
    files = ("utility_evaluation.py", "utility_contracts.py", "utility_parallel.py", "learners.py", "requirements-learners.txt",
             "evaluation.py", "evaluation_numeric.py", "evaluation_contracts.py", "panel.py")
    versions = {}
    for name in ("numpy", "scipy", "scikit-learn", "pyriemann", "mne", "joblib", "pydantic", "threadpoolctl"):
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = None
    return {"utility_version": 1, "primary_suite": list(PRIMARY_SUITE), "learner_suite": list(LEARNER_SUITE),
            "implementation_sha256": {name: file_hash(folder / name) for name in files},
            "supervision_implementation_sha256": {name: file_hash(folder.parent / "preprocessing" / name)
                                                   for name in ("parallel.py", "resources.py")},
            "library_versions": {"numpy": "1.26.4", "scipy": "1.15.3", "scikit-learn": "1.6.1", "pyriemann": "0.7", "mne": "1.10.2"},
            "runtime_library_versions": versions,
            "evaluation_modes": {"group_cross_validation": "each selected subject OOF exactly once",
                                 "subject_holdout": "development eligible denominator only; train subjects never predicted or scored"},
            "selection": "equal mean of subject-macro BA for CSP-LDA, FBCSP, TS-LR; all three required",
            "metrics": {"range": "fractions [0,1], kappa [-1,1], logloss >=0", "f1": "binary right class",
                        "subject_sd_ddof": 0, "lower_quartile": "linear quantile 0.25",
                        "auc": "decision score increasing toward right class; never hard-label pseudo AUC",
                        "logloss": "sklearn float64 epsilon clipping", "probability_calibration": "not independently calibrated"},
            "inner_cv": {"splitter": "GroupKFold", "splits": "min(3, outer training subject count), at least 2",
                         "one_training_subject": "fixed default C=1,n_components=4,k_best=10; no tuning or trial CV",
                         "fbcsp": deepcopy(FBCSP_GRID), "ts_lr": deepcopy(TS_GRID), "ea_fbcsp": deepcopy(FBCSP_GRID),
                         "origin": "frozen engineering candidates; not literature optima", "scope": "all learned stages fit on inner training subjects only"},
            "ea_fbcsp": "pre-adaptation phys_V only; separate complete unlabelled subject/band EA; does not measure candidate upstream EA differences",
            "filter_bank": {"support": "intersection of executed passbands with 4-40Hz", "band_width_hz": 4.0,
                            "filter": "Butterworth order=4 SOS forward/backward, per-epoch default odd padding",
                            "incomplete_last_band": "discard", "minimum_bands": 2},
            "resources": {"execution": utility_execution(execution), "blas_threads": 1, "max_input_bytes": MAX_INPUT_BYTES,
                          "source_loading": "one record at a time; reusable read-only memmaps; one model and sequential outer folds per child",
                          "dispatch_order": ["ea_fbcsp", "ts_lr", "fbcsp", "fgmdm", "csp_lda", "logvar_lr"],
                          "capacity_policy": "min(max_workers, floor((min(frozen budget, available memory)-reserve)/model budget)); live slot reservation can only reduce concurrency",
                          "supervision": "spawn; parent sentinel guard; cancellation, timeout or sampled RSS/available-memory limit terminates and joins every child",
                          "timeout_scope": "model suite including spawn and serialization; assembly uses caller cancellation per record",
                          "memory_scope": "sampled RSS, not OS allocation hard quota; worker cap includes mapped pages/interpreter; total includes parent; enclosing Windows Job owns descendants"},
            "core_replay": "reuse verified core hard OOF labels; independently refit its fixed recipes and require identical predictions before saving fitted models",
            "perfect_scores": "flag for independent replication, never fabricated or automatically accepted as SOTA"}


def utility_fit_budget(panel, available_band=(4.0, 40.0)):
    """Exact pipeline-fit counts for an applicable band, not a runtime promise."""
    channels = len(panel["output_contract"]["channels"])
    bands = int((available_band[1] - available_band[0]) // 4)
    _require(2 <= bands <= 12, "fit budget assumes an applicable default filter bank")
    candidates = {(c, min(channels, n), min(10, bands * min(channels, n)))
                  for c in FBCSP_GRID["C"] for n in FBCSP_GRID["n_components"]}
    counts = {name: 0 for name in LEARNER_SUITE}
    train_trials, dev_trials = [], []
    for fold in panel["folds"]:
        inner = min(3, len(fold["train_subjects"]))
        for name in LEARNER_SUITE:
            count = 1
            if inner >= 2 and name in {"fbcsp", "ea_fbcsp", "ts_lr"}:
                count += inner * (len(TS_GRID["C"]) if name == "ts_lr" else len(candidates))
            counts[name] += count
        train_trials.append(sum(t["eligible"] and t["subject"] in fold["train_subjects"] for t in panel["trials"]))
        dev_trials.append(sum(t["eligible"] and t["subject"] in fold["development_subjects"] for t in panel["trials"]))
    return {"pipeline_fits": counts, "total_utility_pipeline_fits": sum(counts.values()),
            "prior_core_evaluation_fits": 2 * len(panel["folds"]), "filterbank_bands": bands,
            "max_outer_training_trials": max(train_trials), "max_outer_development_trials": max(dev_trials),
            "note": "counts include final refit and core replay; source preprocessing and numerical iterations add runtime"}


def _check_core(core, panel):
    core = EvaluationReceipt.model_validate(core).model_dump(mode="json")
    _require(core["status"] == "evaluated", "core evaluation is not evaluated")
    _require(core["panel_hash"] == panel["panel_hash"] and core["folds"] == panel["folds"], "core panel/folds mismatch")
    _require(core["evaluation_mode"] == panel["evaluation_mode"], "core evaluation mode mismatch")
    path = Path(core["predictions_path"])
    _require(core["predictions_sha256"] and file_hash(path) == core["predictions_sha256"], "core prediction checksum mismatch")
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    frozen = {t["event_id"]: t for t in panel["trials"]}
    _require(Counter(r["event_id"] for r in rows) == Counter({k: 1 for k in frozen}), "core prediction inventory missing/extra/duplicate")
    by_id = {}
    folds = {s: f["id"] for f in panel["folds"] for s in f["development_subjects"]}
    labels = set(panel["class_labels"].values())
    for row in rows:
        trial = frozen[row["event_id"]]
        for field in ("subject", "record_id", "label", "role"):
            _require(row[field] == trial[field], f"core prediction {field} mismatch")
        _require(row["eligible"] == str(trial["eligible"]), "core eligibility mismatch")
        if trial["eligible"] and trial["subject"] in panel["development_subjects"]:
            _require(row["fold_id"] == folds[trial["subject"]], "core prediction is not in the frozen OOF fold")
            _require(row["primary_prediction"] in labels and row["secondary_prediction"] in labels, "core prediction label missing/invalid")
            _require(row["prediction"] == row["primary_prediction"], "core primary prediction aliases differ")
            by_id[row["event_id"]] = row
        else:
            _require(not any(row[k] for k in ("fold_id", "prediction", "primary_prediction", "secondary_prediction")), "core predicted a training or ineligible trial")
    return core, by_id


def _assemble(plan, result, store_root, panel, core, output, *, cancel_check=None, execution=None):
    evaluation._check_plan(result, plan, panel)
    _require(result.status == "completed" and result.completed == result.total == len(plan.records), "preprocessing did not complete")
    eligible = [t for t in panel["trials"] if t["eligible"]]
    n, c, t = len(eligible), len(panel["output_contract"]["channels"]), panel["output_contract"]["n_times"]
    _require(n * c * t * 8 * 2 <= MAX_INPUT_BYTES, "utility input memmap budget exceeded")
    rep = core["representation"]
    _require(rep["channels"] == panel["output_contract"]["channels"] and set(rep["records"]) == set(panel["records"]), "representation record/channel inventory mismatch")
    frozen = {t["event_id"]: t for t in eligible}
    configurations = {r.record_id: r for r in plan.records}
    paths = {"representation": output / "representation.npy", "phys_V": output / "phys_V.npy", "core_covariances": output / "core-covariances.npy"}
    observed, identities, source_audit = set(), [], []
    with ExitStack() as stack, threadpool_limits(limits=1):
        arrays = {}
        for name, path in paths.items():
            shape = (n, c, c) if name == "core_covariances" else (n, c, t)
            arrays[name] = np.lib.format.open_memmap(path, mode="w+", dtype="float64", shape=shape)
            stack.callback(_close_mmap, arrays[name])
        index = 0
        for item in sorted(result.records, key=lambda r: r["record_id"]):
            check_assembly_resources(execution)
            if cancel_check and cancel_check():
                raise UtilityExecutionError("cancelled", "utility cancelled during input assembly")
            rid = item["record_id"]
            _require(item["status"] == "completed" and item["method_id"] == configurations[rid].method_ref.id, "record execution/method mismatch")
            physical = evaluation._artifact_paths(Path(store_root), item)
            phys_hash = next(a["sha256"] for a in item["result"]["artifacts"] if a["name"] == "signal_V.npy")
            rows, shape = evaluation._check_record(physical, item, configurations[rid], plan, panel, observed)
            representation = rep["records"][rid]
            rep_path = Path(representation["array_path"])
            _require(representation["subject"] == panel["records"][rid]["subject"] and representation["shape"] == shape, "representation shape/subject mismatch")
            actual_rep_hash = phys_hash if rep_path.resolve() == physical["signal_V.npy"].resolve() else file_hash(rep_path)
            _require(actual_rep_hash == representation["array_sha256"], "representation checksum mismatch")
            with evaluation._mapped(physical["signal_V.npy"]) as phys, evaluation._mapped(rep_path) as represented:
                for values in (phys, represented):
                    _require(list(values.shape) == shape and values.dtype.kind in "fiu", "representation/phys array geometry invalid")
                for row in rows:
                    epoch = row["epoch_index"]  # Do NOT compact or reindex delivered record arrays.
                    for name, source in (("phys_V", phys), ("representation", represented)):
                        values = np.asarray(source[epoch], dtype=np.float64)
                        _require(np.isfinite(values).all(), f"nonfinite {name} signal: {rid}/{epoch}")
                        cov = covariance(values)
                        _require(np.isfinite(cov).all() and np.trace(cov) > 0, f"constant/zero {name} epoch: {rid}/{epoch}")
                        arrays[name][index] = values
                        if name == "representation":
                            arrays["core_covariances"][index] = cov
                    identities.append({**frozen[row["event_id"]], "array_index": index, "epoch_index": epoch})
                    index += 1
            source_audit.append({"record_id": rid, "phys_V": {"path": str(physical["signal_V.npy"].resolve()), "sha256": phys_hash},
                                 "representation": {"path": str(rep_path.resolve()), "sha256": representation["array_sha256"]}})
        _require(index == n and observed == set(frozen) and len({r["event_id"] for r in identities}) == n, "eligible array assembly is incomplete/duplicate")
        for values in arrays.values():
            values.flush()
    for subject, transform in rep["subjects"].items():
        if transform["transform_path"]:
            _require(file_hash(Path(transform["transform_path"])) == transform["transform_sha256"], f"upstream transform checksum mismatch: {subject}")
    manifest = {"trials": identities, "arrays": {k: _artifact(v) for k, v in paths.items()}, "sources": source_audit,
                "representation_policy": rep["policy"], "channels": rep["channels"], "sfreq": panel["output_contract"]["sfreq"],
                "core_receipt": core, "plan": plan.model_dump(mode="json"), "folds": panel["folds"]}
    return identities, paths, _save(output / "inputs.json", manifest)


def _fit_core(name, covs, train, labels, seed):
    """Exact existing numerical recipes, fitted only on this outer training fold."""
    if name == "csp_lda":
        filters = fit_csp(covs, train, labels[train])
        features = csp_features(covs, filters)
        model = LinearDiscriminantAnalysis(solver="lsqr", covariance_estimator=StableShrinkageCovariance(store_precision=False))
        model.fit(features[train], labels[train])
        return {"kind": name, "filters": filters, "classifier": model}, features
    features = np.log(np.maximum(np.diagonal(covs, axis1=1, axis2=2), VARIANCE_FLOOR))
    scaler = StandardScaler()
    train_features = scaler.fit_transform(features[train])
    model = LogisticRegression(max_iter=1000, random_state=seed, solver="lbfgs", penalty="l2", C=1.0,
                               tol=1e-4, fit_intercept=True, class_weight=None)
    model.fit(train_features, labels[train])
    return {"kind": name, "scaler": scaler, "classifier": model}, scaler.transform(features)


def _prediction_rows(trials, indices, fold, predicted, probability, score, labels):
    _require(len(predicted) == len(indices) and set(predicted) <= set(labels.values()), "prediction shape/classes invalid")
    if probability is not None:
        _require(probability.shape == (len(indices), 2) and np.isfinite(probability).all(), "probability geometry/nonfinite")
        _require(((probability >= 0) & (probability <= 1)).all() and np.allclose(probability.sum(axis=1), 1, atol=1e-10, rtol=0), "probabilities must sum to one; no zero-vector fallback")
        _require(score.shape == (len(indices),) and np.isfinite(score).all(), "invalid decision score")
    rows = []
    for j, i in enumerate(indices):
        trial = trials[i]
        _require(trial["subject"] in fold["development_subjects"] and trial["subject"] not in fold["train_subjects"], "prediction subject is not held out")
        rows.append({"event_id": trial["event_id"], "record_id": trial["record_id"], "epoch_index": trial["epoch_index"],
                     "array_index": int(i), "subject": trial["subject"], "label": trial["label"], "fold_id": fold["id"],
                     "prediction": str(predicted[j]), "proba_left": None if probability is None else float(probability[j, 0]),
                     "proba_right": None if probability is None else float(probability[j, 1]),
                     "decision_score": None if score is None else float(score[j])})
    return rows


def _predict_all(model, X, subjects):
    """One covariance/EA/feature pass, identical to the three public predictions.

    No model refitting or label inputs. FgMDM uses its official distance transform
    and the same negative-squared-distance softmax as pyriemann 0.7.
    """
    _require(model._signal_settings() == model._fitted_signal_settings_, "learner signal settings changed after fit")
    X, _ = model._check_trials(X, fitting=False)
    covs, adaptation = model._covariances(X, subjects, return_audit=True)
    classifier = model.model_.named_steps["classifier"]
    if model.learner == "fgmdm":
        distances = classifier.transform(covs)
        squared = distances ** 2
        predicted = model.classes_[distances.argmin(axis=1)]
        probability = softmax(-squared)
        score = squared[:, 0] - squared[:, 1]
    else:
        features = model.model_[:-1].transform(covs)
        predicted = classifier.predict(features)
        probability = classifier.predict_proba(features)
        score = classifier.decision_function(features)
    return predicted, probability, score, {"subject_ids": [] if subjects is None else np.unique(subjects).tolist(),
                                          "target_labels_received": False, "supervised_model_updated": False,
                                          "adaptation": adaptation, "execution": "single covariance/feature pass"}


def _run_learner(name, trials, paths, panel, core, core_rows, band, output, *, model_memory_bytes=8 * 1024**3):
    outcome = _empty_learner(name)
    destination = output / name
    destination.mkdir(parents=True, exist_ok=True)
    labels = np.asarray([t["label"] for t in trials])
    groups = np.asarray([t["subject"] for t in trials])
    all_rows, fold_outputs = [], []
    seed = panel["seed"] % (2**32)
    try:
        with ExitStack() as stack, threadpool_limits(limits=1):
            if name in {"csp_lda", "logvar_lr"}:
                data = stack.enter_context(evaluation._mapped(paths["core_covariances"]))
            else:
                data = stack.enter_context(evaluation._mapped(paths["phys_V" if name == "ea_fbcsp" else "representation"]))
            for fold in panel["folds"]:
                train = np.flatnonzero(np.isin(groups, fold["train_subjects"]))
                dev = np.flatnonzero(np.isin(groups, fold["development_subjects"]))
                _require(len(train) and len(dev) and not np.intersect1d(train, dev).size, "empty/overlapping outer fold")
                fold_path = destination / fold["id"]
                fold_path.mkdir(parents=True, exist_ok=True)
                with warnings.catch_warnings():
                    warnings.filterwarnings("error", category=RuntimeWarning)
                    warnings.filterwarnings("error", message=".*[Cc]onverg.*")
                    if name in {"csp_lda", "logvar_lr"}:
                        model, features = _fit_core(name, data, train, labels, seed)
                        replayed = model["classifier"].predict(features[dev])
                        column = "primary_prediction" if name == "csp_lda" else "secondary_prediction"
                        predicted = np.asarray([core_rows[trials[i]["event_id"]][column] for i in dev])
                        _require(np.array_equal(replayed, predicted), "core hard predictions differ from independent fold-local replay")
                        probability = score = None  # Never attach newly inferred probabilities to a legacy core receipt.
                        metadata = {"origin": "verified core hard OOF + identical fixed-recipe refit", "learner": name,
                                    "recipe": core["learner_metadata"], "upstream_representation": core["representation"]["policy"],
                                    "inner_cv": {"enabled": False, "reason": "frozen core baseline recipe"},
                                    "core_prediction_sha256": core["predictions_sha256"], "core_replay_exact_labels": True}
                        del features
                    else:
                        splits = min(3, len(fold["train_subjects"]))
                        tune = name != "fgmdm" and splits >= 2
                        model = make_learner(name, sfreq=panel["output_contract"]["sfreq"], available_band=band,
                                             upstream_adaptation="none" if name == "ea_fbcsp" else core["representation"]["policy"]["adaptation"],
                                             tune=tune, inner_splits=max(2, splits), random_state=seed,
                                             param_grid=None if not tune else TS_GRID if name == "ts_lr" else FBCSP_GRID,
                                             blas_threads=1, max_working_bytes=model_memory_bytes)
                        model.fit(data[train], labels[train], groups[train])
                        held_out = data[dev]  # One current fold copy, not another full source load.
                        prediction_subjects = groups[dev] if name == "ea_fbcsp" else None
                        predicted, probability, score, target_audit = _predict_all(model, held_out, prediction_subjects)
                        order = [list(model.classes_).index(panel["class_labels"][side]) for side in ("left", "right")]
                        _require(set(model.classes_) == set(panel["class_labels"].values()), "learner class semantics differ")
                        probability = probability[:, order]
                        if model.classes_[1] != panel["class_labels"]["right"]:
                            score = -score
                        metadata = model.describe()
                        if name != "fgmdm" and not tune:
                            metadata["inner_cv"]["reason"] = "one training subject: frozen default parameters, no label-based choice or trial CV"
                        metadata["target_adaptation_audit"] = target_audit
                        del held_out
                rows = _prediction_rows(trials, dev, fold, predicted, probability, score, panel["class_labels"])
                metadata.update(fold_id=fold["id"], train_subjects=fold["train_subjects"], development_subjects=fold["development_subjects"],
                                train_event_ids=[trials[i]["event_id"] for i in train], development_event_ids=[trials[i]["event_id"] for i in dev],
                                input_representation=outcome["input_representation"], available_band_hz=list(band),
                                grid_origin="frozen engineering candidates, not literature optima")
                model_path = fold_path / "model.joblib"
                joblib.dump(model, model_path, compress=3)
                fold_outputs.append({"fold_id": fold["id"], "train_subjects": fold["train_subjects"], "development_subjects": fold["development_subjects"],
                                     "model": _artifact(model_path), "metadata": _save(fold_path / "metadata.json", metadata),
                                     "predictions": _save(fold_path / "predictions.json", rows)})
                all_rows.extend(rows)
                del model
        expected = {t["event_id"] for t in trials if t["subject"] in panel["development_subjects"]}
        _require(Counter(r["event_id"] for r in all_rows) == Counter({e: 1 for e in expected}), "learner does not predict every eligible trial exactly once")
        subjects = {s: _metrics([r for r in all_rows if r["subject"] == s], panel["class_labels"]["right"]) for s in panel["development_subjects"]}
        if name in {"csp_lda", "logvar_lr"}:
            for s, metric in subjects.items():
                expected_ba = core["subjects"][s]["ba"] if name == "csp_lda" else core["secondary_subjects"][s]
                _require(np.isclose(metric["ba"], expected_ba, rtol=0, atol=1e-12), "core summary differs from actual trial predictions")
        summary = {key: _distribution([s[key] for s in subjects.values()]) for key in METRICS}
        notices = []
        if any(s["ba"] == 1 for s in subjects.values()):
            notices.append("perfect_subject_OOF_BA: check saved folds/models independently; this is not proof of SOTA")
        if len({r["prediction"] for r in all_rows}) == 1:
            notices.append("constant_class_predictions: reported honestly, never replaced with a target score")
        if name == "ea_fbcsp":
            notices.append("pre_adaptation_phys_V_control: does not measure candidate upstream global/subject EA differences")
        outcome.update(status="evaluated", error=None, subjects=subjects, summary=summary, warnings=notices, folds=fold_outputs,
                       predictions=_save(destination / "predictions.json", all_rows),
                       metadata=_save(destination / "metadata.json", {"learner": name, "folds": fold_outputs, "input_representation": outcome["input_representation"]}))
    except (MemoryError, KeyboardInterrupt):
        raise
    except Exception as exc:
        outcome.update(status="not_applicable" if isinstance(exc, LearnerNotApplicable) else "failed",
                       error=f"{type(exc).__name__}: {exc}", folds=fold_outputs,
                       metadata=_save(destination / "failure.json", {"learner": name, "error": f"{type(exc).__name__}: {exc}", "completed_folds": fold_outputs}))
    return outcome


def _empty_learner(name):
    return {"role": "primary" if name in PRIMARY_SUITE else "diagnostic" if name == "logvar_lr" else "benchmark",
            "status": "failed", "input_representation": "pre_adaptation_phys_V" if name == "ea_fbcsp" else "candidate_representation",
            "error": "not run", "predictions": None, "metadata": None, "folds": [], "subjects": {}, "summary": {}, "warnings": []}


def evaluate_dataset_utility(plan, result, store_root, panel, candidate_entry, core_receipt, output_dir, *, execution=None, cancel_check=None):
    """Write utility.json and replay artifacts, returning a strictly validated dict.

    The caller owns outer candidate selection. No scores here change the model
    suite/grid, epoch eligibility, subject grouping or candidate representation.
    Freeze utility_protocol(execution=execution) at service creation. cancel_check
    is a parent-only callable; abort raises UtilityExecutionError after reaping
    children and saving execution.json, never returns a partial selection score.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    # A cancelled rerun must never leave an earlier success receipt discoverable.
    (output / "utility.json").unlink(missing_ok=True)
    learners = {name: _empty_learner(name) for name in LEARNER_SUITE}
    inputs, subjects, common_error = None, {}, None
    config = utility_execution(execution)
    protocol = _save(output / "protocol.json", utility_protocol(execution=config))
    execution_artifact = None
    try:
        check_assembly_resources(config)
        validate_panel(panel)
        core, core_rows = _check_core(core_receipt, panel)
        for subject in panel["development_subjects"]:
            eligible = [t for t in panel["trials"] if t["eligible"] and t["subject"] == subject]
            _require({t["label"] for t in eligible} == set(panel["class_labels"].values()), "utility subject has missing eligible class")
            subjects[subject] = {"eligible_trials": len(eligible), "mean_ba": None, "learner_ba": {name: None for name in LEARNER_SUITE}}
        if core.get("candidate_id") is not None:
            _require(core["candidate_id"] == candidate_entry["id"], "core candidate identity mismatch")
        declared_adaptation = candidate_entry.get("parameters", {}).get("adaptation")
        if declared_adaptation is not None:
            _require(declared_adaptation == core["representation"]["policy"]["adaptation"], "candidate/core adaptation mismatch")
        trials, paths, inputs = _assemble(plan, result, store_root, panel, core, output, cancel_check=cancel_check, execution=config)
        band = _available_band(plan, panel["output_contract"]["sfreq"])
        payload = {"trials": trials, "paths": {k: str(v.resolve()) for k, v in paths.items()}, "panel": panel,
                   "core": core, "core_rows": core_rows, "band": band, "output": str(output.resolve())}
        learners, execution_audit = run_utility_tasks(payload, config, cancel_check)
        execution_artifact = _save(output / "execution.json", execution_audit)
        _require(set(learners) == set(LEARNER_SUITE), "process learner inventory differs from frozen suite")
    except UtilityExecutionError as exc:
        _save(output / "execution.json", {"configuration": config, **exc.audit, "status": "aborted", "failure_code": exc.code, "error": str(exc),
                                         "completed_learners": list(exc.completed)})
        raise
    except (MemoryError, KeyboardInterrupt):
        raise
    except Exception as exc:
        common_error = f"input validation: {type(exc).__name__}: {exc}"
        learners = {name: _empty_learner(name) for name in LEARNER_SUITE}
        for learner in learners.values():
            learner["error"] = common_error
    scores = {name: value["summary"]["ba"]["mean"] if value["status"] == "evaluated" else None for name, value in learners.items()}
    complete = all(scores[name] is not None for name in PRIMARY_SUITE)
    for subject, row in subjects.items():
        row["learner_ba"] = {name: value["subjects"][subject]["ba"] if value["status"] == "evaluated" else None for name, value in learners.items()}
        row["mean_ba"] = sum(row["learner_ba"][name] for name in PRIMARY_SUITE) / 3 if complete else None
    summary = _distribution([s["mean_ba"] for s in subjects.values()]) if complete else None
    receipt = {"utility_version": 1, "candidate_id": str(candidate_entry.get("id", "unknown")), "candidate_hash": digest(candidate_entry),
               "evaluation_mode": panel.get("evaluation_mode") if panel.get("evaluation_mode") in {"group_cross_validation", "subject_holdout"} else None,
               "panel_hash": panel.get("panel_hash") if isinstance(panel.get("panel_hash"), str) and len(panel["panel_hash"]) == 64 else None,
               "core_receipt_hash": digest(core_receipt), "protocol": protocol, "inputs": inputs, "execution": execution_artifact,
               "status": "evaluated" if complete else "incomplete", "selection_score": summary["mean"] if summary else None,
               "primary_suite": list(PRIMARY_SUITE), "learner_scores": scores, "subjects": subjects, "learners": learners,
               "summary": summary, "failure_reasons": [] if complete else [common_error] if common_error else
               [f"{name}: {learners[name]['error']}" for name in PRIMARY_SUITE if scores[name] is None],
               "warnings": ["development utility only; 75% BA is an aspiration, not a fallback or verified result"]}
    receipt = UtilityReceipt.model_validate(receipt).model_dump(mode="json")
    write_json(output / "utility.json", receipt)
    return receipt
