"""Freeze subject folds and original MI denominators without opening signals."""

from __future__ import annotations

from collections import Counter
import csv
import math
from pathlib import Path
import random

from pydantic import ValidationError

from app.preprocessing.schemas import PreprocessInput
from app.preprocessing.storage import digest, file_hash, within
from .evaluation_contracts import FrozenPanel

EVALUATOR_VERSION = 2


class DataUnevaluable(ValueError):
    """The common input cannot support this frozen development comparison."""

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code or message


def freeze_panel(
    data: PreprocessInput,
    record_subjects: dict[str, str],
    *,
    seed: int,
    tmin: float,
    tmax: float,
    sfreq: float,
    train_subjects: list[str] | None = None,
    development_subjects: list[str] | None = None,
) -> dict:
    """Use TSV row identities, MNE 1.10 resampling, and inclusive epoch endpoints.

    ``records`` is keyed by record ID. ``source_sample`` is zero-origin (the
    supported, uncropped BrainVision reader has first_samp=0). ``epoch_stop``
    is exclusive. Hashes use preprocessing.storage.digest; panel_hash excludes
    only itself. Default subject CV covers every subject once out of fold.
    Explicit split arguments must be supplied together and select holdout mode.
    """
    if (
        any(isinstance(v, bool) or not math.isfinite(v) for v in (tmin, tmax, sfreq))
        or sfreq != 160
        or tmin >= tmax
        or type(seed) is not int
    ):
        raise ValueError("finite tmin < tmax, sfreq=160 and integer seed required")
    labels = set(data.survey.event_id)
    if labels == {"left_hand", "right_hand"}:
        class_labels = {"left": "left_hand", "right": "right_hand"}
    elif labels == {"left", "right"}:
        class_labels = {"left": "left", "right": "right"}
    else:
        raise DataUnevaluable(
            "common data unevaluable: exactly left/right MI labels required"
        )
    selected = set(data.collection.selected_record_ids)
    records = sorted(
        (r for r in data.collection.records if r.id in selected), key=lambda r: r.id
    )
    if any(
        not isinstance(record_subjects.get(r.id), str)
        or not record_subjects[r.id].strip()
        for r in records
    ):
        raise ValueError("every selected recording requires a nonempty subject")
    subjects = sorted({record_subjects[r.id] for r in records})
    if len(subjects) < 2:
        raise DataUnevaluable(
            "common data unevaluable: at least two selected subjects required"
        )
    if (train_subjects is None) != (development_subjects is None):
        raise ValueError("supply both train_subjects and development_subjects")
    if train_subjects is None:
        shuffled = subjects.copy()
        random.Random(seed).shuffle(shuffled)
        folds = []
        for i in range(min(5, len(subjects))):
            held_out = sorted(shuffled[i :: min(5, len(subjects))])
            folds.append(
                {
                    "id": f"fold-{i + 1:02d}",
                    "train_subjects": sorted(set(subjects) - set(held_out)),
                    "development_subjects": held_out,
                }
            )
        train_subjects, development_subjects = [], subjects
        evaluation_mode = "group_cross_validation"
    elif (
        not train_subjects
        or not development_subjects
        or len(train_subjects) != len(set(train_subjects))
        or len(development_subjects) != len(set(development_subjects))
        or set(train_subjects) & set(development_subjects)
        or set(train_subjects) | set(development_subjects) != set(subjects)
    ):
        raise ValueError(
            "subject groups must be nonempty, unique, disjoint and cover selected subjects"
        )
    else:
        evaluation_mode = "subject_holdout"
        folds = [
            {
                "id": "fold-01",
                "train_subjects": sorted(train_subjects),
                "development_subjects": sorted(development_subjects),
            }
        ]
    train_subjects, development_subjects = (
        sorted(train_subjects),
        sorted(development_subjects),
    )
    channels = [n for n in records[0].channel_order if records[0].channels[n] == "eeg"]
    if not channels:
        raise DataUnevaluable("common data unevaluable: no EEG channels")
    start, end = round(tmin * sfreq), round(tmax * sfreq)
    if end - start < 1:
        raise DataUnevaluable(
            "common data unevaluable: epoch needs at least two samples"
        )
    panel = {
        "evaluator_version": EVALUATOR_VERSION,
        "evaluation_mode": evaluation_mode,
        "folds": folds,
        "seed": seed,
        "input_hash": digest(data.model_dump(mode="json")),
        "train_subjects": train_subjects,
        "development_subjects": development_subjects,
        "class_labels": class_labels,
        "event_codes": dict(data.survey.event_id),
        "records": {},
        "trials": [],
        "output_contract": {
            "channels": channels,
            "sfreq": float(sfreq),
            "tmin": float(tmin),
            "tmax": float(tmax),
            "epoch_start_offset": start,
            "epoch_end_offset": end,
            "n_times": end - start + 1,
        },
    }
    known = {**data.survey.context_event_id, **data.survey.event_id}
    for record in records:
        if [n for n in record.channel_order if record.channels[n] == "eeg"] != channels:
            raise DataUnevaluable(
                "common data unevaluable: EEG channel order differs across records"
            )
        # MNE treats rates within rtol=1e-6 as a no-op, retaining the OLD rate.
        if record.sfreq != sfreq and abs(sfreq - record.sfreq) <= 1e-6 * record.sfreq:
            raise DataUnevaluable(
                "common data unevaluable: resample no-op would retain a different rate"
            )
        subject = record_subjects[record.id]
        role = "train" if subject in train_subjects else "development"
        ratio = float(sfreq) / record.sfreq
        n_out = max(int(round(ratio * record.samples)), 1)
        panel["records"][record.id] = {
            "record_id": record.id,
            "subject": subject,
            "role": role,
            "n_samples": record.samples,
            "sfreq": record.sfreq,
            "resampled_n_samples": n_out,
        }
        relative = record.bids_path.replace("eeg.vhdr", "events.tsv")
        path = within(Path(data.collection.root), relative)
        if relative not in record.files or file_hash(path) != record.files[relative]:
            raise DataUnevaluable(
                "common data unevaluable: events TSV checksum differs from frozen input"
            )
        previous = -1
        record_trials = []
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for index, row in enumerate(csv.DictReader(stream, delimiter="\t")):
                label = row.get("trial_type")
                if label not in known:
                    raise DataUnevaluable(
                        "common data unevaluable: unknown TSV event meaning"
                    )
                try:
                    onset, duration = float(row["onset"]), float(row["duration"])
                    sample = int(round(onset * record.sfreq))
                    valid = (
                        math.isfinite(onset)
                        and math.isfinite(duration)
                        and onset >= 0
                        and duration >= 0
                        and onset + duration
                        <= record.samples / record.sfreq + 1 / record.sfreq
                        and previous < sample < record.samples
                        and (
                            row.get("sample", "n/a") == "n/a"
                            or float(row["sample"]) == sample
                        )
                        and (
                            row.get("value", "n/a") == "n/a"
                            or float(row["value"]) == known[label]
                        )
                    )
                except (ValueError, OverflowError, KeyError) as exc:
                    raise DataUnevaluable(
                        "common data unevaluable: malformed TSV timing"
                    ) from exc
                if not valid:
                    raise DataUnevaluable(
                        "common data unevaluable: TSV timing/code differs from read_record contract"
                    )
                previous = sample
                if label not in labels:
                    continue
                output_sample = min(int(round(sample * ratio)), n_out - 1)
                epoch_start, epoch_stop = output_sample + start, output_sample + end + 1
                reason = (
                    "NO_DATA"
                    if epoch_start < 0
                    else "TOO_SHORT"
                    if epoch_stop > n_out
                    else None
                )
                record_trials.append(
                    {
                        "event_id": f"{record.id}:event:{index}",
                        "record_id": record.id,
                        "subject": subject,
                        "role": role,
                        "label": label,
                        "source_sample": sample,
                        "source_row": index + 2,
                        "output_sample": output_sample,
                        "epoch_start": epoch_start,
                        "epoch_stop": epoch_stop,
                        "eligible": reason is None,
                        "reason": reason,
                    }
                )
        # The source resample operation rejects collisions rather than dropping
        # one event. Keep both original identities and the common reason.
        collisions = Counter(t["output_sample"] for t in record_trials)
        for trial in record_trials:
            if collisions[trial["output_sample"]] > 1:
                trial.update(eligible=False, reason="RESAMPLE_EVENT_COLLISION")
        panel["trials"].extend(record_trials)
    validate_panel(panel, check_hash=False)
    panel["panel_hash"] = digest(panel)
    FrozenPanel.model_validate(panel)
    return panel


