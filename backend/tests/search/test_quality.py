"""Signal properties and measurement prerequisites, not implementation mirrors."""

import json

import numpy as np
import pytest
from pydantic import ValidationError

from app.search.quality import (
    QualityMetric,
    QualityMetrics,
    SignalView,
    compute_paired_erds,
    compute_signal_quality,
    evaluate_dimensionless_quality,
    evaluate_quality,
)


CHANNELS = ["C3", "Cz", "C4"]


def noise(seconds=4, sfreq=250, n=3, amplitude=5e-6):
    return np.random.default_rng(42).normal(0, amplitude, (n, 3, round(seconds * sfreq)))


def value(report, name):
    return np.asarray(report.by_id(name).value, dtype=float)


def wave(frequency, amplitude, sfreq=250, seconds=4, n=3):
    times = np.arange(round(seconds * sfreq)) / sfreq
    return np.broadcast_to(amplitude * np.sin(2 * np.pi * frequency * times),
                           (n, 3, len(times))).copy()


def test_zero_is_not_good_and_does_not_create_fake_denominators():
    q = evaluate_quality(np.zeros((2, 3, 500)), 250, CHANNELS)
    np.testing.assert_equal(value(q, "numerical_rank"), [0, 0])
    for metric in ("channel_correlation", "covariance_condition", "emg_hf_proxy"):
        assert q.by_id(metric).status == "not_computable"
        assert q.by_id(metric).value is None
        assert q.by_id(metric).reason
    assert q.by_id("oha").value == [0.0, 0.0, 0.0, 0.0]
    assert q.by_id("flat_fraction").status == "not_applicable"
    assert q.by_id("drift_slope").status == "not_applicable"
    assert q.by_id("erds_mu").reason == "baseline_epochs_unavailable"
    assert q.metadata["composite_score"] is None
    assert not q.metadata["scientific_quality_certified"]
    assert "NaN" not in q.model_dump_json() and "Infinity" not in q.model_dump_json()
    QualityMetrics.model_validate(json.loads(q.model_dump_json()))


def test_flat_detection_does_not_bridge_epoch_boundaries():
    short = evaluate_quality(np.zeros((10, 3, 1000)), 250, CHANNELS)
    assert short.by_id("flat_fraction").status == "not_applicable"
    long = evaluate_quality(np.zeros((2, 3, 1500)), 250, CHANNELS)
    np.testing.assert_equal(value(long, "flat_fraction"), np.ones((2, 3)))


def test_short_window_metrics_are_unavailable_instead_of_zero_padded():
    q = evaluate_quality(noise(seconds=1), 250, CHANNELS)
    for mid in ("psd", "oha", "thv", "chv", "channel_correlation", "drift_power_ratio"):
        assert q.by_id(mid).status == "not_applicable"
        assert q.by_id(mid).value is None
    assert q.by_id("numerical_rank").status == "ok"


def test_two_second_scored_grid_is_not_four_second_psd_or_precue():
    q = evaluate_quality(noise(seconds=2), 250, CHANNELS)
    assert q.by_id("psd").details["resolution_hz"] == 0.5
    assert q.by_id("psd").details["nfft"] == 500
    assert q.by_id("psd_window_quantiles").status == "not_applicable"
    assert q.by_id("oha").status == "ok"
    assert q.by_id("erds_mu").status == "not_applicable"


def test_sine_psd_has_correct_physical_density_and_integral():
    q = evaluate_quality(wave(10, 10e-6), 250, CHANNELS)
    psd = q.by_id("psd")
    assert psd.unit == "µV²/Hz"
    frequencies = np.asarray(psd.details["frequencies_hz"])
    spectrum = value(q, "psd")
    assert frequencies[np.argmax(spectrum[0, 0])] == 10.0
    # A 10 µV sine has variance 50 µV² (one Welch segment per epoch).
    np.testing.assert_allclose(np.trapz(spectrum, frequencies, axis=-1), 50, rtol=1e-10)
    assert value(q, "mu_mean_psd").mean() > 100 * value(q, "beta_mean_psd").mean()


