import json

import portalocker
import pytest

from app.preprocessing.storage import digest, file_hash
from app.preprocessing.recovery import RecoveryReceipt, record_interruption
from app.preprocessing.methods import baseline_methods
from app.workflows.artifacts import worker_files
from .test_execution import prepare
from .conftest import OWNER


def test_interrupted_attempt_keeps_native_receipt_and_is_visible_before_retry(service, dataset):
    job, _, plan = prepare(service, dataset, [baseline_methods()[0]])
    service.store.claim()
    record = plan.records[0]
    key = digest([record.method_ref.id, record.record_id])
    assert service.store.record_start(job.job_id, key) == 1
    root = service.store.root / f'runs/{job.job_id}/r0000/a1'
    native = root / 'native-step/native-owned/execution.json'
    native.parent.mkdir(parents=True)
    native.write_text(json.dumps({'status':'running','completed':False,'pid':12345}),encoding='utf-8')
    before = native.read_bytes()
    with portalocker.Lock(service.store.root/'worker.lock',timeout=0):
        service.store.recover()
    status = service.store.status(OWNER, job.job_id)
    row = next(r for r in status.records if r['key']==key)
    assert status.status == 'interrupted' and row['status']=='interrupted' and row['result'] is None
    receipt = RecoveryReceipt.model_validate_json((root/'recovery.json').read_text(encoding='utf-8'))
    assert receipt.native_receipts[0].declared_status == 'running'
    assert receipt.native_receipts[0].sha256 == file_hash(native)
    assert not receipt.previous_outputs_accepted and not receipt.native_process_exit_verified
    assert native.read_bytes() == before
    listed = worker_files(service.store, OWNER, job.job_id)
    assert any(p['name'].endswith('/recovery.json') and p['sha256'] for p in listed)
    original = (root/'recovery.json').read_bytes()
    # Repeat observation is idempotent, including its original timestamp.
    record_interruption(root,job_id=job.job_id,record_key=key,attempt=1)
    assert (root/'recovery.json').read_bytes() == original
    assert service.store.record_start(job.job_id,key)==2
    assert (root/'recovery.json').read_bytes()==original


def test_recovery_does_not_guess_paths_for_a_corrupt_plan(service,dataset):
    job,_,plan=prepare(service,dataset,[baseline_methods()[0]])
    service.store.claim()
    key=digest([plan.records[0].method_ref.id,plan.records[0].record_id])
    service.store.record_start(job.job_id,key)
    with service.store.db() as db:
        db.execute("UPDATE objects SET body='{}' WHERE id=?",(job.plan_ref.id,))
    with portalocker.Lock(service.store.root/'worker.lock',timeout=0):
        service.store.recover()
    assert service.store.status(OWNER,job.job_id).status=='interrupted'
    assert not list(service.store.root.rglob('recovery.json'))


def test_existing_interruption_receipt_cannot_change_identity(tmp_path):
    record_interruption(tmp_path,job_id='job',record_key='key',attempt=1)
    with pytest.raises(ValueError,match='identity'):
        record_interruption(tmp_path,job_id='other',record_key='key',attempt=1)
