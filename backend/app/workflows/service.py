import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from uuid import uuid4

from app.preprocessing.methods import baseline_methods
from app.preprocessing.schemas import PlanRequest, Ref
from app.preprocessing.storage import file_hash, within, write_json
from app.runtime.context import AgentContext, AgentTask
from app.runtime.result import AgentResult
from . import dataset, outputs
from .schemas import STAGES, STAGE_LABELS, WorkflowRequest


def now():
    return datetime.now(timezone.utc).isoformat()


class WorkflowService:
    """Each stage calls its registered domain agent; numeric work stays in Worker."""

    def __init__(self, root, input_roots, preprocessing):
        self.root = Path(root).resolve()
        self.input_roots = [Path(p).resolve() for p in input_roots]
        self.preprocessing = preprocessing
        self.registry = None
        self.tasks = {}
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root not in preprocessing.allowed_roots:
            preprocessing.allowed_roots.append(self.root)

    def folder(self, identity):
        if not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise KeyError("workflow not found")
        return within(self.root, identity)

    def get(self, owner, identity):
        path = self.folder(identity) / "workflow.json"
        if not path.is_file():
            raise KeyError("workflow not found")
        state = json.loads(path.read_text(encoding="utf-8"))
        if state["owner"] != owner:
            raise KeyError("workflow not found")
        return state

    def save(self, state):
        state["updated_at"] = now()
        write_json(self.folder(state["id"]) / "workflow.json", state)

    def list(self, owner):
        records = []
        for path in self.root.glob("*/workflow.json"):
            state = json.loads(path.read_text(encoding="utf-8"))
            if state["owner"] == owner:
                records.append(state)
        return sorted(records, key=lambda s: s["created_at"], reverse=True)

    def create(self, owner, request, *, start=True):
        dataset.allowed_source(
            request, self.input_roots, [self.root, self.preprocessing.store.root]
        )
        state = {
            "id": uuid4().hex,
            "owner": owner,
            "status": "queued",
            "created_at": now(),
            "request": request.model_dump(mode="json"),
            "stages": [
                {"name": name, "label": label, "status": "pending"}
                for name, label in zip(STAGES, STAGE_LABELS)
            ],
            "outputs": {},
            "events": [],
            "artifacts": [],
            "error": None,
        }
        self.save(state)
        if start:
            self.start(owner, state["id"])
        return state

    def start(self, owner, identity):
        if identity not in self.tasks or self.tasks[identity].done():
            self.tasks[identity] = asyncio.create_task(self.run(owner, identity))

    async def resume(self):
        for path in self.root.glob("*/workflow.json"):
            state = json.loads(path.read_text(encoding="utf-8"))
            if state["status"] in {"queued", "running", "interrupted"}:
                self.start(state["owner"], state["id"])

    async def close(self):
        running = [t for t in self.tasks.values() if not t.done()]
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)

    def retry(self, owner, identity):
        state = self.get(owner, identity)
        if state["status"] not in {"failed", "interrupted"}:
            raise ValueError("只有失败或中断的流程可以重试")
        job = state.get("preprocessing_job")
        if job and self.preprocessing.store.status(owner, job).status in {
            "failed",
            "partial",
            "cancelled",
        }:
            self.preprocessing.store.control(owner, job, "retry")
        state.update(status="queued", error=None)
        self.save(state)
        self.start(owner, identity)
        return state

    def event(self, state, stage, status, message):
        state["events"].append(
            {"time": now(), "agent": stage, "status": status, "message": message}
        )

    async def run(self, owner, identity):
        state = self.get(owner, identity)
        if state["status"] == "completed":
            return state
        context = AgentContext(
            owner_id=owner,
            session_id=f"workflow-{identity}",
            user_message="Prepare EEG training data",
            metadata={"workflow_id": identity},
        )
        try:
            state["status"] = "running"
            self.save(state)
            for stage in state["stages"]:
                name = stage["name"]
                if stage["status"] == "completed":
                    context.shared_memory[name] = state["outputs"][name]
                    continue
                stage.update(status="running", started_at=now(), error=None)
                self.event(state, name, "running", stage["label"] + "开始")
                self.save(state)
                result = await self.registry.get(name).run(
                    AgentTask(
                        instruction=stage["label"],
                        inputs={"action": "workflow_stage", "workflow_id": identity},
                    ),
                    context,
                )
                if not result.success:
                    raise ValueError(result.error or f"{name} failed")
                context.record_result(result)
                # A stage may persist its background preprocessing job before waiting.
                latest = self.get(owner, identity)
                if latest.get("preprocessing_job"):
                    state["preprocessing_job"] = latest["preprocessing_job"]
                state["outputs"][name] = result.output
                stage.update(status="completed", finished_at=now())
                self.event(state, name, "completed", stage["label"] + "完成")
                self.save(state)
            state["status"] = "completed"
            folder = self.folder(identity)
            state["artifacts"] = [
                {
                    "name": p.relative_to(folder).as_posix(),
                    "bytes": p.stat().st_size,
                    "sha256": file_hash(p),
                }
                for p in sorted(folder.rglob("*"))
                if p.is_file()
                and p.name != "workflow.json"
                and not p.is_relative_to(folder / "collection/bids")
            ]
            self.save(state)
        except asyncio.CancelledError:
            state.update(status="interrupted", error="服务中断，重新启动后继续")
            latest = self.get(owner, identity)
            if latest.get("preprocessing_job"):
                state["preprocessing_job"] = latest["preprocessing_job"]
            self.save(state)
            raise
        except Exception as exc:
            # Server logs retain details; the persistent stage error is useful for retry.
            import logging

            logging.getLogger(__name__).exception(
                "workflow_failed workflow=%s", identity
            )
            state.update(status="failed", error=str(exc))
            for stage in state["stages"]:
                if stage["status"] == "running":
                    stage.update(status="failed", error=str(exc))
                    self.event(state, stage["name"], "failed", str(exc))
            latest = self.get(owner, identity)
            if latest.get("preprocessing_job"):
                state["preprocessing_job"] = latest["preprocessing_job"]
            self.save(state)
        return state

    async def execute_stage(self, name, owner, identity):
        state = self.get(owner, identity)
        folder = self.folder(identity)
        request = WorkflowRequest.model_validate(state["request"])
        if name == "data_survey":
            root = dataset.allowed_source(
                request, self.input_roots, [self.root, self.preprocessing.store.root]
            )
            value = await asyncio.to_thread(
                dataset.inspect, root, request, folder / "survey"
            )
        elif name == "data_collection":
            value = await asyncio.to_thread(
                dataset.collect,
                state["outputs"]["data_survey"],
                folder / "collection",
                identity,
                self.preprocessing,
                owner,
            )
        elif name == "data_preprocessing":
            value = await self.preprocess(state, request)
        elif name == "data_evaluation":
            prep = state["outputs"]["data_preprocessing"]
            plan = self.preprocessing.store.get(
                owner, Ref.model_validate(prep["plan_ref"]), "plan"
            )
            result = self.preprocessing.store.status(owner, prep["job_id"])
            value = await asyncio.to_thread(
                outputs.choose, result, plan, self.preprocessing.store, request.seed
            )
            write_json(folder / "evaluation/selection.json", value)
        elif name == "data_report":
            value = await asyncio.to_thread(
                outputs.report, state, folder / "report", self.preprocessing.store
            )
        elif name == "data_delivery":
            value = await asyncio.to_thread(
                outputs.deliver, state, folder / "delivery", self.preprocessing.store
            )
        else:
            raise ValueError("unknown workflow stage")
        return AgentResult(
            agent_name=name,
            success=True,
            output=value,
            metadata={"workflow_id": identity, "stage_status": "completed"},
        )

    async def preprocess(self, state, request):
        owner = state["owner"]
        existing = state.get("preprocessing_job")
        if not existing:
            methods = []
            for label, lo, hi in [
                ("broadband", 1.0, 40.0),
                ("sensorimotor", 8.0, 30.0),
            ]:
                method = baseline_methods()[0].model_copy(deep=True)
                method.id = f"mne-training-{label}"
                method.title = f"MNE 训练预设 · {lo:g}–{hi:g} Hz"
                method.recipe = method.recipe[:-1]
                method.output = "epochs"
                method.mechanism = f"filter-reference-epoch:{label}"
                method.recipe[0].params.update(l_freq=lo, h_freq=hi)
                method.recipe[-1].params.update(
                    tmin=request.tmin, tmax=request.tmax, picks="$eeg_channels"
                )
                method.adaptations = [
                    "Engineering training preset, not an author pipeline; no quality ranking",
                    "Fourth-order zero-phase Butterworth on continuous EEG; average reference; epoch on task onset; no baseline subtraction",
                ]
                methods.append(self.preprocessing.register_method(owner, method))
            plan_ref, plan = await asyncio.to_thread(
                self.preprocessing.plan,
                owner,
                PlanRequest(
                    input_ref=Ref.model_validate(
                        state["outputs"]["data_collection"]["input_ref"]
                    ),
                    methods=methods,
                    mode="exploratory",
                    parameters={},
                    selection="all",
                    max_candidates=2,
                ),
            )
            write_json(
                self.folder(state["id"]) / "preprocessing/plan.json",
                plan.model_dump(mode="json"),
            )
            result = await asyncio.to_thread(self.preprocessing.submit, owner, plan_ref)
            state["preprocessing_job"] = result.job_id
            self.save(state)
        else:
            result = self.preprocessing.store.status(owner, existing)
        while result.status in {"queued", "running", "interrupted"}:
            await asyncio.sleep(1)
            result = await asyncio.to_thread(
                self.preprocessing.store.status, owner, result.job_id
            )
        if result.status not in {"completed", "partial"}:
            raise ValueError(
                "预处理未完成："
                + str(
                    [
                        (r["record_id"], r["error"])
                        for r in result.records
                        if r["status"] != "completed"
                    ]
                )
            )
        write_json(
            self.folder(state["id"]) / "preprocessing/result.json",
            result.model_dump(mode="json"),
        )
        return {
            "execution_status": result.status,
            "job_id": result.job_id,
            "plan_ref": result.plan_ref.model_dump(),
            "completed": result.completed,
            "total": result.total,
        }

    def artifact(self, owner, identity, name):
        state = self.get(owner, identity)
        entry = next((a for a in state["artifacts"] if a["name"] == name), None)
        if entry is None:
            raise KeyError("artifact not found")
        path = within(self.folder(identity), name)
        if not path.is_file() or file_hash(path) != entry["sha256"]:
            raise ValueError("产物完整性核验失败")
        return path
