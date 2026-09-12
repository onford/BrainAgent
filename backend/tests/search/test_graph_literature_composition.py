from copy import deepcopy
import pytest
from app.search.literature_space import build_workflow_space, check_execution
from app.search.method_space import seed_entries, edited_entry, verify_registry
from app.search.recipe_compiler import compile_recipe
from app.preprocessing.schemas import MethodSpec
from tests.search.test_literature_space import branch, extract, refs, OUTPUT
from tests.preprocessing.conftest import make_dataset


def test_graph_compositions_retain_source_parents_and_ports(tmp_path):
    data=make_dataset(tmp_path/'bids', subjects=3)
    a=branch(); b=branch('erp',1,.5,20.)
    for source in (a,b):
        for step in source['method']['recipe']:step['implementation_version']='2'
    space,context,report=build_workflow_space(data,OUTPUT,refs(extract(data,[a,b])))
    assert all(r['status']=='eligible' for r in report['methods']),report
    entries=seed_entries(space,context);donors={e['id']:e for e in entries}
    papers=[e for e in entries if e['origin']=='literature']
    basic=next(e for e in entries if e['id']=='basic-acquisition-reference')
    for parent in (basic,papers[1]):
        anchor=parent['recipe'].get('output') or parent['recipe']['nodes'][-1]['id']
        combined=edited_entry(parent,[dict(action='combine_fragment',donor_id=papers[0]['id'],node_ids=['car'],after_node_id=anchor)],
            space,title='Test-only source composition',order=len(entries),context=context,donors=donors)
        method=compile_recipe(combined,space,{'output_contract':OUTPUT},context)
        check_execution(method,data,OUTPUT)
        assert method.recipe[-1].id==method.output
        assert len(combined['parent_ids'])==2
        assert all(s.implementation_version=='2' for s in method.recipe)
        verify_registry({'space':space.model_dump(),'space_context':context},entries+[combined])


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