def test_line_and_muscle_proxies_respond_to_distinct_added_noise():
    base = noise()
    line = evaluate_quality(base + wave(50, 35e-6), 250, CHANNELS)
    hf = evaluate_quality(base + wave(38, 35e-6), 250, CHANNELS)
    clean = evaluate_quality(base, 250, CHANNELS)
    assert value(line, "line_ratio_50hz").mean() > value(clean, "line_ratio_50hz").mean() + 15
    assert value(hf, "emg_hf_proxy").mean() > value(clean, "emg_hf_proxy").mean() + 10
    assert line.by_id("line_ratio_50hz").direction == "lower_residual_only"
    assert hf.by_id("emg_hf_proxy").details["specific_to_emg"] is False


def test_nyquist_requires_both_line_sidebands_and_full_hf_band():
    q = evaluate_quality(noise(sfreq=80), 80, CHANNELS)
    for mid in ("line_ratio_50hz", "line_ratio_60hz", "emg_hf_proxy"):
        assert q.by_id(mid).status == "not_applicable"
    assert q.by_id("beta_mean_psd").status == "ok"


def test_voltage_scaling_changes_physical_metrics_but_not_rank_or_shape():
    x = noise(amplitude=30e-6)
    small, large = evaluate_quality(x, 250, CHANNELS), evaluate_quality(4*x, 250, CHANNELS)
    np.testing.assert_allclose(value(large, "peak_to_peak"), 4*value(small, "peak_to_peak"))
    np.testing.assert_allclose(value(large, "covariance_trace"), 16*value(small, "covariance_trace"))
    np.testing.assert_allclose(value(large, "numerical_rank"), value(small, "numerical_rank"))
    np.testing.assert_allclose(value(large, "channel_correlation"), value(small, "channel_correlation"))
    np.testing.assert_allclose(value(large, "emg_hf_proxy"), value(small, "emg_hf_proxy"))
    assert value(large, "oha")[0] > value(small, "oha")[0]


def test_dimensionless_has_no_microvolt_thresholds_or_physical_psd():
    q = evaluate_dimensionless_quality(noise(amplitude=1), 250, CHANNELS)
    assert q.unit == "dimensionless"
    for mid in ("oha", "thv", "chv", "flat_fraction", "electrical_distance", "erds_mu"):
        assert q.by_id(mid).status == "not_applicable"
    assert q.by_id("psd").unit == "dimensionless²/Hz"
    assert q.by_id("peak_to_peak").unit == "dimensionless"
    assert q.by_id("channel_correlation").status == "ok"


def test_oha_uses_cells_thv_times_and_chv_channels():
    # Exactly one of three channels above 50µV, same value throughout epoch.
    x = np.zeros((1, 3, 500))
    x[:, 0] = 100e-6
    q = evaluate_quality(x, 250, CHANNELS)
    assert value(q, "oha")[1] == pytest.approx(1/3)
    assert value(q, "oha")[2] == 0  # strict >100, not >=100
    assert value(q, "thv")[1] == 1  # cross-channel population SD ≈47µV
    assert value(q, "chv")[1] == 0  # no within-channel time variation
    assert q.by_id("thv").details["ddof"] == 0
    assert q.by_id("chv").details["window_curves"] == [[0.0, 0.0, 0.0]]


def test_copied_channels_have_high_correlation_but_low_rank_and_small_electrical_distance():
    x = noise()
    x[:, 1] = x[:, 0]
    q = evaluate_quality(x, 250, CHANNELS,
                         montage_positions={"C3": [-1., 0., 0.], "Cz": [0., 0., 1.], "C4": [1., 0., 0.]})
    np.testing.assert_equal(value(q, "numerical_rank"), [2, 2, 2])
    assert q.by_id("covariance_condition").value is None
    assert value(q, "channel_correlation")[:, :2].min() > 0.95
    assert value(q, "electrical_distance")[:, 0].max() == 0
    assert q.by_id("electrical_distance").details["bridge_diagnosis"] is False


