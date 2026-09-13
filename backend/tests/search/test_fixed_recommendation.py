"""The model can recommend initially; numerical feedback never reopens the plan."""
from copy import deepcopy
import pytest

from app.search.catalog import BASELINE_ID
from app.search.contracts import InitialSchedule, SearchBudget, SearchRequest
from app.search.io import read, write
from app.search.method_space import basic_space, seed_entries, verify_registry
from app.search.service import IntegrityFailure, SearchService
from tests.search.test_controller import factory, run  # noqa: F401


@pytest.mark.parametrize('strategy', ['adaptive', 'random', 'exhaustive'])
def test_retired_strategies_rejected(strategy):
    with pytest.raises(ValueError):
        SearchRequest(workflow_id='a' * 32, strategy=strategy)


@pytest.mark.parametrize('field', ['max_proposals', 'max_evidence_reads', 'max_diagnostics'])
def test_retired_controller_budgets_rejected(field):
    with pytest.raises(ValueError):
        SearchBudget.model_validate({field: 1})


def test_recommendation_cannot_carry_recipe_edits():
    with pytest.raises(ValueError):
        InitialSchedule(candidate_ids=[], reason='change', edits=[{'action': 'remove_operator'}])
    assert not hasattr(SearchService, 'candidate_action')
    assert not hasattr(SearchService, 'diagnostic_action')
    assert not hasattr(SearchService, 'model_action')


@pytest.mark.asyncio
async def test_invalid_initial_budget_retries_before_any_numerical_execution(factory):
    service, llm, initial = factory([
        {'candidate_ids': ['basic-broadband', 'basic-acquisition-reference'], 'reason': 'Too many'},
        {'candidate_ids': ['basic-broadband'], 'reason': 'Fits remaining initial slot'},
    ], max_candidates=2)
    result = await run(service, initial)
    assert result['status'] == 'completed', result.get('error')
    assert [a['status'] for a in result['actions']] == ['failed', 'completed']
    assert all('results' not in c and c['max_additional_candidates'] == 1 for c in llm.contexts)
    assert service.executed == [BASELINE_ID, 'basic-broadband']
    assert result['usage']['retries'] == 1


@pytest.mark.parametrize('scores', [(.2, .9), (.9, .2)])
@pytest.mark.asyncio
async def test_opposite_measurements_do_not_change_frozen_order(factory, scores):
    ids = ['basic-broadband', 'basic-acquisition-reference']
    service, llm, initial = factory([{'candidate_ids': ids, 'reason': 'Initial evidence'}], max_candidates=3)
    service.scores = dict(zip(ids, scores))
    result = await run(service, initial)
    assert result['status'] == 'completed', result.get('error')
    assert service.executed == [BASELINE_ID, *ids]
    assert len(llm.contexts) == 1
    assert not {'results', 'diagnostics', 'feedback', 'actions', 'history'} & llm.contexts[0].keys()
    assert result['schedule'] == ids == result['recommendation']['candidate_ids']
    assert result['registry'] == initial['registry']
    assert [a['action'] for a in result['actions']] == ['initial_recommendation']


@pytest.mark.asyncio
async def test_resume_reuses_recommendation_after_partial_execution(factory):
    ids = ['basic-broadband', 'basic-acquisition-reference']
    service, llm, initial = factory([{'candidate_ids': ids, 'reason': 'Frozen once'}])
    original = service.candidate
    async def interrupt(state, identity):
        if identity == ids[0]:
            import asyncio
            raise asyncio.CancelledError()
        return await original(state, identity)
    service.candidate = interrupt
    result = await run(service, initial)
    assert result['status'] == 'interrupted'
    assert service.executed == [BASELINE_ID]
    frozen = deepcopy(result['recommendation'])
    service.candidate = original
    result = await run(service, initial)
    assert result['status'] == 'completed', result.get('error')
    assert len(llm.contexts) == 1 and result['recommendation'] == frozen
    assert service.executed == [BASELINE_ID, *ids]


@pytest.mark.asyncio
async def test_recovery_reuses_completed_initial_call_before_projection_publication(factory):
    service, llm, initial = factory()
    saved = service.get('owner', initial['id'])
    service.action(saved, 'initial_recommendation', status='completed',
                   result={'candidate_ids': ['basic-broadband'], 'reason': 'Saved before crash'})
    result = await run(service, initial)
    assert result['status'] == 'completed', result.get('error')
    assert llm.contexts == []
    assert service.executed == [BASELINE_ID, 'basic-broadband']
    assert result['recommendation']['reason'] == 'Saved before crash'


@pytest.mark.asyncio
async def test_retired_protocol_cannot_resume(factory):
    service, _, initial = factory()
    saved = service.get('owner', initial['id'])
    saved['protocol']['version'] = '3'
    saved['status'] = 'interrupted'
    service.save(saved)
    before = (service.folder(initial['id']) / 'search.json').read_bytes()
    with pytest.raises(ValueError, match='只读'):
        service.retry('owner', initial['id'])
    assert (service.folder(initial['id']) / 'search.json').read_bytes() == before
    assert not service.executed


@pytest.mark.parametrize('damage', ['schedule', 'recipe', 'file', 'missing_file'])
@pytest.mark.asyncio
async def test_frozen_execution_rejects_tampering(factory, damage):
    service, llm, initial = factory()
    result = await run(service, initial)
    path = service.folder(result['id']) / 'initial-recommendation.json'
    if damage == 'schedule': result['schedule'] = ['basic-broadband']
    elif damage == 'recipe': result['registry'][0]['recipe']['nodes'][0]['parameters']['invented'] = 1
    elif damage == 'file': write(path, {**read(path), 'reason': 'revised after feedback'})
    else: path.unlink()
    with pytest.raises((IntegrityFailure, FileNotFoundError)):
        service.verify_recommendation(result)
    with pytest.raises((IntegrityFailure, FileNotFoundError)):
        await service.candidate(result, BASELINE_ID)
    assert len(llm.contexts) == 1


@pytest.mark.parametrize('change', ['append', 'parameters', 'drop'])
def test_catalog_is_complete_and_immutable(change):
    space = basic_space().model_dump(mode='json')
    registry = seed_entries(space)
    verify_registry({'space': space}, registry)
    if change == 'append': registry.append(deepcopy(registry[0]))
    elif change == 'drop': registry.pop()
    else: registry[0]['recipe']['nodes'][0]['parameters']['invented'] = 1
    with pytest.raises(ValueError): verify_registry({'space': space}, registry)


@pytest.mark.asyncio
async def test_model_cannot_use_shadow_plan_or_replan_from_measurements():
    from app.agents.data_preprocessing.agent import DataPreprocessingAgent
    from app.runtime.context import AgentContext, AgentTask
    from app.runtime.result import AgentResult
    agent = DataPreprocessingAgent(service=object())
    context = AgentContext(session_id='s', owner_id='o', user_message='Inspect results')
    rejected = await agent.run(AgentTask(instruction='change', inputs={'action': 'shadow_plan'}), context)
    assert rejected.output['execution_status'] == 'needs_input'
    context.record_result(AgentResult(agent_name='data_evaluation', success=True, output={'score': .3}))
    rejected = await agent.run(AgentTask(instruction='change', inputs={'action': 'plan'}), context)
    assert '不能' in rejected.output['blocking_reason']
