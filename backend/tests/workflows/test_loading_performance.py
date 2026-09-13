from types import SimpleNamespace
from unittest.mock import Mock
import json

from app.workflows.service import WorkflowService


def test_summary_listing_does_not_load_stage_outputs(tmp_path):
    service = object.__new__(WorkflowService)
    service.root = tmp_path
    service.get = Mock(side_effect=AssertionError('stage outputs must not be loaded'))
    for identity, owner in [('first', 'owner'), ('private', 'another')]:
        folder = tmp_path / identity
        folder.mkdir()
        (folder / 'workflow.json').write_text(json.dumps({
            'id': identity, 'owner': owner, 'status': 'completed',
            'created_at': '2026-09-13', 'updated_at': '2026-09-13',
            'outputs': {'data_survey': 'missing-output.json'}, 'artifacts': [],
        }))
    assert service.list('owner', summary=True) == [{
        'id': 'first', 'status': 'completed',
        'created_at': '2026-09-13', 'updated_at': '2026-09-13',
    }]
    service.get.assert_not_called()


def test_lightweight_detail_uses_saved_inventory_without_traversing_workers():
    service = object.__new__(WorkflowService)
    saved = [{'name': 'report/report.html', 'sha256': 'saved'}]
    service.get = Mock(return_value={'id': 'run', 'search_id': 'search', 'artifacts': saved})
    service.require_current = Mock()
    service.execution_store = Mock(side_effect=AssertionError('worker scan must not run'))
    summary = dict(id='search', status='running', message='working', usage={}, budget={}, selected_candidate_id=None)
    searches = SimpleNamespace(describe=Mock(return_value=summary))
    service.search_service = Mock(return_value=searches)
    result = service.describe('owner', 'run', include_artifacts=False)
    assert result['artifacts'] == saved
    assert result['search_summary'] == summary
    assert result['execution_control'] == {'allowed': True}
    searches.describe.assert_called_once_with('owner', 'search', False)
    service.execution_store.assert_not_called()