def test_precue_power_produces_signed_percent_and_is_scale_invariant():
    baseline = wave(10, 20e-6)
    task = wave(10, 10e-6)
    q = evaluate_quality(task, 250, CHANNELS, baseline_epochs_V=baseline)
    scaled = evaluate_quality(task*7, 250, CHANNELS, baseline_epochs_V=baseline*7)
    np.testing.assert_allclose(value(q, "erds_mu"), -75, atol=1e-10)
    np.testing.assert_allclose(value(scaled, "erds_mu"), value(q, "erds_mu"), atol=1e-10)
    assert q.by_id("erds_mu").unit == "%"
    assert "not a multitaper TFR" in q.by_id("erds_mu").details["definition"]


def test_zero_or_too_short_baseline_is_not_repaired_with_epsilon():
    task = noise(seconds=2)
    zero = evaluate_quality(task, 250, CHANNELS, baseline_epochs_V=np.zeros_like(task))
    assert zero.by_id("erds_mu").status == "not_computable"
    assert zero.by_id("erds_mu").value is None
    short = evaluate_quality(task, 250, CHANNELS, baseline_epochs_V=noise(seconds=0.5))
    assert short.by_id("erds_mu").status == "not_applicable"


def test_nonfinite_epoch_preserves_exclusion_denominator_and_original_arrays():
    x = noise()
    x[0, 1, 0] = np.nan
    saved = x.copy()
    x.flags.writeable = False
    q = evaluate_quality(x, 250, CHANNELS)
    assert q.by_id("psd").status == "partial"
    assert q.by_id("psd").denominator["finite_epochs"] == 2
    assert q.by_id("psd").denominator["excluded_nonfinite_epoch_indices"] == [0]
    np.testing.assert_array_equal(x, saved)
    json.dumps(q.model_dump(), allow_nan=False)


def test_reference_change_reports_change_not_clean_ground_truth():
    ref = noise()
    q = evaluate_quality(ref/2, 250, CHANNELS, reference_epochs_V=ref)
    np.testing.assert_allclose(value(q, "reference_nrmse"), 0.5)
    assert q.by_id("reference_nrmse").details["reference_is_not_clean_ground_truth"]


def test_drift_requires_long_epoch_and_tracks_linear_trend():
    sfreq = 100
    times = np.arange(3000)/sfreq
    q = evaluate_quality(np.broadcast_to(2e-6*times, (1, 3, len(times))), sfreq, CHANNELS)
    np.testing.assert_allclose(value(q, "drift_slope"), 2.0, atol=1e-12)
    assert q.by_id("drift_power_ratio").status == "ok"


@pytest.mark.parametrize("arguments", [
    (np.zeros((3, 500)), 250, CHANNELS),
    (np.zeros((1, 3, 500)), 0, CHANNELS),
    (np.zeros((1, 3, 500)), 250, ["C3", "C3", "C4"]),
    (np.zeros((1, 3, 500)), np.inf, CHANNELS),
])
def test_invalid_shapes_or_metadata_do_not_produce_scores(arguments):
    with pytest.raises(ValueError):
        evaluate_quality(*arguments)


def test_strict_metric_rejects_unexplained_missing_or_nan():
    with pytest.raises(ValidationError):
        QualityMetric(metricID="x", value=None, unit="%", status="not_applicable", reason=None, formula="x")
    with pytest.raises(ValidationError):
        QualityMetric(metricID="x", value=[float("nan")], unit="%", status="ok", reason=None, formula="x")


def power_view(**kwargs):
    settings = dict(sfreq=250, unit="V", channels=tuple(CHANNELS), source_id="source",
                    processing_id="cleaned", reference="CAR", measurement_id="same_tfr",
                    passband_hz=(0.5, 45))
    settings.update(kwargs)
    return SignalView(**settings)


