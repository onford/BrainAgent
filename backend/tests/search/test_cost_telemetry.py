import csv
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


@pytest.mark.skipif(os.name != 'nt', reason='Windows telemetry driver')
@pytest.mark.asyncio
async def test_cost_probe_rejects_output_inside_input_before_any_write(tmp_path):
    import json
    script = Path(__file__).resolve().parents[2] / 'scripts/profile_search_cost.py'
    spec = importlib.util.spec_from_file_location('profile_cost_boundary_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / 'input.json'
    source.write_text(json.dumps({'collection': {'root': str(tmp_path)}}), encoding='utf-8')
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError, match='disjoint'):
        await module.main(SimpleNamespace(output=tmp_path / 'output', input_json=source))
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


@pytest.mark.skipif(os.name != 'nt', reason='Windows Job telemetry contract')
def test_cost_accounting_keeps_exited_child_cpu_and_io(tmp_path):
    script = Path(__file__).resolve().parents[2] / 'scripts/profile_search_cost.py'
    spec = importlib.util.spec_from_file_location('profile_search_cost_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    # Real descendant terminates before the final Job query. Its counters must
    # remain in that query even though it is absent from the live PID list.
    child = "import sys,time; end=time.process_time()+.15\nwhile time.process_time()<end: pass\nsys.stdout.write('x'*65536)"
    parent = f'import subprocess,sys; subprocess.run([sys.executable,"-c",{child!r}],check=True)'
    with (tmp_path / 'child.log').open('wb') as stream:
        process = module.ProfiledTree([sys.executable, '-c', parent, '--stage', 'telemetry-test'],
                                      stdout=stream, stderr=subprocess.STDOUT)
        try:
            assert process.wait(timeout=15) == 0
        finally:
            process.kill()
            process.wait()
            process.close()
    assert len(module.ProfiledTree.records) == 1
    result = module.ProfiledTree.records[0]
    assert result['sampling_errors'] == []
    counters = result['final_job_counters']
    assert counters['total_processes'] >= 2 and counters['active_processes'] == 0
    assert counters['cpu_user_seconds'] + counters['cpu_kernel_seconds'] >= .15
    assert counters['write_bytes'] >= 65536
    assert result['io_wait_seconds'] is None
    with Path(result['trace_path']).open(newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    assert rows and float(rows[-1]['cpu_user_seconds']) == counters['cpu_user_seconds']
