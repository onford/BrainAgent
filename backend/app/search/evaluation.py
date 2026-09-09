"""Independent, fixed-denominator development evaluator (no test-set fitting)."""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import csv
import errno
import json
import math
from pathlib import Path
from time import perf_counter
import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from app.preprocessing.schemas import ExecutionPlan, RunResult
from app.preprocessing.storage import digest, file_hash, within, write_json
from .evaluation_contracts import EvaluationReceipt
from .panel import DataUnevaluable, EVALUATOR_VERSION, validate_panel


class CandidateInvalid(ValueError):
    pass


@contextmanager
def _mapped(path):
    values = np.load(path, mmap_mode="r", allow_pickle=False)
    try:
        yield values
    finally:
        # Explicit closure matters on Windows, including failed feature extraction.
        mmap = getattr(values, "_mmap", None)
        if mmap is not None:
            mmap.close()


def _require(condition, message):
    if not condition:
        raise CandidateInvalid(message)


def _check_plan(result, plan, panel):
    identity = digest(plan.model_dump(mode="json"))
    _require(
        result.plan_ref.id == result.plan_ref.sha256 == identity,
        "result/plan checksum mismatch",
    )
    _require(
        digest(plan.input_snapshot.model_dump(mode="json")) == panel["input_hash"],
        "plan/frozen input mismatch",
    )
    _require(
        plan.request.input_ref.id
        == plan.request.input_ref.sha256
        == panel["input_hash"],
        "plan input reference mismatch",
    )
    expected = set(panel["records"])
    _require(
        set(plan.input_snapshot.collection.selected_record_ids) == expected,
        "selected records differ from panel",
    )
    _require(
        Counter(c.record_id for c in plan.records) == Counter({r: 1 for r in expected}),
        "plan records missing/extra/duplicate",
    )
    _require(
        Counter(r["record_id"] for r in result.records)
        == Counter({r: 1 for r in expected}),
        "result records missing/extra/duplicate",
    )
    _require(
        len({c.method_ref.id for c in plan.records}) == 1,
        "evaluate exactly one candidate method",
    )
    contract = panel["output_contract"]
    allowed = {
        "filter": "EEG-FILTER",
        "reference": "EEG-REREFERENCE",
        "resample": "EEG-RESAMPLE",
        "epoch": "EEG-EPOCH",
    }
    for config in plan.records:
        predecessor, resamples, epochs = "raw", 0, 0
        rate = panel["records"][config.record_id]["sfreq"]
        for step in config.steps:
            _require(
                allowed.get(step.op) == step.unit_id,
                "only fixed filter/reference/resample/epoch supported",
            )
            _require(
                step.fit_scope is None
                and step.model_from is None
                and step.decision_from is None,
                "fitted/adaptive preprocessing is unsupported",
            )
            _require(
                step.input == predecessor and not epochs,
                "candidate must be a continuous chain ending with epoch",
            )
            predecessor = step.id
            if step.op == "resample":
                resamples += 1
                rate = step.params["sfreq"]
                _require(
                    resamples == 1 and rate == contract["sfreq"],
                    "resampling must use the frozen rate exactly once",
                )
            if step.op == "epoch":
                epochs += 1
                _require(rate == contract["sfreq"], "epoch sampling rate differs")
                _require(
                    all(step.params[k] == contract[k] for k in ("tmin", "tmax")),
                    "epoch time contract differs",
                )
                _require(
                    step.params["picks"] == contract["channels"],
                    "epoch channel order differs",
                )
                _require(
                    step.params["event_id"] == panel["event_codes"],
                    "epoch labels differ",
                )
        _require(
            epochs == 1 and config.output == predecessor,
            "candidate output must be the terminal epoch",
        )


