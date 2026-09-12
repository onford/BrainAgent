import pytest

from app.llm.budget import BudgetExceeded, CallBudget, DEFAULT_LIMITS
from app.preprocessing.service import PreprocessingService
from app.workflows.schemas import WorkflowRequest
from app.workflows.service import WorkflowService


def test_new_workflow_freezes_model_deadline_and_retry_cannot_renew_it(tmp_path, monkeypatch):
    clock = [1000.]
    monkeypatch.setattr('app.llm.budget.time', lambda: clock[0])
    source = tmp_path / 'source'
    source.mkdir()
    service = WorkflowService(tmp_path / 'flows', [source], PreprocessingService(tmp_path / 'prep'))
    request = WorkflowRequest(source_root=str(source), model_budget_seconds=43200)
    state = service.create('owner', request, start=False)
    path = service.folder(state['id']) / 'llm-budget.json'
    budget = CallBudget(path)
    assert budget.read()['limits'] == {**DEFAULT_LIMITS, 'max_seconds': 43200}
    assert budget.read()['expires_at'] == 44200.
    budget.reserve(123, 'first', 'survey')
    frozen = path.read_bytes()
    state['status'] = 'failed'
    service.save(state)
    # Retry's execution start is suppressed; the real retry/format/lock path
    # must leave the complete persistent budget bytes unchanged.
    monkeypatch.setattr(service, 'start', lambda *args: None)
    service.retry('owner', state['id'])
    assert path.read_bytes() == frozen
    clock[0] = 44201.
    with pytest.raises(BudgetExceeded, match='absolute time'):
        CallBudget(path).reserve(123, 'after-numerical-wait', 'search')
    assert len(CallBudget(path).read()['attempts']) == 1
    with pytest.raises(ValueError, match='limits changed'):
        CallBudget(path, {**DEFAULT_LIMITS, 'max_seconds': 86400})


@pytest.mark.parametrize('seconds', [0, -1, 604801])
def test_model_deadline_requires_bounded_positive_seconds(seconds):
    with pytest.raises(ValueError):
        WorkflowRequest(source_root='source', model_budget_seconds=seconds)
