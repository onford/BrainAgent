from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil
import traceback

import mne
import numpy as np

from .inputs import read_record
from .storage import canonical, digest, file_hash, within, write_json
from .units import invoke


class Cancelled(Exception):
    pass


def state(x):
    eeg = x.get_data(picks="eeg")
    rank_data = (
        eeg if eeg.ndim == 2 else eeg.transpose(1, 0, 2).reshape(eeg.shape[1], -1)
    )
    return {
        "kind": "raw" if isinstance(x, mne.io.BaseRaw) else "epochs",
        "channels": x.ch_names,
        "types": x.get_channel_types(),
        "bads": list(x.info["bads"]),
        "unit": "V",
        "custom_ref_applied": int(x.info["custom_ref_applied"]),
        "sfreq": float(x.info["sfreq"]),
        "shape": list(x.get_data().shape),
        "first_sample": int(x.first_samp) if isinstance(x, mne.io.BaseRaw) else None,
        "epoch_selection": x.selection.tolist()
        if isinstance(x, mne.BaseEpochs)
        else None,
        "highpass": float(x.info["highpass"]),
        "lowpass": float(x.info["lowpass"]),
        "rank": int(np.linalg.matrix_rank(rank_data)),
    }


def data_hash(x):
    import hashlib

    return hashlib.sha256(
        canonical(state(x)).encode() + np.ascontiguousarray(x.get_data()).tobytes()
    ).hexdigest()


def save_artifacts(value, directory: Path, name="artifacts"):
    """Lossless arrays with explicit nonfinite masks; small JSON has no NaN."""
    if isinstance(value, np.ndarray):
        if value.dtype.hasobject:
            raise ValueError("object arrays are not serializable artifacts")
        filename = name + ".npy"
        np.save(directory / filename, value, allow_pickle=False)
        loaded = np.load(directory / filename, allow_pickle=False)
        if not np.array_equal(value, loaded, equal_nan=True):
            raise ValueError("array reread failed")
        result = {
            "file": filename,
            "shape": list(value.shape),
            "dtype": str(value.dtype),
            "sha256": file_hash(directory / filename),
        }
        if np.issubdtype(value.dtype, np.number) and not np.isfinite(value).all():
            mask = name + "_valid.npy"
            np.save(directory / mask, np.isfinite(value), allow_pickle=False)
            result.update(
                valid_mask=mask,
                missing_reason="nonfinite diagnostic values; see unit contract",
            )
        return result
    if isinstance(value, np.generic):
        return save_artifacts(value.item(), directory, name)
    if isinstance(value, float) and not np.isfinite(value):
        return {"value": None, "reason": "nonfinite diagnostic"}
    if isinstance(value, dict):
        return {
            str(k): save_artifacts(v, directory, f"{name}_{i}")
            for i, (k, v) in enumerate(value.items())
        }
    if isinstance(value, (list, tuple)):
        return [
            save_artifacts(v, directory, f"{name}_{i}") for i, v in enumerate(value)
        ]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"unregistered artifact serializer: {type(value).__name__}")


def verify_result(root: Path, result):
    if not result or not result.get("artifacts"):
        return False
    try:
        for artifact in result["artifacts"]:
            if file_hash(within(root, artifact["path"])) != artifact["sha256"]:
                return False
        data = next(a for a in result["artifacts"] if a["kind"] == "data")
        path = within(root, data["path"])
        x = (
            mne.read_epochs(path, preload=True, verbose="ERROR")
            if path.name.endswith("-epo.fif")
            else mne.io.read_raw_fif(path, preload=True, verbose="ERROR")
        )
        return bool(x.get_data().size and np.isfinite(x.get_data()).all())
    except (OSError, ValueError, StopIteration):
        return False