def _artifact_paths(root, item):
    entries = item["result"]["artifacts"]
    _require(bool(entries), "missing artifact inventory")
    _require(
        len({a["name"] for a in entries}) == len(entries), "duplicate artifact names"
    )
    _require(
        len({a["path"] for a in entries}) == len(entries), "duplicate artifact paths"
    )
    paths = {}
    for entry in entries:
        path = within(root, entry["path"])
        _require(file_hash(path) == entry["sha256"], "artifact checksum mismatch")
        paths[entry["name"]] = path
    _require(
        {"signal_V.npy", "events.json", "delta.json", "data-epo.fif", "provenance.json"}
        <= paths.keys(),
        "required artifact missing",
    )
    return paths


def _check_record(paths, item, config, plan, panel, observed):
    import mne

    contract = panel["output_contract"]
    rows = json.loads(paths["events.json"].read_text(encoding="utf-8"))
    delta = json.loads(paths["delta.json"].read_text(encoding="utf-8"))
    provenance = json.loads(paths["provenance.json"].read_text(encoding="utf-8"))
    _require(delta == item["result"]["delta"], "delta differs from result")
    _require(
        provenance["input_ref"] == plan.request.input_ref.model_dump(),
        "artifact input reference differs",
    )
    _require(
        provenance["method_ref"] == config.method_ref.model_dump(),
        "artifact method reference differs",
    )
    _require(
        provenance["engine_sha256"] == plan.engine_sha256, "artifact engine differs"
    )
    logs = [s for s in provenance["steps"] if s["branch"] == "main"]
    _require(len(logs) == len(config.steps), "artifact preprocessing steps differ")
    for log, step in zip(logs, config.steps):
        _require(
            (log["step_id"], log["unit_id"], log["op"])
            == (step.id, step.unit_id, step.op),
            "artifact operation differs",
        )
        _require(
            all(
                log["parameters"].get(k) == v
                for k, v in step.params.items()
                if k != "events"
            ),
            "artifact parameters differ",
        )
    after = delta["after"]
    _require(
        after["kind"] == "epochs" and after["unit"] == "V", "expected voltage epochs"
    )
    _require(
        after["channels"] == contract["channels"]
        and after["sfreq"] == contract["sfreq"],
        "artifact channels/rate differ",
    )
    _require(
        after["types"] == ["eeg"] * len(contract["channels"]),
        "artifact channel types differ",
    )
    frozen = {
        t["event_id"]: t for t in panel["trials"] if t["record_id"] == config.record_id
    }
    ids = [r["event_id"] for r in rows]
    _require(len(ids) == len(set(ids)), "duplicate original trial")
    _require(not (set(ids) - frozen.keys()), "extra original trial")
    retained = []
    for row in rows:
        trial = frozen[row["event_id"]]
        _require(
            row["label"] == trial["label"]
            and row["code"] == panel["event_codes"][trial["label"]],
            "wrong trial label/code",
        )
        _require(
            row["original_sample"] == trial["source_sample"], "source sample mismatch"
        )
        _require(
            row["output_sample"] == trial["output_sample"]
            and row["output_sfreq"] == contract["sfreq"],
            "resampled event sample/rate mismatch",
        )
        _require(type(row["retained"]) is bool, "invalid retention flag")
        if row["retained"]:
            _require(trial["eligible"], "candidate retained a common invalid window")
            _require(type(row["epoch_index"]) is int, "invalid epoch index")
            retained.append(row)
            observed.add(row["event_id"])
        else:
            _require(row["epoch_index"] is None, "dropped trial has an epoch index")
    expected = {k for k, t in frozen.items() if t["eligible"]}
    _require(
        {r["event_id"] for r in retained} == expected,
        "missing eligible original trial; denominator is frozen",
    )
    _require(set(ids) == set(frozen), "original event inventory is incomplete")
    retained.sort(key=lambda r: r["epoch_index"])
    _require(
        [r["epoch_index"] for r in retained] == list(range(len(retained))),
        "duplicate/missing epoch index",
    )
    _require(
        delta["events_before"] == len(frozen)
        and delta["events_retained"] == len(retained),
        "delta event counts differ",
    )
    expected_shape = [len(retained), len(contract["channels"]), contract["n_times"]]
    _require(after["shape"] == expected_shape, "artifact epoch shape differs")
    # Read FIFF metadata only. Do not call runner.verify_result: it preloads all
    # epochs and a second full signal array. Explicitly close MNE's file handles.
    epochs = mne.read_epochs(paths["data-epo.fif"], preload=False, verbose="ERROR")
    try:
        times = (
            np.arange(contract["epoch_start_offset"], contract["epoch_end_offset"] + 1)
            / contract["sfreq"]
        )
        _require(
            epochs.ch_names == contract["channels"]
            and epochs.info["sfreq"] == contract["sfreq"],
            "FIFF channel/rate contract differs",
        )
        _require(
            epochs.get_channel_types() == ["eeg"] * len(contract["channels"]),
            "FIFF channel types differ",
        )
        _require(
            epochs.times.shape == times.shape
            and np.allclose(epochs.times, times, rtol=0, atol=1e-12),
            "FIFF epoch time grid differs",
        )
        _require(
            np.array_equal(
                epochs.events, [[r["output_sample"], 0, r["code"]] for r in retained]
            ),
            "FIFF event/epoch correspondence differs",
        )
        _require(
            epochs.selection.tolist() == after["epoch_selection"],
            "FIFF epoch selection differs",
        )
    finally:
        for raw in getattr(epochs, "_raw", []) or []:
            raw.fid.close()
    return retained, expected_shape


