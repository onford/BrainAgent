"""Copy a completed, verified workflow into an existing local service store.

No execution is started, no source paths/state are rewritten, and existing IDs
are never overwritten. The source must remain available for provenance paths.
The workflow is made visible only after both complete trees are verified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def identifier(value):
    require(isinstance(value, str) and re.fullmatch('[a-f0-9]{32}', value), 'Invalid workflow/search ID')
    return value


def inventory(root):
    result = {}
    directories = [root]
    while directories:
        for path in sorted(directories.pop().iterdir()):
            require(not path.is_symlink() and not path.is_junction(), 'Linked source entries are not portable')
            require(path.resolve().is_relative_to(root), 'Source entry escapes its root')
            if path.is_dir():
                directories.append(path)
            elif path.is_file():
                require(not path.name.endswith(('-wal', '-shm')), 'SQLite sidecars remain; source is not quiescent')
                result[path.relative_to(root).as_posix()] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
    return result


def import_completed(run, destination, expected_build, owner, output):
    run, destination = run.resolve(strict=True), destination.resolve(strict=True)
    require(not run.is_relative_to(destination) and not destination.is_relative_to(run), 'Source and destination must be disjoint')
    output = output.resolve()
    require(not output.is_relative_to(run) and not output.is_relative_to(destination), 'Receipt must be outside source and destination stores')
    require(not output.exists(), 'Preserve existing import receipt')
    require(not output.with_suffix('.tmp').exists(), 'Preserve existing temporary receipt')
    result = read(run / 'result.json')
    require(result.get('status') == 'completed' and result.get('mechanical_gate_passed') is True,
            'Source workflow has not completed its mechanical acceptance')
    require(all(result.get(key) is True for key in ('original_data_unchanged', 'code_unchanged_during_run', 'driver_unchanged_during_run')),
            'Source integrity acceptance missing')
    workflow_id, search_id = identifier(result['workflow_id']), identifier(result['search_id'])
    source_workflow, source_search = run / 'workflows' / workflow_id, run / 'offline-search' / search_id
    for path in (source_workflow, source_search):
        require(path.resolve().is_relative_to(run) and not path.is_symlink() and not path.is_junction(), 'Linked source root is not portable')
    workflow, search = read(source_workflow / 'workflow.json'), read(source_search / 'search.json')
    require(workflow['id'] == workflow_id and workflow['search_id'] == search_id and search['id'] == search_id
            and search['workflow_id'] == workflow_id, 'Workflow/search identity mismatch')
    require(workflow['status'] == search['status'] == 'completed', 'Source is still active')
    require(workflow['owner'] == search['owner'] == owner, 'Destination owner mismatch')
    require(workflow.get('execution_build') == expected_build, 'Destination execution build mismatch')
    target_workflow, target_search = destination / 'workflows' / workflow_id, destination / 'offline-search' / search_id
    for parent in (target_workflow.parent, target_search.parent):
        require(parent.is_dir() and parent.resolve().is_relative_to(destination)
                and not parent.is_symlink() and not parent.is_junction(), 'Destination store must be an existing unlinked directory')
    require(not target_workflow.exists() and not target_search.exists(), 'Destination ID exists; never overwrite')
    staging = destination / ('.completed-import-' + workflow_id)
    require(not staging.exists(), 'Previous import staging exists; preserve it for review')
    before = {'workflow': inventory(source_workflow), 'search': inventory(source_search)}
    required_bytes = sum(v['bytes'] for rows in before.values() for v in rows.values())
    require(shutil.disk_usage(destination).free > required_bytes + 1024 ** 3, 'Insufficient free space for verified copies')
    staging.mkdir()
    receipt = {'status': 'copying', 'workflow_id': workflow_id, 'search_id': search_id,
               'source': str(run), 'destination': str(destination), 'execution_build': expected_build,
               'original_paths_preserved': True, 'execution_started': False, 'final_core_acceptance': False,
               'inventory': before, 'published': []}
    output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        temporary = output.with_suffix('.tmp')
        temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(output)

    save()
    try:
        for name, source in [('workflow', source_workflow), ('search', source_search)]:
            shutil.copytree(source, staging / name)
            require(inventory(staging / name) == before[name], 'Copied bytes differ: ' + name)
        require(inventory(source_workflow) == before['workflow'] and inventory(source_search) == before['search'],
                'Source changed during copy; do not publish')
        require(not target_workflow.exists() and not target_search.exists(), 'Destination ID appeared during copy')
        # Publish dependency first. A failed second rename leaves an explicitly
        # recorded orphan search, never an incomplete visible workflow.
        (staging / 'search').rename(target_search)
        receipt['published'].append('search')
        save()
        (staging / 'workflow').rename(target_workflow)
        receipt['published'].append('workflow')
        receipt.update(status='copied_and_verified', source_unchanged=True,
                       remaining='Verify actual service API, page rendering and artifact downloads')
        staging.rmdir()
    except Exception as exc:
        receipt.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        save()
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--service-build-receipt', type=Path, required=True,
                        help='Fresh GET /api/build-info response from the actual destination')
    parser.add_argument('--owner', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = import_completed(args.run, args.destination, read(args.service_build_receipt)['execution_build'], args.owner, args.output)
    print(report['status'], report['workflow_id'])
