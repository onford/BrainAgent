from copy import deepcopy

import numpy as np
import pytest

from app.search.interpretation import Guide, evidence_document, interpretation_context, interpretation_guide
from app.search.quality import evaluate_quality
from app.search.quality_diagnostics import diagnostic_views
from app.search.quality_evaluation import METRIC_IDS


def test_guide_covers_metrics_and_resolves_sources():
    guide = interpretation_guide()
    assert set(METRIC_IDS) <= {m for c in guide['cards'] for m in c['metrics']}
    broken = deepcopy(guide)
    broken['cards'][0]['source_ids'] = ['invented-paper']
    with pytest.raises(ValueError, match='unknown interpretation source'):
        Guide.model_validate(broken)


def test_context_uses_frozen_document_and_preserves_history():
    assert interpretation_context([])['status'] == 'not_frozen_in_this_run'
    guide = interpretation_guide()
    guide['cards'][0]['reading'] = 'Saved historical interpretation'
    context = interpretation_context([evidence_document(guide)])
    assert context['cards'][0]['reading'] == 'Saved historical interpretation'
    assert context['source_id'] == 'interpretation-guide'
    assert 'Saved historical' not in interpretation_guide()['cards'][0]['reading']


def test_preview_retains_transient_native_samples_and_input():
    data = np.zeros((2, 3, 2000))
    data[0] = np.nan
    data[1, 0, 1701] = 75e-6
    before = data.copy()
    view = diagnostic_views(data, 160, ['C3', 'Cz', 'C4'], trial_ids=['a', 'b'])
    assert view['trial_id'] == 'b' and view['epoch_index'] == 1
    assert len(view['waveform']['times_seconds']) == 640
    assert max(view['overview']['maximum_uv'][0]) == pytest.approx(75)
    assert len(view['overview']['start_seconds']) <= 256
    assert view['waveform']['times_seconds'][1] == 1/160
    np.testing.assert_array_equal(data, before)


def test_window_psd_axes_and_quantiles_are_same_data():
    data = np.random.default_rng(42).normal(0, 1e-5, (2, 3, 1500))
    report = evaluate_quality(data, 160, ['C3', 'Cz', 'C4'])
    metric = report.by_id('psd_window_quantiles')
    windows = np.asarray(metric.details['window_channel_median_psd'])
    assert windows.shape == (4, len(metric.details['frequencies_hz']))
    np.testing.assert_allclose(metric.value, np.quantile(windows, [.1, .5, .9], axis=0))
    assert [w['epoch_index'] for w in metric.details['windows']] == [0, 0, 1, 1]
    assert [w['start_seconds_in_epoch'] for w in metric.details['windows']] == [0, 4, 0, 4]


def test_short_epoch_never_fabricates_full_window_psd():
    report = evaluate_quality(np.ones((3, 2, 320))*1e-6, 160, ['C3', 'C4'])
    assert report.by_id('psd_window_quantiles').status == 'not_applicable'
    assert 'window_channel_median_psd' not in report.by_id('psd_window_quantiles').details
    assert diagnostic_views(np.full((1, 2, 320), np.nan), 160, ['C3', 'C4'])['status'] == 'not_applicable'
