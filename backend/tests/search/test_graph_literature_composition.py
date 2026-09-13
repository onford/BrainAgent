from copy import deepcopy
import pytest
from app.search.literature_space import build_workflow_space, check_execution
from app.search.method_space import seed_entries, verify_registry
from app.search.recipe_compiler import compile_recipe
from app.preprocessing.schemas import MethodSpec
from tests.search.test_literature_space import branch, extract, refs, OUTPUT
from tests.preprocessing.conftest import make_dataset




def test_csd_units_never_enter_voltage_panel(tmp_path):
    from app.search.graph_evaluation import check_config
    from app.preprocessing.schemas import Step
    from types import SimpleNamespace
    data=make_dataset(tmp_path/'bids');r=data.collection.records[0]
    s=Step(id='csd',unit_id='EEG-CSD',op='csd',implementation_version='2',evidence_indices=[0])
    # Use the registry identity, not an assumed code spelling.
    from app.preprocessing.units.operations_v2 import DEFINITIONS
    s.unit_id=next(u for u,o in DEFINITIONS if o=='csd')
    with pytest.raises(ValueError,match='V/m'):
        check_config(SimpleNamespace(steps=[s],output='csd'),r,OUTPUT)


def test_noncontained_source_window_keeps_engineering_origin_after_graph_projection(tmp_path):
    from app.preprocessing.schemas import Step, Evidence
    data = make_dataset(tmp_path / 'bids', subjects=3)
    method = MethodSpec(id='late-source-window', version='1', title='Late source window fixture',
        source='survey_literature', mechanism='source terminal epoch',
        evidence=[Evidence(source_url='fixture://late-window', source_version='1', locator='test',
                           text='Fixture: source epoch 1 to 4 seconds; no empirical source claim.')],
        recipe=[Step(id='late', unit_id='EEG-EPOCH', op='epoch', implementation_version='2',
            evidence_indices=[0], params={'events':'$events', 'event_id':'$event_id',
                                         'picks':'$eeg_channels', 'tmin':1., 'tmax':4.})],
        output='late', lineage={'kind':'literature', 'branch_id':'late'})
    before = method.model_dump(mode='json')
    space, context, report = build_workflow_space(data, OUTPUT, refs([method]))
    assert [r['status'] for r in report['methods']] == ['blocked', 'eligible'], report
    entry = next(e for e in seed_entries(space, context) if e['origin'] == 'literature_adaptation')
    compiled = compile_recipe(entry, space, {'output_contract':OUTPUT}, context)
    assert compiled.evaluation_window is None  # A replaced window, not a scoring projection.
    epoch = next(s for s in compiled.recipe if s.op == 'epoch')
    assert {k:epoch.params[k] for k in ('tmin', 'tmax')} == {k:OUTPUT[k] for k in ('tmin', 'tmax')}
    assert epoch.parameter_sources['tmin'].origin == 'target_binding'
    assert any(t.get('fidelity') == 'engineering_adaptation' and
               t['adaptation']['original'] == {'tmin':1., 'tmax':4.} for t in entry['lineage'])
    assert any('不能称为论文窗口或忠实复现' in d for d in compiled.adaptations)
    assert not any('all source windows/operations are retained' in d for d in compiled.adaptations)
    assert method.model_dump(mode='json') == before


def test_fitted_ica_diagnostic_ports_survive_three_axis_replay(tmp_path):
    from tests.search.test_integrated_operator_evaluation import _synthetic_bids, _execute, _assess
    from app.preprocessing.schemas import Step, Evidence, ArtifactPort, DecisionPolicy
    from app.search.panel import freeze_panel
    data = _synthetic_bids(tmp_path/'bids')
    def step(identity, op, params, **kwargs):
        return Step(id=identity, unit_id='EEG-FILTER' if op=='filter' else 'EEG-ICA', op=op,
                    implementation_version='2', evidence_indices=[0], params=params, **kwargs)
    method = MethodSpec(id='ica-port-fixture', version='1', title='ICA diagnostic dependency fixture',
        source='survey_literature', mechanism='fit-assess-apply',
        evidence=[Evidence(source_url='fixture://ica-ports', source_version='1', locator='numerical fixture',
                           text='Explicit test of fitted model and diagnostic ports, not literature evidence.')],
        recipe=[step('hp', 'filter', {'l_freq':1.,'h_freq':60.,'picks':'$eeg_channels','method':'iir','phase':'zero'}),
                step('fit', 'ica_fit', {'method':'fastica','n_components':3,'seed':17,'max_iter':1000,
                     'scope':'$scope','reference_id':'$reference_id'}, input='hp', adaptation_scope='record_unlabeled'),
                step('assess','muscle_assess',{'mode':'slope','threshold':.5,'reference_id':'$reference_id'},
                     input='hp',model_from='fit'),
                step('clean','ica_apply',{'reference_id':'$reference_id'},input='hp',model_from='fit',decision_from='assess',
                     artifact_inputs={'exclude':ArtifactPort(step='assess',port='artifacts',path=['candidates'])},
                     decision=DecisionPolicy(mode='accept_candidates',reason='Explicit fixture policy'))],
        output='clean',lineage={'kind':'literature','workflow_id':'fixture','branch_id':'ica'})
    output={'sfreq':160.,'tmin':0.,'tmax':2.}
    space, context, report = build_workflow_space(data, output, refs([method]))
    assert all(row['status']=='eligible' for row in report['methods']), [r['reasons'] for r in report['methods']]
    entry=next(e for e in seed_entries(space,context) if e['origin']=='literature')
    panel=freeze_panel(data,{r.id:r.id for r in data.collection.records},seed=47,**output)
    run=_execute((tmp_path,data,context,panel,space,[],[]),entry)
    assert _assess(run)['selection_ready']


