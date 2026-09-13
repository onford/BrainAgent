"""Audit a finished profile run without borrowing historical real-data evidence.

Writes a reviewable matrix and capability evidence into a new directory only.
It never updates the service registry. Missing and failed profiles stay visible.
"""
import argparse
import json
from pathlib import Path

from app.preprocessing.storage import file_hash, write_json
from app.preprocessing.units import engine_hash, environment
from app.preprocessing.units.operations_v2 import inventory


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit(profiles, validation_script, output):
    profiles = Path(profiles).resolve(strict=True)
    validation_script = Path(validation_script).resolve(strict=True)
    output = Path(output).resolve()
    require(not output.exists(), 'Audit output must be a new directory')
    require(not output.is_relative_to(profiles) and not profiles.is_relative_to(output),
            'Audit output must be disjoint from profile evidence')
    rows = inventory()
    by_identity = {row['identity']: row for row in rows}
    require(len(rows) == len(by_identity), 'Duplicate inventory identity')
    current_engine, current_environment = engine_hash(), environment()
    script_sha = file_hash(validation_script)
    tracked = {validation_script: script_sha}

    def checked(path, expected=None, size=None):
        path = Path(path).resolve(strict=True)
        require(path.is_relative_to(profiles), 'Receipt artifact is outside profile evidence')
        actual = file_hash(path)
        require(expected is None or actual == expected, 'Receipt artifact checksum mismatch')
        require(size is None or path.stat().st_size == size, 'Receipt artifact size mismatch')
        require(path not in tracked or tracked[path] == actual, 'Evidence changed during audit')
        tracked[path] = actual
        return path

    index = json.loads(checked(profiles / 'results.json').read_text(encoding='utf-8'))
    require(index['total_inventory'] == len(rows), 'Inventory denominator differs from run')
    indexed = index['results']
    require(index['attempted'] == len(indexed), 'Attempted count differs from result index')
    require(index['passed'] == sum(r['status'] == 'passed' for r in indexed),
            'Passed count differs from result index')
    require(len({r['identity'] for r in indexed}) == len(indexed), 'Duplicate indexed identity')
    indexed = {r['identity']: r for r in indexed}
    evidence, receipts = {}, []
    for path in sorted(profiles.glob('*/receipt.json')):
        receipt = json.loads(checked(path).read_text(encoding='utf-8'))
        identity = receipt['identity']
        require(identity in by_identity, 'Receipt identity is outside current inventory')
        require(identity not in evidence, 'Duplicate profile receipt')
        require(indexed.get(identity) == receipt, 'Result index and individual receipt differ')
        require(receipt['status'] in ('passed', 'failed'), 'Unknown profile status')
        require(receipt['engine_sha256'] == current_engine, 'Stale engine evidence')
        require(receipt['environment'] == current_environment, 'Runtime differs from profile evidence')
        require(receipt['validation_script_sha256'] == script_sha, 'Validation script differs')
        source_sha = by_identity[identity]['source']['source']['code_sha256']
        require(receipt['source_sha256'] == source_sha, 'Stale source evidence')
        require(bool(receipt.get('files')), 'Profile receipt has no runtime artifacts')
        seen_files = set()
        for asset in receipt['files']:
            resolved = checked(profiles / asset['path'], asset['sha256'], asset['bytes'])
            require(resolved not in seen_files, 'Duplicate artifact entry')
            seen_files.add(resolved)
        passed = receipt['status'] == 'passed'
        flags = ('compiled_graph', 'executed', 'numerical_verified', 'boundary_passed')
        require(not passed or all(receipt.get(k) is True for k in flags),
                'Passed profile lacks required verification evidence')
        evidence[identity] = dict(
            source_sha256=source_sha, engine_sha256=current_engine,
            compiled_passed=passed and receipt.get('compiled_graph') is True,
            execution_passed=passed and receipt.get('executed') is True,
            numerical_passed=passed and receipt.get('numerical_verified') is True,
            boundary_passed=passed and receipt.get('boundary_passed') is True,
            real_data_passed=False, real_receipts=[], status=receipt['status'],
            receipt=str(path.resolve()), receipt_sha256=tracked[path.resolve()],
            numerical_basis=receipt.get('numerical_basis'),
            max_abs_error=receipt.get('max_abs_error'), failure=receipt.get('error'))
        receipts.append(dict(identity=identity, path=str(path.resolve()),
                             sha256=tracked[path.resolve()], status=receipt['status']))
    require(set(indexed) == set(evidence), 'Result index has missing profile receipts')
    for identity, row in by_identity.items():
        if identity not in evidence:
            evidence[identity] = dict(source_sha256=row['source']['source']['code_sha256'],
                engine_sha256=current_engine, compiled_passed=False, execution_passed=False,
                numerical_passed=False, boundary_passed=False, real_data_passed=False,
                real_receipts=[], status='not_executed', failure='No current profile receipt')
    counts = dict(profiles=len(rows), attempted=len(receipts),
                  passed=sum(e['status'] == 'passed' for e in evidence.values()),
                  failed=sum(e['status'] == 'failed' for e in evidence.values()),
                  not_executed=sum(e['status'] == 'not_executed' for e in evidence.values()),
                  real_data_verified=0)
    require(engine_hash() == current_engine and environment() == current_environment,
            'Engine or runtime changed during audit')
    for path, expected in tracked.items():
        require(file_hash(path) == expected, 'Evidence changed during audit')
    report = dict(status='passed' if counts['passed'] == len(rows) else 'partial',
                  engine_sha256=current_engine, environment=current_environment, counts=counts,
                  validation_script_sha256=script_sha, read_files_unchanged=True,
                  read_file_count=len(tracked), receipts=receipts,
                  scope='Pinned-source adapter equivalence only; no independent algorithm validity '
                        'or real-EEG claim. All current identities retained; service registry untouched.')
    output.mkdir(parents=True)
    write_json(output / 'verification_v2.json', evidence)
    write_json(output / 'audit.json', report)
    lines = ['# 当前配置验证', '',
             f"全部 {counts['profiles']} 项；通过 {counts['passed']}，失败 {counts['failed']}，"
             f"未执行 {counts['not_executed']}。真实 EEG 本轮验证 0 项。", '',
             '数值证据仅验证冻结来源与图适配器的一致性，未借用历史真实数据回执。', '',
             '| 配置身份 | 状态 | 失败或缺口 |', '|---|---|---|']
    for identity, item in evidence.items():
        cells = [identity, item['status'], str(item.get('failure') or '')]
        lines.append('| ' + ' | '.join(c.replace('|', '\\|').replace('\n', ' ') for c in cells) + ' |')
    (output / 'matrix.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profiles', required=True, type=Path)
    parser.add_argument('--validation-script', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.profiles, args.validation_script, args.output)
    print(json.dumps(dict(status=result['status'], counts=result['counts'])))
