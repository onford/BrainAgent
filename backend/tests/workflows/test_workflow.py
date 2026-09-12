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
from app.workflows import dataset, outputs
from app.workflows.schemas import WorkflowRequest
from app.workflows.contracts import STAGE_CONTRACTS, SurveyOutput
from app.workflows.records import load_stage, publish_stage, report_data
from tests.workflows.fakes import workflow_service as WorkflowService
from app.workflows.templates.train_example import train
from tests.fakes import ScriptedLLMClient

OWNER = "workflow-test"


@pytest.fixture
def source(tmp_path, monkeypatch):
    """Simulated EDF; real BIDS/workers/exports with short frozen learner training."""
    from app.search import utility_parallel

    normalize_execution = utility_parallel.utility_execution
    monkeypatch.setattr(utility_parallel, "utility_execution", lambda value=None:
        normalize_execution({**(value or {}), "eegnet_training": {
            "max_epochs": 2, "patience": 1, "batch_size": 8}}))
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
    async with asyncio.timeout(120):
        while not service.tasks[identity].done():
            await asyncio.sleep(0.05)
        await service.tasks[identity]
    return service.get(OWNER, identity)


@pytest.mark.asyncio
async def test_six_agents_retry_delivery_alignment_training_and_api(
    source, tmp_path, monkeypatch
):
    from app.search import utility_parallel

    # Freeze a short, real training protocol before the synthetic search is
    # created. Workers still train and verify every seed; no scores are mocked.
    normalize_execution = utility_parallel.utility_execution
    monkeypatch.setattr(utility_parallel, "utility_execution", lambda value=None:
        normalize_execution({**(value or {}), "eegnet_training": {
            "max_epochs": 2, "patience": 1, "batch_size": 8}}))
    prep = PreprocessingService(tmp_path / "preprocessing")
    service = WorkflowService(tmp_path / "workflows", [source], prep)
    service.registry = build_agent_registry(preprocessing=prep, workflow=service)
    request = WorkflowRequest(
        source_root=str(source), search_budget={"max_candidates": 1}
    )
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
    store, execution_owner = service.execution_store(failed)
    assert execution_owner == "offline-search"
    assert store.status(execution_owner, job_id).completed == 3
    with pytest.raises(KeyError):
        prep.store.status(OWNER, job_id)
    failed_files = {
        a["name"] for a in service.describe(OWNER, state["id"])["artifacts"]
    }
    assert "survey/survey.json" in failed_files
    from app.workflows.survey_reporting import REPORTS

    assert {"survey/reports/" + name for name in REPORTS} <= failed_files
    assert any(n.startswith("collection/bids/") for n in failed_files)
    assert any(
        n.startswith("preprocessing/runs/") and n.endswith("provenance.json")
        for n in failed_files
    )
    service.retry(OWNER, state["id"])
    completed = await finish(service, state["id"])
    assert completed["status"] == "completed"
    assert all(s["status"] == "completed" for s in completed["stages"])
    assert all(r["attempt"] == 1 for r in store.status(execution_owner, job_id).records)
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
        "process/formats.json",
        "process/schema.json",
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
    assert set(splits) == {"train"}
    assert train(delivery)["training_trials"] == 12
    with zipfile.ZipFile(folder / "training-data.zip") as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert archive.testzip() is None
        assert manifest["split_counts"] == {"train": 12, "validation": 0, "test": 0}
        assert len(json.loads(archive.read("evaluation/folds.json"))) == 3
        selection = completed["outputs"]["data_evaluation"]
        panel_bytes = archive.read("evaluation/panel.json")
        prediction_bytes = archive.read("evaluation/originalpredictions.tsv")
        assert panel_bytes == (store.root.parent / "panel.json").read_bytes()
        assert json.loads(panel_bytes)["trials"]
        assert (
            hashlib.sha256(panel_bytes).hexdigest() == selection["panel"]["file_sha256"]
        )
        assert (
            hashlib.sha256(prediction_bytes).hexdigest()
            == selection["selected_receipt"]["predictions_sha256"]
        )
        predictions = list(
            csv.DictReader(
                prediction_bytes.decode("utf-8").splitlines(), delimiter="\t"
            )
        )
        eligible = {
            t["event_id"] for t in json.loads(panel_bytes)["trials"] if t["eligible"]
        }
        scored = [row for row in predictions if row["primary_prediction"]]
        assert {row["event_id"] for row in scored} == eligible
        subject_scores = []
        for subject in sorted({row["subject"] for row in scored}):
            subject_rows = [row for row in scored if row["subject"] == subject]
            recalls = []
            for label in sorted({row["label"] for row in subject_rows}):
                class_rows = [row for row in subject_rows if row["label"] == label]
                recalls.append(
                    sum(row["primary_prediction"] == label for row in class_rows)
                    / len(class_rows)
                )
            subject_scores.append(sum(recalls) / len(recalls))
        assert sum(subject_scores) / len(subject_scores) == pytest.approx(
            selection["selected_receipt"]["macro_ba"]
        )
        # Recompute selection from the exported predictions, independently of
        # the receipt's precomputed model scores and utility summary.
        assessment_index = json.loads(archive.read("evaluation/assessment-index.json"))
        utility = json.loads(archive.read(assessment_index["utility_receipt"]))
        primary_suite = ["eegnet"]
        assert utility["utility_version"] == 2
        assert set(utility["learners"]) == {"eegnet", "csp_lda"}
        assert utility["primary_suite"] == primary_suite
        panel = json.loads(panel_bytes)
        frozen = {t["event_id"]: t for t in panel["trials"] if t["eligible"] and t["role"] == "development"}
        candidate_root = store.root.parent / "candidates" / selection["selected_candidate_id"]
        model_scores = []
        assert set(utility["learners"]["eegnet"]["seeds"]) == {"17", "42", "2026"}
        for seed in [17, 42, 2026]:
            learner = utility["learners"]["eegnet"]["seeds"][str(seed)]
            assert learner["status"] == "evaluated"
            prediction_ref = learner["predictions"]
            member = "evaluation/" + Path(prediction_ref["path"]).relative_to(candidate_root).as_posix()
            payload = archive.read(member)
            assert hashlib.sha256(payload).hexdigest() == prediction_ref["sha256"]
            model_rows = json.loads(payload)
            assert len(model_rows) == len(frozen)
            assert {row["seed"] for row in model_rows} == {seed}
            assert {row["event_id"] for row in model_rows} == set(frozen)
            for row in model_rows:
                trial = frozen[row["event_id"]]
                assert (row["subject"], row["label"]) == (trial["subject"], trial["label"])
            model_subject_scores = []
            for subject in panel["development_subjects"]:
                subject_rows = [row for row in model_rows if row["subject"] == subject]
                recalls = []
                for label in panel["class_labels"].values():
                    class_rows = [row for row in subject_rows if row["label"] == label]
                    assert class_rows
                    recalls.append(sum(row["prediction"] == label for row in class_rows) / len(class_rows))
                model_subject_scores.append(sum(recalls) / len(recalls))
            model_scores.append(sum(model_subject_scores) / len(model_subject_scores))
        independently_scored = sum(model_scores) / 3
        assert assessment_index["seed_summary"]["seeds"] == [17, 42, 2026]
        assert assessment_index["seed_summary"]["mean_ba"] == pytest.approx(independently_scored)
        assert assessment_index["seed_summary"]["seed_sd"] == pytest.approx(float(np.std(model_scores)))
        assert independently_scored == pytest.approx(selection["score"])
        assert independently_scored == pytest.approx(assessment_index["selection_score"])
        assert "EEGNet" in rendered and f"{selection['score']:.4f}" in rendered
        assert "FBCSP=" not in rendered and "TS/LR=" not in rendered
        assert f"核心 CSP 锚点 macro_ba={selection['selected_receipt']['macro_ba']:.4f}" in rendered
        for entry in manifest["files"]:
            assert (
                hashlib.sha256(archive.read(entry["name"])).hexdigest()
                == entry["sha256"]
            )
            assert file_hash(delivery / entry["name"]) == entry["sha256"]
    selection = completed["outputs"]["data_evaluation"]
    plan = store.get(
        execution_owner,
        Ref.model_validate(completed["outputs"]["data_preprocessing"]["plan_ref"]),
        "plan",
    )
    result = store.status(execution_owner, job_id)
    search = service.search_service().get(OWNER, completed["search_id"])
    assert outputs.choose(search, plan, store) == selection
    assert (
        selection["quality_evaluated"] is True
        and selection["evaluation_scope"] == "development"
        and len(selection["candidate_summary"]) == len(search["candidates"])
    )
    assert selection["selected_method_ref"] == plan["request"]["methods"][0]
    assert any(
        candidate["candidate_id"] == selection["selected_candidate_id"]
        and candidate["score"] == selection["score"]
        for candidate in selection["candidate_summary"]
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
            p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and p.suffix not in {'.lock', '.db'}
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
        assert report.headers["Cache-Control"] == "private, no-cache"
        assert "开发被试平均平衡准确率" in report.text
        assert "未进行质量排名" not in report.text
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
    # Corruption invalidates the measured winner; no substitute is selected.
    victim = next(
        r
        for r in result.records
        if r["method_id"] == selection["selected_method_ref"]["id"]
    )
    artifact = next(
        a for a in victim["result"]["artifacts"] if a["name"] == "signal_V.npy"
    )
    (store.root / artifact["path"]).write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        outputs.choose(search, plan, store)
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
        source, WorkflowRequest(source_root=str(source)), tmp_path / "survey"
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
    request = WorkflowRequest(source_root=str(source), subjects=["S001"])
    survey = dataset.inspect(source, request, tmp_path / "survey")
    (source / "S001/S001R04.edf").write_bytes(b"changed")
    with pytest.raises(ValueError, match="源文件已变化"):
        dataset.check_sources(survey)


def test_source_boundary_and_request_validation(source, tmp_path):
    request = WorkflowRequest(
        source_root=str(source), search_budget={"max_candidates": 1}
    )
    assert WorkflowRequest(source_root=str(source), tmin=-0.2, tmax=6).tmin == -0.2
    with pytest.raises(ValueError, match="允许范围"):
        dataset.allowed_source(request, [tmp_path / "elsewhere"], [])
    with pytest.raises(ValueError, match="分离"):
        dataset.allowed_source(request, [source], [source / "outputs"])
    for invalid in [
        {"subjects": ["../escape"]},
        {"runs": [4, 8]},
        {"runs": [3]},
        {"runs": [4, 4]},
        {"tmin": 2, "tmax": 1},
    ]:
        with pytest.raises(ValueError):
            WorkflowRequest(source_root=str(source), **invalid)


@pytest.mark.asyncio
async def test_single_subject_cannot_produce_cross_subject_evaluation(source, tmp_path):
    prep = PreprocessingService(tmp_path / "preprocessing")
    service = WorkflowService(tmp_path / "workflows", [source], prep)
    service.registry = build_agent_registry(preprocessing=prep, workflow=service)
    state = service.create(
        OWNER,
        WorkflowRequest(source_root=str(source), subjects=["S001"]),
        start=False,
    )
    assert state["status"] == "queued"
    # A fresh service instance resumes the persisted queue after restart.
    service = WorkflowService(tmp_path / "workflows", [source], prep)
    service.registry = build_agent_registry(preprocessing=prep, workflow=service)
    await service.resume()
    result = await finish(service, state["id"])
    assert result["status"] == "failed"
    assert result["stages"][2]["status"] == "failed"
    assert "subject" in result["error"].lower() or "被试" in result["error"]
    assert "data_evaluation" not in result["outputs"]
    assert not (service.folder(state["id"]) / "training-data.zip").exists()
    await service.close()
