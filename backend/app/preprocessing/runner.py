from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import shutil
import traceback

import mne
import numpy as np

from .inputs import read_record, working_files
from .storage import canonical, digest, file_hash, within, write_json
from .units import invoke


class Cancelled(Exception):
    pass


def _state_metadata(x):
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
    }


def state(x):
    from threadpoolctl import threadpool_limits

    eeg = x.get_data(picks="eeg")
    rank_data = eeg if eeg.ndim == 2 else eeg.transpose(1, 0, 2).reshape(eeg.shape[1], -1)
    # True data rank remains in artifact state. Hashing has no reason to recompute it.
    with threadpool_limits(limits=1, user_api="blas"):
        rank = int(np.linalg.matrix_rank(rank_data)) if rank_data.size else 0
    return {**_state_metadata(x), "rank": rank}


def data_hash(x):
    import hashlib

    h = hashlib.sha256(canonical(_state_metadata(x)).encode())
    def array(value):
        a = np.ascontiguousarray(value)
        h.update(canonical([list(a.shape), str(a.dtype)]).encode())
        h.update(a.tobytes())
    array(x.get_data())
    # Decisions also depend on montage, annotations and projection state.
    for ch in x.info["chs"]:
        array(ch["loc"])
        h.update(canonical([int(ch["coord_frame"]), int(ch["unit"])]).encode())
    for proj in x.info["projs"]:
        h.update(canonical([proj["desc"], bool(proj["active"]), proj["data"]["col_names"]]).encode())
        array(proj["data"]["data"])
    if isinstance(x, mne.io.BaseRaw):
        array(x.annotations.onset)
        array(x.annotations.duration)
        h.update(canonical([x.annotations.description.tolist(), str(x.annotations.orig_time),
                            [list(v) for v in x.annotations.ch_names]]).encode())
    else:
        array(x.events)
        h.update(canonical([x.event_id, x.baseline, x.drop_log]).encode())
    return h.hexdigest()


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
        entries = result["artifacts"]
        if len({a["path"] for a in entries}) != len(entries):
            return False
        for artifact in result["artifacts"]:
            if file_hash(within(root, artifact["path"])) != artifact["sha256"]:
                return False
        data_files = [a for a in entries if a["kind"] == "data"]
        if len(data_files) != 1:
            return False
        data = data_files[0]
        path = within(root, data["path"])
        required = {"events.json", "delta.json", "provenance.json", "signal_V.npy"}
        siblings = {
            within(root, a["path"]).name
            for a in entries
            if within(root, a["path"]).parent == path.parent
        }
        if not required <= siblings:
            return False
        x = (
            mne.read_epochs(path, preload=True, verbose="ERROR")
            if path.name.endswith("-epo.fif")
            else mne.io.read_raw_fif(path, preload=True, verbose="ERROR")
        )
        signal = np.load(path.parent / "signal_V.npy", allow_pickle=False)
        delta = json.loads((path.parent / "delta.json").read_text(encoding="utf-8"))
        events = json.loads((path.parent / "events.json").read_text(encoding="utf-8"))
        if (
            not x.get_data().size
            or not np.isfinite(signal).all()
            or signal.shape != x.get_data().shape
            or not np.allclose(
                signal, x.get_data(), rtol=2 * np.finfo(np.float32).eps, atol=1e-18
            )
            or delta != result["delta"]
            or delta["after"]["shape"] != list(signal.shape)
            or delta["after"]["channels"] != x.ch_names
            or delta["after"]["sfreq"] != x.info["sfreq"]
            or delta["events_before"] != len(events)
            or len({e["event_id"] for e in events}) != len(events)
        ):
            return False
        retained = [e for e in events if e["retained"]]
        if len(retained) != delta["events_retained"]:
            return False
        if isinstance(x, mne.BaseEpochs):
            continuous = [a for a in entries if a["kind"] == "continuous_data"]
            if len(continuous) != 1 or continuous[0]["name"] != "continuous-raw.fif":
                return False
            provenance = json.loads((path.parent / "provenance.json").read_text(encoding="utf-8"))
            snapshot = provenance.get("continuous_raw")
            if (not snapshot or snapshot["path"] != continuous[0]["path"]
                    or snapshot["sha256"] != continuous[0]["sha256"]
                    or snapshot["bytes"] != within(root, continuous[0]["path"]).stat().st_size):
                return False
            retained.sort(key=lambda e: e["epoch_index"])
            if [e["epoch_index"] for e in retained] != list(range(len(x))):
                return False
            if not np.array_equal(
                [[e["output_sample"], 0, e["code"]] for e in retained], x.events
            ):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, IndexError):
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
    logs = []
    try:
        work = output / "input"
        # A materialized copy protects originals from readers and library in-place operations.
        for relative, expected in working_files(record).items():
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
        nodes = {
            "raw": {
                "data": raw,
                "model": None,
                "artifacts": {},
                "events": events,
                "event_origin": raw.first_samp,
            }
        }
        decisions, model_bindings = {}, {}
        steps = {s.id: s for s in config.steps}
        data_chain = []
        cursor = config.output
        while cursor != "raw":
            data_chain.append(cursor)
            cursor = steps[cursor].input
        data_chain.reverse()
        epoch_id = next((name for name in data_chain if steps[name].op == "epoch"), None)
        continuous_raw = None

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

        for step in config.steps:
            check_cancel()
            directory = output / step.id
            directory.mkdir()
            x = nodes[step.input]["data"]
            current_events = nodes[step.input]["events"]
            event_origin = nodes[step.input]["event_origin"]
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
            elif step.op in {"epoch", "resample"}:
                actual["events"] = current_events.copy()
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
            if step.id == epoch_id:
                snapshot_path = output / "continuous-raw.fif"
                x.save(snapshot_path, fmt="double", overwrite=False, verbose="ERROR")
                snapshot = mne.io.read_raw_fif(snapshot_path, preload=True, verbose="ERROR")
                if (snapshot.ch_names != x.ch_names or snapshot.first_samp != x.first_samp
                        or snapshot.info["sfreq"] != x.info["sfreq"]
                        or snapshot.get_data().shape != x.get_data().shape
                        or not np.allclose(snapshot.get_data(), x.get_data(),
                                           rtol=2 * np.finfo(np.float32).eps, atol=1e-18)):
                    raise ValueError("continuous snapshot roundtrip failed")
                position = data_chain.index(epoch_id)
                continuous_raw = {
                    "file": "continuous-raw.fif",
                    "path": snapshot_path.relative_to(storage_root).as_posix(),
                    "sha256": file_hash(snapshot_path), "bytes": snapshot_path.stat().st_size,
                    "before_epoch_step_id": epoch_id, "source_node_id": step.input,
                    "pipeline_index": next(i for i, s in enumerate(config.steps) if s.id == epoch_id),
                    "main_chain_step_ids": data_chain[:position],
                    "pre_epoch_step_ids": data_chain[:position],
                    "post_epoch_step_ids": data_chain[position + 1:],
                    "post_epoch_steps": [steps[n].model_dump(mode="json") for n in data_chain[position + 1:]],
                    "unit": "V", "format": "FIFF double",
                    "sfreq": float(x.info["sfreq"]), "channels": list(x.ch_names),
                    "channel_types": x.get_channel_types(), "first_sample": int(x.first_samp),
                    "highpass": float(x.info["highpass"]), "lowpass": float(x.info["lowpass"]),
                    "bads": list(x.info["bads"]), "custom_ref_applied": int(x.info["custom_ref_applied"]),
                    "shape": list(x.get_data().shape), "source_data_hash": before_hash,
                    "target_events": current_events.tolist(), "event_origin": int(event_origin),
                    "roundtrip_max_error_V": float(np.max(np.abs(snapshot.get_data() - x.get_data()))),
                    "applied_through": step.input,
                    "post_epoch_operations_applied": False,
                }
                del snapshot
            result = invoke(step.unit_id, step.op, x, model=model, **actual)
            y = result["data"]
            if data_hash(x) != before_hash:
                raise ValueError("unit mutated its input")
            if not y.get_data().size or not np.isfinite(y.get_data()).all():
                raise ValueError("empty or invalid output")
            if (
                step.op not in {"epoch", "resample"}
                and y.get_data().shape != x.get_data().shape
            ):
                raise ValueError("unexpected signal shape change")
            if step.op == "resample":
                synchronized = result["artifacts"]["events"]
                if len(synchronized) != len(current_events) or not np.array_equal(
                    synchronized[:, 1:], current_events[:, 1:]
                ):
                    raise ValueError("resampling changed event identity")
                current_events, event_origin = synchronized, y.first_samp
            result["events"], result["event_origin"] = current_events, event_origin
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
            if step.op in {"amplitude_windows", "detect_bad_channels"}:
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
                    "continuous_raw": continuous_raw,
                },
            )
        check_cancel()
        final = nodes[config.output]["data"]
        output_events = nodes[config.output]["events"]
        output_origin = nodes[config.output]["event_origin"]
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
                output_sample=int(output_events[i, 0]),
                output_sfreq=float(final.info["sfreq"]),
                output_onset_s=float(
                    (output_events[i, 0] - output_origin) / final.info["sfreq"]
                ),
                resampling_error_s=float(
                    (output_events[i, 0] - output_origin) / final.info["sfreq"]
                    - row["original_onset_s"]
                ),
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
            / final.info["sfreq"]
            * (len(final) if epoched else 1),
            "duration_basis": "sum of epoch sample durations (may overlap)"
            if epoched
            else "continuous sample duration",
            "channels_removed": sorted(set(raw.ch_names) - set(final.ch_names)),
            "scope": "Survey target events in the Collection recording; declared context events remain in the standardized input",
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
                        "kind": "data" if artifact == path else (
                            "continuous_data" if artifact.name == "continuous-raw.fif" else "provenance"),
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
    except BaseException as exc:
        write_json(
            output / "failure.json",
            {"completed_steps": logs, "error": traceback.format_exc(),
             "failure_code": getattr(exc, "code", type(exc).__name__),
             "failure_details": getattr(exc, "details", {})},
        )
        raise
