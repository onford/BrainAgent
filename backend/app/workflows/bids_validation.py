"""Pinned, offline official BIDS validation; immutable receipts outside the dataset."""
from __future__ import annotations

from collections import Counter
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

from pydantic import Field, model_validator
from typing import Literal

from app.preprocessing.schemas import Contract
from app.preprocessing.storage import file_hash
from app.search.processes import ProcessTree

BIDS_VERSION = '1.11.1'
SCHEMA_VERSION = '1.2.7'
BUNDLE_SHA256 = '6fba22693b737742468963cfa79b677c178ee597ea5abc5d2394b2088b7c82cf'
MAX_OUTPUT_BYTES = 128 * 1024 * 1024


class WarningDisposition(Contract):
    code: str
    field: str | None
    occurrences: int = Field(ge=1)
    action: Literal['retain_missing_recommended_metadata', 'review_required']
    reason: str


class OfficialValidation(Contract):
    status: Literal['passed', 'passed_with_warnings', 'failed', 'unavailable',
                    'timed_out', 'cancelled', 'invalid_result', 'input_changed', 'review_required']
    validator_version: Literal['3.0.1'] = '3.0.1'
    deno_version: Literal['2.9.6'] = '2.9.6'
    bids_version: Literal['1.11.1'] = BIDS_VERSION
    schema_version: Literal['1.2.7'] = SCHEMA_VERSION
    declared_bids_version: str | None = None
    errors: int | None = Field(default=None, ge=0)
    warnings: int | None = Field(default=None, ge=0)
    warning_dispositions: list[WarningDisposition] = Field(default_factory=list)
    validated_files: int | None = Field(default=None, ge=0)
    input_unchanged: bool = False
    receipt_path: str
    receipt_sha256: str
    reason: str | None = None

    @model_validator(mode='after')
    def completed_status_requires_evidence(self):
        if self.status in {'passed', 'passed_with_warnings', 'review_required', 'failed'}:
            if self.errors is None or self.warnings is None or self.validated_files is None:
                raise ValueError('completed official validation requires counts')
            if sum(w.occurrences for w in self.warning_dispositions) != self.warnings:
                raise ValueError('all warning occurrences require a disposition')
        if self.status in {'passed', 'passed_with_warnings'}:
            if self.errors != 0 or not self.input_unchanged:
                raise ValueError('passed validation requires zero errors and unchanged input')
            if any(w.action == 'review_required' for w in self.warning_dispositions):
                raise ValueError('unreviewed warning cannot be passed')
            if (self.status == 'passed') != (self.warnings == 0):
                raise ValueError('warning status contradicts count')
        return self


def _write(path, data):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def _manifest(root):
    files = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('validator input contains a symbolic link or escaped path')
        if path.is_file():
            files[path.relative_to(root).as_posix()] = file_hash(path)
    return files


def _runtime():
    if version('bids-validator-deno') != '3.0.1' or version('deno') != '2.9.6':
        raise ValueError('official validator requires pinned inspection dependencies')
    import bids_validator_deno
    from deno import find_deno_bin
    binary = Path(find_deno_bin())
    bundle = Path(bids_validator_deno.__file__).parent / 'bids-validator.js'
    if file_hash(bundle) != BUNDLE_SHA256:
        raise ValueError('official validator bundle differs from pinned bytes')
    return binary, bundle


def _strict_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError('nonfinite JSON number: ' + value)
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=nonfinite)


def _interpret(result, returncode, file_count):
    summary = result['summary']
    issues = result['issues']['issues']
    if (summary['schemaVersion'] != SCHEMA_VERSION
            or type(summary['totalFiles']) is not int
            or summary['totalFiles'] != file_count or not isinstance(issues, list)):
        raise ValueError('official validator schema or file coverage differs')
    counts = Counter()
    warnings = Counter()
    for issue in issues:
        if (not isinstance(issue, dict) or issue.get('severity') not in {'error', 'warning', 'info'}
                or not isinstance(issue.get('code'), str)):
            raise ValueError('unknown or suppressed official issue')
        counts[issue['severity']] += 1
        if issue['severity'] == 'warning':
            field = issue.get('subCode')
            if field is not None and not isinstance(field, str):
                raise ValueError('invalid warning field')
            warnings[(issue['code'], field)] += 1
    # Pinned 3.0.1 src/api/app.ts uses 16 for detected BIDS errors; 1 is a crash.
    if returncode != (16 if counts['error'] else 0):
        raise ValueError('official exit status contradicts its complete issue list')
    dispositions = []
    for (code, field), occurrences in sorted(warnings.items(), key=lambda item: (item[0][0], item[0][1] or '')):
        retain = code in {'JSON_KEY_RECOMMENDED', 'SIDECAR_KEY_RECOMMENDED'} and field is not None
        dispositions.append(dict(code=code, field=field, occurrences=occurrences,
            action='retain_missing_recommended_metadata' if retain else 'review_required',
            reason=('The official schema recommends this absent field. Retain its absence; '
                    'do not fabricate acquisition, participant, or measured-coordinate facts. '
                    'This disposition does not establish applicability of methods needing that metadata.')
                    if retain else 'No fixed retention rationale exists for this warning; input registration is blocked.'))
    status = ('failed' if counts['error'] else 'review_required'
              if any(w['action'] == 'review_required' for w in dispositions)
              else 'passed_with_warnings' if counts['warning'] else 'passed')
    return dict(status=status, errors=counts['error'], warnings=counts['warning'],
                warning_dispositions=dispositions, validated_files=summary['totalFiles'])


