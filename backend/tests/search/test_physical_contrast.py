from copy import deepcopy
from types import SimpleNamespace
import numpy as np
import pytest

from app.preprocessing.storage import digest
from app.search.physical_contrast import contrast_epochs,check_sample_geometry
from app.search.physical_frames import measurement_frame,paired_frames


def test_shared_projection_is_linear_physical_and_does_not_fit_or_mutate():
    fs=160
    x=np.random.default_rng(4).normal(0,1e-5,(3,4,640))
    cleaned=x*.75
    before=x.copy()
    kwargs=dict(sfreq=fs,channels=['C3','C4','F3','F4'],source_trial_ids=['a','b','c'],processed_trial_ids=['a','b','c'],
        source_history={'nominal_band_hz':[0,80]},processed_history={'nominal_band_hz':[8,30]},time_window=[0,639/fs])
    arrays,report=contrast_epochs(x,cleaned,**kwargs)
    np.testing.assert_array_equal(x,before)
    np.testing.assert_allclose(arrays['processed'],.75*arrays['source'],atol=1e-18,rtol=1e-12)
    np.testing.assert_allclose(arrays['difference'],.25*arrays['source'],atol=1e-18,rtol=1e-12)
    assert report['contract']['space']['band_hz']==[8,30]
    assert report['contract']['fit_scope']=='not_fitted'
    assert report['contract']['neural_preservation']=='not_established'
    assert report['contract_sha256']==digest(report['contract'])
    # Arbitrary scalar electrode references cancel under the explicit CAR.
    shifted,_=contrast_epochs(x+3e-5,cleaned-7e-5,**kwargs)
    np.testing.assert_allclose(shifted['difference'],arrays['difference'],atol=1e-18,rtol=1e-12)
    with pytest.raises(ValueError,match='trial_order'):
        contrast_epochs(x,cleaned,**{**kwargs,'processed_trial_ids':['b','a','c']})
    with pytest.raises(ValueError,match='finite'):
        contrast_epochs(x*np.nan,cleaned,**kwargs)
    with pytest.raises(ValueError,match='analysis_band'):
        contrast_epochs(x,cleaned,**{**kwargs,'processed_history':{'nominal_band_hz':[50,70]}})


def test_frame_uses_executed_operations_and_record_provenance_not_operator_aliases():
    report=dict(unit='V',sfreq=160,channel_names=['C3','C4'],n_epochs=2,n_samples_per_epoch=321,
        metadata={'history':{'nominal_band_hz':[8,30],'reference':'acquisition','operations':[
            dict(operator='paper_filter_any_name',unit_id='EEG-FILTER',op='butter',implementation_version='2',
                 profile='default',frozen_parameters={'l_freq':8,'h_freq':30,'order':5})]}})
    def frame(r):return measurement_frame(r,source_files={'r.vhdr':'abc'},record_id='r',stage='processed_task',
        sample_identity={'trials':['a','b']},verified=True)
    a=frame(report)
    changed=deepcopy(report)
    changed['metadata']['history']['operations'][0]['operator']='another_alias'
    assert frame(changed)==a
    changed['metadata']['history']['operations'][0]['frozen_parameters']['h_freq']=25
    b=frame(changed)
    def records(f):return [dict(record_id='r',measurement_frames={'processed_task':f})]
    assert paired_frames(records(a),records(a),'processed_task')==(True,{})
    assert not paired_frames(records(a),records(b),'processed_task')[0]
    assert not paired_frames(records(a),[{'record_id':'r'}],'processed_task')[0]
    b['sha256']=a['sha256']
    assert 'checksum' in paired_frames(records(a),records(b),'processed_task')[1]['r']


def test_time_changed_graph_requires_explicit_interior_mapping():
    step=SimpleNamespace(id='cut',input='raw',implementation_version='2',unit_id='EEG-CROP',op='crop_join',params={})
    with pytest.raises(ValueError,match='geometry'):
        check_sample_geometry(SimpleNamespace(steps=[step],output='cut'),160)


def test_fit_branch_filter_does_not_change_output_band_history():
    from app.preprocessing.schemas import Step
    from app.search.quality_evaluation import _history
    steps=[Step(id='fit_band',unit_id='EEG-FILTER',op='filter',implementation_version='2',params={'l_freq':1,'h_freq':5},evidence_indices=[0]),
        Step(id='output_band',unit_id='EEG-FILTER',op='filter',implementation_version='2',params={'l_freq':.5,'h_freq':60},evidence_indices=[0]),
        Step(id='epoch',unit_id='EEG-EPOCH',op='epoch',implementation_version='2',input='output_band',params={},evidence_indices=[0])]
    entry={'recipe':{'nodes':[dict(id=s.id,operator='arbitrary_alias_'+s.id,parameters={},
        graph=dict(unit_id=s.unit_id,op=s.op,profile=s.profile)) for s in steps]}}
    history=_history(SimpleNamespace(info=dict(highpass=0.,lowpass=80.)),{},SimpleNamespace(steps=steps,output='epoch'),entry)
    assert history['nominal_band_hz']==[.5,60.]
    assert {s['step_id'] for s in history['operations']}=={'output_band','epoch'}
