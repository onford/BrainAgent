import json
import re
from pathlib import Path

import h5py
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.agents import build_agent_registry
from app.agents.orchestrator import Orchestrator
from app.agents.planner.agent import PlannerAgent
from app.llm.client import LLMClient
from app.main import create_app
from app.preprocessing.invasive.schemas import InvasivePlanRequest, InvasiveRunRequest, NWBInspectRequest
from app.preprocessing.service import PreprocessingService
from app.runtime.context import AgentContext
from app.runtime.state import RunStatus
from tests.fakes import ScriptedLLMClient


OWNER = "invasive-test-owner"
KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


def make_nwb(path: Path, *, include_units: bool = True) -> Path:
    with h5py.File(path, "w") as root:
        root.attrs["nwb_version"] = "2.8.0"
        string = h5py.string_dtype("utf-8")
        root.create_dataset("identifier", data="tiny-nwb", dtype=string)
        root.create_dataset("session_id", data="session-1", dtype=string)
        root.create_dataset("session_description", data="Neuropixels visual behavior fixture", dtype=string)
        subject = root.create_group("general/subject")
        subject.create_dataset("subject_id", data="mouse-1", dtype=string)
        device = root.create_group("general/devices/Neuropixels-1")
        device.attrs["description"] = "Neuropixels 1.0 probe"

        electrical = root.create_group("acquisition/raw_probe")
        electrical.attrs["neurodata_type"] = "ElectricalSeries"
        voltage = electrical.create_dataset("data", shape=(30_000, 4), dtype="int16", chunks=(1000, 4), compression="gzip")
        voltage.attrs["unit"] = "volts"
        starting = electrical.create_dataset("starting_time", data=0.0)
        starting.attrs["rate"] = 30_000.0

        behavior = root.create_group("processing/behavior/running_speed")
        behavior.attrs["neurodata_type"] = "TimeSeries"
        timestamps = np.linspace(0, 10, 101)
        behavior.create_dataset("timestamps", data=timestamps)
        behavior.create_dataset("data", data=np.sin(timestamps)[:, None])
        emg = root.create_group("acquisition/preprocessed_emg")
        for name, values in {
            "flexor": np.sin(timestamps),
            "extensor": np.cos(timestamps),
        }.items():
            series = emg.create_group(name)
            series.attrs["neurodata_type"] = "TimeSeries"
            series.create_dataset("timestamps", data=timestamps)
            series.create_dataset("data", data=values)
        evaluation = root.create_group("acquisition/eval_mask")
        evaluation.attrs["neurodata_type"] = "TimeSeries"
        evaluation.create_dataset("timestamps", data=timestamps)
        evaluation.create_dataset("data", data=np.arange(timestamps.size) >= 80)

        trials = root.create_group("intervals/trials")
        trials.create_dataset("start_time", data=[0.0, 5.0])
        trials.create_dataset("stop_time", data=[4.0, 9.0])

        if include_units:
            units = root.create_group("units")
            good = np.arange(0.05, 9.95, 0.1)
            sparse = np.asarray([1.0])
            units.create_dataset("id", data=[11, 42])
            units.create_dataset("spike_times", data=np.concatenate([good, sparse]))
            units.create_dataset("spike_times_index", data=[good.size, good.size + sparse.size])
            units.create_dataset("quality", data=np.asarray(["good", "noise"], dtype=object), dtype=string)
    return path


