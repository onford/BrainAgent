import pytest

from app.preprocessing.methods import baseline_methods
from .conftest import OWNER
from .test_execution import prepare


def test_progress_counts_without_decoding_result_payloads(service, dataset):
    job, _, _ = prepare(service, dataset, [baseline_methods()[0]])
    store = service.store
    assert store.progress(OWNER, job.job_id) == {
        "status": "queued",
        "total": job.total,
        "completed": 0,
    }
    # Polling uses only state/counts even when a result body is not JSON-decodable.
    with store.db() as db:
        db.execute(
            "UPDATE records SET status='completed',result='unread payload' "
            "WHERE job_id=? AND key=?",
            (job.job_id, job.records[0]["key"]),
        )
        db.execute("UPDATE jobs SET status='running' WHERE id=?", (job.job_id,))
    assert store.progress(OWNER, job.job_id) == {
        "status": "running",
        "total": job.total,
        "completed": 1,
    }
    with pytest.raises(KeyError):
        store.progress("other-owner", job.job_id)
    with pytest.raises(KeyError):
        store.progress(OWNER, "missing")
