import csv
from pathlib import Path

import numpy as np
import pytest

from app.preprocessing.schemas import PreprocessInput
from app.preprocessing.storage import digest, file_hash
from app.search.panel import DataUnevaluable, freeze_panel


def make_input(root, counts=(4, 2, 18), sfreq=200.0):
    """TSV-only fixture: freezing must not require any signal file or reader."""
    root = Path(root)
    records = []
    for number, count in enumerate(counts, 1):
        rid = f"sub-{number:02}"
        base = f"{rid}/eeg/{rid}_task-mi_"
        relative = base + "events.tsv"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        n_samples = int((count + 2) * sfreq)
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=["onset", "duration", "trial_type", "sample", "value"],
                delimiter="\t",
            )
            writer.writeheader()
            # Include context so filtered target identities cannot be renumbered.
            for onset, label, code in [
                (0, "rest", 3),
                (1 / sfreq, "left_hand", 1),
                *[
                    (
                        i + 1,
                        "left_hand" if i % 2 == 0 else "right_hand",
                        1 if i % 2 == 0 else 2,
                    )
                    for i in range(count)
                ],
                ((n_samples - 1) / sfreq, "right_hand", 2),
            ]:
                writer.writerow(
                    dict(
                        onset=onset,
                        duration=0,
                        trial_type=label,
                        sample=round(onset * sfreq),
                        value=code,
                    )
                )
        records.append(
            dict(
                id=rid,
                bids_path=base + "eeg.vhdr",
                files={relative: file_hash(path)},
                sfreq=sfreq,
                samples=n_samples,
                channels={"C4": "eeg", "VEOG": "eog", "C3": "eeg"},
                channel_order=["C4", "VEOG", "C3"],
                reference="acquisition",
            )
        )
    evidence = dict(
        source_url="fixture:test",
        locator="generator",
        text="Synthetic MI",
        source_version="1",
    )
    return PreprocessInput.model_validate(
        dict(
            purpose="development_fixture",
            survey=dict(
                dataset_id="fixture",
                dataset_version="1",
                survey_run_id="test",
                task="left_right_motor_imagery",
                event_id={"left_hand": 1, "right_hand": 2},
                context_event_id={"rest": 3},
                processing_history=[],
                facts=[evidence],
            ),
            collection=dict(
                dataset_id="fixture",
                dataset_version="1",
                root=str(root),
                standard_version="1.9.0",
                validation_evidence=evidence,
                selection_reason="all MI",
                selected_record_ids=[r["id"] for r in records],
                records=records,
            ),
        )
    )


def freeze(data, **kwargs):
    return freeze_panel(
        data,
        {r.id: r.id for r in data.collection.records},
        seed=42,
        tmin=-0.1,
        tmax=0.1,
        sfreq=160,
        **kwargs,
    )


def test_freeze_only_selected_subjects_stable_hash_and_no_signal_reads(
    tmp_path, monkeypatch
):
    from app.preprocessing import inputs

    monkeypatch.setattr(
        inputs, "read_record", lambda *a, **k: pytest.fail("freezing read signal")
    )
    data = make_input(tmp_path, counts=(4,) * 7)
    data.collection.selected_record_ids = [r.id for r in data.collection.records[:5]]
    panel = freeze(data)
    assert panel["train_subjects"] == []
    assert len(panel["development_subjects"]) == 5
    assert len(panel["folds"]) == 5
    assert panel["evaluation_mode"] == "group_cross_validation"
    assert set(panel["records"]) == set(data.collection.selected_record_ids)
    assert panel["output_contract"]["channels"] == ["C4", "C3"]
    assert panel == freeze(data)
    assert panel["input_hash"] == digest(data.model_dump(mode="json"))
    assert panel["panel_hash"] == digest(
        {k: v for k, v in panel.items() if k != "panel_hash"}
    )
    assert panel["trials"][0]["event_id"] == "sub-01:event:1"
    assert panel["trials"][0]["reason"] == "NO_DATA"
    assert panel["trials"][5]["reason"] == "TOO_SHORT"
    # Extra subject mappings cannot enlarge the frozen selected set.
    other = freeze_panel(
        data,
        {**{r.id: r.id for r in data.collection.records}, "unused": "test"},
        seed=42,
        tmin=-0.1,
        tmax=0.1,
        sfreq=160,
    )
    assert other == panel


@pytest.mark.parametrize(
    "train,dev",
    [
        (["sub-01"], ["sub-01", "sub-02"]),
        (["sub-01"], ["sub-02"]),
        (["sub-01", "sub-01"], ["sub-02", "sub-03"]),
        (["sub-01"], None),
        ([], ["sub-01", "sub-02", "sub-03"]),
    ],
)
def test_explicit_split_must_cover_selected_subjects(tmp_path, train, dev):
    with pytest.raises(ValueError, match="subject"):
        freeze(make_input(tmp_path), train_subjects=train, development_subjects=dev)


def test_every_subject_requires_both_eligible_classes(tmp_path):
    # There are two ORIGINAL classes, but the only right trial cannot be epoched.
    with pytest.raises(DataUnevaluable, match="both eligible classes"):
        freeze(make_input(tmp_path, counts=(4, 1)))


