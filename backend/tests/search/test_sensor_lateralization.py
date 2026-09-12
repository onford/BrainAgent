from copy import deepcopy

import numpy as np
import pytest

from app.search.sensor_lateralization import extract_record, lateralization_diagnostic
from app.search.neural_diagnostics import run_diagnostic
from app.search.io import read, write
from app.preprocessing.storage import file_hash
from tests.search.test_diagnostic_registry import diagnostic  # noqa: F401
from tests.search.test_neural_priors import bundle  # noqa: F401


def report():
    ids = ['t0','t1','t2']
    r = dict(unit='V', n_epochs=3, channel_names=['C3','Cz','C4'], metrics=[
        dict(metricID='erds_'+band, status='ok', value=[[-50.,0.,0.],[-20.,0.,10.],[0.,0.,20.]],
            denominator={'original_trial_ids':ids}, details=dict(paired_original_trial_ids=ids,
                baseline_interval_seconds=[-2.5,-.5], baseline_stop_exclusive=True,
                baseline_audit=[dict(event_id=t,epoch_index=i,status='ok') for i,t in enumerate(ids)],
                baseline_power_uv2_per_hz=[[2.,3.,4.],[2.,3.,4.],[2.,3.,4.]])) for band in ['mu','beta']])
    return r, ids


def test_sensor_contrast_keeps_baseline_values_and_delete_one_sensitivity():
    r, ids = report()
    out = extract_record(r,ids)['bands']['mu']
    assert out['value'] == pytest.approx(-100/3)
    assert out['trials'][0]['difference_percentage_points'] == -50
    assert out['trials'][0]['baseline_C3_uv2_per_hz'] == 2
    assert out['delete_one_trial_sensitivity']['minimum'] == -40
    assert out['delete_one_trial_sensitivity']['maximum'] == -25
    assert out['available_trials'] == out['expected_trials'] == 3


@pytest.mark.parametrize('change', ['channel','missing','baseline_zero','baseline_order','trial_order','partial','interval'])
def test_missing_or_unpaired_baselines_do_not_become_lateralization(change):
    r, ids = report()
    row = r['metrics'][0]
    if change == 'channel': r['channel_names'][0] = 'Fp1'
    if change == 'missing': row['details'].pop('baseline_power_uv2_per_hz')
    if change == 'baseline_zero': row['details']['baseline_power_uv2_per_hz'][0][0] = 0
    if change == 'baseline_order': row['details']['baseline_audit'].reverse()
    if change == 'trial_order': row['details']['paired_original_trial_ids'] = list(reversed(ids))
    if change == 'partial': row['status'] = 'partial'
    if change == 'interval': row['details']['baseline_interval_seconds'] = [0.,2.]
    if change == 'missing':
        with pytest.raises(ValueError): extract_record(r,ids)
    else:
        out = extract_record(r,ids)['bands']['mu']
        assert out['status'] == 'unavailable' and out['value'] is None
        assert out['missing_trial_ids'] == ids


def quality():
    r, ids = report()
    measurement = extract_record(r,ids)
    measurement['measurement_frame_sha256'] = 'f'*64
    def record(rid, offset):
        m = deepcopy(measurement)
        for row in m['bands'].values():
            row['value'] += offset
            for t in row['trials']:
                t['erds_C3_percent'] += offset
                t['difference_percentage_points'] += offset
        return dict(record_id=rid,coverage={'eligible_trials':3},
            measurement_frames={'processed_task':dict(status='verified',sha256='f'*64)},
            sensor_lateralization={'processed_task':m})
    return dict(coverage=dict(records_expected=3,records_visited=3,subjects_expected=2,subjects_visited=2),
        bysubject={'a':{'records':[record('r1',0),record('r2',0)]}, 'b':{'records':[record('r3',30)]}})


def test_group_equal_aggregation_keeps_record_and_group_denominators():
    q = quality()
    result = lateralization_diagnostic(q,'processed_task',{'check':lambda:None})
    row = result['sensor_lateralization']['summary']['mu']
    assert row['value'] == pytest.approx(-100/3 + 15)
    assert row['delete_one_subject_sensitivity']['minimum'] == pytest.approx(-100/3)
    q['bysubject']['a']['records'][0].pop('sensor_lateralization')
    row = lateralization_diagnostic(q,'processed_task',{'check':lambda:None})['sensor_lateralization']['summary']['mu']
    assert row['value'] is None and row['available_records'] == 2 and row['expected_records'] == 3
    assert row['available_subjects'] == 1


def test_registered_lateralization_uses_frozen_receipt_and_numeric_branch(diagnostic):
    root, state, request, path, ref = diagnostic
    q = read(path)
    q.update(quality())
    write(path,q); ref['sha256'] = file_hash(path)
    request.update(kind='sensor_lateralization',stage='processed_task')
    request['experiment'].update(metric='sensor_lateralization.summary.mu.value',comparison='lt',threshold=0.)
    r = run_diagnostic(root,state,request)
    assert r['decision_effect']['outcome'] == 'condition_met'
    assert r['decision_effect']['value'] == pytest.approx(-100/3+15)
    assert len(r['input_artifacts']) == 1


@pytest.mark.parametrize('change', ['unvisited_record', 'unvisited_subject', 'trial_count', 'duplicate', 'frame', 'changed_mean'])
def test_incomplete_inventory_or_changed_frame_cannot_certify_contrast(change):
    q = quality()
    if change == 'unvisited_record': q['coverage']['records_expected'] = 4
    if change == 'unvisited_subject': q['coverage']['subjects_expected'] = 3
    if change == 'trial_count': q['bysubject']['a']['records'][0]['coverage']['eligible_trials'] = 4
    if change == 'duplicate': q['bysubject']['b']['records'][0]['record_id'] = 'r1'
    if change == 'frame': q['bysubject']['a']['records'][0]['measurement_frames']['processed_task']['sha256'] = 'b'*64
    if change == 'changed_mean': q['bysubject']['a']['records'][0]['sensor_lateralization']['processed_task']['bands']['mu']['value'] = 5.
    if change in ('duplicate','frame','changed_mean'):
        with pytest.raises(ValueError): lateralization_diagnostic(q,'processed_task',{'check':lambda:None})
    else:
        r = lateralization_diagnostic(q,'processed_task',{'check':lambda:None})
        assert r['status'] == 'unavailable'
        assert r['sensor_lateralization']['summary']['mu']['value'] is None