class OmittedDelegateFieldsLLM(LLMClient):
    """Mimics the provider output that triggered the frontend regression."""

    def __init__(self, source: Path) -> None:
        self.source = source
        self.calls = 0

    async def chat(self, messages: list[dict[str, str]]) -> str:
        completed = messages[-1]["content"]
        self.calls += 1
        if self.calls == 1:
            response = {
                "action": "delegate",
                "rationale": "先读取 NWB 结构和 metadata",
                "inputs": {
                    "action": "invasive_inspect",
                    "request": {"path": str(self.source)},
                },
            }
        elif self.calls == 2:
            snapshot_id = re.search(
                r"snapshot_ref.*?'id': '([a-f0-9]{64})'", completed, re.DOTALL
            )
            assert snapshot_id
            ref = {"id": snapshot_id.group(1), "sha256": snapshot_id.group(1)}
            response = {
                "action": "delegate",
                "rationale": "根据已发布 Units 规划解码预处理",
                "inputs": {
                    "action": "invasive_plan",
                    "request": {
                        "snapshot_ref": ref,
                        "task": {
                            "description": "生成用于行为解码的 T×N 神经活动矩阵",
                            "validation": "baseline validation",
                        },
                        "transform": {"bin_size_s": 0.02, "run_baseline": True},
                    },
                },
            }
        elif self.calls == 3:
            plan_id = re.search(
                r"plan_ref.*?'id': '([a-f0-9]{64})'", completed, re.DOTALL
            )
            assert plan_id
            ref = {"id": plan_id.group(1), "sha256": plan_id.group(1)}
            response = {
                "action": "delegate",
                "rationale": "计划可执行，运行预处理和 baseline",
                "inputs": {"action": "invasive_run", "request": {"plan_ref": ref}},
            }
        else:
            response = {
                "action": "finish",
                "rationale": "预处理已完成",
                "final_answer": "已生成 20 ms T×N 矩阵并完成 baseline 验证。",
            }
        return json.dumps(response, ensure_ascii=False)


def test_bounded_survey_plan_qc_alignment_transform_validate_and_report(tmp_path):
    source = make_nwb(tmp_path / "tiny.nwb")
    service = PreprocessingService(tmp_path / "output", [tmp_path])
    snapshot_ref, snapshot = service.inspect_invasive(
        OWNER, NWBInspectRequest(path=str(source), max_scalar_reads=32)
    )
    assert snapshot.modality == "neuropixels"
    assert snapshot.inspected_values <= 32
    assert next(item for item in snapshot.collections if item.id == "units").shape[1] == 2
    raw = next(item for item in snapshot.collections if item.representation == "raw_voltage")
    assert raw.shape == [30_000, 4] and raw.chunks == [1000, 4]

    plan_ref, plan = service.plan_invasive(
        OWNER,
        InvasivePlanRequest(
            snapshot_ref=snapshot_ref,
            task="decode running speed",
            transform={"bin_size_s": 0.1, "target_series_path": "/processing/behavior/running_speed/data"},
        ),
    )
    assert plan.executable and plan.strategy == "consume_released_derivative"
    sorting = next(step for step in plan.steps if step.id == "spike_sorting")
    assert sorting.status == "skip" and "Units/spike_times" in sorting.reason

    result_ref, result = service.run_invasive(OWNER, InvasiveRunRequest(plan_ref=plan_ref))
    assert result_ref.id == result_ref.sha256 and result["status"] == "completed"
    output = Path(result["output_dir"])
    matrix = np.load(output / "neural-matrix.npy", allow_pickle=False)
    tensor = np.load(output / "trial-aligned.npy", allow_pickle=False)
    assert matrix.shape[1] == 1
    assert tensor.shape[0] == 2 and tensor.shape[2] == 1
    decisions = json.loads((output / "qc-decisions.json").read_text())
    assert decisions[0]["retained"] is True
    assert decisions[1]["retained"] is False
    assert "upstream_quality=noise" in decisions[1]["reasons"]
    validation = json.loads((output / "validation.json").read_text())
    assert validation["unit_retention_ratio"] == 0.5
    assert validation["baseline"]["status"] == "completed"
    assert validation["baseline"]["split"] == "nwb_eval_mask"
    config = json.loads((output / "preprocessing-config.json").read_text())
    assert config["strategy"] == "consume_released_derivative"
    assert (output / "report.md").is_file() and (output / "manifest.json").is_file()