def test_tsv_hash_is_checked_before_freezing(tmp_path):
    data = make_input(tmp_path)
    path = tmp_path / next(iter(data.collection.records[0].files))
    path.write_text(path.read_text().replace("left_hand", "right_hand"))
    with pytest.raises(DataUnevaluable, match="checksum"):
        freeze(data)


@pytest.mark.parametrize("n_subjects", [2, 3, 5, 7, 12])
def test_group_cv_covers_every_subject_exactly_once(tmp_path, n_subjects):
    panel = freeze(make_input(tmp_path, counts=(4,) * n_subjects))
    assert panel["evaluator_version"] == 2
    assert panel["train_subjects"] == []
    assert len(panel["folds"]) == min(5, n_subjects)
    held_out = [s for fold in panel["folds"] for s in fold["development_subjects"]]
    assert sorted(held_out) == panel["development_subjects"]
    for fold in panel["folds"]:
        assert not set(fold["train_subjects"]) & set(fold["development_subjects"])
        assert set(fold["train_subjects"] + fold["development_subjects"]) == set(
            held_out
        )
    assert all(t["role"] == "development" for t in panel["trials"])
    assert all(r["role"] == "development" for r in panel["records"].values())


@pytest.mark.parametrize("mutation", ["overlap", "duplicate", "missing", "v1", "role"])
def test_panel_rejects_invalid_fold_contract(tmp_path, mutation):
    from app.search.panel import validate_panel

    panel = freeze(make_input(tmp_path))
    if mutation == "overlap":
        panel["folds"][0]["train_subjects"].extend(
            panel["folds"][0]["development_subjects"]
        )
    elif mutation == "duplicate":
        panel["folds"][1] = panel["folds"][0].copy()
    elif mutation == "missing":
        panel["folds"].pop()
    elif mutation == "v1":
        panel["evaluator_version"] = 1
    else:
        panel["records"]["sub-01"]["role"] = "train"
    panel["panel_hash"] = digest({k: v for k, v in panel.items() if k != "panel_hash"})
    with pytest.raises(DataUnevaluable):
        validate_panel(panel)


def test_explicit_holdout_has_one_matching_fold(tmp_path):
    panel = freeze(
        make_input(tmp_path),
        train_subjects=["sub-01"],
        development_subjects=["sub-02", "sub-03"],
    )
    assert panel["evaluation_mode"] == "subject_holdout"
    assert panel["folds"] == [
        {
            "id": "fold-01",
            "train_subjects": ["sub-01"],
            "development_subjects": ["sub-02", "sub-03"],
        }
    ]


@pytest.mark.parametrize(
    "sfreq,n_samples", [(256, 259), (200, 202), (128, 129), (160, 163)]
)
def test_exact_resample_and_inclusive_epoch_samples_match_source_unit(
    tmp_path, sfreq, n_samples
):
    import mne
    from app.preprocessing.units import invoke

    data = make_input(tmp_path, counts=(2, 2), sfreq=sfreq)
    # Non-integral sample positions, endpoint clipping, and half-sample epochs.
    samples = [0, 1, sfreq // 4 + 1, sfreq // 2 + 3, n_samples - 1]
    for record in data.collection.records:
        record.samples = n_samples
        relative = next(iter(record.files))
        path = tmp_path / relative
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream, delimiter="\t")
            writer.writerow(["onset", "duration", "trial_type", "sample", "value"])
            for i, sample in enumerate(samples):
                label = (
                    "rest" if i == 0 else "left_hand" if i % 2 == 0 else "right_hand"
                )
                writer.writerow(
                    [
                        sample / sfreq,
                        0,
                        label,
                        sample,
                        3 if i == 0 else 1 if i % 2 == 0 else 2,
                    ]
                )
        record.files[relative] = file_hash(path)
    panel = freeze_panel(
        data,
        {r.id: r.id for r in data.collection.records},
        seed=1,
        tmin=-2.5 / 160,
        tmax=3.5 / 160,
        sfreq=160,
    )
    raw = mne.io.RawArray(
        np.zeros((2, n_samples)),
        mne.create_info(["C4", "C3"], sfreq, "eeg"),
        verbose="ERROR",
    )
    events = np.array(
        [
            [sample, 0, 1 if i % 2 == 0 else 2]
            for i, sample in enumerate(samples)
            if i > 0
        ]
    )
    resampled = invoke("EEG-RESAMPLE", "resample", raw, sfreq=160, events=events)
    epochs = invoke(
        "EEG-EPOCH",
        "epoch",
        resampled["data"],
        events=resampled["artifacts"]["events"],
        event_id=data.survey.event_id,
        tmin=-2.5 / 160,
        tmax=3.5 / 160,
        picks=["C4", "C3"],
    )["data"]
    trials = [t for t in panel["trials"] if t["record_id"] == "sub-01"]
    assert [t["output_sample"] for t in trials] == resampled["artifacts"]["events"][
        :, 0
    ].tolist()
    assert [
        i for i, t in enumerate(trials) if t["eligible"]
    ] == epochs.selection.tolist()
    assert (
        panel["records"]["sub-01"]["resampled_n_samples"] == resampled["data"].n_times
    )
    assert panel["output_contract"]["n_times"] == len(epochs.times) == 7