def validate_bids(root, receipt_parent, *, cancelled=lambda: False, timeout_s=180):
    """Validate every file and every TSV row, retaining all unmodified issues.

    The bundled schema is fixed independently of the dataset's declared version.
    Historical callers therefore receive both versions and cannot rewrite history.
    """
    root = Path(root).resolve(strict=True)
    parent = Path(receipt_parent).resolve()
    if parent.is_relative_to(root) or root.is_relative_to(parent):
        raise ValueError('validator receipt directory must be separate from input tree')
    output = parent / uuid4().hex
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    before = _manifest(root)
    description = root / 'dataset_description.json'
    declared = None
    try:
        value = _strict_json(description).get('BIDSVersion')
        declared = value if isinstance(value, str) else None
    except (OSError, ValueError, AttributeError):
        pass  # The official validator must report malformed dataset metadata.
    receipt = dict(input_root=str(root), input_manifest=before, declared_bids_version=declared,
                   bids_version=BIDS_VERSION, schema_version=SCHEMA_VERSION,
                   validator_version='3.0.1', deno_version='2.9.6', max_rows=-1,
                   offline=True, ignored_issues=False, pruned_files=False,
                   timeout_s=timeout_s, peak_process_tree_rss_bytes=0)
    result = dict(status='unavailable', declared_bids_version=declared)
    raw_result = output / 'result.json'
    try:
        if any(Path(p).name in {'.bidsignore', '.bids-validator-config.json'} for p in before):
            raise ValueError('validation requires input without ignored-file or issue overrides')
        binary, bundle = _runtime()
        receipt.update(binary_sha256=file_hash(binary), bundle_sha256=file_hash(bundle))
        command = [str(binary), '--no-prompt', '--allow-read', '--allow-env',
                   '--allow-write=' + str(output), '--allow-sys=osRelease',
                   str(bundle), str(root), '--format', 'json', '--max-rows', '-1',
                   '--outfile', str(raw_result)]
        receipt['command'] = command
        # No BIDS_SCHEMA, remote credentials, or network permissions are inherited.
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {'SYSTEMROOT', 'SYSTEMDRIVE', 'PATH', 'TEMP', 'TMP', 'WINDIR', 'HOME'}}
        if cancelled():
            result.update(status='cancelled', reason='cancelled before official validator')
        else:
            result['status'] = 'invalid_result'
            with (output / 'stdout.log').open('xb') as stdout, (output / 'stderr.log').open('xb') as stderr:
                with ProcessTree(command, stdout=stdout, stderr=stderr, env=env, cwd=output) as tree:
                    while True:
                        if cancelled():
                            result.update(status='cancelled', reason='cancelled during official validator')
                            break
                        if time.monotonic() - started >= timeout_s:
                            result.update(status='timed_out', reason='official validator deadline exceeded')
                            break
                        if any(p.stat().st_size > MAX_OUTPUT_BYTES for p in output.iterdir() if p.is_file()):
                            raise ValueError('official validator output exceeded bound; incomplete result')
                        rss = tree.memory_bytes()
                        receipt['peak_process_tree_rss_bytes'] = max(receipt['peak_process_tree_rss_bytes'], rss)
                        if rss > 2 * 1024**3:
                            raise ValueError('official validator process tree exceeded 2 GiB')
                        try:
                            returncode = tree.wait(timeout=.1)
                            receipt['exit_code'] = returncode
                            break
                        except subprocess.TimeoutExpired:
                            pass
            if result['status'] == 'invalid_result':
                if raw_result.stat().st_size > MAX_OUTPUT_BYTES:
                    raise ValueError('official validator JSON exceeds bound')
                result.update(_interpret(_strict_json(raw_result), returncode, len(before)))
    except Exception as exc:
        result['reason'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        try:
            result['input_unchanged'] = before == _manifest(root)
        except (OSError, ValueError):
            result['input_unchanged'] = False
        if not result['input_unchanged']:
            result.update(status='input_changed', reason='input manifest changed during official validation')
        receipt.update(result, elapsed_seconds=time.monotonic() - started,
                       artifacts={p.name: file_hash(p) for p in output.iterdir() if p.is_file()})
        _write(output / 'receipt.json', receipt)
    return OfficialValidation(**result, receipt_path=(output / 'receipt.json').relative_to(parent.parent).as_posix(),
                              receipt_sha256=file_hash(output / 'receipt.json'))