def run_record(
    plan,
    config,
    source_root: Path,
    output: Path,
    storage_root: Path,
    cancelled=lambda: False,
):
    record = next(
        r for r in plan.input_snapshot.collection.records if r.id == config.record_id
    )
    output.mkdir(parents=True, exist_ok=False)
    work = output / "input"
    # A materialized copy protects originals from readers and library in-place operations.
    for relative, expected in record.files.items():
        src, dst = within(source_root, relative), within(work, relative)
        if file_hash(src) != expected:
            raise ValueError("source changed before copy")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        if file_hash(dst) != expected:
            raise ValueError("work copy checksum mismatch")
    raw, events, event_map = read_record(
        work,
        record,
        plan.input_snapshot.survey.event_id,
        plan.input_snapshot.survey.context_event_id,
    )
    input_state = state(raw)
    nodes = {"raw": {"data": raw, "model": None, "artifacts": {}}}
    logs, decisions, model_bindings = [], {}, {}
    steps = {s.id: s for s in config.steps}

    def check_cancel():
        if cancelled():
            raise Cancelled("cancelled at step boundary")

    def scoped_input(name, scope):
        interval = next(i for i in record.intervals if i.id == scope.ids[0])
        if name == "raw":
            return raw.copy().crop(
                interval.start / record.sfreq, (interval.stop - 1) / record.sfreq
            )
        predecessor = steps[name]
        if predecessor.op not in ("filter", "reference", "detrend"):
            raise ValueError(
                "fit ancestors must be replayable without fitted state or data-dependent decisions"
            )
        check_cancel()
        x = scoped_input(predecessor.input, scope)
        result = invoke(
            predecessor.unit_id, predecessor.op, x, **deepcopy(predecessor.params)
        )
        logs.append(
            {
                "step_id": predecessor.id,
                "branch": "fit",
                "scope": scope.model_dump(),
                "parameters": predecessor.params,
                "input_hash": data_hash(x),
                "output_hash": data_hash(result["data"]),
            }
        )
        return result["data"]

    try:
        for step in config.steps:
            check_cancel()
            directory = output / step.id
            directory.mkdir()
            x = nodes[step.input]["data"]
            actual = deepcopy(step.params)
            model = None
            if step.op == "eog_fit":
                x = scoped_input(step.input, step.fit_scope)
                actual["scope"] = step.fit_scope.model_dump()
            elif step.op == "eog_apply":
                model = nodes[step.model_from]["model"]
                binding = model_bindings[step.model_from]
                if file_hash(output / binding["file"]) != binding["sha256"]:
                    raise ValueError("fitted model artifact changed")
            elif step.op == "epoch":
                actual["events"] = events.copy()
            elif step.op == "mark_channels":
                detection = decisions[step.decision_from]
                if detection["input_hash"] != data_hash(x):
                    raise ValueError("decision bound to a different data version")
                actual["bads"] = detection["candidates"]
                write_json(
                    directory / "decision.json",
                    {
                        **detection,
                        "policy": "accept detector candidates within explicit max_fraction",
                        "max_fraction": actual["max_fraction"],
                        "applied_at": step.id,
                    },
                )
            before_hash = data_hash(x)
            result = invoke(step.unit_id, step.op, x, model=model, **actual)
            y = result["data"]
            if data_hash(x) != before_hash:
                raise ValueError("unit mutated its input")
            if not y.get_data().size or not np.isfinite(y.get_data()).all():
                raise ValueError("empty or invalid output")
            if step.op != "epoch" and y.get_data().shape != x.get_data().shape:
                raise ValueError("unexpected signal shape change")
            if step.op == "eog_fit":
                model_path = directory / "eog-model.h5"
                result["model"]["estimator"].save(model_path, overwrite=False)
                loaded = mne.preprocessing.read_eog_regression(model_path)
                if not np.array_equal(loaded.coef_, result["model"]["estimator"].coef_):
                    raise ValueError("model reread differs")
                binding = {
                    "file": model_path.relative_to(output).as_posix(),
                    "sha256": file_hash(model_path),
                    "fit_data_hash": before_hash,
                    "scope": step.fit_scope.model_dump(),
                    "intervals": [
                        i.model_dump()
                        for i in record.intervals
                        if i.id in step.fit_scope.ids
                    ],
                    "signature": save_artifacts(
                        result["model"]["signature"], directory
                    ),
                    "reference_id": actual["reference_id"],
                }
                write_json(directory / "model-binding.json", binding)
                model_bindings[step.id] = binding
            if step.op == "amplitude_windows":
                decisions[step.id] = {
                    "decision_id": digest(
                        [config.method_ref.id, record.id, step.id, before_hash]
                    ),
                    "input_hash": before_hash,
                    "candidates": result["artifacts"]["candidates"],
                    "source_step": step.id,
                }
            nodes[step.id] = result
            serialized = save_artifacts(result["artifacts"], directory)
            write_json(directory / "artifacts.json", serialized)
            # Diagnostics have been persisted; don't keep large removed-signal
            # arrays alive for the remainder of the recording.
            result["artifacts"] = {}
            # Actual runtime bindings stay in provenance, including source defaults.
            effective = save_artifacts(actual, directory, "parameters")
            logs.append(
                {
                    "step_id": step.id,
                    "branch": "main",
                    "unit_id": step.unit_id,
                    "op": step.op,
                    "profile": step.profile,
                    "implementation_version": step.implementation_version,
                    "parameters": effective,
                    "input_hash": before_hash,
                    "output_hash": data_hash(y),
                    "state": state(y),
                    "model_binding": model_bindings.get(step.model_from),
                }
            )
            write_json(
                output / "provenance.json",
                {
                    "steps": logs,
                    "environment": plan.environment,
                    "engine_sha256": plan.engine_sha256,
                    "method_ref": config.method_ref.model_dump(),
                    "input_ref": plan.request.input_ref.model_dump(),
                    "mode": plan.request.mode,
                },
            )
        check_cancel()
        final = nodes[config.output]["data"]
        epoched = isinstance(final, mne.BaseEpochs)
        path = output / ("data-epo.fif" if epoched else "data-raw.fif")
        final.save(path, fmt="double", overwrite=False, verbose="ERROR")
        reread = (
            mne.read_epochs(path, preload=True, verbose="ERROR")
            if epoched
            else mne.io.read_raw_fif(path, preload=True, verbose="ERROR")
        )
        roundtrip_error = float(np.max(np.abs(reread.get_data() - final.get_data())))
        # FIFF stores channel calibration as float32 even with double signal data.
        # Also retain exact physical values for consumers needing bitwise identity.
        save_artifacts(final.get_data(), output, "signal_V")
        if (
            reread.ch_names != final.ch_names
            or not np.allclose(
                reread.get_data(),
                final.get_data(),
                rtol=2 * np.finfo(np.float32).eps,
                atol=1e-18,
            )
            or (epoched and not np.array_equal(reread.events, final.events))
        ):
            raise ValueError(
                f"saved signal/event reread failed (max absolute error {roundtrip_error} V)"
            )
        selected = set(final.selection.tolist()) if epoched else set(range(len(events)))
        for i, row in enumerate(event_map):
            row.update(
                retained=i in selected,
                epoch_index=int(np.where(final.selection == i)[0][0])
                if epoched and i in selected
                else None,
                output_sample=int(events[i, 0]),
                reason=list(final.drop_log[i]) if epoched else [],
            )
        trials = {}
        for row in event_map:
            trials.setdefault(row["trial_id"], []).append(row["retained"])
        delta = {
            "before": input_state,
            "after": state(final),
            "events_before": len(events),
            "events_retained": len(selected),
            "trials_before": len(trials),
            "trials_fully_retained": sum(all(v) for v in trials.values()),
            "trials_partly_retained": sum(
                any(v) and not all(v) for v in trials.values()
            ),
            "duration_before_s": record.samples / record.sfreq,
            "duration_after_s": len(final.times)
            / record.sfreq
            * (len(final) if epoched else 1),
            "duration_basis": "sum of epoch sample durations (may overlap)"
            if epoched
            else "continuous sample duration",
            "channels_removed": sorted(set(raw.ch_names) - set(final.ch_names)),
            "scope": "all events in Collection recording",
        }
        write_json(output / "events.json", event_map)
        write_json(output / "delta.json", delta)
        for relative, expected in record.files.items():
            if file_hash(within(source_root, relative)) != expected:
                raise ValueError("source changed during processing")
        artifacts = []
        for artifact in sorted(output.rglob("*")):
            if artifact.is_file() and not artifact.is_relative_to(work):
                artifacts.append(
                    {
                        "name": artifact.relative_to(output).as_posix(),
                        "path": artifact.relative_to(storage_root).as_posix(),
                        "sha256": file_hash(artifact),
                        "kind": "data" if artifact == path else "provenance",
                        "bytes": artifact.stat().st_size,
                    }
                )
        result = {
            "artifacts": artifacts,
            "delta": delta,
            "source_unchanged": True,
            "mode": plan.request.mode,
            "roundtrip_max_error_V": roundtrip_error,
        }
        if not verify_result(storage_root, result):
            raise ValueError("required artifacts failed verification")
        return result
    except BaseException:
        write_json(
            output / "failure.json",
            {"completed_steps": logs, "error": traceback.format_exc()},
        )
        raise
