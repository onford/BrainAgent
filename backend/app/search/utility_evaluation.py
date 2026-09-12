"""Two-model OOF utility: three independent EEGNet seeds and CSP-LDA control."""

from __future__ import annotations

from collections import Counter
from contextlib import ExitStack
import csv
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import warnings

import joblib
import numpy as np
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score, cohen_kappa_score, f1_score,
    log_loss, roc_auc_score,
)
from threadpoolctl import threadpool_limits

from app.preprocessing.storage import digest, file_hash, write_json
from . import evaluation
from .evaluation_contracts import EvaluationReceipt
from .evaluation_numeric import (
    StableShrinkageCovariance, covariance, csp_features, fit_csp,
)
from . import eegnet
from .panel import validate_panel
from .utility_contracts import EEGNET_SEEDS, LEARNER_SUITE, PRIMARY_SUITE, UtilityReceipt
from .utility_parallel import UtilityExecutionError, check_assembly_resources, run_utility_tasks, utility_execution


METRICS = ("ba", "accuracy", "f1", "kappa", "auc", "brier", "logloss")
MAX_INPUT_BYTES = 8 * 1024**3  # Candidate signal and covariance memmaps combined.


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


def utility_protocol(*, execution=None):
    """Freeze implementation, training settings, seeds and runtime before search."""
    folder = Path(__file__).parent
    files = ("utility_evaluation.py", "utility_contracts.py", "utility_parallel.py", "eegnet.py", "requirements-learners.txt",
             "evaluation.py", "evaluation_numeric.py", "evaluation_contracts.py", "panel.py")
    versions = {}
    for name in ("numpy", "scipy", "scikit-learn", "torch", "mne", "joblib", "pydantic", "threadpoolctl"):
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = None
    config = utility_execution(execution)
    return {"utility_version": 2, "primary_suite": list(PRIMARY_SUITE), "learner_suite": list(LEARNER_SUITE),
            "implementation_sha256": {name: file_hash(folder / name) for name in files},
            "supervision_implementation_sha256": {name: file_hash(folder.parent / "preprocessing" / name)
                                                   for name in ("parallel.py", "resources.py")},
            "runtime_library_versions": versions, "eegnet": eegnet.protocol(config["eegnet_training"]),
            "seeds": list(EEGNET_SEEDS),
            "evaluation_modes": {"group_cross_validation": "each selected subject OOF once per seed",
                                 "subject_holdout": "development eligible denominator only"},
            "selection": "mean of three EEGNet seed subject-macro balanced accuracies; all seeds required; no probability ensemble",
            "benchmark": "CSP-LDA subject-macro BA, excluded from selection",
            "metrics": {"range": "fractions [0,1], kappa [-1,1], logloss >=0", "f1": "binary right class",
                        "subject_sd_ddof": 0, "seed_sd_ddof": 0, "lower_quartile": "linear quantile 0.25",
                        "subject_aggregation": "mean metric across seeds, then equal-subject distribution",
                        "auc": "right-class probability; never hard-label pseudo AUC",
                        "logloss": "sklearn float64 epsilon clipping", "probability_calibration": "not independently calibrated"},
            "resources": {"execution": config, "blas_threads": 1, "max_input_bytes": MAX_INPUT_BYTES,
                          "source_loading": "one record at a time; reusable read-only memmaps; sequential seeds and folds per model process",
                          "dispatch_order": list(LEARNER_SUITE),
                          "supervision": "spawn; parent sentinel; cancellation, timeout and sampled memory bounds terminate and join workers"},
            "core_replay": "CSP-LDA independently refitted on each outer training fold; hard labels must match core receipt",
            "perfect_scores": "independent replication required; not proof of SOTA"}


