from copy import deepcopy
import mne
import numpy as np
import pytest
from app.preprocessing.units.source.eeg_relax_native import event_markers, mapped_events


def test_event_identity_survives_first_sample_and_native_excision():
    raw = mne.io.RawArray(
        np.zeros((1, 1000)),
        mne.create_info(["Cz"], 200, "eeg"),
        first_samp=200,
        verbose="ERROR",
    )
    raw.set_annotations(
        mne.Annotations([1.0, 2.0, 3.0], [0.2, 0.2, 0.2], ["a", "b", "a"])
    )
    events = np.array([[400, 0, 1], [600, 0, 2], [800, 0, 1]])
    markers = event_markers(raw, events)
    native = [
        dict(type="boundary", latency=0.5, duration=100, ba_index=[]),
        dict(type="b", latency=301.0, duration=40, ba_index=2),
        dict(type="a", latency=501.0, duration=40, ba_index=3),
    ]
    mapped, kept = mapped_events(native, events, markers, ["a", "b", "a"], 900)
    assert kept.tolist() == [1, 2] and mapped.tolist() == [[300, 0, 2], [500, 0, 1]]
    for field, value in [("ba_index", 1), ("latency", 301.5), ("type", "invented")]:
        altered = deepcopy(native)
        altered[1][field] = value
        with pytest.raises(ValueError):
            mapped_events(altered, events, markers, ["a", "b", "a"], 900)
    with pytest.raises(ValueError):
        mapped_events(native + [native[1]], events, markers, ["a", "b", "a"], 900)


def test_ambiguous_or_missing_input_annotation_cannot_get_an_event_marker():
    raw = mne.io.RawArray(
        np.zeros((1, 1000)), mne.create_info(["Cz"], 200, "eeg"), verbose="ERROR"
    )
    raw.set_annotations(mne.Annotations([1.0, 1.0], [0.2, 0.2], ["a", "b"]))
    with pytest.raises(ValueError, match="exactly one"):
        event_markers(raw, np.array([[200, 0, 1]]))
    with pytest.raises(ValueError, match="exactly one"):
        event_markers(raw, np.array([[400, 0, 1]]))
