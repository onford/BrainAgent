import copy
import json

import numpy as np
import pytest

from app.search.reconstruction import (
    ARRAY_NAMES,
    KINDS,
    align_fair_targets,
    evaluate_negative_controls,
    evaluate_reconstruction,
    generate_contamination,
)


@pytest.fixture
def probe():
    sfreq = 256.0
    t = np.arange(512) / sfreq
    x = 20e-6 * np.array(
        [
            [np.sin(2 * np.pi * 10 * t), np.cos(2 * np.pi * 12 * t)],
            [np.cos(2 * np.pi * 9 * t), np.sin(2 * np.pi * 13 * t)],
        ]
    )
    y, a, plan = generate_contamination(
        x,
        sfreq,
        kind="line",
        seed=731,
        rms_ratio=0.5,
        window_keys=['["s1","w1"]', '["s2","w1"]'],
    )
    space = {
        "sfreq": sfreq,
        "band_hz": None,
        "reference": "acquisition",
        "unit": "V",
        "channels": ["C3", "C4"],
    }
    meta = {
        "reference_kind": "real_eeg_cleanproxy",
        "reference_provenance": "fixture representing prespecified source EEG windows",
        "processor": {
            "id": "known_injection_oracle",
            "implemented": True,
            "paired_execution": True,
        },
        "windows": [{"subject_id": s, "window_id": "w1"} for s in ("s1", "s2")],
        "expected_windows": {"s1": ["w1"], "s2": ["w1"]},
        "spaces": {name: copy.deepcopy(space) for name in ARRAY_NAMES},
        "injection": plan,
    }
    return x, y, a, sfreq, meta


def evaluate(probe, **changes):
    x, y, a, sfreq, meta = probe
    args = dict(
        reference=x,
        contaminated=y,
        cleaned=x.copy(),
        sfreq=sfreq,
        contamination=a,
        metadata=meta,
        processed_reference=x.copy(),
    )
    args.update(changes)
    result = evaluate_reconstruction(**args)
    json.dumps(result, allow_nan=False)
    return result


def value(result, metric):
    return result["summary"][metric]["value"]


def test_oracle_recovers_known_injection_without_claiming_neural_truth(probe):
    result = evaluate(probe)
    assert result["status"] == "evaluated"
    assert result["reference_kind"] == "real_eeg_cleanproxy"
    assert result["n_subjects"] == result["n_windows"] == 2
    assert value(result, "input_nrmse") == pytest.approx(0.5)
    assert value(result, "reconstruction_nrmse") == 0
    assert value(result, "paired_nrmse") == 0
    assert value(result, "artifact_residual_coefficient") == 0
    assert value(result, "clean_retention_nrmse") == 0
    assert value(result, "clean_retention_rms_ratio") == 1
    assert value(result, "reconstruction_correlation") == pytest.approx(1)
    assert result["windows"][0]["metrics"]["paired_ser_improvement_db"] == {
        "value": None,
        "status": "zero_error",
    }
    assert "score" not in result and "overall_score" not in result


def test_negative_controls_expose_identity_zero_and_scaling_cheats(probe):
    x, y, a, sfreq, meta = probe
    controls = evaluate_negative_controls(x, y, sfreq, a, meta, scale=0.1)
    json.dumps(controls, allow_nan=False)
    identity, zero, scaling = (controls[k] for k in ("identity", "zero", "scaling"))
    assert value(identity, "artifact_residual_coefficient") == pytest.approx(1)
    assert value(identity, "paired_ser_improvement_db") == pytest.approx(0, abs=1e-12)
    assert "identity_output" in identity["windows"][0]["flags"]
    assert value(zero, "paired_error_cleanproxy_ratio") == 0
    assert value(zero, "paired_nrmse") is None
    assert value(zero, "reconstruction_nrmse") == 1
    assert value(zero, "clean_retention_nrmse") == 1
    assert value(zero, "clean_retention_rms_ratio") == 0
    assert "zero_output" in zero["windows"][0]["flags"]
    assert value(scaling, "clean_retention_correlation") == pytest.approx(1)
    assert value(scaling, "clean_retention_nrmse") == pytest.approx(0.9)
    assert value(scaling, "clean_retention_gain") == pytest.approx(0.1)
    assert value(scaling, "paired_nrmse") == pytest.approx(0.5)
    assert value(scaling, "paired_ser_improvement_db") == pytest.approx(20)
    assert "pure_scaling_output" in scaling["windows"][0]["flags"]


