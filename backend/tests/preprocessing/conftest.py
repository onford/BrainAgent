from pathlib import Path
import json

import pytest

mne = pytest.importorskip("mne", reason="install the eeg extra for preprocessing tests")
np = pytest.importorskip("numpy")
pytest.importorskip("mne_bids")
from mne_bids import BIDSPath, write_raw_bids

from app.preprocessing.schemas import (
    CollectionSnapshot,
    Evidence,
    Interval,
    PreprocessInput,
    RecordSpec,
    SurveySnapshot,
)
from app.preprocessing.service import PreprocessingService
from app.preprocessing.storage import file_hash

PARAMETERS = {
    "l_freq": 1.0,
    "h_freq": 35.0,
    "tmin": -0.2,
    "tmax": 0.5,
    "baseline": [-0.2, 0],
}
OWNER = "eeg-test-owner"


def make_dataset(root: Path, *, subjects=2, test_amplitude=1.0):
    sf, samples = 200.0, 8000
    t = np.arange(samples) / sf
    records = []
    for subject in range(1, subjects + 1):
        rng = np.random.default_rng(10 + subject)
        eog = 70e-6 * np.sin(2 * np.pi * 1.3 * t)
        eog[samples // 2 :] *= test_amplitude
        data = np.vstack(
            [
                12e-6 * np.sin(2 * np.pi * (10 + i) * t)
                + weight * eog
                + rng.normal(0, 1e-6, samples)
                for i, weight in enumerate([0.8, 0.2, -0.2, 0.4])
            ]
            + [eog]
        )
        names, types = ["C3", "C4", "Cz", "Pz", "VEOG"], ["eeg"] * 4 + ["eog"]
        raw = mne.io.RawArray(data, mne.create_info(names, sf, types), verbose="ERROR")
        raw.set_montage("standard_1020", on_missing="ignore")
        raw.set_annotations(
            mne.Annotations(
                [0.05, 3, 8, 13, 23, 28, 33, 38], [0] * 8, ["left", "right"] * 4
            )
        )
        bids = BIDSPath(
            root=root, subject=str(subject).zfill(2), task="motor", datatype="eeg"
        )
        write_raw_bids(
            raw,
            bids,
            format="BrainVision",
            allow_preload=True,
            event_id={"left": 1, "right": 2},
            overwrite=True,
            verbose="ERROR",
        )
        path = bids.copy().update(suffix="eeg", extension=".vhdr").fpath
        meta = json.loads(path.with_suffix(".json").read_text())
        meta["EEGReference"] = "acquisition"
        path.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")
        records.append(
            RecordSpec(
                id=f"sub-{subject:02}",
                bids_path=path.relative_to(root).as_posix(),
                files={"pending": "0" * 64},
                sfreq=sf,
                samples=samples,
                channels=dict(zip(names, types)),
                channel_order=names,
                reference="acquisition",
                intervals=[
                    Interval(id="calibration", role="calibration", start=0, stop=4000),
                    Interval(id="heldout", role="test", start=4000, stop=8000),
                ],
            )
        )
    inventory = {
        p.relative_to(root).as_posix(): file_hash(p)
        for p in root.rglob("*")
        if p.is_file()
    }
    for record in records:
        record.files = inventory.copy()
    description = json.loads((root / "dataset_description.json").read_text())
    evidence = Evidence(
        source_url="fixture://deterministic-eeg",
        locator="generator",
        text="Synthetic 4-channel scalp EEG and VEOG, known event codes, 200 Hz, calibrated first half.",
        source_version="1",
    )
    return PreprocessInput(
        purpose="development_fixture",
        survey=SurveySnapshot(
            dataset_id="synthetic",
            dataset_version="1",
            survey_run_id="fixture-survey",
            task="motor",
            event_id={"left": 1, "right": 2},
            processing_history=[],
            facts=[evidence],
        ),
        collection=CollectionSnapshot(
            dataset_id="synthetic",
            dataset_version="1",
            root=str(root),
            standard_version=description["BIDSVersion"],
            validation_evidence=evidence,
            selection_reason="all generated records",
            selected_record_ids=[r.id for r in records],
            records=records,
        ),
    )


@pytest.fixture
def dataset(tmp_path):
    return make_dataset(tmp_path / "bids")


@pytest.fixture
def service(tmp_path):
    return PreprocessingService(tmp_path / "output", [tmp_path / "bids"])