def utility_fit_budget(panel, available_band=None):
    """Exact fixed training counts, independent of the candidate passband."""
    folds = panel["folds"]
    counts = {"eegnet": len(EEGNET_SEEDS) * len(folds), "csp_lda": len(folds)}
    return {"pipeline_fits": counts, "total_utility_pipeline_fits": sum(counts.values()),
            "prior_core_evaluation_fits": len(folds),
            "max_outer_training_trials": max(sum(t["eligible"] and t["subject"] in f["train_subjects"] for t in panel["trials"]) for f in folds),
            "max_outer_development_trials": max(sum(t["eligible"] and t["subject"] in f["development_subjects"] for t in panel["trials"]) for f in folds),
            "note": "EEGNet early stopping within outer-training subjects; no extra refit or model hyperparameter search"}


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
            _require(row["primary_prediction"] in labels, "core prediction label missing/invalid")
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
    _require(8 * n * c * (t + c) <= MAX_INPUT_BYTES, "utility input memmap budget exceeded")
    rep = core["representation"]
    _require(rep["channels"] == panel["output_contract"]["channels"] and set(rep["records"]) == set(panel["records"]), "representation record/channel inventory mismatch")
    frozen = {t["event_id"]: t for t in eligible}
    configurations = {r.record_id: r for r in plan.records}
    paths = {"representation": output / "representation.npy", "core_covariances": output / "core-covariances.npy"}
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
                        if name == "representation":
                            arrays[name][index] = values
                            arrays["core_covariances"][index] = cov
                    identities.append({**frozen[row["event_id"]], "array_index": index, "epoch_index": epoch})
                    index += 1
            source_audit.append({"record_id": rid, "phys_V": {"path": str(physical["signal_V.npy"].resolve()), "sha256": phys_hash},
                                 "representation": {"path": str(rep_path.resolve()), "sha256": representation["array_sha256"]}})
        _require(index == n and observed == set(frozen) and len({r["event_id"] for r in identities}) == n, "eligible array assembly is incomplete/duplicate")
        for values in arrays.values():
            values.flush()
    manifest = {"trials": identities, "arrays": {k: _artifact(v) for k, v in paths.items()}, "sources": source_audit,
                "representation_version": rep["version"], "channels": rep["channels"], "sfreq": panel["output_contract"]["sfreq"],
                "core_receipt": core, "plan": plan.model_dump(mode="json"), "folds": panel["folds"]}
    return identities, paths, _save(output / "inputs.json", manifest)


def _fit_core(name, covs, train, labels, seed):
    """CSP-LDA fitted only on the frozen outer-training subjects."""
    _require(name == "csp_lda", "unsupported core learner")
    filters = fit_csp(covs, train, labels[train])
    features = csp_features(covs, filters)
    model = LinearDiscriminantAnalysis(solver="lsqr", covariance_estimator=StableShrinkageCovariance(store_precision=False))
    model.fit(features[train], labels[train])
    return {"kind": name, "filters": filters, "classifier": model}, features


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


def _empty_prediction():
    return {"status": "failed", "error": "not run", "predictions": None, "metadata": None,
            "folds": [], "subjects": {}, "summary": {}, "warnings": []}


def _empty_learner(name):
    return {**_empty_prediction(), "role": "primary" if name == "eegnet" else "benchmark",
            "input_representation": "candidate_representation", "seeds": {}, "seed_summary": None}


def _summarize_run(rows, folds, panel, trials, destination, metadata):
    expected = {t["event_id"] for t in trials if t["subject"] in panel["development_subjects"]}
    _require(Counter(r["event_id"] for r in rows) == Counter({e: 1 for e in expected}), "every seed/model must predict every eligible trial exactly once")
    subjects = {s: _metrics([r for r in rows if r["subject"] == s], panel["class_labels"]["right"])
                for s in panel["development_subjects"]}
    return {"status": "evaluated", "error": None, "folds": folds, "subjects": subjects,
            "summary": {key: _distribution([s[key] for s in subjects.values()]) for key in METRICS},
            "predictions": _save(destination / "predictions.json", rows),
            "metadata": _save(destination / "metadata.json", metadata), "warnings": []}