def test_partial_artifact_removal_has_analytical_residual_and_db(probe):
    x, y, a, _, _ = probe
    result = evaluate(probe, cleaned=y - 0.75 * a)
    assert value(result, "paired_nrmse") == pytest.approx(0.125)
    assert value(result, "artifact_residual_coefficient") == pytest.approx(0.25)
    assert value(result, "artifact_residual_rms_ratio") == pytest.approx(0.25)
    assert value(result, "paired_ser_improvement_db") == pytest.approx(20 * np.log10(4))
    assert value(result, "clean_retention_rms_ratio") == 1


def test_nonlinear_clipping_requires_separate_processed_reference(probe):
    x, y, a, _, _ = probe
    q, z = np.clip(x, -5e-6, 5e-6), np.clip(y, -5e-6, 5e-6)
    result = evaluate(probe, cleaned=z, processed_reference=q)
    row = result["windows"][0]["metrics"]
    assert row["paired_nrmse"]["value"] == pytest.approx(
        np.linalg.norm(z[0] - q[0]) / np.linalg.norm(q[0])
    )
    assert row["clean_retention_nrmse"]["value"] > 0.6
    assert value(result, "reconstruction_nrmse") != value(result, "paired_nrmse")


@pytest.mark.parametrize("kind", KINDS)
def test_contamination_is_reproducible_keyed_and_exact_strength(probe, kind):
    x, _, _, sfreq, _ = probe
    original = x.copy()
    x.flags.writeable = False
    args = dict(kind=kind, seed=902, rms_ratio=1.25, window_keys=["s1/w1", "s2/w1"])
    state = np.random.get_state()
    y, a, plan = generate_contamination(x, sfreq, **args)
    y2, a2, plan2 = generate_contamination(x, sfreq, **args)
    assert np.array_equal(a, a2) and np.array_equal(y, y2) and plan == plan2
    np.testing.assert_array_equal(x, original)
    np.testing.assert_allclose(y, x + a)
    np.testing.assert_allclose(
        np.linalg.norm(a, axis=(1, 2)) / np.linalg.norm(x, axis=(1, 2)), 1.25
    )
    _, reordered, _ = generate_contamination(
        x[::-1], sfreq, **{**args, "window_keys": args["window_keys"][::-1]}
    )
    np.testing.assert_array_equal(a[::-1], reordered)
    _, other_seed, _ = generate_contamination(x, sfreq, **{**args, "seed": 903})
    assert not np.array_equal(a, other_seed)
    after = np.random.get_state()
    assert state[0] == after[0] and state[2:] == after[2:]
    np.testing.assert_array_equal(state[1], after[1])
    json.dumps(plan, allow_nan=False)


def test_recorded_artifact_template_keeps_spatial_temporal_pattern(probe):
    x, _, a, sfreq, _ = probe
    _, output, plan = generate_contamination(
        x,
        sfreq,
        kind="eog",
        seed=3,
        rms_ratio=1,
        window_keys=["a", "b"],
        template=a,
    )
    np.testing.assert_allclose(output, 2 * a, rtol=1e-12)
    assert plan["model"] == "recorded_template" and len(plan["template_sha256"]) == 64


