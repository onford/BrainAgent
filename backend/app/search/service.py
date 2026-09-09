import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import time
from uuid import uuid4


from app.llm.client import OpenAICompatibleClient
from app.preprocessing.resources import budget as resource_budget
from app.preprocessing.schemas import PreprocessInput
from app.preprocessing.storage import digest, file_hash, within
from app.preprocessing.units import engine_hash, environment
from .catalog import BASELINE_ID, catalog, method, search_engine_hash, select
from .contracts import ActionRecord, Candidate, SearchRequest, SearchState
from .io import directory_bytes, process_memory, read, write
from .reasoning import decide, read_evidence
from .evaluation_contracts import FrozenPanel, EvaluationReceipt


def now():
    return datetime.now(timezone.utc).isoformat()


class BudgetStop(RuntimeError):
    pass


class IntegrityFailure(RuntimeError):
    pass


class SearchService:
    def __init__(self, root, workflows, llm=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.workflows = workflows
        self.llm = llm if llm is not None else workflows.llm
        if isinstance(self.llm, OpenAICompatibleClient):
            # Every actual provider request is charged by the search ledger.
            self.llm = OpenAICompatibleClient(
                self.llm.config, self.llm._transport, max_retries=0
            )
        self.tasks = {}
        self.children = {}
        self.cancelled = set()

    def folder(self, identity):
        if not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise KeyError("search not found")
        return within(self.root, identity)

    def get(self, owner, identity):
        state = SearchState.model_validate(
            read(self.folder(identity) / "search.json")
        ).model_dump(mode="json")
        if state["owner"] != owner:
            raise KeyError("search not found")
        return state

    def save(self, state):
        state["updated_at"] = now()
        if state["status"] in {"running", "preparing"}:
            state["usage"]["elapsed_seconds"] = max(
                0, time.time() - (state["deadline"] - state["budget"]["max_seconds"])
            )
        value = SearchState.model_validate(state).model_dump(mode="json")
        write(self.folder(state["id"]) / "search.json", value)

    def describe(self, owner, identity):
        state = self.get(owner, identity)
        root = self.folder(identity)
        documents = []
        descriptions = {
            "search.json": "搜索状态、动作历史与累计预算",
            "protocol.json": "冻结的数据、评价器和方法目录",
            "panel.json": "训练与开发被试、原始 trial 清单及可评价窗口",
            "report.html": "候选比较、逐轮决定与适用范围",
            "selection.json": "按固定开发指标和精确平局规则选择的方案",
            "format.schema.json": "搜索过程文件的结构合同",
            "sources.json": "定向阅读可用的冻结资料",
            "input.json": "标准化输入及校验清单",
            "files.json": "全部搜索与数值执行产物索引",
            "limits.json": "冻结资源预算",
        }
        for path in sorted(root.rglob("*")):
            if (
                not path.is_file()
                or "engine" in path.relative_to(root).parts
                or path.name.endswith((".tmp", ".lock"))
            ):
                continue
            name = path.relative_to(root).as_posix()
            if path.suffix not in {".json", ".tsv", ".html"}:
                continue
            documents.append(
                {
                    "name": name,
                    "description": descriptions.get(
                        name,
                        {
                            "receipt.json": "实际评价、覆盖和诊断回执",
                            "predictions.tsv": "原始事件到预测的逐行对应",
                            "plan.json": "编译后的执行方案",
                            "result.json": "逐记录执行与产物校验结果",
                            "method.json": "该候选的固定操作及参数",
                            "execution.json": "数值任务定位与恢复状态",
                        }.get(path.name, "过程记录"),
                    ),
                    "url": f"/api/searches/{identity}/artifacts/{name}?download=true",
                }
            )
        state["artifacts"] = documents
        if state["panel"]:
            panel = state["panel"]
            state["panel"] = {k: v for k, v in panel.items() if k != "trials"}
        return state

    def list(self, owner):
        rows = []
        for path in self.root.glob("*/search.json"):
            s = read(path)
            if s["owner"] == owner:
                rows.append(
                    {
                        k: s[k]
                        for k in (
                            "id",
                            "workflow_id",
                            "status",
                            "created_at",
                            "updated_at",
                            "selected_candidate_id",
                            "stop_reason",
                            "usage",
                            "budget",
                        )
                    }
                )
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)

    def create(self, owner, request: SearchRequest, *, start=True):
        source = self.workflows.get(owner, request.workflow_id)
        if "data_collection" not in source["outputs"]:
            raise ValueError("先完成数据接入与标准化，再开始预算搜索")
        folder = self.workflows.folder(request.workflow_id)
        data = PreprocessInput.model_validate(read(folder / "collection/input.json"))
        if (
            data.survey.dataset_id != "eegmmidb"
            or data.survey.task != "left_right_motor_imagery"
        ):
            raise ValueError("当前搜索合同仅支持 EEGMMIDB 左右手运动想象")
        if not any(
            Path(data.collection.root).resolve().is_relative_to(p.resolve())
            for p in self.workflows.preprocessing.allowed_roots
        ):
            raise ValueError("标准化数据不在允许的输入目录内")
        identity = uuid4().hex
        root = self.folder(identity)
        root.mkdir()
        started = time.time()
        limits = resource_budget(root, request.budget)
        data_json = data.model_dump(mode="json")
        subjects = {
            r["id"]: r["subject"] for r in source["outputs"]["data_survey"]["records"]
        }
        panel_request = {
            "record_subjects": subjects,
            "seed": request.seed,
            "tmin": source["request"]["tmin"],
            "tmax": source["request"]["tmax"],
            "sfreq": 160.0,
            "train_subjects": request.train_subjects or None,
            "development_subjects": request.development_subjects or None,
        }
        documents = []
        for prefix in ("survey", "collection"):
            path = folder / prefix / "sources.json"
            if path.exists():
                for doc in read(path).get("documents", []):
                    if doc["id"] not in {d["id"] for d in documents}:
                        documents.append(doc)
        protocol = {
            "version": "1",
            "request": request.model_dump(mode="json"),
            "deadline": started + request.budget.max_seconds,
            "input_hash": digest(data_json),
            "source_workflow_id": request.workflow_id,
            "scope": "offline_development_panel",
            "evaluator": "logvariance-scaler-logistic-v1",
            "metric": "subject_macro_balanced_accuracy",
            "selection": "highest_development_ba",
            "tie_break": ["reference", "fewer_operators", "catalog_order"],
            "baseline_id": BASELINE_ID,
            "catalog": catalog(),
            "catalog_hash": digest(catalog()),
            "environment": environment(),
            "numeric_engine_hash": engine_hash(),
            "search_engine_hash": search_engine_hash(),
            "sources_hash": digest(documents),
            "panel_request_hash": digest(panel_request),
            "limits": limits.model_dump(),
            "adaptation": "fixed_full_record_operations_only",
            "confirmation": "not_performed; these data are development data previously available to the workflow",
            "failure_denominator": "candidate must predict every predeclared eligible development trial",
            "cost_scope": "elapsed time includes preprocessing, evaluation, LLM, failed attempts and downtime; memory is sampled worker RSS; money/provider token usage unavailable",
        }
        state = SearchState(
            id=identity,
            owner=owner,
            workflow_id=request.workflow_id,
            status="preparing",
            request=request,
            budget=request.budget,
            created_at=now(),
            updated_at=now(),
            deadline=started + request.budget.max_seconds,
            protocol=protocol,
        ).model_dump(mode="json")
        write(root / "input.json", data_json)
        write(root / "panel-request.json", panel_request)
        write(root / "sources.json", documents)
        write(root / "protocol.json", protocol)
        write(root / "limits.json", limits.model_dump())
        schema = SearchState.model_json_schema()
        panel_schema = FrozenPanel.model_json_schema()
        schema.setdefault("$defs", {}).update(panel_schema.pop("$defs", {}))
        schema["$defs"]["FrozenPanel"] = panel_schema
        write(root / "format.schema.json", schema)
        self.save(state)
        if start:
            self.start(owner, identity)
        return self.describe(owner, identity)

    def start(self, owner, identity):
        if identity not in self.tasks or self.tasks[identity].done():
            self.tasks[identity] = asyncio.create_task(self.run(owner, identity))

    async def resume(self):
        for path in self.root.glob("*/search.json"):
            state = read(path)
            if state["status"] in {"preparing", "running", "interrupted"}:
                self.start(state["owner"], state["id"])

    async def close(self):
        active = [t for t in self.tasks.values() if not t.done()]
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)

    def cancel(self, owner, identity):
        state = self.get(owner, identity)
        if state["status"] not in {"preparing", "running", "interrupted"}:
            raise ValueError("只有正在进行的搜索可以取消")
        self.cancelled.add(identity)
        task = self.tasks.get(identity)
        if task and not task.done():
            task.cancel()
        else:
            state.update(status="cancelled", stop_reason="cancelled_by_user")
            self.save(state)
        return self.describe(owner, identity)

    def retry(self, owner, identity):
        state = self.get(owner, identity)
        if state["stop_reason"] == "integrity_failure":
            raise ValueError("冻结内容或已验证产物改变，需重新创建搜索")
        if state["status"] not in {"failed", "interrupted", "cancelled"}:
            raise ValueError(
                "仅故障、中断或取消的搜索可恢复；停止后的协议和预算不能重置"
            )
        try:
            self.guard(state)
        except BudgetStop as exc:
            raise ValueError("总时间预算已用尽，恢复不能重置预算") from exc
        if state["usage"]["retries"] >= state["budget"]["max_retries"]:
            raise ValueError("故障重试预算已用尽，恢复不能重置预算")
        if not any(
            c["attempts"]
            and c["status"] in {"running", "interrupted", "execution_failure"}
            for c in state["candidates"]
        ):
            state["usage"]["retries"] += 1
        self.cancelled.discard(identity)
        state.update(status="running", error=None, stop_reason=None)
        self.save(state)
        self.start(owner, identity)
        return self.describe(owner, identity)

    def guard(self, state):
        if time.time() >= state["deadline"]:
            raise BudgetStop("time_budget_exhausted")

    async def child(self, state, stage, candidate_id=None):
        self.guard(state)
        root = self.folder(state["id"])
        command = [
            sys.executable,
            "-m",
            "app.search.worker",
            "--root",
            str(root),
            "--stage",
            stage,
            "--parent-pid",
            str(os.getpid()),
        ]
        if candidate_id:
            command.extend(["--candidate", candidate_id])
        kwargs = (
            {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        )
        env = dict(
            os.environ,
            PYTHONUTF8="1",
            PYTHONPATH=str(Path(__file__).resolve().parents[2]),
        )
        logfile = root / (f"{stage}-{candidate_id or 'panel'}.log")
        with logfile.open("ab") as log:
            process = await asyncio.create_subprocess_exec(
                *command, stdout=log, stderr=log, env=env, **kwargs
            )
            self.children[state["id"]] = process
            waiter = asyncio.create_task(process.wait())
            last_disk = 0.0
            try:
                while not waiter.done():
                    self.guard(state)
                    memory = process_memory(process.pid)
                    if memory is not None:
                        state["usage"]["peak_worker_memory_bytes"] = max(
                            memory, state["usage"]["peak_worker_memory_bytes"]
                        )
                        if memory > state["protocol"]["limits"]["memory_limit_bytes"]:
                            raise BudgetStop("memory_budget_exhausted")
                    if time.monotonic() - last_disk >= 5:
                        used = await asyncio.to_thread(directory_bytes, root)
                        state["usage"]["disk_bytes"] = used
                        if used > state["protocol"]["limits"]["disk_limit_bytes"]:
                            raise BudgetStop("disk_budget_exhausted")
                        last_disk = time.monotonic()
                        self.save(state)
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(waiter),
                            timeout=min(1, max(0.01, state["deadline"] - time.time())),
                        )
                    except TimeoutError:
                        pass
                self.guard(state)
                return process.returncode
            finally:
                if process.returncode is None:
                    process.kill()
                await waiter
                self.children.pop(state["id"], None)

    def action(self, state, action, **kwargs):
        row = ActionRecord(
            index=len(state["actions"]) + 1, action=action, **kwargs
        ).model_dump(mode="json")
        state["actions"].append(row)
        self.save(state)
        return row

    async def model_action(self, state, documents, *, one_shot=False):
        if self.llm is None:
            raise RuntimeError("动态搜索和一次性 LLM 对照需要配置模型")
        self.guard(state)
        state["usage"]["llm_calls"] += 1
        action = self.action(
            state,
            "initial_schedule" if one_shot else "model_decision",
            status="running",
        )
        started = time.monotonic()
        try:
            async with asyncio.timeout(max(0.001, state["deadline"] - time.time())):
                result = await decide(self.llm, state, documents, one_shot=one_shot)
            action.update(status="completed", result=result)
            return result
        except TimeoutError:
            action.update(status="failed", error="模型调用期间总时间预算耗尽")
            raise BudgetStop("time_budget_exhausted") from None
        except Exception as exc:
            action.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            duration = time.monotonic() - started
            action["cost_seconds"] = duration
            state["usage"]["llm_seconds"] += duration
            self.save(state)

    async def candidate(self, state, identity):
        root = self.folder(state["id"])
        entry = next(c for c in catalog() if c["id"] == identity)
        existing = next((c for c in state["candidates"] if c["id"] == identity), None)
        if existing is None:
            if state["usage"]["candidates"] >= state["budget"]["max_candidates"]:
                raise BudgetStop("candidate_budget_exhausted")
            state["usage"]["candidates"] += 1
            existing = Candidate(
                id=identity, title=entry["title"], parameters=entry["parameters"]
            ).model_dump(mode="json")
            state["candidates"].append(existing)
            write(
                root / "candidates" / identity / "method.json",
                method(entry, state["panel"]).model_dump(mode="json"),
            )
        receipt_path = root / "candidates" / identity / "receipt.json"
        while True:
            if existing["attempts"]:
                if state["usage"]["retries"] >= state["budget"]["max_retries"]:
                    existing.update(
                        status="execution_failure", error="暂时故障重试预算已用尽"
                    )
                    self.save(state)
                    return existing
                state["usage"]["retries"] += 1
            existing["attempts"] += 1
            existing["status"] = "running"
            state.update(phase="candidate", message=f"执行并评价：{entry['title']}")
            self.save(state)
            started = time.monotonic()
            try:
                exit_code = await self.child(state, "candidate", identity)
                receipt = (
                    read(receipt_path)
                    if receipt_path.exists()
                    else {
                        "status": "execution_failure",
                        "error": "数值子进程结束但没有产生回执；详见执行日志",
                    }
                )
                if exit_code != 0 and receipt["status"] == "evaluated":
                    receipt = {
                        "status": "execution_failure",
                        "error": "本次子进程异常退出，不能使用旧成功回执",
                    }
                receipt = EvaluationReceipt.model_validate(receipt).model_dump(
                    mode="json"
                )
            finally:
                existing["cost_seconds"] += time.monotonic() - started
            existing.update(
                status=receipt["status"], receipt=receipt, error=receipt.get("error")
            )
            execution = root / "candidates" / identity / "execution.json"
            if execution.exists():
                info = read(execution)
                existing.update(
                    job_id=info.get("job_id"), plan_ref=info.get("plan_ref")
                )
            state["usage"]["preprocessing_seconds"] += (
                receipt.get("preprocessing_seconds", 0) or 0
            )
            state["usage"]["evaluation_seconds"] += (
                receipt.get("evaluation_seconds") or 0
            )
            self.save(state)
            if receipt["status"] == "resource_failure":
                raise BudgetStop("resource_unavailable")
            if receipt.get("stop_search") or receipt["status"] == "data_unevaluable":
                raise IntegrityFailure(receipt.get("error") or "共同输入不可评价")
            if (
                receipt["status"] != "execution_failure"
                or state["usage"]["retries"] >= state["budget"]["max_retries"]
            ):
                return existing

    async def run(self, owner, identity):
        import portalocker

        root = self.folder(identity)
        state = self.get(owner, identity)
        try:
            with portalocker.Lock(root / "search.lock", timeout=0):
                await self._run(state)
        except portalocker.exceptions.LockException:
            return
        except asyncio.CancelledError:
            state["usage"]["elapsed_seconds"] = max(
                0, time.time() - (state["deadline"] - state["budget"]["max_seconds"])
            )
            state.update(
                status="cancelled" if identity in self.cancelled else "interrupted",
                stop_reason="cancelled_by_user"
                if identity in self.cancelled
                else "service_interrupted",
            )
            self.save(state)
        except BudgetStop as exc:
            await self.stop(state, "stopped", str(exc))
        except IntegrityFailure as exc:
            for candidate in state["candidates"]:
                if candidate["status"] == "evaluated":
                    candidate["status"] = "invalidated"
            state["error"] = str(exc)
            await self.stop(state, "failed", "integrity_failure")
        except Exception as exc:
            state["error"] = f"{type(exc).__name__}: {exc}"
            await self.stop(state, "failed", "execution_conditions_unavailable")

    async def _run(self, state):
        root = self.folder(state["id"])
        self.guard(state)
        protocol = state["protocol"]
        if (
            state["request"] != protocol["request"]
            or state["budget"] != protocol["request"]["budget"]
            or state["deadline"] != protocol["deadline"]
            or protocol["limits"] != read(root / "limits.json")
        ):
            raise IntegrityFailure("冻结请求、预算或资源上限已改变")
        if protocol != read(root / "protocol.json") or protocol["input_hash"] != digest(
            read(root / "input.json")
        ):
            raise IntegrityFailure("冻结协议或输入快照已改变，不能混用历史结果")
        if (
            protocol["numeric_engine_hash"] != engine_hash()
            or protocol["search_engine_hash"] != search_engine_hash()
            or protocol["environment"] != environment()
        ):
            raise IntegrityFailure("冻结的执行或评价代码/环境已改变，请创建新搜索")
        documents = read(root / "sources.json")
        if protocol["sources_hash"] != digest(documents) or protocol[
            "panel_request_hash"
        ] != digest(read(root / "panel-request.json")):
            raise IntegrityFailure("冻结资料或面板请求已改变")
        if state["panel"] is None:
            if await self.child(state, "prepare") != 0:
                error = (
                    read(root / "prepare-error.json")
                    if (root / "prepare-error.json").exists()
                    else {"error": "冻结面板失败，详见日志"}
                )
                raise ValueError(error["error"])
            full_panel = read(root / "panel.json")
            state["panel"] = {k: v for k, v in full_panel.items() if k != "trials"}
            state["panel"].update(
                trial_count=len(full_panel["trials"]),
                eligible_count=sum(t["eligible"] for t in full_panel["trials"]),
                file_sha256=file_hash(root / "panel.json"),
            )
            self.save(state)
        elif state["panel"]["file_sha256"] != file_hash(root / "panel.json"):
            raise IntegrityFailure("冻结面板文件与搜索记录不一致")
        else:
            if await self.child(state, "verify") != 0:
                failure = read(root / "verification.json")
                raise IntegrityFailure(failure.get("error") or "恢复前完整性校验失败")
        state.update(status="running", error=None)
        self.save(state)
        strategy = state["request"]["strategy"]
        if strategy == "one_shot" and state["schedule"] is None:
            plan = await self.model_action(state, documents, one_shot=True)
            valid = {c["id"] for c in catalog()} - {BASELINE_ID}
            ids = plan["candidate_ids"]
            if (
                len(ids) != len(set(ids))
                or not set(ids) <= valid
                or len(ids) > state["budget"]["max_proposals"]
            ):
                state["usage"]["proposals"] += 1
                raise ValueError("一次性提案包含重复或目录外候选")
            state["schedule"] = ids
            state["usage"]["proposals"] += len(ids)
            self.save(state)
        baseline = next(
            (c for c in state["candidates"] if c["id"] == BASELINE_ID), None
        )
        if baseline is None or baseline["status"] in {
            "reserved",
            "running",
            "interrupted",
            "execution_failure",
        }:
            baseline = await self.candidate(state, BASELINE_ID)
        if baseline["status"] != "evaluated":
            state["error"] = baseline.get("error") or "固定参考流程未能完成共同面板评价"
            await self.stop(state, "failed", "reference_failed")
            return
        # Complete a reserved numeric action before asking for a different one.
        for pending in state["candidates"]:
            if pending["id"] != BASELINE_ID and pending["status"] in {
                "reserved",
                "running",
                "interrupted",
            }:
                await self.candidate(state, pending["id"])
        while True:
            self.guard(state)
            state["selected_candidate_id"] = select(state["candidates"])
            attempted = {c["id"] for c in state["candidates"]}
            remaining = [c["id"] for c in catalog() if c["id"] not in attempted]
            if not remaining:
                await self.stop(state, "completed", "catalog_exhausted")
                return
            if state["usage"]["candidates"] >= state["budget"]["max_candidates"]:
                await self.stop(state, "stopped", "candidate_budget_exhausted")
                return
            if (
                strategy != "one_shot"
                and state["usage"]["proposals"] >= state["budget"]["max_proposals"]
            ):
                await self.stop(state, "stopped", "proposal_budget_exhausted")
                return
            state.update(phase="decision", message="根据开发评价与剩余预算选择下一步")
            self.save(state)
            if strategy in {"random", "exhaustive", "one_shot"}:
                if state["schedule"] is None:
                    ids = [c["id"] for c in catalog() if c["id"] != BASELINE_ID]
                    if strategy == "random":
                        random.Random(state["request"]["seed"]).shuffle(ids)
                    state["schedule"] = ids
                available = [i for i in state["schedule"] if i not in attempted]
                if not available:
                    await self.stop(state, "completed", "schedule_exhausted")
                    return
                proposal = {
                    "action": "propose_candidate",
                    "candidate_id": available[0],
                    "base_candidate_id": BASELINE_ID,
                    "reason": f"冻结的 {strategy} 对照顺序",
                    "expected_result": "按共同面板测量开发效用",
                    "decision_branches": {
                        "improvement": "保持冻结顺序",
                        "no_improvement": "保持冻结顺序",
                    },
                }
            else:
                # If every option fits count, time and disk estimates, enumerate.
                plan_path = root / "candidates" / BASELINE_ID / "plan.json"
                estimated = (
                    read(plan_path).get("estimated_disk_bytes", 0)
                    if plan_path.exists()
                    else 0
                )
                exhaustive_fits = (
                    state["budget"]["max_candidates"] - state["usage"]["candidates"]
                    >= len(remaining)
                    and state["budget"]["max_proposals"] - state["usage"]["proposals"]
                    >= len(remaining)
                    and state["deadline"] - time.time()
                    > max(60, baseline["cost_seconds"] * len(remaining) * 2)
                    and estimated > 0
                    and protocol["limits"]["disk_limit_bytes"]
                    - state["usage"]["disk_bytes"]
                    > estimated * len(remaining)
                )
                if exhaustive_fits:
                    self.action(
                        state,
                        "enumerate_remaining",
                        status="completed",
                        reason="全部剩余选项在候选数、时间及磁盘保守估算内，可直接穷举",
                    )
                    strategy = "exhaustive"
                    continue
                try:
                    proposal = (await self.model_action(state, documents))["decision"]
                except ValueError as exc:
                    state["usage"]["proposals"] += 1
                    self.action(
                        state,
                        "invalid_proposal",
                        status="rejected",
                        error=str(exc)[:2000],
                    )
                    continue
                except BudgetStop:
                    raise
                except RuntimeError:
                    if state["usage"]["retries"] >= state["budget"]["max_retries"]:
                        raise
                    state["usage"]["retries"] += 1
                    self.save(state)
                    continue
            if proposal["action"] == "finish":
                self.action(
                    state,
                    "finish",
                    status="completed",
                    reason=proposal["reason"],
                    request=proposal,
                )
                state["unresolved"] = proposal["unresolved"]
                await self.stop(state, "completed", "model_finished")
                return
            if proposal["action"] == "request_evidence":
                if (
                    state["usage"]["evidence_reads"]
                    >= state["budget"]["max_evidence_reads"]
                ):
                    state["usage"]["proposals"] += 1
                    self.action(
                        state,
                        "request_evidence",
                        status="rejected",
                        request=proposal,
                        error="补充阅读预算已用尽",
                    )
                    continue
                state["usage"]["evidence_reads"] += 1
                action = self.action(
                    state,
                    "request_evidence",
                    status="running",
                    reason=proposal["reason"],
                    request=proposal,
                )
                started = time.monotonic()
                try:
                    if any(
                        a["index"] != action["index"]
                        and a.get("request", {}).get("source_id")
                        == proposal["source_id"]
                        and a.get("request", {}).get("query") == proposal["query"]
                        for a in state["actions"]
                        if a.get("request")
                    ):
                        raise ValueError("该来源和查询已读取，重复动作不产生新信息")
                    action.update(
                        status="completed", result=read_evidence(proposal, documents)
                    )
                except ValueError as exc:
                    action.update(status="rejected", error=str(exc))
                action["cost_seconds"] = time.monotonic() - started
                self.save(state)
                continue
            if strategy != "one_shot":
                state["usage"]["proposals"] += 1
            action = self.action(
                state,
                "propose_candidate",
                status="reserved",
                **{
                    k: proposal[k]
                    for k in (
                        "candidate_id",
                        "base_candidate_id",
                        "reason",
                        "expected_result",
                        "decision_branches",
                    )
                },
            )
            if proposal["candidate_id"] not in remaining or proposal[
                "base_candidate_id"
            ] not in {
                c["id"] for c in state["candidates"] if c["status"] == "evaluated"
            }:
                action.update(
                    status="rejected",
                    error="候选重复/不在固定目录，或父候选没有有效评价",
                )
                self.save(state)
                continue
            result = await self.candidate(state, proposal["candidate_id"])
            action.update(
                status="completed",
                result={"candidate_id": result["id"], "status": result["status"]},
            )
            self.save(state)

    async def stop(self, state, status, reason):
        state["usage"]["elapsed_seconds"] = max(
            0, time.time() - (state["deadline"] - state["budget"]["max_seconds"])
        )
        state.update(
            status=status,
            phase="finished",
            stop_reason=reason,
            selected_candidate_id=select(state["candidates"]),
        )
        state["message"] = "搜索结束，开发候选与完整记录已保存"
        self.save(state)
        from .reporting import render

        await asyncio.to_thread(render, self.folder(state["id"]), state)

    def artifact(self, owner, identity, name):
        self.get(owner, identity)
        path = within(self.folder(identity), name)
        if (
            not path.is_file()
            or path.suffix in {".db", ".lock", ".tmp"}
            or path.name.endswith(("-wal", "-shm"))
        ):
            raise KeyError("artifact not found")
        return path