@pytest.mark.asyncio
async def test_exact_prompt_shape_runs_end_to_end_when_planner_omits_delegate_fields(
    tmp_path,
):
    source = make_nwb(tmp_path / "session_behavior+ecephys.nwb")
    service = PreprocessingService(tmp_path / "output", [tmp_path])
    llm = OmittedDelegateFieldsLLM(source)
    registry = build_agent_registry(preprocessing=service)
    registry.register(PlannerAgent(llm))
    prompt = (
        f"请处理这个 NWB 文件：{source}。\n"
        "任务是生成用于行为解码的 T×N 神经活动矩阵，使用 20 ms bin，并运行 baseline 验证。"
    )

    context = await Orchestrator(registry).execute(
        AgentContext(owner_id=OWNER, session_id="frontend-regression", user_message=prompt)
    )

    assert context.status is RunStatus.COMPLETED
    assert context.error is None
    assert llm.calls == 4
    assert [result.output["execution_status"] for result in context.agent_results] == [
        "surveyed",
        "invasive_plan_ready",
        "completed",
    ]
    assert context.agent_results[1].output["plan"]["task"] == (
        "生成用于行为解码的 T×N 神经活动矩阵; baseline validation"
    )
    completed = context.agent_results[-1].output
    assert completed["final_shapes"]["neural_matrix"][1] == 1
    assert completed["validation"]["baseline"]["status"] == "completed"
    assert completed["invasive_url"].startswith("/invasive?id=")


def test_raw_voltage_requires_evidence_and_does_not_choose_universal_sorter(tmp_path):
    source = make_nwb(tmp_path / "raw-only.nwb", include_units=False)
    service = PreprocessingService(tmp_path / "output", [tmp_path])
    snapshot_ref, _ = service.inspect_invasive(OWNER, NWBInspectRequest(path=str(source)))
    _, plan = service.plan_invasive(
        OWNER,
        InvasivePlanRequest(snapshot_ref=snapshot_ref, task="prepare spikes from raw voltage"),
    )
    assert plan.strategy == "reprocess_from_raw" and not plan.executable
    assert any(step.operation == "literature_and_code_search" for step in plan.steps)
    assert any(step.operation == "filter_artifact_reference_detect_sort" and step.status == "blocked" for step in plan.steps)


def test_falcon_units_are_threshold_crossings_not_single_units(tmp_path):
    folder = tmp_path / "falcon" / "000941"
    folder.mkdir(parents=True)
    source = make_nwb(folder / "session_behavior+ecephys.nwb")
    service = PreprocessingService(tmp_path / "output", [tmp_path])
    snapshot_ref, snapshot = service.inspect_invasive(
        OWNER, NWBInspectRequest(path=str(source))
    )
    assert snapshot.modality == "intracortical_array"
    assert next(item for item in snapshot.collections if item.id == "units").representation == "threshold_crossings"
    _, plan = service.plan_invasive(
        OWNER,
        InvasivePlanRequest(snapshot_ref=snapshot_ref, task="decode sixteen EMG targets"),
    )
    assert plan.input_representation == "threshold_crossings"
    qc = next(step for step in plan.steps if step.id == "unit_qc")
    assert "refractory-period rejection is not applicable" in qc.reason


def test_source_must_be_under_an_allowed_input_root(tmp_path):
    source = make_nwb(tmp_path / "tiny.nwb")
    service = PreprocessingService(tmp_path / "output", [tmp_path / "different"])
    try:
        service.inspect_invasive(OWNER, NWBInspectRequest(path=str(source)))
    except ValueError as exc:
        assert "PREPROCESSING_INPUT_ROOTS" in str(exc)
    else:
        raise AssertionError("source outside the allowed roots was accepted")