def test_common_alignment_preserves_additivity_and_does_not_fit_gain(probe):
    x, y, a, sfreq, _ = probe
    inputs = {"x": x, "y": y, "a": a, "scaled_x": 0.1 * x}
    original = {k: v.copy() for k, v in inputs.items()}
    aligned, space = align_fair_targets(
        inputs,
        sfreq,
        channels=["C3", "C4"],
        input_unit="V",
        output_unit="uV",
        source_reference="acquisition",
        reference="average",
        band_hz=(4, 40),
        trim_samples=32,
    )
    np.testing.assert_allclose(aligned["x"] + aligned["a"], aligned["y"], atol=1e-11)
    np.testing.assert_allclose(aligned["scaled_x"], 0.1 * aligned["x"], atol=1e-12)
    np.testing.assert_allclose(aligned["x"].mean(axis=1), 0, atol=1e-12)
    assert aligned["x"].shape == (2, 2, 448)
    assert space["unit"] == "uV" and space["band_hz"] == [4, 40]
    for key in inputs:
        np.testing.assert_array_equal(inputs[key], original[key])


def test_aligned_space_integrates_with_evaluator(probe):
    x, y, a, sfreq, meta = probe
    arrays, space = align_fair_targets(
        dict(
            reference=x,
            contaminated=y,
            contamination=a,
            cleaned=x,
            processed_reference=x,
        ),
        sfreq,
        channels=["C3", "C4"],
        input_unit="V",
        output_unit="uV",
        source_reference="acquisition",
    )
    meta["spaces"] = {name: space for name in ARRAY_NAMES}
    result = evaluate_reconstruction(**arrays, sfreq=sfreq, metadata=meta)
    assert result["status"] == "evaluated"
    assert value(result, "input_nrmse") == pytest.approx(0.5)


def test_all_109_subjects_are_equally_weighted_despite_unequal_window_counts(probe):
    x, _, _, sfreq, meta = probe
    windows = [{"subject_id": f"s{i}", "window_id": "w0"} for i in range(109)]
    windows.extend({"subject_id": "s0", "window_id": f"w{i}"} for i in range(1, 10))
    meta["windows"] = windows
    meta["expected_windows"] = {f"s{i}": ["w0"] for i in range(109)}
    meta["expected_windows"]["s0"] += [f"w{i}" for i in range(1, 10)]
    ref = np.repeat(x[:1], len(windows), axis=0)
    contaminated, noise, meta["injection"] = generate_contamination(
        ref,
        sfreq,
        kind="line",
        seed=731,
        rms_ratio=0.5,
        window_keys=[json.dumps([w["subject_id"], w["window_id"]]) for w in windows],
    )
    cleaned = ref.copy()
    for i, row in enumerate(windows):
        if row["subject_id"] == "s0":
            cleaned[i] = 0
    result = evaluate_reconstruction(
        ref, contaminated, cleaned, sfreq, noise, meta, processed_reference=ref
    )
    assert result["status"] == "evaluated" and result["n_subjects"] == 109
    assert result["n_windows"] == 118
    assert value(result, "reconstruction_nrmse") == pytest.approx(1 / 109)
    assert result["summary"]["reconstruction_nrmse"]["n_total"] == 109


def test_undefined_channels_do_not_silently_shrink_denominator(probe):
    x, y, _, _, _ = probe
    q, z = x.copy(), y.copy()
    q[0, 0], z[0, 0] = 0, 0
    result = evaluate(probe, cleaned=z, processed_reference=q)
    assert (
        result["windows"][0]["metrics"]["paired_correlation"]["status"]
        == "constant_channel"
    )
    assert (
        result["windows"][0]["metrics"]["paired_correlation"]["n_valid_channels"] == 1
    )
    assert result["summary"]["paired_correlation"] == {
        "value": None,
        "status": "incomplete",
        "n_valid": 1,
        "n_total": 2,
    }


@pytest.mark.parametrize(
    "field,new",
    [
        ("processed_reference", None),
        ("sfreq", 0),
        ("sfreq", float("nan")),
        ("sfreq", True),
        ("metadata", {"invalid": float("inf")}),
        ("reference", np.ones((2, 512))),
        ("cleaned", np.ones((2, 3, 512))),
        ("cleaned", np.full((2, 2, 512), np.nan)),
        ("cleaned", np.ones((2, 2, 512), dtype=complex)),
    ],
)
def test_invalid_inputs_return_strict_json_without_metrics(probe, field, new):
    result = evaluate(probe, **{field: new})
    assert result["status"] == "invalid_input"
    assert result["windows"] == [] and result["summary"] == {}


