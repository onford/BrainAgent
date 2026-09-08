# Optional EEG imports must be checked before importing the numeric worker.
# ruff: noqa: E402
import asyncio
import csv
import hashlib
import json
import shutil
from pathlib import Path
import zipfile

import pytest
from fastapi.testclient import TestClient

np = pytest.importorskip("numpy")
mne = pytest.importorskip("mne")
pytest.importorskip("mne_bids")

from app.agents import build_agent_registry
from app.core.config import Settings
from app.main import create_app
from app.preprocessing.schemas import Ref
from app.preprocessing.service import PreprocessingService
from app.preprocessing.storage import file_hash
from app.preprocessing.worker import Worker
from app.workflows import dataset, outputs
from app.workflows.schemas import WorkflowRequest
from app.workflows.contracts import STAGE_CONTRACTS, SurveyOutput
from app.workflows.records import load_stage, publish_stage, report_data
from app.workflows.service import WorkflowService
from app.workflows.templates.train_example import train
from tests.fakes import ScriptedLLMClient

OWNER = "workflow-test"


@pytest.fixture
def source(tmp_path, monkeypatch):
    """Only EDF decoding is substituted; BIDS, numeric worker and exports are real."""
    root = tmp_path / "source"
    for subject in ["S001", "S002", "S003"]:
        path = root / subject / f"{subject}R04.edf"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"fixture EDF input: " + subject.encode())
    names = mne.channels.make_standard_montage("standard_1005").ch_names[:64]

    def read(path, **kwargs):
        values = np.random.default_rng(int(Path(path).parent.name[1:])).normal(
            0, 5e-6, (64, 3200)
        )
        raw = mne.io.RawArray(
            values, mne.create_info(names, 160, "eeg"), verbose="ERROR"
        )
        raw.set_annotations(
            mne.Annotations(
                [1, 4, 8, 12, 16], [1, 2, 2, 2, 2], ["T0", "T1", "T2", "T1", "T2"]
            )
        )
        return raw

    monkeypatch.setattr(mne.io, "read_raw_edf", read)
    return root


async def finish(service, identity):
    worker = Worker(service.preprocessing.store, service.preprocessing.allowed_roots)
    async with asyncio.timeout(60):
        while not service.tasks[identity].done():
            await asyncio.to_thread(worker.run_once)
            await asyncio.sleep(0.05)
        await service.tasks[identity]
    return service.get(OWNER, identity)