def test_agent_omission_sentinels_and_user_path_are_normalized():
    request = NWBInspectRequest.model_validate(
        {
            "path": "Users/example/session\\_behavior+ecephys.nwb",
            "hash_source": "not_provided",
            "max_scalar_reads": "not_provided",
        }
    )
    assert request.path == "/Users/example/session_behavior+ecephys.nwb"
    assert request.hash_source is False and request.max_scalar_reads == 4096
    plan = InvasivePlanRequest.model_validate(
        {
            "snapshot_ref": {"id": "f" * 64, "sha256": "f" * 64},
            "task": "prepare model input",
            "qc": "not_provided",
            "transform": "not_provided",
            "method_profile": "not_provided",
        }
    )
    assert plan.method_profile is None and plan.transform.bin_size_s == 0.02

    object_task = InvasivePlanRequest.model_validate(
        {
            "snapshot_ref": {"id": "e" * 64, "sha256": "e" * 64},
            "task": {
                "description": "Generate a T×N neural activity matrix",
                "validation": "baseline validation",
            },
            "qc": {"min_firing_rate_hz": "not_provided"},
            "transform": {
                "bin_size_s": "20 ms",
                "run_baseline": "not_provided",
            },
        }
    )
    assert object_task.task == (
        "Generate a T×N neural activity matrix; baseline validation"
    )
    assert object_task.qc.min_firing_rate_hz == 0.01
    assert object_task.transform.bin_size_s == 0.02
    assert object_task.transform.run_baseline is True


def test_api_exposes_invasive_inspect_plan_and_run(tmp_path):
    source = make_nwb(tmp_path / "api.nwb")
    settings = Settings(
        database_url_override=f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}",
        brain_agent_credential_encryption_key=KEY,
        preprocessing_root=str(tmp_path / "output"),
        preprocessing_input_roots=[str(tmp_path)],
        workflow_root=str(tmp_path / "workflows"),
        workflow_input_roots=[str(tmp_path)],
    )
    headers = {"X-Brain-Agent-Owner-ID": OWNER}
    with TestClient(create_app(settings, ScriptedLLMClient([]))) as client:
        survey = client.post(
            "/api/preprocessing/invasive/inspect",
            json={"path": str(source)},
            headers=headers,
        )
        assert survey.status_code == 201, survey.text
        planned = client.post(
            "/api/preprocessing/invasive/plans",
            json={"snapshot_ref": survey.json()["snapshot_ref"], "task": "prepare model input"},
            headers=headers,
        )
        assert planned.status_code == 201 and planned.json()["plan"]["executable"] is True
        run = client.post(
            "/api/preprocessing/invasive/runs",
            json={"plan_ref": planned.json()["plan_ref"]},
            headers=headers,
        )
        assert run.status_code == 201, run.text
        assert run.json()["result"]["status"] == "completed"
        assert run.json()["result"]["plan_ref"] == planned.json()["plan_ref"]
        assert run.json()["result"]["snapshot_ref"] == survey.json()["snapshot_ref"]
        assert run.json()["result"]["final_shapes"]["aligned_target"][1] == 2
        assert run.json()["result"]["final_shapes"]["evaluation_mask"][0] > 0
        result_id = run.json()["result_ref"]["id"]
        sources = client.get("/api/preprocessing/invasive/sources", headers=headers)
        assert sources.status_code == 200
        assert str(tmp_path.resolve()) in sources.json()["allowed_roots"]
        listed = client.get("/api/preprocessing/invasive/results", headers=headers)
        assert listed.status_code == 200 and listed.json()[0]["result_ref"]["id"] == result_id
        detail = client.get(
            f"/api/preprocessing/invasive/results/{result_id}/detail", headers=headers
        )
        assert detail.status_code == 200
        assert detail.json()["plan"]["transform"]["bin_size_s"] == 0.02
        assert detail.json()["snapshot"]["modality"] == "neuropixels"
        assert any(item["name"] == "report.md" for item in detail.json()["artifacts"])
        report = client.get(
            f"/api/preprocessing/invasive/results/{result_id}/artifacts/report.md",
            headers=headers,
        )
        assert report.status_code == 200 and "Invasive preprocessing report" in report.text
        assert client.get(
            f"/api/preprocessing/invasive/results/{result_id}",
            headers={"X-Brain-Agent-Owner-ID": "different-owner"},
        ).status_code == 404
