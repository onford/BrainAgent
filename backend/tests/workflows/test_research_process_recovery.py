"""Real HTTP and process termination, using no external provider or credentials."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from app.workflows.cognition_contracts import ResearchSources
from app.workflows.research_journal import ResearchJournal


@pytest.fixture
def source_server():
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            body = (b'<html><title>Recovery transport fixture</title><body>'
                    + b'This local transport fixture contains no scientific claims. ' * 8
                    + b'</body></html>')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/source', calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextmanager
def child(root, url, phase):
    helper = Path(__file__).with_name('recovery_process_probe.py')
    backend = helper.parents[2]
    environment = {**os.environ, 'PYTHONPATH': str(backend), 'PYTHONUTF8': '1', 'NO_PROXY': '*'}
    process = subprocess.Popen([sys.executable, '-u', str(helper), str(root), url, phase],
        cwd=backend, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)


def phase_reached(process, root, expected):
    deadline = time.monotonic() + 30
    path = root / 'phase.json'
    while time.monotonic() < deadline:
        if path.exists():
            try:
                if json.loads(path.read_text())['phase'] == expected:
                    return
            except json.JSONDecodeError:
                pass
        if process.poll() is not None:
            out, err = process.communicate()
            pytest.fail(f'Child exited before barrier: {out}\n{err}')
        time.sleep(.02)
    pytest.fail('Child did not reach the controlled crash point')


def result(process):
    out, err = process.communicate(timeout=30)
    assert process.returncode == 0, err
    return json.loads(out)


def journal(root):
    value = ResearchJournal(root / 'recovery-tools.json', ResearchSources(documents=[], observations=[]))
    value.bind_budget('literature_review', 4, {'fixture': 'process-recovery'}, 120)
    return value


@pytest.mark.parametrize('phase', ['before_commit', 'after_commit'])
def test_process_death_does_not_resend_or_reset_budget(tmp_path, source_server, phase):
    url, calls = source_server
    first = journal(tmp_path)
    deadline = first.read()['budgets']['literature_review']['expires_at']
    with child(tmp_path, url, phase) as process:
        phase_reached(process, tmp_path, phase)
        assert calls == ['/source']
        process.terminate()
        process.wait(timeout=5)
    for _ in range(2):
        with child(tmp_path, url, 'resume') as process:
            reply = result(process)
        if phase == 'before_commit':
            assert reply['status'] == 'error' and 'outcome unknown' in reply['error']
        else:
            assert reply['status'] == 'success'
        assert calls == ['/source']
    restarted = journal(tmp_path)
    assert restarted.read()['budgets']['literature_review']['expires_at'] == deadline
    assert restarted.remaining('literature_review') == 1
    rows = restarted.read()['actions']
    assert len(rows) == 3 and all('reused_sequence' in row for row in rows[1:])
    assert rows[0]['status'] == ('reserved' if phase == 'before_commit' else 'completed')


def test_late_result_survives_concurrent_unknown_response_across_processes(tmp_path, source_server):
    url, calls = source_server
    first = journal(tmp_path)
    deadline = first.read()['budgets']['literature_review']['expires_at']
    with child(tmp_path, url, 'before_commit') as original:
        phase_reached(original, tmp_path, 'before_commit')
        with child(tmp_path, url, 'resume') as concurrent:
            reply = result(concurrent)
        assert reply['status'] == 'error' and 'outcome unknown' in reply['error']
        (tmp_path / 'release').touch()
        saved = result(original)
        assert saved['status'] == 'success'
    with child(tmp_path, url, 'resume') as resumed:
        assert result(resumed) == saved
    assert calls == ['/source']
    state = journal(tmp_path).read()
    assert state['budgets']['literature_review']['expires_at'] == deadline
    assert state['actions'][1]['uncertain'] is True
    assert state['actions'][2]['uncertain'] is False
    assert state['actions'][2]['reused_sequence'] == state['actions'][0]['sequence']
