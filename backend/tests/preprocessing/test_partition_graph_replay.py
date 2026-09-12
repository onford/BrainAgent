from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from app.preprocessing.artifact_codec import Codec, fingerprint
from app.preprocessing.graph_partition import replay_ancestors
from app.preprocessing.graph_runtime import GraphExecutor, Packet
from app.preprocessing.planner import compile_steps
from app.preprocessing.schemas import ArtifactPort, ArtifactValue, DecisionPolicy, Scope
from tests.preprocessing.conftest import make_dataset
from tests.preprocessing.test_graph_v2 import method, raw_fixture, step


def chain(partition='cal'):
    highpass = step('highpass', 'EEG-FILTER', 'filter', dict(l_freq=1., h_freq=35., method='iir', phase='zero', picks=['C3','C4','Cz','Pz']))
    fit = step('first_fit', 'EEG-CCA', 'cca_fit', dict(scope='$scope', reference_id='$reference_id', lags=1),
        adaptation_scope='record_unlabeled', input='highpass')
    selected = ArtifactValue(kind='nonzero', items=[ArtifactValue(kind='less', items=[
        ArtifactValue(kind='port', source=ArtifactPort(step=fit.id, path=['canonical_correlations'])),
        ArtifactValue(kind='literal', value=.9)])])
    clean = step('clean', 'EEG-CCA', 'cca_apply', dict(reference_id='$reference_id', decision_id='fixture-correlation'),
        input='highpass', model_from=fit.id, decision_from=fit.id, parameter_inputs={'exclude':selected},
        decision=DecisionPolicy(mode='accept_candidates', reason='Synthetic correlation threshold'))
    second = step('second_fit', 'EEG-ICA', 'ica_fit', dict(scope='$scope', reference_id='$reference_id',
        method='fastica', n_components=2, seed=17, max_iter=1000), input='clean',
        fit_scope=Scope(role='calibration', ids=[partition]))
    return [highpass, fit, clean, second]


def test_fitted_models_and_diagnostic_ports_recompute_inside_nonzero_partition(tmp_path):
    raw, events = raw_fixture()
    original = Packet(raw, events, np.arange(4), ['a','b','c','d'], 'acquisition')
    record = SimpleNamespace(id='r', sfreq=200., intervals=[SimpleNamespace(id='cal', start=500, stop=2500, role='calibration')])
    changed = deepcopy(original)
    changed.data._data[:, :500] += np.random.default_rng(9).normal(0, .001, (4, 500))
    changed.data._data[:, 2500:] += np.random.default_rng(8).normal(0, .001, (4, 1500))
    engines = []
    for name, packet in [('original', original), ('outside_changed', changed)]:
        engine = GraphExecutor(record, chain(), packet, tmp_path/name)
        for operation in engine.steps.values():
            engine.execute(operation)
        engines.append(engine)
    first, second = engines
    assert fingerprint(first.nodes['first_fit']['model']) != fingerprint(second.nodes['first_fit']['model'])
    assert fingerprint(first.nodes['second_fit']['model']) == fingerprint(second.nodes['second_fit']['model'])
    assert first.nodes['second_fit']['packet'].event_indices.tolist() == [1, 2]
    logs = [log for log in first.logs if log['branch']=='fit_replay']
    assert [log['step_id'] for log in logs] == ['highpass', 'first_fit', 'clean']
    assert logs[1]['model_binding']['scope'] == {'role':'calibration', 'ids':['cal']}
    first_params = Codec(tmp_path/'original/fit-replay-second_fit/clean').load(logs[2]['parameters'])
    second_params = Codec(tmp_path/'outside_changed/fit-replay-second_fit/clean').load(second.logs[-2]['parameters'])
    assert first_params['exclude'] == second_params['exclude']
    assert first.logs[-1]['partition_replay']['external_fitted_state_reused'] is False
    assert first.logs[-1]['partition_replay']['partition']['start'] == 500
    # The original graph's full-record model remains intact alongside the
    # separately serialized model recomputed for the target partition.
    assert first.nodes['first_fit']['binding']['scope']['ids'] != ['cal']


def test_planner_accepts_stateful_automatic_dependency_closure(tmp_path):
    data = make_dataset(tmp_path/'bids')
    compiled = compile_steps(method(chain('calibration')), data.collection.records[0], data, {})
    assert [s.id for s in compiled] == ['highpass', 'first_fit', 'clean', 'second_fit']


def test_partition_closure_never_rebinds_other_explicit_scope_or_manual_decision():
    operations = chain()
    operations[1].adaptation_scope = 'none'
    operations[1].fit_scope = Scope(role='train', ids=['other'])
    with pytest.raises(ValueError, match='different explicit fit partition'):
        replay_ancestors(operations[-1], operations[:-1])
    operations = chain()
    operations[2].decision = DecisionPolicy(mode='manual', status='confirmed', reason='Full-record decision')
    with pytest.raises(ValueError, match='manual decision'):
        replay_ancestors(operations[-1], operations[:-1])


def test_parameter_only_dependency_is_part_of_partition_closure():
    operations = chain()
    target = operations[-1].model_copy(deep=True)
    target.input = 'raw'
    target.parameter_inputs['seed'] = ArtifactValue(kind='port', source=ArtifactPort(step='clean', path=['exclude']))
    # Structural closure only; the numerical seed contract still rejects a list.
    assert [s.id for s in replay_ancestors(target, operations[:-1])] == ['highpass', 'first_fit', 'clean']


def test_partition_replay_is_persisted_through_planner_and_worker(tmp_path):
    import json
    from app.preprocessing.schemas import PlanRequest
    from app.preprocessing.service import PreprocessingService
    from app.preprocessing.worker import Worker
    from app.preprocessing.runner import verify_result
    data = make_dataset(tmp_path/'bids')
    service = PreprocessingService(tmp_path/'out', [tmp_path/'bids'])
    inp = service.register_input('fixture', data)
    ref = service.register_method('fixture', method(chain('calibration')))
    planned, _ = service.plan('fixture', PlanRequest(input_ref=inp, methods=[ref], mode='validation'))
    service.submit('fixture', planned)
    result = Worker(service.store, service.allowed_roots).run_once()
    assert result.status == 'completed', result.model_dump()
    for item in result.records:
        assert verify_result(service.store.root, item['result'])
        artifacts = {a['name']:service.store.root/a['path'] for a in item['result']['artifacts']}
        context = json.loads(artifacts['fit-replay-second_fit/context.json'].read_text(encoding='utf-8'))
        assert context['ancestor_step_ids'] == ['highpass', 'first_fit', 'clean']
        provenance = json.loads(artifacts['provenance.json'].read_text(encoding='utf-8'))
        assert len([log for log in provenance['steps'] if log['branch']=='main']) == 4
        assert len([log for log in provenance['steps'] if log['branch']=='fit_replay']) == 3
        assert item['result']['delta']['events_retained'] == 4