def _coverage(panel, observed, predicted):
    groups = {}
    for role in ("train", "development"):
        trials = [t for t in panel["trials"] if t["role"] == role]
        eligible = {t["event_id"] for t in trials if t["eligible"]}
        groups[role] = {
            "original": len(trials),
            "eligible": len(eligible),
            "available": len(eligible & observed),
            "predicted": len(eligible & predicted),
            "missing": len(eligible - observed),
            "common_invalid": len(trials) - len(eligible),
            "common_invalid_reasons": dict(
                Counter(t["reason"] for t in trials if not t["eligible"])
            ),
        }
    # All top-level counts, including common invalid windows, use DEV only.
    return {**groups["development"], **groups}


def _baseline(baseline, panel):
    if baseline is None:
        return None
    if (
        baseline.get("status") != "evaluated"
        or baseline.get("panel_hash") != panel["panel_hash"]
        or baseline.get("evaluator_version") != EVALUATOR_VERSION
        or set(baseline.get("subjects", {})) != set(panel["development_subjects"])
    ):
        raise DataUnevaluable(
            "Baseline is not evaluated on this frozen panel/version and development subject set.",
            code="baseline_invalid",
        )
    scores = {
        s: baseline["subjects"][s].get("ba") for s in panel["development_subjects"]
    }
    macro = baseline.get("macro_ba")
    if any(
        type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
        for v in [*scores.values(), macro]
    ):
        raise DataUnevaluable(
            "Baseline subject BA and macro BA must be finite values in [0, 1].",
            code="baseline_invalid",
        )
    if not math.isclose(macro, sum(scores.values()) / len(scores), abs_tol=1e-12):
        raise DataUnevaluable(
            "Baseline macro BA differs from its development subject mean.",
            code="baseline_invalid",
        )
    for subject in scores:
        expected = sum(
            t["eligible"] for t in panel["trials"] if t["subject"] == subject
        )
        summary = baseline["subjects"][subject]
        if summary.get("missing") != 0 or summary.get("predicted_trials") != expected:
            raise DataUnevaluable(
                f"Baseline has incomplete frozen trial coverage for subject {subject}.",
                code="baseline_invalid",
            )
    return scores