@pytest.mark.asyncio
async def test_six_agents_retry_delivery_alignment_training_and_api(
    source, tmp_path, monkeypatch
):
    prep = PreprocessingService(tmp_path / "preprocessing")
    service = WorkflowService(tmp_path / "workflows", [source], prep)
    service.registry = build_agent_registry(preprocessing=prep, workflow=service)
    request = WorkflowRequest(source_root=str(source), runs=[4])
    original = outputs.report
    calls = []

    def fail_once(*args):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("report unavailable")
        return original(*args)

    monkeypatch.setattr(outputs, "report", fail_once)
    state = service.create(OWNER, request)
    failed = await finish(service, state["id"])
    assert failed["status"] == "failed" and failed["stages"][4]["status"] == "failed"
    job_id = failed["preprocessing_job"]
    assert prep.store.status(OWNER, job_id).completed == 6
    failed_files = {
        a["name"] for a in service.describe(OWNER, state["id"])["artifacts"]
    }
    assert "survey/survey.json" in failed_files
    assert any(n.startswith("collection/bids/") for n in failed_files)
    assert any(
        n.startswith("preprocessing/runs/") and n.endswith("provenance.json")
        for n in failed_files
    )
    service.retry(OWNER, state["id"])
    completed = await finish(service, state["id"])
    assert completed["status"] == "completed"
    assert all(s["status"] == "completed" for s in completed["stages"])
    assert all(r["attempt"] == 1 for r in prep.store.status(OWNER, job_id).records)
    folder = service.folder(state["id"])
    index = json.loads((folder / "process/index.json").read_text(encoding="utf-8"))
    for stage in index["stages"]:
        assert stage["data_path"] == STAGE_CONTRACTS[stage["name"]][1]
        load_stage(folder, stage["name"])
    survey_text = (folder / "survey/survey.json").read_text(encoding="utf-8")
    assert '\n  "profile": {' in survey_text
    assert len(json.loads(survey_text)["channel_sets"]) == 1
    disk_state = json.loads((folder / "workflow.json").read_text(encoding="utf-8"))
    assert disk_state["outputs"]["data_survey"] == "survey/survey.json"
    view = report_data(folder)
    assert (
        view.after.trials == 12 and sum(r.events_retained for r in view.records) == 12
    )
    # Reproduce the report from process records alone, with no live DB.
    projection = tmp_path / "standalone-report"
    for relative in [
        "process/index.json",
        *[STAGE_CONTRACTS[n][1] for n in STAGE_CONTRACTS][:4],
    ]:
        destination = projection / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(folder / relative, destination)
    survey_data = json.loads(
        (projection / "survey/survey.json").read_text(encoding="utf-8")
    )
    survey_data["profile"]["name"] = "<script>dataset</script>"
    publish_stage(projection, "data_survey", survey_data)
    outputs.report({}, projection / "report", None)
    rendered = (projection / "report/report.html").read_text(encoding="utf-8")
    assert "&lt;script&gt;dataset&lt;/script&gt;" in rendered
    assert "<script>dataset</script>" not in rendered
    delivery = folder / "delivery"
    X, y, groups, splits = [
        np.load(delivery / f"{name}.npy", allow_pickle=False)
        for name in ["X", "y", "subjects", "split"]
    ]
    assert X.shape == (12, 64, 321) and X.dtype == np.float32 and np.isfinite(X).all()
    assert list(y) == [0, 1, 0, 1] * 3
    for subject in groups:
        assert len(set(splits[groups == subject])) == 1
    with (delivery / "trial-index.tsv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    assert [int(r["source_sample"]) for r in rows] == [640, 1280, 1920, 2560] * 3
    assert [r["subject"] for r in rows] == list(groups)
    assert [r["split"] for r in rows] == list(splits)
    assert train(delivery)["training_trials"] == 4
    with zipfile.ZipFile(folder / "training-data.zip") as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert archive.testzip() is None
        for entry in manifest["files"]:
            assert (
                hashlib.sha256(archive.read(entry["name"])).hexdigest()
                == entry["sha256"]
            )
            assert file_hash(delivery / entry["name"]) == entry["sha256"]
    selection = completed["outputs"]["data_evaluation"]
    plan = prep.store.get(
        OWNER,
        Ref.model_validate(completed["outputs"]["data_preprocessing"]["plan_ref"]),
        "plan",
    )
    result = prep.store.status(OWNER, job_id)
    assert outputs.choose(result, plan, prep.store, 42) == selection
    assert (
        selection["quality_evaluated"] is False
        and len(selection["eligible_candidates"]) == 2
    )

    settings = Settings(
        database_url_override=f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}",
        brain_agent_credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        preprocessing_root=str(prep.store.root),
        workflow_root=str(service.root),
        workflow_input_roots=[str(source)],
    )
    with TestClient(create_app(settings, ScriptedLLMClient([]))) as client:
        prefix = f"/api/workflows/{state['id']}"
        headers = {"X-Brain-Agent-Owner-ID": OWNER}
        described = client.get(prefix, headers=headers).json()
        assert described["status"] == "completed"
        names = {a["name"] for a in described["artifacts"]}
        expected_local = {
            p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()
        }
        assert expected_local <= names
        assert any(n.startswith("delivery/provenance/") for n in names)
        worker_entries = [
            a
            for a in described["artifacts"]
            if a["name"].startswith("preprocessing/runs/")
        ]
        expected_worker = {
            "preprocessing/" + a["path"]
            for r in result.records
            for a in r["result"]["artifacts"]
        }
        assert {a["name"] for a in worker_entries} == expected_worker
        for entry in worker_entries:
            response = client.get(
                prefix + "/artifacts/" + entry["name"], headers=headers
            )
            assert response.status_code == 200
            assert hashlib.sha256(response.content).hexdigest() == entry["sha256"]
        assert (
            client.get(prefix, headers={"X-Brain-Agent-Owner-ID": "other"}).status_code
            == 404
        )
        report = client.get(
            prefix + "/artifacts/report/report.html?download=false", headers=headers
        )
        assert report.status_code == 200 and "Content-Disposition" not in report.headers
        assert "未进行质量排名" in report.text
        assert (
            client.get(
                prefix + "/artifacts/training-data.zip", headers=headers
            ).status_code
            == 200
        )
        assert (
            client.get(
                prefix + "/artifacts/training-data.zip",
                headers={"X-Brain-Agent-Owner-ID": "other"},
            ).status_code
            == 404
        )
        assert client.post(prefix + "/retry", headers=headers).status_code == 422
        assert (
            client.get("/api/workflows/not-an-id", headers=headers).status_code == 404
        )
        (delivery / "labels.json").write_text("{}", encoding="utf-8")
        assert (
            client.get(
                prefix + "/artifacts/delivery/labels.json", headers=headers
            ).status_code
            == 422
        )
    # A corrupt candidate must not remain eligible for random selection.
    victim = next(
        r
        for r in result.records
        if r["method_id"] == selection["selected_method_ref"]["id"]
    )
    artifact = next(
        a for a in victim["result"]["artifacts"] if a["name"] == "signal_V.npy"
    )
    (prep.store.root / artifact["path"]).write_bytes(b"corrupt")
    remaining = outputs.choose(result, plan, prep.store, 42)
    assert len(remaining["eligible_candidates"]) == 1
    assert remaining["selected_method_ref"] != selection["selected_method_ref"]
    await service.close()