@pytest.mark.parametrize(
    "case",
    [
        "missing_subject",
        "missing_window",
        "duplicate",
        "units",
        "band",
        "order",
        "no_seed",
        "no_execution",
    ],
)
def test_manifest_and_comparison_space_fail_closed(probe, case):
    x, y, a, sfreq, meta = probe
    if case == "missing_subject":
        meta["expected_windows"]["s3"] = ["w1"]
    elif case == "missing_window":
        meta["expected_windows"]["s1"].append("w2")
    elif case == "duplicate":
        meta["windows"][1] = meta["windows"][0]
    elif case == "units":
        meta["spaces"]["cleaned"]["unit"] = "dimensionless"
    elif case == "band":
        meta["spaces"]["cleaned"]["band_hz"] = [8, 30]
    elif case == "order":
        meta["spaces"]["cleaned"]["channels"].reverse()
    elif case == "no_seed":
        del meta["injection"]["seed"]
    else:
        meta["processor"]["paired_execution"] = False
    result = evaluate(probe)
    assert result["status"] == "invalid_input" and result["summary"] == {}


def test_wrong_known_contamination_is_rejected_at_microvolt_scale(probe):
    result = evaluate(probe, contamination=0.9 * probe[2])
    assert result["status"] == "invalid_input"
    assert "reference + known contamination" in result["reason"]


def test_unimplemented_identity_is_not_evaluated_as_cleaning(probe):
    probe[4]["processor"]["implemented"] = False
    result = evaluate(probe, cleaned=probe[1])
    assert result["status"] == "not_implemented" and not result["summary"]


@pytest.mark.parametrize("amplitude", [1e-250, 1e250])
def test_metrics_are_unit_scale_invariant_and_json_finite(probe, amplitude):
    x, y, a, _, _ = probe
    result = evaluate(
        probe,
        reference=x * amplitude,
        contaminated=y * amplitude,
        contamination=a * amplitude,
        cleaned=(x + 0.25 * a) * amplitude,
        processed_reference=x * amplitude,
    )
    assert result["status"] == "evaluated"
    assert value(result, "paired_nrmse") == pytest.approx(0.125)


def test_zero_reference_and_absent_contamination_are_explicit(probe):
    zeros = np.zeros_like(probe[0])
    result = evaluate(
        probe,
        reference=zeros,
        contaminated=zeros,
        contamination=zeros,
        cleaned=zeros,
        processed_reference=zeros,
    )
    metrics = result["windows"][0]["metrics"]
    assert metrics["input_nrmse"]["status"] == "zero_reference"
    assert metrics["artifact_residual_coefficient"]["status"] == "no_contamination"
    assert metrics["paired_ser_improvement_db"]["status"] == "no_contamination"
    assert value(result, "clean_retention_rms_ratio") is None


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "unknown"},
        {"seed": -1},
        {"seed": True},
        {"rms_ratio": 0},
        {"rms_ratio": float("nan")},
        {"line_frequency": 128},
        {"window_keys": ["a", "a"]},
        {"spatial_weights": [0, 0]},
        {"spatial_weights": [1]},
    ],
)
def test_invalid_contamination_plan_is_rejected(probe, changes):
    args = dict(kind="line", seed=1, rms_ratio=1, window_keys=["a", "b"])
    with pytest.raises(ValueError):
        generate_contamination(probe[0], probe[3], **{**args, **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"output_unit": "dimensionless"},
        {"band_hz": (4, 128)},
        {"trim_samples": 256},
        {"channels": ["C3"]},
        {"reference": "fit_to_cleaned"},
    ],
)
def test_alignment_rejects_incompatible_or_fitted_targets(probe, changes):
    args = dict(
        channels=["C3", "C4"],
        input_unit="V",
        output_unit="V",
        source_reference="acquisition",
    )
    with pytest.raises(ValueError):
        align_fair_targets({"x": probe[0]}, probe[3], **{**args, **changes})
