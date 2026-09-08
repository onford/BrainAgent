import json
from pathlib import Path

import numpy as np
import pytest

from app.preprocessing.methods import baseline_methods
from app.preprocessing.planner import compile_steps, training_grid
from app.preprocessing.schemas import Step
from app.preprocessing.worker import Worker
from app.preprocessing.inputs import read_record
from app.preprocessing.units import invoke
from .conftest import PARAMETERS, make_dataset
from .test_execution import prepare


def method_with_resampling():
    method = baseline_methods()[0]
    resample = Step(
        id="resample",
        unit_id="EEG-RESAMPLE",
        op="resample",
        input="filter",
        params={"sfreq": 128},
        evidence_indices=[0],
    )
    unrelated = resample.model_copy(
        update={"id": "unused_grid", "params": {"sfreq": 80}}
    )
    method.recipe[1].input = "resample"
    method.recipe[1:1] = [unrelated, resample]
    return method


def test_mixed_rates_keep_event_identity_and_yield_one_training_grid(service, tmp_path):
    data = make_dataset(tmp_path / "bids", sfreqs=[160, 128])
    job, _, plan = prepare(service, data, [method_with_resampling()])
    assert (
        len(
            {training_grid(c, r) for c, r in zip(plan.records, data.collection.records)}
        )
        == 1
    )
    outcome = Worker(service.store, service.allowed_roots).run_once()
    assert outcome.status == "completed", outcome.model_dump()
    grids = set()
    records = {r.id: r for r in data.collection.records}
    for result in outcome.records:
        record = records[result["record_id"]]
        artifacts = {
            a["name"]: service.store.root / a["path"]
            for a in result["result"]["artifacts"]
        }
        mapping = json.loads(artifacts["events.json"].read_text())
        original, events, _ = read_record(
            Path(data.collection.root),
            record,
            data.survey.event_id,
        )
        expected = original.copy().filter(
            1,
            35,
            picks="eeg",
            method="iir",
            iir_params={"order": 4, "ftype": "butter"},
            phase="zero",
            verbose="ERROR",
        )
        expected, synced = expected.resample(
            128, events=events, method="polyphase", verbose="ERROR"
        )
        assert [r["original_sample"] for r in mapping] == events[:, 0].tolist()
        assert [r["output_sample"] for r in mapping] == synced[:, 0].tolist()
        assert all(
            abs(r["resampling_error_s"]) <= 1 / record.sfreq + 1 / 128 for r in mapping
        )
        assert len(mapping) == result["result"]["delta"]["events_before"]
        info = result["result"]["delta"]["after"]
        grids.add((info["sfreq"], tuple(info["shape"][1:])))
        assert info["sfreq"] == 128
        # Compare full numerical processing, including resampling before epoching.
        import mne

        expected.set_eeg_reference("average", projection=False, verbose="ERROR")
        epochs = mne.Epochs(
            expected,
            synced,
            event_id=data.survey.event_id,
            tmin=-0.2,
            tmax=0.5,
            baseline=(-0.2, 0),
            picks=record.channel_order,
            preload=True,
            proj=False,
            verbose="ERROR",
        )
        np.testing.assert_allclose(
            np.load(artifacts["signal_V.npy"]),
            epochs.get_data(),
            rtol=1e-10,
            atol=1e-18,
        )
    assert len(grids) == 1


def test_filter_nyquist_uses_its_input_sampling_rate(dataset):
    method = method_with_resampling()
    method.recipe[2].params["sfreq"] = 64
    method.recipe.insert(
        3,
        Step(
            id="invalid_filter",
            unit_id="EEG-FILTER",
            op="filter",
            input="resample",
            params={
                "l_freq": 1,
                "h_freq": 35,
                "method": "iir",
                "phase": "zero",
                "picks": "$eeg_channels",
            },
            evidence_indices=[0],
        ),
    )
    with pytest.raises(ValueError, match="sampling rate"):
        compile_steps(method, dataset.collection.records[0], dataset, PARAMETERS)


def test_resampling_rejects_event_collisions_without_mutating_source(dataset):
    from pathlib import Path

    raw, _, _ = read_record(
        Path(dataset.collection.root),
        dataset.collection.records[0],
        dataset.survey.event_id,
    )
    before = raw.get_data().copy()
    with pytest.raises(ValueError, match="碰撞"):
        invoke(
            "EEG-RESAMPLE",
            "resample",
            raw,
            sfreq=1,
            events=np.array([[1, 0, 1], [2, 0, 2]]),
        )
    np.testing.assert_array_equal(raw.get_data(), before)