@pytest.mark.asyncio
async def test_invalid_agent_output_cannot_complete_or_publish(source, tmp_path):
    from app.runtime.result import AgentResult

    class InvalidAgent:
        async def run(self, task, context):
            return AgentResult(
                agent_name="data_survey", success=True, output={"summary": "looks fine"}
            )

    class Registry:
        def get(self, name):
            return InvalidAgent()

    prep = PreprocessingService(tmp_path / "preprocessing")
    service = WorkflowService(tmp_path / "workflows", [source], prep)
    service.registry = Registry()
    state = service.create(OWNER, WorkflowRequest(source_root=str(source)))
    await service.tasks[state["id"]]
    state = service.get(OWNER, state["id"])
    assert state["status"] == "failed" and state["outputs"] == {}
    assert state["stages"][0]["status"] == "failed"
    assert not (service.folder(state["id"]) / "survey/survey.json").exists()


def test_survey_contract_rejects_extra_fields_and_dangling_channels(source, tmp_path):
    survey = dataset.inspect(
        source, WorkflowRequest(source_root=str(source), runs=[4]), tmp_path / "survey"
    )
    SurveyOutput.model_validate(survey)
    with pytest.raises(ValueError):
        publish_stage(
            tmp_path, "data_survey", {**survey, "extra_narrative": "redundant"}
        )
    survey["records"][0]["channel_set"] = "missing"
    with pytest.raises(ValueError, match="unknown channel set"):
        SurveyOutput.model_validate(survey)


def test_source_changed_after_survey_is_rejected(source, tmp_path):
    request = WorkflowRequest(source_root=str(source), subjects=["S001"], runs=[4])
    survey = dataset.inspect(source, request, tmp_path / "survey")
    (source / "S001/S001R04.edf").write_bytes(b"changed")
    with pytest.raises(ValueError, match="源文件已变化"):
        dataset.check_sources(survey)


def test_source_boundary_and_request_validation(source, tmp_path):
    request = WorkflowRequest(source_root=str(source))
    with pytest.raises(ValueError, match="允许范围"):
        dataset.allowed_source(request, [tmp_path / "elsewhere"], [])
    with pytest.raises(ValueError, match="分离"):
        dataset.allowed_source(request, [source], [source / "outputs"])
    for invalid in [
        {"subjects": ["../escape"]},
        {"runs": [3]},
        {"runs": [4, 4]},
        {"tmin": 2, "tmax": 1},
    ]:
        with pytest.raises(ValueError):
            WorkflowRequest(source_root=str(source), **invalid)


@pytest.mark.asyncio
async def test_single_subject_delivery_records_empty_groups(source, tmp_path):
    prep = PreprocessingService(tmp_path / "preprocessing")
    service = WorkflowService(tmp_path / "workflows", [source], prep)
    service.registry = build_agent_registry(preprocessing=prep, workflow=service)
    state = service.create(
        OWNER,
        WorkflowRequest(source_root=str(source), subjects=["S001"], runs=[4]),
        start=False,
    )
    assert state["status"] == "queued"
    # A fresh service instance resumes the persisted queue after restart.
    service = WorkflowService(tmp_path / "workflows", [source], prep)
    service.registry = build_agent_registry(preprocessing=prep, workflow=service)
    await service.resume()
    result = await finish(service, state["id"])
    assert result["status"] == "completed", result["error"]
    manifest = json.loads(
        (service.folder(state["id"]) / "delivery/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["split_counts"] == {"train": 4, "validation": 0, "test": 0}
    assert np.load(
        service.folder(state["id"]) / "delivery/split.npy", allow_pickle=False
    ).dtype == np.dtype("<U10")
    assert any("分组为空" in s for s in manifest["limitations"])
    # A legacy persisted run resumes with the original numeric attempts intact.
    result.pop("schema_version")
    result["status"] = "failed"
    result["stages"][4]["status"] = "failed"
    result["stages"][5]["status"] = "pending"
    result["outputs"].pop("data_report")
    result["outputs"].pop("data_delivery")
    survey = result["outputs"]["data_survey"]
    channels = survey.pop("channel_sets")
    for record in survey["records"]:
        record["channels"] = channels[record.pop("channel_set")]
    prep_output = result["outputs"]["data_preprocessing"]
    prep_output.pop("methods")
    prep_output.pop("records")
    (service.folder(state["id"]) / "delivery/leftover.json").write_text(
        "{}", encoding="utf-8"
    )
    service.save(result)
    service.retry(OWNER, state["id"])
    upgraded = await finish(service, state["id"])
    assert upgraded["status"] == "completed", upgraded["error"]
    assert upgraded["schema_version"] == "1"
    with zipfile.ZipFile(service.folder(state["id"]) / "training-data.zip") as archive:
        assert "output.json" not in archive.namelist()
        assert "leftover.json" not in archive.namelist()
        upgraded_manifest = json.loads(archive.read("manifest.json"))
        assert set(archive.namelist()) == {
            a["name"] for a in upgraded_manifest["files"]
        } | {"manifest.json"}
    assert all(
        r["attempt"] == 1
        for r in prep.store.status(OWNER, upgraded["preprocessing_job"]).records
    )
    await service.close()
