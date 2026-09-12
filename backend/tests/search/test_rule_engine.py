from copy import deepcopy
import pytest

from app.search.pipeline_space import validate_recipe
from app.search.rule_engine import audit
from app.search.space_contracts import ExplorationSpace
from tests.search.test_pipeline_space import space, recipe  # noqa: F401


def configured(space, **changes):
    value = space.model_dump(mode='json')
    value['priors'] = [dict(id='order', strength='hard', relation='before',
        operators=['reference', 'filter'], condition='same signal ancestry',
        rationale='reference before filter', origin='implementation', **changes)]
    return value


def test_parallel_list_order_does_not_manufacture_signal_order(space, recipe):
    value = configured(space)
    with pytest.raises(ValueError, match='order'):
        validate_recipe(recipe, value)
    recipe['nodes'][1]['input_from'] = 'raw'
    canonical, warnings = validate_recipe(recipe, value)
    assert warnings == []
    assert audit(canonical, ExplorationSpace.model_validate(value))['decisions'][0]['status'] == 'not_applicable'


def test_required_evidence_must_be_an_ancestor_not_an_unrelated_branch(space, recipe):
    value = configured(space)
    value['priors'][0].update(relation='requires', operators=['reference', 'filter'])
    validate_recipe(recipe, value)
    recipe['nodes'][1]['input_from'] = 'raw'
    with pytest.raises(ValueError, match='order'):
        validate_recipe(recipe, value)
    recipe['nodes'][1]['decision_from'] = 'band'
    validate_recipe(recipe, value)


def test_variant_binding_is_explicit_and_version_limited(space, recipe):
    value = configured(space)
    clone = deepcopy(value['operators'][1])
    clone.update(id='hashed-reference', implementation_version='2')
    value['operators'].append(clone)
    recipe['nodes'][1]['operator'] = clone['id']
    # Explicitly opt into the operation and its implementation version.
    value['priors'][0].update(operator_match='unit_operation', implementation_versions=['1', '2'])
    with pytest.raises(ValueError, match='order'):
        validate_recipe(recipe, value)
    value['priors'][0]['implementation_versions'] = ['1']
    validate_recipe(recipe, value)


def test_revocation_retains_evidence_and_changes_frozen_rule_digest(space, recipe):
    value = configured(space, status='revoked', change_reason='Counterevidence invalidates this engineering constraint')
    canonical, warnings = validate_recipe(recipe, value)
    assert warnings == []
    row = audit(canonical, ExplorationSpace.model_validate(value))['decisions'][0]
    assert row['status'] == 'revoked'
    value['priors'][0]['change_reason'] = None
    with pytest.raises(ValueError, match='change reason'):
        ExplorationSpace.model_validate(value)


def test_conflicting_soft_orders_are_both_visible(space, recipe):
    value = configured(space)
    value['priors'][0]['strength'] = 'soft'
    opposite = deepcopy(value['priors'][0])
    opposite.update(id='opposite', operators=['filter', 'reference'])
    value['priors'].append(opposite)
    canonical, warnings = validate_recipe(recipe, value)
    assert [w['prior_id'] for w in warnings] == ['order']
    rows = audit(canonical, ExplorationSpace.model_validate(value))['decisions']
    assert [r['status'] for r in rows] == ['violated', 'satisfied']
    assert rows[0]['conflicts_with'] == ['opposite']
    value['priors'][0]['strength'] = 'hard'
    with pytest.raises(ValueError, match='order'):
        validate_recipe(recipe, value)


def test_direct_source_graph_cannot_bypass_explicit_shared_order_rule():
    from app.search.method_space import basic_space
    from app.search.recipe_compiler import compile_recipe
    method = dict(id='direct-graph', version='1', title='Direct graph fixture', source='classic',
        mechanism='native graph', evidence=[dict(source_url='brainagent:test', source_version='1',
        locator='test', text='Numerical graph fixture')], recipe=[
            dict(id='grid', unit_id='EEG-RESAMPLE', op='resample', implementation_version='2',
                 input='raw', params={'sfreq':160.0,'events':'$events'}, evidence_indices=[0]),
            dict(id='epoch', unit_id='EEG-EPOCH', op='epoch', implementation_version='2',
                 input='grid', params={'tmin':0.0,'tmax':2.0,'events':'$events','event_id':'$event_id','picks':'$eeg_channels'}, evidence_indices=[0])],
        output='epoch', applicability={})
    value = basic_space().model_dump(mode='json')
    entry = dict(schema_version='unit_graph_v2', method=method)
    result = compile_recipe(entry, value, None)
    assert result.lineage['rule_audit']['decisions'][0]['status'] == 'satisfied'
    value['priors'][0]['operators'].reverse()
    with pytest.raises(ValueError, match='continuous-before-epoch'):
        compile_recipe(entry, value, None)
