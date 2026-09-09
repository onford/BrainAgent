import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from uuid import uuid4

from app.preprocessing.schemas import Ref
from app.preprocessing.storage import file_hash, within, write_json
from app.preprocessing.storage import Storage
from app.runtime.context import AgentContext, AgentTask
from app.runtime.result import AgentResult
from . import artifacts, dataset, outputs
from .records import (
    check_format,
    publish_stage,
    validate_stage,
    write_index,
    write_readable,
)
from .contracts import STAGE_CONTRACTS
from .schemas import STAGES, STAGE_LABELS, WorkflowRequest
from .cognition import WorkflowCognition
from .cognition_contracts import ResearchSources


def now():
    return datetime.now(timezone.utc).isoformat()


class WorkflowService:
    """Domain agents use model research/design; numeric work stays in Worker."""

    def __init__(
        self, root, input_roots, preprocessing, llm=None, tools=None, source_reader=None
    ):
        self.root = Path(root).resolve()
        self.input_roots = [Path(p).resolve() for p in input_roots]
        self.preprocessing = preprocessing
        self.llm, self.tools, self.source_reader = llm, tools, source_reader
        self.registry = None
        self.searches = None
        self.tasks = {}
        self.artifact_cache = {}
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
        if state.get("schema_version") == "1":
            state["outputs"] = {
                name: json.loads(
                    within(self.folder(identity), STAGE_CONTRACTS[name][1]).read_text(
                        encoding="utf-8"
                    )
                )
                for name in state["outputs"]
            }
        return state

    def search_service(self):
        if self.searches is None:
            from app.search.service import SearchService

            self.searches = SearchService(self.root.parent / "offline-search", self)
        return self.searches

    def execution_store(self, state):
        if state.get("search_id"):
            searches = self.search_service()
            searches.get(state["owner"], state["search_id"])
            return Storage(
                searches.folder(state["search_id"]) / "engine"
            ), "offline-search"
        return self.preprocessing.store, state["owner"]

    def save(self, state):
        state["updated_at"] = now()
        if state.get("schema_version") == "1":
            write_index(self.folder(state["id"]), state)
        state["artifacts"] = artifacts.local_files(
            self.folder(state["id"]), state, state.get("artifacts", [])
        )
        snapshot = dict(state)
        if state.get("schema_version") == "1":
            snapshot["outputs"] = {
                name: STAGE_CONTRACTS[name][1] for name in state["outputs"]
            }
        write_json(self.folder(state["id"]) / "workflow.json", snapshot)

    def describe(self, owner, identity):
        state = self.get(owner, identity)
        store, execution_owner = self.execution_store(state)
        # Inventory retains previously published hashes.
        known = {a["name"]: a for a in self.artifact_cache.get(identity, [])}
        known.update({a["name"]: a for a in state["artifacts"]})
        entries = artifacts.local_files(self.folder(identity), state, known.values())
        state["artifacts"] = sorted(
            entries
            + artifacts.worker_files(
                store,
                execution_owner,
                state.get("preprocessing_job"),
                known.values(),
            ),
            key=lambda a: a["name"],
        )
        self.artifact_cache[identity] = state["artifacts"]
        if state.get("search_id"):
            searches = self.search_service()
            search = searches.describe(owner, state["search_id"])
            state["search_summary"] = {
                k: search[k]
                for k in (
                    "id",
                    "status",
                    "message",
                    "usage",
                    "budget",
                    "selected_candidate_id",
                )
            }
            search_root = searches.folder(state["search_id"])
            index_path = search_root / "files.json"
            index = (
                {
                    item["name"]: item
                    for item in json.loads(index_path.read_text(encoding="utf-8"))[
                        "files"
                    ]
                }
                if index_path.exists()
                else {}
            )
            state["artifacts"].extend(
                {
                    **entry,
                    "name": "preprocessing/search/" + entry["name"],
                    "bytes": index.get(entry["name"], {}).get(
                        "bytes", within(search_root, entry["name"]).stat().st_size
                    ),
                    "sha256": index.get(entry["name"], {}).get("sha256"),
                }
                for entry in search["artifacts"]
            )
        return state

    def list(self, owner):
        records = []
        for path in self.root.glob("*/workflow.json"):
            state = json.loads(path.read_text(encoding="utf-8"))
            if state["owner"] == owner:
                records.append(self.get(owner, state["id"]))
        return sorted(records, key=lambda s: s["created_at"], reverse=True)

    def create(self, owner, request, *, start=True):
        dataset.allowed_source(
            request, self.input_roots, [self.root, self.preprocessing.store.root]
        )
        state = {
            "schema_version": "1",
            "engine": "diagnostic-policy-search-v2",
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
        self.require_current(self.get(owner, identity))
        if identity not in self.tasks or self.tasks[identity].done():
            self.tasks[identity] = asyncio.create_task(self.run(owner, identity))

    def require_current(self, state):
        if state.get("engine") != "diagnostic-policy-search-v2":
            raise ValueError(
                "此运行的执行协议与当前版本不同，请新建运行；已有产物保持只读"
            )
        check_format(self.folder(state["id"]))

    async def resume(self):
        for path in self.root.glob("*/workflow.json"):
            state = json.loads(path.read_text(encoding="utf-8"))
            if state["status"] in {"queued", "running", "interrupted"}:
                try:
                    self.start(state["owner"], state["id"])
                except (ValueError, OSError, KeyError):
                    continue

    async def close(self):
        running = [t for t in self.tasks.values() if not t.done()]
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)

    def retry(self, owner, identity):
        state = self.get(owner, identity)
        self.require_current(state)
        if state["status"] not in {"failed", "interrupted"}:
            raise ValueError("只有失败或中断的流程可以重试")
        if state.get("search_id"):
            searches = self.search_service()
            search = searches.get(owner, state["search_id"])
            if search["status"] in {"failed", "interrupted", "cancelled"}:
                searches.retry(owner, search["id"])
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
        self.require_current(state)
        context = AgentContext(
            owner_id=owner,
            session_id=f"workflow-{identity}",
            user_message="Prepare EEG training data",
            metadata={"workflow_id": identity},
        )
        try:
            check_format(self.folder(identity))
            state["status"] = "running"
            self.save(state)
            for stage in state["stages"]:
                name = stage["name"]
                if stage["status"] == "completed":
                    context.shared_memory[name] = state["outputs"][name]
                    continue
                stage.update(status="running", started_at=now(), error=None)
                # Files from a failed attempt may be replaced by this stage.
                prefix = artifacts.STAGE_FOLDERS[name] + "/"
                state["artifacts"] = [
                    a for a in state["artifacts"] if not a["name"].startswith(prefix)
                ]
                if name == "data_delivery":
                    state["artifacts"] = [
                        a
                        for a in state["artifacts"]
                        if a["name"] != "training-data.zip"
                    ]
                self.artifact_cache.pop(identity, None)
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
                # Validate every agent result at the orchestration boundary too.
                # Invalid/missing fields cannot enter shared memory or complete a stage.
                result.output = publish_stage(
                    self.folder(identity), name, result.output
                )
                context.record_result(result)
                # A stage may persist its background preprocessing job before waiting.
                latest = self.get(owner, identity)
                state["events"] = latest["events"]
                if latest.get("search_id"):
                    state["search_id"] = latest["search_id"]
                if latest.get("preprocessing_job"):
                    state["preprocessing_job"] = latest["preprocessing_job"]
                state["outputs"][name] = result.output
                stage.update(status="completed", finished_at=now())
                self.event(state, name, "completed", stage["label"] + "完成")
                self.save(state)
            state["status"] = "completed"
            self.save(state)
        except asyncio.CancelledError:
            state.update(status="interrupted", error="服务中断，重新启动后继续")
            latest = self.get(owner, identity)
            state["events"] = latest["events"]
            if latest.get("search_id"):
                state["search_id"] = latest["search_id"]
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
            state["events"] = latest["events"] + [
                e for e in state["events"] if e not in latest["events"]
            ]
            if latest.get("search_id"):
                state["search_id"] = latest["search_id"]
            if latest.get("preprocessing_job"):
                state["preprocessing_job"] = latest["preprocessing_job"]
            self.save(state)
        return state

    async def execute_stage(self, name, owner, identity):
        state = self.get(owner, identity)
        folder = self.folder(identity)
        check_format(folder)
        request = WorkflowRequest.model_validate(state["request"])
        cognition = WorkflowCognition(self, state, name)
        if name == "data_survey":
            root = dataset.allowed_source(
                request, self.input_roots, [self.root, self.preprocessing.store.root]
            )
            checkpoint = folder / "survey/survey.json"
            if checkpoint.exists():
                value = validate_stage(
                    name, json.loads(checkpoint.read_text(encoding="utf-8"))
                )
                await asyncio.to_thread(dataset.check_sources, value)
            else:
                value = await asyncio.to_thread(
                    dataset.inspect, root, request, folder / "survey"
                )
                # Persist the measured input before remote research can fail.
                # A retry cannot silently combine new source bytes with old findings.
                write_readable(checkpoint, value)
            cognition.progress(
                f"路径调研发现 {value['available_subjects']} 名被试；本轮选择 {len(value['selected_subjects'])} 名、{len(value['records'])} 条记录，开始资料核对"
            )
            findings = await cognition.research(value)
            sources = cognition.load("survey/sources.json", ResearchSources)
            value["profile"] = dict(value["profile"])
            value["profile"]["unknown_fields"] = list(
                value["profile"]["unknown_fields"]
            )
            for item in findings.metadata:
                value["profile"][item.field] = item.value or "unknown"
                if item.value is None:
                    value["profile"]["unknown_fields"].append(item.field)
            value["profile"]["profile_reviewed"] = now().split("T")[0]
            value["profile"]["references"] = [
                {"title": d.title, "url": d.url} for d in sources.documents
            ]
            value["profile"]["literature_status"] = findings.summary
            value["evidence"] = [
                {
                    "source_url": d.url,
                    "locator": "survey/sources.json#" + d.id,
                    "type": "retrieved_" + d.kind,
                }
                for d in sources.documents
            ]
            from .survey_reporting import render_survey_reports

            await asyncio.to_thread(render_survey_reports, folder / "survey", value)
        elif name == "data_collection":
            review = await cognition.collection_review(state["outputs"]["data_survey"])
            value = await asyncio.to_thread(
                dataset.collect,
                state["outputs"]["data_survey"],
                folder / "collection",
                identity,
                self.preprocessing,
                owner,
            )
            value["adaptations"].extend(review.limitations)
        elif name == "data_preprocessing":
            value = await self.preprocess(state, request)
        elif name == "data_evaluation":
            search = self.search_service().get(owner, state["search_id"])
            store, execution_owner = self.execution_store(state)
            prep = state["outputs"]["data_preprocessing"]
            plan = store.get(
                execution_owner, Ref.model_validate(prep["plan_ref"]), "plan"
            )
            value = await asyncio.to_thread(outputs.choose, search, plan, store)
        elif name == "data_report":
            await cognition.narrative()
            value = await asyncio.to_thread(
                outputs.report, state, folder / "report", self.preprocessing.store
            )
        elif name == "data_delivery":
            store, execution_owner = self.execution_store(state)
            delivery_state = {**state, "owner": execution_owner}
            value = await asyncio.to_thread(
                outputs.deliver, delivery_state, folder / "delivery", store
            )
        else:
            raise ValueError("unknown workflow stage")
        return AgentResult(
            agent_name=name,
            success=True,
            output=validate_stage(name, value),
            metadata={"workflow_id": identity, "stage_status": "completed"},
        )

    async def preprocess(self, state, request):
        owner = state["owner"]
        searches = self.search_service()
        identity = state.get("search_id")
        if identity is None:
            from app.search.contracts import SearchRequest

            search = searches.create(
                owner,
                SearchRequest(
                    workflow_id=state["id"],
                    seed=request.seed,
                    budget=request.search_budget,
                ),
                start=False,
            )
            identity = state["search_id"] = search["id"]
            self.save(state)
        search = searches.get(owner, identity)
        if search["status"] in {"preparing", "running", "interrupted"}:
            searches.start(owner, identity)
        last_progress = None
        while search["status"] in {"preparing", "running", "interrupted"}:
            progress = (
                search["phase"],
                search["usage"]["candidates"],
                search["message"],
            )
            if progress != last_progress:
                self.event(state, "data_preprocessing", "running", search["message"])
                self.save(state)
                last_progress = progress
            await asyncio.sleep(1)
            search = searches.get(owner, identity)
            task = searches.tasks.get(identity)
            if (
                task is not None
                and task.done()
                and search["status"] in {"preparing", "running", "interrupted"}
            ):
                if task.cancelled():
                    raise ValueError("预处理搜索已中断")
                if task.exception() is not None:
                    raise ValueError(
                        "预处理搜索未能保存最终状态：" + str(task.exception())
                    )
                # Another supervisor may own this search. Only an unlocked root
                # proves that the recorded active state has no running writer.
                import portalocker

                try:
                    with portalocker.Lock(
                        searches.folder(identity) / "search.lock", timeout=0
                    ):
                        raise ValueError("预处理搜索进程已退出，未发布完整结果")
                except portalocker.exceptions.LockException:
                    pass
        task = searches.tasks.get(identity)
        if task is not None and not task.done():
            await asyncio.shield(task)
            search = searches.get(owner, identity)
        if (
            search["status"] not in {"completed", "stopped"}
            or not search["selected_candidate_id"]
        ):
            raise ValueError(
                "预处理搜索未产生可交付方案："
                + (search["error"] or search["stop_reason"] or search["status"])
            )
        selected = next(
            c
            for c in search["candidates"]
            if c["id"] == search["selected_candidate_id"]
        )
        store, execution_owner = self.execution_store(state)
        result = store.status(execution_owner, selected["job_id"])
        plan = store.get(execution_owner, result.plan_ref, "plan")
        state["preprocessing_job"] = result.job_id
        self.save(state)
        write_readable(self.folder(state["id"]) / "preprocessing/plan.json", plan)
        write_readable(
            self.folder(state["id"]) / "preprocessing/result.json",
            result.model_dump(mode="json"),
        )
        record_positions = {
            (r["method_ref"]["id"], r["record_id"]): i
            for i, r in enumerate(plan["records"])
        }
        methods = []
        for ref in plan["request"]["methods"]:
            method = store.get(execution_owner, Ref.model_validate(ref), "method")
            methods.append(
                {"ref": ref, "title": method["title"], "recipe": method["recipe"]}
            )
        return {
            "search_id": identity,
            "execution_status": result.status,
            "job_id": result.job_id,
            "plan_ref": result.plan_ref.model_dump(),
            "completed": result.completed,
            "total": result.total,
            "methods": methods,
            "records": [
                {
                    "record_id": r["record_id"],
                    "method_id": r["method_id"],
                    "status": r["status"],
                    "attempt": r["attempt"],
                    "artifact_root": (
                        f"preprocessing/runs/{result.job_id}/"
                        f"r{record_positions[(r['method_id'], r['record_id'])]:04}/a{r['attempt']}"
                    ),
                    **(
                        {
                            "events_before": r["result"]["delta"]["events_before"],
                            "events_retained": r["result"]["delta"]["events_retained"],
                            "shape": r["result"]["delta"]["after"]["shape"],
                        }
                        if r.get("result")
                        else {"error": r.get("error")}
                    ),
                }
                for r in result.records
            ],
        }

    def artifact(self, owner, identity, name):
        state = self.describe(owner, identity)
        entry = next((a for a in state["artifacts"] if a["name"] == name), None)
        if entry is None:
            raise KeyError("artifact not found")
        if name.startswith("preprocessing/search/"):
            path = self.search_service().artifact(
                owner, state["search_id"], name.removeprefix("preprocessing/search/")
            )
        elif name.startswith("preprocessing/runs/"):
            store, _ = self.execution_store(state)
            path = within(store.root, name.removeprefix("preprocessing/"))
        else:
            path = within(self.folder(identity), name)
        if not path.is_file() or (
            entry["sha256"] and file_hash(path) != entry["sha256"]
        ):
            raise ValueError("产物完整性核验失败")
        return path
