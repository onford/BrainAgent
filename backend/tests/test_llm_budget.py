import asyncio
import json

import httpx
import pytest

from app.llm.budget import BudgetExceeded, CallBudget, DEFAULT_LIMITS
from app.llm.usage import usage_scope
from tests.test_llm_client import make_client, completion


def test_restart_and_failed_requests_do_not_replenish_budget(tmp_path):
    path = tmp_path / 'budget.json'
    budget = CallBudget(path, {**DEFAULT_LIMITS, 'max_requests': 2})
    first, _ = budget.reserve(100, 'one', 'read')
    budget.complete(first, status='failed')
    CallBudget(path).reserve(100, 'two', 'read')
    with pytest.raises(BudgetExceeded, match='request attempt'):
        CallBudget(path).reserve(100, 'three', 'read')
    with pytest.raises(ValueError, match='limits changed'):
        CallBudget(path, DEFAULT_LIMITS)


@pytest.mark.parametrize('limits,reason', [
    ({'max_input_bytes_per_request': 10}, 'single request'),
    ({'max_input_bytes': 10}, 'cumulative input'),
    ({'max_reserved_output_tokens': 10}, 'reserved output'),
])
def test_limits_reject_without_creating_a_transport_reservation(tmp_path, limits, reason):
    budget = CallBudget(tmp_path / 'budget.json', {**DEFAULT_LIMITS, **limits})
    with pytest.raises(BudgetExceeded, match=reason):
        budget.reserve(100, 'one', 'read')
    assert budget.read()['attempts'] == []


def test_absolute_deadline_survives_restart(tmp_path):
    path = tmp_path / 'budget.json'
    budget = CallBudget(path)
    data = budget.read()
    data['expires_at'] = 0
    path.write_text(json.dumps(data), encoding='utf8')
    with pytest.raises(BudgetExceeded, match='absolute time'):
        CallBudget(path).reserve(100, 'one', 'read')


@pytest.mark.asyncio
async def test_retry_reserves_before_io_and_is_stopped_by_shared_budget(tmp_path, monkeypatch):
    import app.llm.client as client_module
    async def no_delay(_):
        pass
    monkeypatch.setattr(client_module.asyncio, 'sleep', no_delay)
    path = tmp_path / 'budget.json'
    CallBudget(path, {**DEFAULT_LIMITS, 'max_requests': 1})
    requests = []

    def handler(request):
        requests.append(request)
        assert CallBudget(path).read()['attempts'][0]['status'] == 'reserved'
        assert json.loads(request.content)['max_tokens'] == 32768
        return httpx.Response(503)

    with usage_scope(tmp_path / 'survey/calls.json', 'survey', budget_path=path):
        with pytest.raises(BudgetExceeded):
            await make_client(handler).chat([])
    with usage_scope(tmp_path / 'search/calls.json', 'search', budget_path=path):
        with pytest.raises(BudgetExceeded):
            await make_client(handler).chat([])
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_cancellation_keeps_unknown_attempt_and_full_reservation(tmp_path):
    path = tmp_path / 'llm-budget.json'

    def handler(request):
        raise asyncio.CancelledError()

    with usage_scope(tmp_path / 'calls.json', 'cancel'):
        with pytest.raises(asyncio.CancelledError):
            await make_client(handler).chat([])
    row = CallBudget(path).read()['attempts'][0]
    assert row['status'] == 'reserved' and row['usage'] is None
    assert row['reserved_output_tokens'] == 32768


@pytest.mark.asyncio
async def test_actual_usage_preserved_without_claiming_unknown_dollar_cost(tmp_path):
    with usage_scope(tmp_path / 'calls.json', 'success'):
        await make_client(lambda _: completion()).chat([])
    row = CallBudget(tmp_path / 'llm-budget.json').read()['attempts'][0]
    assert row['status'] == 'completed'
    assert row['usage'] == {'prompt_tokens': 123, 'completion_tokens': 45}
    call = json.loads((tmp_path / 'calls.json').read_text(encoding='utf8'))['calls'][0]
    assert call['monetary_cost'] is None
