from types import SimpleNamespace

from app.workflows.artifacts import worker_files


def test_failed_and_previous_attempt_files_are_listed_but_active_inputs_are_not(
    tmp_path,
):
    class Store:
        root = tmp_path

        def status(self, owner, job_id):
            assert owner == "owner" and job_id == "job"
            return SimpleNamespace(
                plan_ref=None,
                records=[
                    {
                        "record_id": "S001R04",
                        "method_id": "method",
                        "attempt": 2,
                        "status": "running",
                        "result": None,
                    }
                ],
            )

        def get(self, owner, ref, kind):
            return {
                "records": [{"record_id": "S001R04", "method_ref": {"id": "method"}}]
            }

    for name in [
        "a1/failure.json",
        "a1/steps/parameters.json",
        "a1/input/source.vhdr",
        "a2/partial.json",
    ]:
        path = tmp_path / "runs/job/r0000" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    entries = worker_files(Store(), "owner", "job")
    assert {a["name"] for a in entries} == {
        "preprocessing/runs/job/r0000/a1/failure.json",
        "preprocessing/runs/job/r0000/a1/steps/parameters.json",
    }
    previous_hash = next(
        a["sha256"] for a in entries if a["name"].endswith("failure.json")
    )
    (tmp_path / "runs/job/r0000/a1/failure.json").write_text("changed")
    refreshed = worker_files(Store(), "owner", "job", entries)
    assert (
        next(a["sha256"] for a in refreshed if a["name"].endswith("failure.json"))
        == previous_hash
    )