def test_provenance_aware_erds_refuses_raw_precue_plus_cleaned_grid():
    q = compute_paired_erds(np.ones((1, 3, 10)), np.ones((1, 3, 10)),
                            task_view=power_view(kind="scored_grid"),
                            baseline_view=power_view(kind="raw_precue", processing_id="raw"),
                            task_trial_ids=["t"], baseline_trial_ids=["t"],
                            baseline_times=np.linspace(-2, -1, 10), baseline_interval=(-2, -1))
    assert q["metric"]["status"] == "not_comparable"
    assert q["metric"]["reason"] == "processing_id_mismatch"


def test_provenance_erds_aligns_trial_ids_and_checks_full_support():
    task = np.ones((2, 3, 10))
    baseline = np.stack([np.full((3, 10), 4.), np.full((3, 10), 2.)])
    kwargs = dict(task_view=power_view(), baseline_view=power_view(kind="task_baseline"),
                  task_trial_ids=["a", "b"], baseline_trial_ids=["b", "a"],
                  baseline_times=np.linspace(-2, -1, 10), baseline_interval=(-2, -1))
    result = compute_paired_erds(task, baseline, **kwargs)
    np.testing.assert_allclose(result["metric"]["value"][0], -50)
    np.testing.assert_allclose(result["metric"]["value"][1], -75)
    support = np.ones((2, 3, 10), dtype=bool)
    support[0, 0, 0] = False
    partial = compute_paired_erds(task, baseline, baseline_valid_mask=support, **kwargs)
    assert partial["metric"]["status"] == "partial"
    assert partial["metric"]["value"][1][0] == [None] * 10


def test_dimensionless_erds_needs_exact_same_fitted_transform():
    view = power_view(unit="dimensionless", coordinate_space="transformed",
                      transform_kind="spatial_linear", transform_id="fit-a")
    mismatch = power_view(unit="dimensionless", coordinate_space="transformed",
                          transform_kind="spatial_linear", transform_id="fit-b")
    result = compute_paired_erds(np.ones((1, 3, 10)), np.ones((1, 3, 10)),
                                 task_view=view, baseline_view=mismatch,
                                 task_trial_ids=["a"], baseline_trial_ids=["a"],
                                 baseline_times=np.linspace(-2, -1, 10), baseline_interval=(-2, -1))
    assert result["metric"]["reason"] == "transform_id_mismatch"


def test_curves_preserve_epoch_times_and_report_unmeasured_tail():
    x = noise(seconds=7)
    x[0, 0, 0] = np.nan
    report = evaluate_quality(x, 250, CHANNELS)
    windows = report.by_id("oha").details["windows"]
    assert [(w["epoch_index"], w["start_seconds_in_epoch"], w["stop_seconds_in_epoch"])
            for w in windows] == [(1, 0, 4), (1, 4, 7), (2, 0, 4), (2, 4, 7)]
    tail = evaluate_quality(noise(seconds=5), 250, CHANNELS).by_id("oha")
    assert tail.details["excluded_tail_samples_per_epoch"] == 250


def test_continuous_view_short_flat_is_unavailable():
    result = compute_signal_quality(np.zeros((3, 500)), power_view())
    assert result["metrics"]["flat_fraction"]["status"] == "not_applicable"


@pytest.mark.parametrize("baseline_view, interval, expected", [
    (power_view(passband_hz=(1, 45)), (-2, -1), "passband_hz_mismatch"),
    (power_view(), (-1.95, -1.94), "baseline_interval_has_fewer_than_two_samples"),
])
def test_baseline_provenance_and_sample_support_cannot_be_inferred(baseline_view, interval, expected):
    result = compute_paired_erds(np.ones((1, 3, 10)), np.ones((1, 3, 10)),
                                 task_view=power_view(), baseline_view=baseline_view,
                                 task_trial_ids=["a"], baseline_trial_ids=["a"],
                                 baseline_times=np.linspace(-2, -1, 10), baseline_interval=interval)
    assert result["metric"]["status"] == "not_comparable"
    assert result["metric"]["reason"] == expected