def evaluate(
    result: RunResult,
    plan: ExecutionPlan,
    store_root: Path,
    panel: dict,
    output: Path,
    baseline: dict | None = None,
) -> dict:
    """Return aggregate metrics; write raw labels/predictions only to local TSV.

    ``output`` is a directory. ``subjects`` maps DEVELOPMENT subject IDs to
    summaries. No train predictions are made. All top-level coverage counts use
    development only; coverage.train/development give separate group counts.
    Missing means eligible - available, NOT eligible - predicted. Before candidate
    validation finishes, available counts only inspected matching trials.
    Resource errors propagate to the supervising worker, which owns budgets.
    """
    receipt = {
        "status": "execution_failure",
        "macro_ba": None,
        "mean_delta": None,
        "subjects": {},
        "coverage": None,
        "panel_hash": panel.get("panel_hash")
        if isinstance(panel.get("panel_hash"), str)
        else None,
        "evaluator_version": EVALUATOR_VERSION,
        "diagnostics": {"floor_fraction": None, "converged": None, "warnings": []},
        "timings": {"feature": 0.0, "train": 0.0, "predict": 0.0},
        "attribution": "Development-condition preprocessing utility; no test-set or causal generalization claim.",
    }
    observed, predicted_ids = set(), set()
    stage, started = "validation", perf_counter()
    panel_valid = False
    try:
        validate_panel(panel)
        panel_valid = True
        baseline_scores = _baseline(baseline, panel)
        _check_plan(result, plan, panel)
        if result.status != "completed" or any(
            r["status"] != "completed" for r in result.records
        ):
            raise RuntimeError("preprocessing execution did not complete")
        _require(
            result.completed == result.total == len(plan.records),
            "run completion counts differ",
        )
        configs = {c.record_id: c for c in plan.records}
        sources = []
        for item in sorted(result.records, key=lambda r: r["record_id"]):
            config = configs[item["record_id"]]
            _require(item["method_id"] == config.method_ref.id, "result method differs")
            paths = _artifact_paths(Path(store_root), item)
            rows, shape = _check_record(paths, item, config, plan, panel, observed)
            sources.append((paths["signal_V.npy"], rows, shape))
        stage, started = "feature", perf_counter()
        features, identities = [], []
        floored, total = 0, 0
        for path, rows, shape in sources:
            with _mapped(path) as values:
                _require(
                    list(values.shape) == shape and values.dtype.kind in "fiu",
                    "signal shape/dtype differs",
                )
                for row in rows:
                    # A bounded owning copy prevents views from outliving mmap.
                    trial = np.array(
                        values[row["epoch_index"]], dtype=np.float64, copy=True
                    )
                    if not np.isfinite(trial).all():
                        raise RuntimeError("nonfinite signal")
                    with np.errstate(over="raise", invalid="raise"):
                        variance = np.var(trial, axis=-1, dtype=np.float64)
                        feature = np.log(np.maximum(variance, 1e-20))
                    if not np.isfinite(feature).all():
                        raise RuntimeError("nonfinite logvariance")
                    floored += int(np.count_nonzero(variance <= 1e-20))
                    total += len(variance)
                    features.append(feature)
                    identities.append(row["event_id"])
        receipt["timings"][stage] = perf_counter() - started
        receipt["diagnostics"]["floor_fraction"] = floored / total
        frozen = {t["event_id"]: t for t in panel["trials"]}
        X = np.asarray(features, dtype=np.float64)
        labels = np.asarray([frozen[e]["label"] for e in identities])
        train = np.asarray([frozen[e]["role"] == "train" for e in identities])
        stage, started = "train", perf_counter()
        scaler = StandardScaler()
        train_X = scaler.fit_transform(X[train])
        classifier = LogisticRegression(max_iter=1000, random_state=42)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            classifier.fit(train_X, labels[train])
        receipt["diagnostics"].update(
            converged=not any(
                issubclass(w.category, ConvergenceWarning) for w in caught
            ),
            warnings=[w.category.__name__ for w in caught],
        )
        receipt["timings"][stage] = perf_counter() - started
        stage, started = "predict", perf_counter()
        predictions = classifier.predict(scaler.transform(X[~train]))
        dev_ids = [e for e, is_train in zip(identities, train) if not is_train]
        by_id = dict(zip(dev_ids, predictions.tolist()))
        predicted_ids.update(by_id)
        for subject in panel["development_subjects"]:
            original = [t for t in panel["trials"] if t["subject"] == subject]
            eligible = [t for t in original if t["eligible"]]
            recalls = {}
            for side, label in panel["class_labels"].items():
                members = [t for t in eligible if t["label"] == label]
                recalls[side] = sum(
                    by_id[t["event_id"]] == label for t in members
                ) / len(members)
            ba = (recalls["left"] + recalls["right"]) / 2
            receipt["subjects"][subject] = {
                "recalls": recalls,
                "recall_left": recalls["left"],
                "recall_right": recalls["right"],
                "ba": ba,
                "delta": None
                if baseline_scores is None
                else ba - baseline_scores[subject],
                "original_trials": len(original),
                "eligible_trials": len(eligible),
                "available_trials": len(eligible),
                "predicted_trials": len(eligible),
                "missing": 0,
            }
        receipt["macro_ba"] = float(
            np.mean([s["ba"] for s in receipt["subjects"].values()])
        )
        if baseline_scores is not None:
            receipt["mean_delta"] = float(
                np.mean([s["delta"] for s in receipt["subjects"].values()])
            )
        receipt["timings"][stage] = perf_counter() - started
        stage = "output"
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        prediction_path = output / "originalpredictions.tsv"
        fields = [
            "event_id",
            "record_id",
            "subject",
            "role",
            "label",
            "eligible",
            "reason",
            "prediction",
        ]
        with prediction_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t")
            writer.writeheader()
            for trial in panel["trials"]:
                writer.writerow(
                    {
                        **{k: trial[k] for k in fields if k != "prediction"},
                        "prediction": by_id.get(trial["event_id"], ""),
                    }
                )
        receipt.update(
            status="evaluated", predictions_path=str(prediction_path.resolve())
        )
    except MemoryError:
        raise
    except DataUnevaluable as exc:
        receipt.update(
            status="data_unevaluable",
            error_code=exc.code,
            error=str(exc),
            stop_search=True,
        )
    except CandidateInvalid as exc:
        receipt.update(status="candidate_invalid", error_code=str(exc), error=str(exc))
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        if isinstance(exc, OSError) and (
            exc.errno in {errno.ENOMEM, errno.ENOSPC, errno.EDQUOT}
            or getattr(exc, "winerror", None) in {112, 1455}
        ):
            raise  # memory/disk exhaustion belongs to the worker
        receipt.update(
            status="candidate_invalid"
            if stage == "validation"
            else "execution_failure",
            error_code=f"{stage}: {type(exc).__name__}",
            error=str(exc) or type(exc).__name__,
        )
    except Exception as exc:
        receipt.update(
            status="execution_failure",
            error_code=f"{stage}: {type(exc).__name__}",
            error=str(exc) or type(exc).__name__,
        )
    finally:
        if stage in receipt["timings"]:
            receipt["timings"][stage] = perf_counter() - started
    if receipt["status"] != "evaluated":
        receipt["macro_ba"] = receipt["mean_delta"] = None
        receipt["subjects"] = {}
        predicted_ids.clear()
    if panel_valid:
        receipt["coverage"] = _coverage(panel, observed, predicted_ids)
        for subject in panel["development_subjects"]:
            if subject not in receipt["subjects"]:
                trials = [t for t in panel["trials"] if t["subject"] == subject]
                receipt["subjects"][subject] = {
                    "recalls": {"left": None, "right": None},
                    "recall_left": None,
                    "recall_right": None,
                    "ba": None,
                    "delta": None,
                    "original_trials": len(trials),
                    "eligible_trials": sum(t["eligible"] for t in trials),
                    "available_trials": sum(
                        t["eligible"] and t["event_id"] in observed for t in trials
                    ),
                    "predicted_trials": 0,
                    "missing": sum(
                        t["eligible"] and t["event_id"] not in observed for t in trials
                    ),
                }
    receipt = EvaluationReceipt.model_validate(receipt).model_dump(mode="json")
    write_json(Path(output) / "receipt.json", receipt)
    return receipt