def test_scoring_projection_preserves_source_baseline_and_all_three_axes(tmp_path):
    from tests.search.test_integrated_operator_evaluation import _synthetic_bids,_execute,_assess
    from app.search.panel import freeze_panel
    from app.preprocessing.schemas import Step, Evidence
    data=_synthetic_bids(tmp_path/'bids')
    method=MethodSpec(id='wide-context',version='1',title='Fixture source baseline with wider context',source='survey_literature',
        mechanism='source wide epochs then baseline',evidence=[Evidence(source_url='fixture://window',source_version='1',locator='Fixture contract',text='Explicit numerical fixture, not a paper.')],
        recipe=[Step(id='wide',unit_id='EEG-EPOCH',op='epoch',implementation_version='2',evidence_indices=[0],
                    params={'events':'$events','event_id':'$event_id','picks':'$eeg_channels','tmin':-.5,'tmax':2.5}),
                Step(id='center',unit_id='EEG-BASELINE',op='baseline',implementation_version='2',input='wide',evidence_indices=[0],params={'baseline':[-.5,0.]})],
        output='center',output_roles={'source_epochs':'wide','source_baselined':'center'},lineage={'kind':'literature','workflow_id':'fixture','branch_id':'wide'})
    original=method.model_dump(mode='json');output={'sfreq':160.,'tmin':0.,'tmax':2.}
    space,context,report=build_workflow_space(data,output,refs([method]))
    assert method.model_dump(mode='json')==original
    assert [r['status'] for r in report['methods']]==['blocked','eligible'],report
    entry=next(e for e in seed_entries(space,context) if e['origin']=='literature_adaptation')
    panel=freeze_panel(data,{r.id:r.id for r in data.collection.records},seed=47,**output)
    run=_execute((tmp_path,data,context,panel,space,[],[]),entry)
    assert _assess(run)['selection_ready']
    import numpy as np
    from app.preprocessing.artifact_codec import Codec
    import json
    for config in run[0].records:
        root=run[2]/config.record_id
        descriptor=root/'source-output'/'data.json'
        source=Codec(descriptor.parent).load(json.loads(descriptor.read_text(encoding='utf-8')))
        assert source.tmin==-.5 and source.tmax==2.5
        baseline=source.get_data()[:,:,source.times<=0].mean(axis=-1)
        np.testing.assert_allclose(baseline,0,atol=1e-18)
        np.testing.assert_array_equal(source.copy().crop(tmin=0,tmax=2).get_data(),np.load(root/'signal_V.npy'))


def test_parallel_final_epoch_keeps_frozen_panel_and_three_axis_replay(tmp_path):
    from tests.search.test_integrated_operator_evaluation import _synthetic_bids, _execute, _assess
    from app.search.panel import freeze_panel
    from app.preprocessing.schemas import Step, Evidence
    from app.preprocessing.artifact_codec import Codec
    import json
    data = _synthetic_bids(tmp_path/'bids')
    # Common 0..2 s windows are all valid, while 12 seconds of source context
    # excludes the first event in each record. The denominator remains 78.
    method = MethodSpec(id='edge-context', version='1', title='Boundary fixture', source='survey_literature',
        mechanism='terminal epoch', evidence=[Evidence(source_url='fixture://edge', source_version='1',
        locator='test', text='Synthetic boundary test; no paper claim.')], recipe=[Step(id='wide',
        unit_id='EEG-EPOCH', op='epoch', implementation_version='2', evidence_indices=[0],
        params={'events':'$events', 'event_id':'$event_id', 'picks':'$eeg_channels', 'tmin':-12., 'tmax':3.})],
        output='wide', lineage={'kind':'literature', 'workflow_id':'fixture', 'branch_id':'edge'})
    output = {'sfreq':160., 'tmin':0., 'tmax':2.}
    space, context, report = build_workflow_space(data, output, refs([method]))
    assert [r['status'] for r in report['methods']] == ['blocked', 'eligible'], report
    entry = next(e for e in seed_entries(space, context) if e['origin']=='literature_adaptation')
    panel = freeze_panel(data, {r.id:r.id for r in data.collection.records}, seed=47, **output)
    run = _execute((tmp_path, data, context, panel, space, [], []), entry)
    assert _assess(run)['selection_ready']
    for config in run[0].records:
        root = run[2]/config.record_id
        descriptor = root/'source-output'/'data.json'
        source = Codec(descriptor.parent).load(json.loads(descriptor.read_text(encoding='utf-8')))
        assert len(source) == 25 and source.tmin == -12
        audit = json.loads((root/'evaluation-adapter.json').read_text(encoding='utf-8'))
        assert audit['restored_boundary_event_indices'] == [0]
        assert config.evaluation_window.source_output in {s.id for s in config.steps}