def _run_learner(name, trials, paths, panel, core, core_rows, band, output, *, model_memory_bytes=8 * 1024**3,
                 training_config=None):
    _require(name in LEARNER_SUITE, "unknown learner")
    outcome = _empty_learner(name)
    destination = output / name
    destination.mkdir(parents=True, exist_ok=True)
    labels = np.asarray([t["label"] for t in trials])
    groups = np.asarray([t["subject"] for t in trials])
    binary = (labels == panel["class_labels"]["right"]).astype(int)
    combined = []
    completed_folds = []
    seed = None  # Input mapping can fail before the first seeded run begins.
    try:
        with evaluation._mapped(paths["core_covariances" if name == "csp_lda" else "representation"]) as data, threadpool_limits(limits=1):
            for seed in (EEGNET_SEEDS if name == "eegnet" else (panel["seed"] % (2**32),)):
                run_path = destination / f"s{seed}" if name == "eegnet" else destination
                run_path.mkdir(parents=True, exist_ok=True)
                rows, completed_folds = [], []
                if name == "eegnet":
                    outcome["seeds"][str(seed)] = {**_empty_prediction(), "seed": seed}
                for fold_index, fold in enumerate(panel["folds"]):
                    train = np.flatnonzero(np.isin(groups, fold["train_subjects"]))
                    dev = np.flatnonzero(np.isin(groups, fold["development_subjects"]))
                    _require(len(train) and len(dev) and not np.intersect1d(train, dev).size, "empty/overlapping outer fold")
                    fold_path = run_path / f"f{fold_index}"
                    fold_path.mkdir(parents=True, exist_ok=True)
                    if name == "eegnet":
                        model_path = fold_path / "model.pt"
                        metadata = eegnet.train_fold(data[train], binary[train], groups[train], seed=seed,
                            sfreq=panel["output_contract"]["sfreq"], checkpoint_path=model_path, training_config=training_config)
                        probability = eegnet.predict_checkpoint(model_path, data[dev]).astype(np.float64)
                        _require(probability.shape == (len(dev), 2) and np.isfinite(probability).all()
                                 and ((probability >= 0) & (probability <= 1)).all()
                                 and np.allclose(probability.sum(axis=1), 1, atol=1e-6, rtol=0),
                                 "invalid EEGNet probability distribution; no fallback")
                        probability /= probability.sum(axis=1, keepdims=True)
                        predicted = np.asarray([panel["class_labels"]["left"], panel["class_labels"]["right"]])[probability.argmax(axis=1)]
                        score = probability[:, 1]
                        metadata.update(fit_event_ids=[trials[i]["event_id"] for i in train if groups[i] in metadata["fit_subjects"]],
                                        validation_event_ids=[trials[i]["event_id"] for i in train if groups[i] in metadata["validation_subjects"]])
                    else:
                        with warnings.catch_warnings():
                            warnings.filterwarnings("error", category=RuntimeWarning)
                            model, features = _fit_core(name, data, train, labels, seed)
                            predicted = model["classifier"].predict(features[dev])
                        _require(np.array_equal(predicted, [core_rows[trials[i]["event_id"]]["primary_prediction"] for i in dev]),
                                 "core hard predictions differ from independent fold-local replay")
                        probability = score = None
                        metadata = {"learner": name, "recipe": core["learner_metadata"], "core_replay_exact_labels": True,
                                    "core_prediction_sha256": core["predictions_sha256"]}
                        model_path = fold_path / "model.joblib"
                        joblib.dump(model, model_path, compress=3)
                        del model, features
                    fold_rows = _prediction_rows(trials, dev, fold, predicted, probability, score, panel["class_labels"])
                    if name == "eegnet":
                        for row in fold_rows:
                            row["seed"] = seed
                    metadata.update(fold_id=fold["id"], train_subjects=fold["train_subjects"], development_subjects=fold["development_subjects"],
                                    train_event_ids=[trials[i]["event_id"] for i in train], development_event_ids=[trials[i]["event_id"] for i in dev],
                                    input_representation="candidate_representation", target_labels_received=False)
                    completed_folds.append({"fold_id": fold["id"], "train_subjects": fold["train_subjects"], "development_subjects": fold["development_subjects"],
                        "model": _artifact(model_path), "metadata": _save(fold_path / "metadata.json", metadata),
                        "predictions": _save(fold_path / "predictions.json", fold_rows)})
                    rows.extend(fold_rows)
                run = _summarize_run(rows, completed_folds, panel, trials, run_path, {"learner": name, "seed": seed, "folds": completed_folds})
                if name == "csp_lda":
                    for subject, metric in run["subjects"].items():
                        _require(np.isclose(metric["ba"], core["subjects"][subject]["ba"], rtol=0, atol=1e-12), "core summary differs from actual predictions")
                    outcome.update(run)
                else:
                    outcome["seeds"][str(seed)] = {**run, "seed": seed}
                    combined.extend(rows)
        if name == "eegnet":
            runs = list(outcome["seeds"].values())
            subjects = {}
            for subject in panel["development_subjects"]:
                subject_runs = [run["subjects"][subject] for run in runs]
                subjects[subject] = {"n_trials": subject_runs[0]["n_trials"], "probability_status": "available",
                    **{key: float(np.mean([record[key] for record in subject_runs])) for key in METRICS}}
            scores = [run["summary"]["ba"]["mean"] for run in runs]
            seed_summary = {"seeds": list(EEGNET_SEEDS), "mean_ba": float(np.mean(scores)), "seed_sd": float(np.std(scores, ddof=0)),
                            "minimum_ba": min(scores), "maximum_ba": max(scores)}
            outcome.update(status="evaluated", error=None, subjects=subjects,
                summary={key: _distribution([s[key] for s in subjects.values()]) for key in METRICS}, seed_summary=seed_summary,
                predictions=_save(destination / "predictions.json", combined),
                metadata=_save(destination / "metadata.json", {"learner": name, "seeds": outcome["seeds"], "seed_summary": seed_summary}))
    except (MemoryError, KeyboardInterrupt):
        raise
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        if name == "eegnet" and seed is not None and str(seed) in outcome["seeds"] and outcome["seeds"][str(seed)]["status"] != "evaluated":
            outcome["seeds"][str(seed)].update(error=error, folds=completed_folds)
        outcome.update(status="failed", error=error,
            metadata=_save(destination / "failure.json", {"learner": name, "error": error, "completed_folds": completed_folds, "seeds": outcome["seeds"]}))
    return outcome


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
        trials, paths, inputs = _assemble(plan, result, store_root, panel, core, output, cancel_check=cancel_check, execution=config)
        band = None
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
        row["mean_ba"] = sum(row["learner_ba"][name] for name in PRIMARY_SUITE) / len(PRIMARY_SUITE) if complete else None
    summary = _distribution([s["mean_ba"] for s in subjects.values()]) if complete else None
    receipt = {"utility_version": 2, "candidate_id": str(candidate_entry.get("id", "unknown")), "candidate_hash": digest(candidate_entry),
               "evaluation_mode": panel.get("evaluation_mode") if panel.get("evaluation_mode") in {"group_cross_validation", "subject_holdout"} else None,
               "panel_hash": panel.get("panel_hash") if isinstance(panel.get("panel_hash"), str) and len(panel["panel_hash"]) == 64 else None,
               "core_receipt_hash": digest(core_receipt), "protocol": protocol, "inputs": inputs, "execution": execution_artifact,
               "status": "evaluated" if complete else "incomplete", "selection_score": summary["mean"] if summary else None,
               "primary_suite": list(PRIMARY_SUITE), "seed_summary": learners["eegnet"]["seed_summary"], "learner_scores": scores, "subjects": subjects, "learners": learners,
               "summary": summary, "failure_reasons": [] if complete else [common_error] if common_error else
               [f"{name}: {learners[name]['error']}" for name in PRIMARY_SUITE if scores[name] is None],
               "warnings": ["development utility; final held-out test required after preprocessing selection"]}
    receipt = UtilityReceipt.model_validate(receipt).model_dump(mode="json")
    write_json(output / "utility.json", receipt)
    return receipt
