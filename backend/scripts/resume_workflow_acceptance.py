"""Resume an interrupted formal run in its original frozen runtime.

No new workflow, candidate injection, budget reset or numerical override.
The failed driver receipt is preserved; recovery evidence lives separately.
"""
import argparse
import asyncio
import json
from pathlib import Path

import httpx

from app.core.config import Settings
from app.main import create_app
from app.preprocessing.storage import file_hash
from app.search.io import read, write
from app.search.method_provenance import participation
from scripts.release_workflow_acceptance import code_hashes, source_scope


async def poll(client, identity, *, attempts=9):
    """Retry only the observed transient snapshot-read response, never bad JSON."""
    errors = []
    for attempt in range(attempts):
        response = await client.get(f'/api/workflows/{identity}')
        if response.status_code == 422:
            detail = response.json().get('detail')
            transient = (isinstance(detail, str) and '[Errno 13] Permission denied:' in detail
                         and ('search.json' in detail or 'workflow.json' in detail))
            if transient and attempt + 1 < attempts:
                errors.append(detail)
                await asyncio.sleep(min(.02 * 2**attempt, .25))
                continue
        response.raise_for_status()
        return response.json(), errors
    raise AssertionError('unreachable')


async def main(args):
    root = Path(args.run).resolve(strict=True)
    output = Path(args.output).resolve()
    if output.exists() or output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError('Recovery audit must be a new directory disjoint from the run')
    design = read(root / 'design.json')
    identity = read(root / 'active.json')['workflow_id']
    folder = root / 'workflows' / identity
    state = read(folder / 'workflow.json')
    if state['status'] != 'interrupted' or not state.get('search_id'):
        raise ValueError('Recovery requires an interrupted existing numerical workflow')
    search_root = root / 'offline-search' / state['search_id']
    search_before = read(search_root / 'search.json')
    budget_path = folder / 'llm-budget.json'
    budget_before = read(budget_path)
    import app
    code_root = Path(app.__file__).resolve().parent
    before_code = code_hashes(code_root)
    if before_code != design['code_hashes']:
        raise ValueError('Use the ORIGINAL frozen application, not an updated implementation')
    source = Path(state['request']['source_root']).resolve(strict=True)
    source_before, scope = source_scope(source, output, design['selected_participants'])
    if source_before != design['source_hashes']:
        raise ValueError('Original source data changed since fresh workflow creation')
    original_result = file_hash(root / 'result.json')
    old_models = {str(p.relative_to(root)): file_hash(p)
                  for p in search_root.glob('candidates/*/assessment/*/utility/eegnet/**/*.pt')}
    driver_before = file_hash(Path(__file__))
    output.mkdir(parents=True)
    for name, value in [('workflow-before', state), ('search-before', search_before),
                        ('model-budget-before', budget_before), ('failed-driver-result', read(root / 'result.json'))]:
        write(output / (name + '.json'), value)
    write(output / 'design.json', dict(entry='Original create_app lifespan resumes the existing interrupted workflow; formal GET polling',
        workflow_id=identity, run_root=str(root), original_code_root=str(code_root),
        original_failure_sha256=original_result, original_checkpoints=old_models,
        budget_limits=budget_before['limits'], model_expires_at=budget_before['expires_at'],
        search_deadline=search_before['deadline'], source_scope=scope,
        driver_sha256=driver_before, dependency_overrides=[], numerical_overrides=[]))
    settings = Settings(_env_file=args.config).model_copy(update={
        'workflow_root':str(root / 'workflows'), 'preprocessing_root':str(root / 'methods'),
        'log_dir':root / 'logs', 'db_create_tables':False,
        'database_url_override':args.database_url})
    if not settings.llm_api_key:
        raise ValueError('Original configured provider is required')
    result = dict(status='failed', acceptance_passed=False, workflow_id=identity,
                  transient_poll_errors=[])
    application = create_app(settings)
    try:
        async with application.router.lifespan_context(application):
            task = application.state.workflows.tasks.get(identity)
            if task is None:
                raise ValueError('Original application did not admit this interrupted run for resume')
            print('RESUMED', identity, flush=True)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                    base_url='http://brainagent.local', timeout=180) as client:
                while not task.done():
                    await asyncio.wait({task}, timeout=15)
                    described, errors = await poll(client, identity)
                    result['transient_poll_errors'].extend(errors)
                    print('POLL', described['status'], flush=True)
                described, errors = await poll(client, identity)
                result['transient_poll_errors'].extend(errors)
                result['status'] = described['status']
                search = read(search_root / 'search.json')
                result['literature_participation'] = participation(search)
                result['selected_candidate_id'] = search.get('selected_candidate_id')
                result['mechanical_gate_passed'] = bool(described['status'] == 'completed'
                    and result['literature_participation']['substantive_literature_evaluated_ids'])
                result['review_required'] = 'Source semantics, subsequent model use, winner and delivery audits remain required.'
    except Exception as exc:
        result['failure'] = f'{type(exc).__name__}: {exc}'
        if isinstance(exc, httpx.HTTPStatusError):
            result['http_error_detail'] = exc.response.text[:8000]
    finally:
        after_budget = read(budget_path)
        after_search = read(search_root / 'search.json')
        result['original_budget_preserved'] = (
            all(after_budget[k] == budget_before[k] for k in ['limits', 'started_at', 'expires_at'])
            and after_budget['attempts'][:len(budget_before['attempts'])] == budget_before['attempts']
            and after_search['deadline'] == search_before['deadline']
            and after_search['budget'] == search_before['budget'])
        result['original_failure_receipt_unchanged'] = file_hash(root / 'result.json') == original_result
        result['original_checkpoints_unchanged'] = all(file_hash(root / name) == sha for name, sha in old_models.items())
        result['code_unchanged'] = code_hashes(code_root) == before_code
        result['driver_unchanged'] = file_hash(Path(__file__)) == driver_before
        after_source, _ = source_scope(source, output, design['selected_participants'])
        result['original_data_unchanged'] = after_source == source_before
        write(output / 'result.json', result)
        print('RESULT', result['status'], result.get('mechanical_gate_passed', False), flush=True)
    return 0 if result.get('mechanical_gate_passed') and all(result[k] for k in [
        'original_budget_preserved', 'original_failure_receipt_unchanged',
        'original_checkpoints_unchanged', 'code_unchanged', 'driver_unchanged',
        'original_data_unchanged']) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['run', 'output', 'config', 'database-url']:
        parser.add_argument('--' + name, required=True)
    raise SystemExit(asyncio.run(main(parser.parse_args())))