def validate_panel(panel: dict, *, check_hash: bool = True) -> None:
    """Fail closed before any feature extraction or model fitting."""
    try:
        FrozenPanel.model_validate(
            panel if check_hash else {**panel, "panel_hash": "0" * 64}
        )
    except ValidationError as exc:
        # Keep raw trial values out of aggregate error receipts.
        details = "; ".join(
            f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
            for e in exc.errors(include_input=False)
        )
        raise DataUnevaluable(
            f"invalid frozen panel: {details}", code="panel_schema_invalid"
        ) from exc
    if panel["evaluator_version"] != EVALUATOR_VERSION:
        raise DataUnevaluable("unsupported evaluator version")
    if check_hash and panel["panel_hash"] != digest(
        {k: v for k, v in panel.items() if k != "panel_hash"}
    ):
        raise DataUnevaluable("frozen panel checksum mismatch")
    train, dev = panel["train_subjects"], panel["development_subjects"]
    if not dev or set(train) & set(dev) or len(train + dev) != len(set(train + dev)):
        raise DataUnevaluable("common data unevaluable: invalid subject split")
    if set(train + dev) != {r["subject"] for r in panel["records"].values()}:
        raise DataUnevaluable("common data unevaluable: subject coverage differs")
    ids = set()
    labels = set(panel["event_codes"])
    for trial in panel["trials"]:
        record = panel["records"][trial["record_id"]]
        if (
            trial["event_id"] in ids
            or trial["subject"] != record["subject"]
            or trial["role"] != record["role"]
            or trial["label"] not in labels
            or trial["role"]
            != ("train" if trial["subject"] in train else "development")
        ):
            raise DataUnevaluable(
                "common data unevaluable: inconsistent trial identity or role"
            )
        ids.add(trial["event_id"])
    for subject in train + dev:
        eligible_labels = {
            t["label"]
            for t in panel["trials"]
            if t["subject"] == subject and t["eligible"]
        }
        if eligible_labels != labels:
            raise DataUnevaluable(
                f"common data unevaluable: subject {subject} needs both eligible classes"
            )
