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


def test_soft_exception_requires_known_condition_and_preserves_evidence(space, recipe):
    value = configured(space)
    source = 'fixture-source'
    value['evidence'][source] = dict(source_url='fixture://exception', source_version='1',
        locator='Synthetic test', text='A test of conditional control, not scientific evidence.')
    value['priors'][0].update(strength='soft', exceptions=[dict(id='erp-context',
        when=[dict(scope='context', key='task', comparison='eq', value='erp')],
        reason='Synthetic conditional exception', evidence_ids=[source])])
    frozen = ExplorationSpace.model_validate(value)
    canonical, warnings = validate_recipe(recipe, frozen, {'task':'erp'})
    assert not warnings
    row = audit(canonical, frozen, {'task':'erp'})['decisions'][0]
    assert row['status']=='exception_applies' and row['exceptions'][0]['evidence_ids']==[source]
    _, warnings = validate_recipe(recipe, frozen, {})
    assert warnings and audit(canonical, frozen, {})['decisions'][0]['exceptions'][0]['applies'] is None
    value['priors'][0]['strength']='hard'
    with pytest.raises(ValueError, match='cannot disable hard constraints'):
        ExplorationSpace.model_validate(value)


def test_requires_incompatible_conflict_keeps_hard_precedence(space, recipe):
    value = configured(space)
    value['priors'][0].update(relation='requires', operators=['reference','filter'])
    opposite = deepcopy(value['priors'][0])
    opposite.update(id='avoid-filter', strength='soft', relation='incompatible')
    value['priors'].append(opposite)
    canonical, warnings = validate_recipe(recipe, value)
    result = audit(canonical, ExplorationSpace.model_validate(value))
    assert result['conflict_sets'][0]['resolution']=='hard_constraint_precedence'
    assert result['conflict_sets'][0]['hard_rule_ids']==['order']
    assert [w['prior_id'] for w in warnings]==['avoid-filter']
    value['priors'][1]['strength']='hard'
    with pytest.raises(ValueError, match='avoid-filter'):
        validate_recipe(recipe, value)


def test_absent_trigger_does_not_turn_unknown_condition_into_a_blocker(space, recipe):
    value = configured(space)
    value['priors'][0]['when']=[dict(scope='context',key='unobserved',comparison='eq',value=True)]
    # Epoch exists, but this rule's trigger reference is absent.
    recipe['nodes'] = [n for n in recipe['nodes'] if n['operator']!='reference']
    canonical, warnings = validate_recipe(recipe, value)
    assert not warnings
    assert audit(canonical, ExplorationSpace.model_validate(value))['decisions'][0]['status']=='not_applicable'


def test_fixed_bindings_distinguish_declared_null_from_unresolved_runtime_tokens(space, recipe):
    value = configured(space)
    value['operators'][0]['bindings'] = {'h_freq':None}
    value['priors'][0].update(relation='parameter_condition', operators=['filter'],
        requirements=[dict(scope='parameter',operator='filter',key='h_freq',comparison='eq',value=None)])
    canonical, warnings = validate_recipe(recipe, value)
    assert not warnings
    assert audit(canonical, ExplorationSpace.model_validate(value))['decisions'][0]['status']=='satisfied'
    value['operators'][0]['bindings']['h_freq']='$unknown_cutoff'
    with pytest.raises(ValueError, match='必要参数条件'):
        validate_recipe(recipe, value)
    value['operators'][0]['bindings']['h_freq']=30.
    with pytest.raises(ValueError, match='order'):
        validate_recipe(recipe, value)


def test_incompatible_numeric_requirements_record_the_actual_variable(space, recipe):
    value = configured(space)
    rule = value['priors'][0]
    rule.update(strength='soft',relation='parameter_condition',operators=['filter'],
        requirements=[dict(scope='parameter',operator='filter',key='low',comparison='gt',value=10.)])
    opposite = deepcopy(rule)
    opposite.update(id='low-cutoff',requirements=[dict(scope='parameter',operator='filter',key='low',comparison='le',value=5.)])
    value['priors'].append(opposite)
    canonical, warnings = validate_recipe(recipe,value)
    result = audit(canonical, ExplorationSpace.model_validate(value))
    conflict, = result['conflict_sets']
    variable, = conflict['parameter_conflicts']
    assert variable['node_id']=='band' and variable['key']=='low'
    assert conflict['resolution']=='diagnostic_or_explicit_challenge_required'
    assert len(warnings)==2


@pytest.mark.parametrize('clauses,expected', [
    ([('ge',1),('le',1)],False), ([('gt',1),('le',1)],True),
    ([('ge',1),('le',1),('ne',1)],True), ([('eq','iir'),('eq','fir')],True),
    ([('in',[1,2]),('gt',2)],True), ([('in',[1,2]),('ge',2)],False),
    ([('gt','unknown'),('le',1)],False),
])
def test_parameter_conflict_proof_handles_open_bounds_and_finite_choices(clauses, expected):
    from app.search.rule_conflicts import impossible
    assert impossible([dict(comparison=op,value=value) for op,value in clauses]) is expected
