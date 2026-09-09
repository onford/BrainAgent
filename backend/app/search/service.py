import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import random
import re
import sys
import time
from uuid import uuid4


from app.llm.client import OpenAICompatibleClient
from app.preprocessing.resources import budget as resource_budget
from app.preprocessing.schemas import PreprocessInput
from app.preprocessing.storage import digest, file_hash, within
from app.preprocessing.units import engine_hash, environment
from .catalog import BASELINE_ID, method, search_engine_hash, select
from .contracts import ActionRecord, Candidate, SearchRequest, SearchState
from .io import directory_bytes, read, write
from .processes import ProcessTree
from .reasoning import decide, read_context_evidence
from .evaluation_contracts import FrozenPanel, EvaluationReceipt
from .hypotheses import validate_hypothesis, check_predictions
from .method_space import seed_entries, edited_entry, verify_registry
from .scientific_space import build_space, input_context, knowledge
from .space_contracts import ExplorationSpace
from .knowledge_contracts import ScientificKnowledge
from .exploration_coverage import coverage


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
        workflows.searches = self
        self.llm = llm if llm is not None else workflows.llm
        if isinstance(self.llm, OpenAICompatibleClient):
            # Every actual provider request is charged by the search ledger.
            self.llm = OpenAICompatibleClient(
                self.llm.config, self.llm._transport, max_retries=0
            )
        self.tasks = {}
        self.children = {}
        self.cancelled = set()
        self.verified = set()

    def folder(self, identity):
        if not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise KeyError("search not found")
        return within(self.root, identity)

    def get(self, owner, identity):
        state = read(self.folder(identity) / "search.json")
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
        write(self.folder(state["id"]) / "registry.json", value["registry"])
        write(self.folder(state["id"]) / "coverage.json", coverage(value))

    def describe(self, owner, identity, include_artifacts=True):
        state = self.get(owner, identity)
        if not include_artifacts:
            state["artifacts"] = []
            return state
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
            "space.json": "算子、参数域、方法起点及可检查的科学先验",
            "registry.json": "候选完整配方、方法来源与算子编辑谱系",
            "coverage.json": "方法家族、算子与编辑类型的探索覆盖情况",
            "control-design.json": "有限对照邻域、参数与换序提案、排除原因和覆盖范围",
            "probe-panel.json": "覆盖全部被试的固定重建探针与污染条件分配",
            "scientific-knowledge.json": "顺序、参数及适用条件的来源与证据缺口",
            "evaluation-evidence.json": "质量评价设计和论文基准的可比性依据",
        }
        for path in sorted(root.rglob("*")):
            if (
                not path.is_file()
                or path.suffix in {".db", ".tmp", ".lock"}
                or path.name.endswith(("-wal", "-shm"))
                or any(
                    part.startswith(".verify-") for part in path.relative_to(root).parts
                )
            ):
                continue
            name = path.relative_to(root).as_posix()
            if "/operator-usage/" in name:
                descriptions[name] = "逐记录算子应用、校准不足、失败与未执行的证据和计数"
            elif "/core-receipts/" in name:
                descriptions[name] = "该次评价输入的共同CSP与对数方差模型原始回执"
            documents.append(
                {
                    "name": name,
                    "description": descriptions.get(
                        name,
                        {
                            "receipt.json": "实际评价、覆盖和诊断回执",
                            "originalpredictions.tsv": "原始试次、训练/开发角色和开发预测的逐行对应",
                            "plan.json": "编译后的执行方案",
                            "result.json": "逐记录执行与产物校验结果",
                            "method.json": "该候选的固定操作及参数",
                            "execution.json": "数值任务定位与恢复状态",
                            "assessment.json": "训练效用、信号质量和重建实验的统一摘要",
                            "utility.json": "六种模型的逐被试成绩、固定三模型主指标与拟合证据",
                            "data-quality.json": "全部记录在不同信号阶段的质量指标、单位和分母",
                            "reconstruction_evaluation.json": "已知污染的去除效果与原信号保留，含失败及适用性",
                            "artifact-manifest.json": "本次多维评价的完整文件、大小与校验清单",
                            "core-receipt.json": "共同CSP和对数方差对照的原始数值回执",
                            "model.joblib": "仅由该折训练数据拟合的可复算模型",
                        }.get(
                            path.name,
                            {
                                ".fif": "该候选的 EEG 数值数据",
                                ".npy": "该候选的数值数组",
                                ".npz": "该候选的压缩数值数组",
                                ".tsv": "逐条数据与处理结果",
                                ".json": "结构化执行与校验记录",
                                ".log": "数值执行日志",
                            }.get(path.suffix, "过程记录"),
                        ),
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
        from .utility_evaluation import utility_protocol
        from .utility_parallel import utility_execution

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
        utility_memory = limits.memory_limit_bytes
        utility_reserve = min(4 * 1024**3, utility_memory // 4)
        utility_config = utility_execution({
            "max_workers": min(4, os.cpu_count() or 1),
            "memory_budget_bytes": utility_memory,
            "reserve_bytes": utility_reserve,
            "model_memory_bytes": min(8 * 1024**3, utility_memory - utility_reserve),
            "timeout_seconds": float(request.budget.max_seconds),
        })
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
        space_context = input_context(data)
        space = build_space(space_context)
        seeds = seed_entries(space, space_context)
        controls = None
        registry = seeds
        if request.strategy != "adaptive":
            from .control_design import control_entries

            controls = control_entries(space, space_context, request.seed, max_entries=256)
            registry = controls["registry"]
        research = knowledge().model_dump(mode="json")
        research_text = "\n\n".join(
            f"{r['id']} · {r['claim']}\n条件：{r['condition']}\n解释：{r['implication']}\n来源："
            + ", ".join(r["source_ids"])
            for r in research["rules"]
        )
        research_text += "\n\n来源索引\n" + "\n".join(
            f"{s['id']}: {s['title']} · {s['url']}" for s in research["sources"]
        )
        documents.append(
            {
                "id": "scientific-priors",
                "title": "预处理顺序与参数的证据目录（核对后概述）",
                "url": "brainagent:scientific-knowledge:1",
                "text": research_text,
                "sha256": digest(research_text),
            }
        )
        evaluation_evidence = read(Path(__file__).parent / "resources/evaluation-evidence.json")
        metric_text = evaluation_evidence["interpretation"] + "\n\n" + "\n\n".join(
            f"{m['id']} · {m['name']}\n定义：{m['formula']}\n边界：{m['overCleaningAndLeakageRisk']}\n选择角色：{m['selectionRole']}"
            for m in evaluation_evidence["quality"]["metrics"]
        )
        documents.append({"id": "evaluation-evidence", "title": "评价指标定义与解释边界（研究目录）",
                          "url": "brainagent:evaluation-evidence:1", "text": metric_text, "sha256": digest(metric_text)})
        protocol = {
            "version": "3",
            "request": request.model_dump(mode="json"),
            "deadline": started + request.budget.max_seconds,
            "input_hash": digest(data_json),
            "source_workflow_id": request.workflow_id,
            "scope": "offline_development_panel",
            "evaluator": "fixed-three-learner-subject-macro-utility-v1",
            "anchor_evaluator": "csp-shrinkage-lda-v2",
            "benchmark_evaluators": ["fgmdm", "ea_fbcsp", "logvar_lr"],
            "evaluation_mode": "subject_holdout"
            if request.train_subjects
            else "group_cross_validation",
            "split_rationale": "Explicit subject roles"
            if request.train_subjects
            else "Seeded subject folds, min(5, n_subjects); every subject has out-of-fold predictions. Engineering evaluation protocol, not a dataset optimum.",
            "metric": "mean_subject_macro_ba_across_csp_lda_fbcsp_ts_lr",
            "selection": "highest_complete_three_learner_utility",
            "tie_break": ["reference", "fewer_operators", "candidate_id"],
            "assessment": {
                "version": 1,
                "primary_suite": ["csp_lda", "fbcsp", "ts_lr"],
                "weighting": "equal_subjects_then_equal_learners",
                "missing_primary": "no_selection_score",
                "quality": "physical_signal_metrics_separate_axes",
                "reconstruction_design": "balanced",
                "reconstruction_scope": "one_fixed_record_per_subject_all_eligible_trials",
                "reconstruction_interpretation": "semi_synthetic_cleanproxy_not_neural_ground_truth",
            },
            "utility_execution": utility_config,
            "utility_protocol": utility_protocol(execution=utility_config),
            "baseline_id": BASELINE_ID,
            "catalog": seeds,
            "catalog_hash": digest(seeds),
            "control_design_hash": digest(controls) if controls else None,
            "control_comparison": (
                "frozen finite single-edit seed neighbourhood; not exhaustive continuous or multigeneration adaptive search"
                if controls else "adaptive multigeneration operator editing"
            ),
            "space": space.model_dump(mode="json"),
            "space_hash": digest(space.model_dump(mode="json")),
            "space_context": space_context,
            "scientific_knowledge_hash": digest(research),
            "evaluation_evidence_hash": digest(evaluation_evidence),
            "environment": environment(),
            "numeric_engine_hash": engine_hash(),
            "search_engine_hash": search_engine_hash(),
            "sources_hash": digest(documents),
            "panel_request_hash": digest(panel_request),
            "limits": limits.model_dump(),
            "numeric_threads": 1,
            "record_workers": min(4, max(1, (os.cpu_count() or 1) // 2)),
            "adaptation": "shared_policy_with_label_free_subject_batch_fitting",
            "information_permissions": {
                "target_signals": "whole_unlabelled_subject_batch",
                "target_labels": "scoring_only",
                "policy_selection": "development_feedback",
                "independent_confirmation": False,
            },
            "parameter_provenance": {
                "domains": "operator-specific bounded domains with source or engineering provenance in space.json",
                "alignment": "He & Wu, arXiv:1808.05464",
                "conditional_thresholds": "bounded engineering hypotheses, not validated physiological cutoffs",
            },
            "confirmation": "not_performed; these data are development data previously available to the workflow",
            "failure_denominator": "candidate must predict every predeclared eligible development trial",
            "cost_scope": "elapsed time includes preprocessing, evaluation, LLM, failed attempts and downtime; memory is sampled process-tree RSS; final report export is separate; money/provider token usage unavailable",
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
            registry=registry,
        ).model_dump(mode="json")
        write(root / "input.json", data_json)
        write(root / "panel-request.json", panel_request)
        write(root / "sources.json", documents)
        write(root / "protocol.json", protocol)
        write(root / "space.json", protocol["space"])
        if controls is not None:
            write(root / "control-design.json", controls)
        write(root / "scientific-knowledge.json", research)
        write(root / "evaluation-evidence.json", evaluation_evidence)
        write(root / "space.schema.json", ExplorationSpace.model_json_schema())
        write(
            root / "scientific-knowledge.schema.json",
            ScientificKnowledge.model_json_schema(),
        )
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
        self.verify_runtime(self.get(owner, identity))
        if identity not in self.tasks or self.tasks[identity].done():
            self.tasks[identity] = asyncio.create_task(self.run(owner, identity))

    async def resume(self):
        for path in self.root.glob("*/search.json"):
            state = read(path)
            if state["status"] in {"preparing", "running", "interrupted"}:
                try:
                    self.start(state["owner"], state["id"])
                except (IntegrityFailure, OSError, KeyError):
                    continue

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
        try:
            self.verify_runtime(state)
        except IntegrityFailure as exc:
            raise ValueError(str(exc)) from exc
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

    @staticmethod
    def verify_runtime(state):
        from .utility_evaluation import utility_protocol

        protocol = state["protocol"]
        if (
            protocol["numeric_engine_hash"] != engine_hash()
            or protocol["search_engine_hash"] != search_engine_hash()
            or protocol["environment"] != environment()
            or (protocol.get("assessment") and protocol.get("utility_protocol") != utility_protocol(execution=protocol.get("utility_execution")))
        ):
            raise IntegrityFailure("冻结的执行或评价代码/环境已改变，请创建新搜索")

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
        env = dict(
            os.environ,
            PYTHONUTF8="1",
            PYTHONPATH=str(Path(__file__).resolve().parents[2]),
            OMP_NUM_THREADS="1",
            OPENBLAS_NUM_THREADS="1",
            MKL_NUM_THREADS="1",
            NUMEXPR_NUM_THREADS="1",
        )
        logfile = root / (f"{stage}-{candidate_id or 'panel'}.log")
        with logfile.open("ab") as log:
            # Windows Job membership is assigned atomically at process creation,
            # before the venv launcher can start the actual numerical worker.
            process = ProcessTree(command, stdout=log, stderr=log, env=env)
            self.children[state["id"]] = process
            waiter = asyncio.create_task(asyncio.to_thread(process.wait))
            last_disk = 0.0
            try:
                while not waiter.done():
                    self.guard(state)
                    memory = process.memory_bytes()
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
                try:
                    process.kill()
                    await waiter
                finally:
                    process.close()
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
        self.verify_runtime(state)
        state["usage"]["llm_calls"] += 1
        action = self.action(
            state,
            "initial_schedule" if one_shot else "model_decision",
            status="running",
        )
        folder = self.folder(state["id"]) / "decisions" / f"{action['index']:03}"

        def capture(messages):
            config = getattr(self.llm, "config", None)
            write(
                folder / "request.json",
                {
                    "schema_version": "1",
                    "action_index": action["index"],
                    "model": getattr(config, "model", None),
                    "reasoning_effort": getattr(config, "reasoning_effort", None),
                    "messages": messages,
                },
            )

        started = time.monotonic()
        try:
            async with asyncio.timeout(max(0.001, state["deadline"] - time.time())):
                result = await decide(
                    self.llm, state, documents, one_shot=one_shot, capture=capture
                )
            write(
                folder / "response.json",
                {"schema_version": "1", "status": "accepted", "result": result},
            )
            action.update(status="completed", result=result)
            return result
        except TimeoutError:
            action.update(status="failed", error="模型调用期间总时间预算耗尽")
            raise BudgetStop("time_budget_exhausted") from None
        except Exception as exc:
            write(
                folder / "response.json",
                {
                    "schema_version": "1",
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "rejected_content": getattr(exc, "content", None),
                },
            )
            action.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            duration = time.monotonic() - started
            action["cost_seconds"] = duration
            state["usage"]["llm_seconds"] += duration
            self.save(state)

    async def candidate(self, state, identity):
        root = self.folder(state["id"])
        entry = verify_registry(state["protocol"], state["registry"])[identity]
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
                method(
                    entry,
                    state["panel"],
                    state["protocol"]["space"],
                    state["protocol"].get("space_context"),
                ).model_dump(mode="json"),
            )
            write(root / "candidates" / identity / "policy.json", entry)
        receipt_path = root / "candidates" / identity / "receipt.json"
        while True:
            self.verify_runtime(state)
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
                self.verify_runtime(state)
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
                if receipt["status"] == "evaluated":
                    if state["protocol"].get("assessment") and (
                        receipt.get("assessment") is None or not receipt.get("assessment_path") or not receipt.get("core_receipt_path")
                    ):
                        raise IntegrityFailure("当前协议要求完整多维评价回执，不能回退单模型评分")
                    versions = receipt.get("versions") or {}
                    expected = {
                        "search_engine_sha256": state["protocol"]["search_engine_hash"],
                        "engine_sha256": state["protocol"]["numeric_engine_hash"],
                        "environment_sha256": digest(state["protocol"]["environment"]),
                    }
                    if any(
                        versions.get(key) != value for key, value in expected.items()
                    ):
                        raise IntegrityFailure(
                            "成功回执的执行/评价版本与冻结协议不一致"
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
                self.verified.discard(identity)
                await self._run(state)
        except portalocker.exceptions.LockException:
            return
        except asyncio.CancelledError:
            self.interrupt_pending(state, "搜索已中断，尚未产生完整评价")
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
        self.verify_runtime(state)
        documents = read(root / "sources.json")
        if (
            read(root / "space.json") != protocol["space"]
            or digest(protocol["space"]) != protocol["space_hash"]
            or digest(read(root / "scientific-knowledge.json")) != protocol["scientific_knowledge_hash"]
            or digest(read(root / "evaluation-evidence.json")) != protocol["evaluation_evidence_hash"]
        ):
            raise IntegrityFailure("冻结算子空间或科学依据目录已改变")
        verify_registry(protocol, state["registry"])
        if protocol.get("control_design_hash"):
            controls = read(root / "control-design.json")
            if digest(controls) != protocol["control_design_hash"] or controls["registry"] != state["registry"]:
                raise IntegrityFailure("frozen finite control design differs")
        registry_path = root / "registry.json"
        saved_registry = read(registry_path) if registry_path.exists() else []
        if saved_registry != state["registry"]:
            # search.json is the atomic authoritative ledger; a crash may
            # precede publication of its derived worker-facing projection.
            if saved_registry != state["registry"][:len(saved_registry)]:
                raise IntegrityFailure("候选配方登记与搜索记录不一致")
            write(registry_path, state["registry"])
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
        self.verified.add(state["id"])
        state.update(status="running", error=None)
        self.save(state)
        strategy = state["request"]["strategy"]
        if strategy == "one_shot" and state["schedule"] is None:
            while True:
                try:
                    plan = await self.model_action(state, documents, one_shot=True)
                    break
                except (BudgetStop, IntegrityFailure):
                    raise
                except RuntimeError:
                    if state["usage"]["retries"] >= state["budget"]["max_retries"]:
                        raise
                    state["usage"]["retries"] += 1
                    self.save(state)
            valid = {c["id"] for c in state["registry"]}
            proposed = plan["candidate_ids"]
            # The compulsory reference is run once regardless of whether the
            # initial list includes it. Preserve every other proposed position.
            ids = [identity for identity in proposed if identity != BASELINE_ID]
            if (
                len(proposed) != len(set(proposed))
                or not set(proposed) <= valid
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
        # Reconcile the proposal as well as the numerical candidate. A crash can
        # occur before candidate reservation or after its receipt was saved.
        for action in state["actions"]:
            if action["action"] == "propose_candidate" and action["status"] in {
                "reserved",
                "running",
                "interrupted",
            }:
                await self.candidate_action(state, action, recovering=True)
        # Retain support for reserved numerical work without a proposal record.
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
            remaining = [c["id"] for c in state["registry"] if c["id"] not in attempted]
            if not remaining and strategy != "adaptive":
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
                    ids = [c["id"] for c in state["registry"] if c["id"] != BASELINE_ID]
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
                except (BudgetStop, IntegrityFailure):
                    raise
                except RuntimeError:
                    if state["usage"]["retries"] >= state["budget"]["max_retries"]:
                        raise
                    state["usage"]["retries"] += 1
                    self.save(state)
                    continue
            if proposal["action"] == "finish":
                missing_seeds = [
                    s["id"] for s in protocol["catalog"] if s["id"] not in attempted
                ]
                if missing_seeds:
                    state["usage"]["proposals"] += 1
                    self.action(
                        state,
                        "finish",
                        status="rejected",
                        reason=proposal["reason"],
                        request=proposal,
                        error="仍有未探索的方法起点：" + ", ".join(missing_seeds),
                    )
                    continue
                exploration = coverage(state)
                explanations = proposal.get("unexplored_edit_reasons", {})
                missing = [
                    name
                    for name in exploration["unexplored_edit_families"]
                    if not explanations.get(name, "").strip()
                ]
                n_edits = sum(
                    bool(e["edits"]) and e["id"] in attempted for e in state["registry"]
                )
                minimum_edits = min(
                    8,
                    max(
                        0, state["budget"]["max_candidates"] - len(protocol["catalog"])
                    ),
                )
                if missing or n_edits < minimum_edits:
                    state["usage"]["proposals"] += 1
                    self.action(
                        state,
                        "finish",
                        status="rejected",
                        request=proposal,
                        error=f"提前结束需至少尝试 {minimum_edits} 个不同编辑方案（当前 {n_edits}），并逐项解释未覆盖编辑类型：{', '.join(missing)}",
                    )
                    continue
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
                    reading = read_context_evidence(proposal, state, documents)
                    if any(
                        a["index"] != action["index"]
                        and a.get("request", {}).get("source_id")
                        == proposal["source_id"]
                        and a.get("request", {}).get("query") == proposal["query"]
                        and a.get("status") == "completed"
                        and (a.get("result") or {}).get("source_sha256") == reading.get("source_sha256")
                        for a in state["actions"]
                        if a.get("request")
                    ):
                        raise ValueError("该来源和查询已读取，重复动作不产生新信息")
                    action.update(
                        status="completed", result=reading
                    )
                except ValueError as exc:
                    action.update(status="rejected", error=str(exc))
                action["cost_seconds"] = time.monotonic() - started
                self.save(state)
                continue
            if strategy != "one_shot":
                state["usage"]["proposals"] += 1
            try:
                parent_id = proposal["base_candidate_id"]
                if parent_id not in {
                    c["id"] for c in state["candidates"] if c["status"] == "evaluated"
                }:
                    raise ValueError("父候选没有有效评价")
                if strategy == "adaptive":
                    validate_hypothesis(proposal, state["candidates"])
                if proposal.get("edits"):
                    entries = verify_registry(protocol, state["registry"])
                    entry = edited_entry(
                        entries[parent_id],
                        proposal["edits"],
                        protocol["space"],
                        title=proposal["title"],
                        order=len(entries),
                        context=protocol.get("space_context"),
                        prior_challenges=proposal.get("prior_challenges"),
                    )
                    if entry["recipe_hash"] in {
                        e["recipe_hash"] for e in entries.values()
                    }:
                        raise ValueError("该执行配方已经存在，请选择未试方法或不同编辑")
                    # Compile before reservation so structural failures do not consume a numerical trial.
                    method(
                        entry,
                        state["panel"],
                        protocol["space"],
                        protocol.get("space_context"),
                    )
                    proposal["candidate_id"] = entry["id"]
                    state["registry"].append(entry)
                    remaining.append(entry["id"])
                elif proposal["candidate_id"] not in remaining:
                    raise ValueError("方法起点重复或不存在")
            except (ValueError, KeyError) as exc:
                self.action(
                    state,
                    "invalid_proposal",
                    status="rejected",
                    request=proposal,
                    error=str(exc),
                )
                continue
            action = self.action(
                state,
                "propose_candidate",
                status="reserved",
                request=proposal,
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
            await self.candidate_action(state, action)

    async def candidate_action(self, state, action, *, recovering=False):
        proposal = action.get("request") or {}
        if (
            proposal.get("candidate_id") != action["candidate_id"]
            or proposal.get("base_candidate_id") != action["base_candidate_id"]
        ):
            raise IntegrityFailure("候选动作与保存的原提案不一致")
        parent = next(
            (c for c in state["candidates"] if c["id"] == action["base_candidate_id"]),
            None,
        )
        if parent is None or parent["status"] != "evaluated":
            raise IntegrityFailure("候选动作缺少已验证的父候选评价")
        if recovering and proposal.get("hypothesis"):
            validate_hypothesis(proposal, state["candidates"])

        def candidate_record():
            return next(
                (c for c in state["candidates"] if c["id"] == action["candidate_id"]),
                None,
            )

        if recovering:
            previous = candidate_record()
            result = dict(action.get("result") or {})
            result["recovery_history"] = [
                *result.get("recovery_history", []),
                {
                    "status": action["status"],
                    "error": action.get("error"),
                    "candidate_status": previous["status"] if previous else None,
                    "candidate_attempts": previous["attempts"] if previous else 0,
                    "retries_used": state["usage"]["retries"],
                    "resumed_at": now(),
                },
            ]
            action["result"] = result
        action.update(status="running", error=None)
        self.save(state)

        def finish(result, error=None, *, interrupted=False):
            status = result["status"] if result else "interrupted"
            if status in {"reserved", "running", "interrupted"}:
                status = "interrupted"
            receipt = (result.get("receipt") or {}) if result else {}
            # A failed/retried worker can leave an older receipt on the record.
            # Only a normally returned, evaluated candidate supplies measurements.
            measured = (
                error is None
                and status == "evaluated"
                and receipt.get("status") == "evaluated"
            )
            action.update(
                status="interrupted"
                if interrupted or status == "interrupted"
                else "completed"
                if measured
                else "failed",
                error=error or (result.get("error") if result else None),
                result={
                    **(action.get("result") or {}),
                    "candidate_id": action["candidate_id"],
                    "status": status,
                    "prediction_checks": check_predictions(
                        proposal,
                        parent.get("receipt") or {},
                        receipt if measured else {},
                    ),
                },
            )
            self.save(state)

        try:
            result = candidate_record()
            if result is None or result["status"] in {
                "reserved",
                "running",
                "interrupted",
                "execution_failure",
            }:
                result = await self.candidate(state, action["candidate_id"])
            elif result["status"] == "resource_failure":
                raise BudgetStop("resource_unavailable")
            elif result["status"] == "data_unevaluable":
                raise IntegrityFailure(result.get("error") or "共同输入不可评价")
        except (asyncio.CancelledError, Exception) as exc:
            reason = (
                "搜索已中断，尚未产生完整评价"
                if isinstance(exc, asyncio.CancelledError)
                else str(exc)
            )
            finish(
                candidate_record(),
                error=reason,
                interrupted=isinstance(exc, asyncio.CancelledError),
            )
            raise
        finish(result)

    @staticmethod
    def interrupt_pending(state, reason):
        for candidate in state["candidates"]:
            if candidate["status"] in {"reserved", "running"}:
                candidate.update(status="interrupted", error=reason)
        for action in state["actions"]:
            if action["status"] in {"reserved", "running"}:
                action.update(status="interrupted", error=reason)

    async def stop(self, state, status, reason):
        self.interrupt_pending(state, reason)
        verified = state["id"] in self.verified
        if not verified and state["candidates"] and not state["error"]:
            state["error"] = "本次恢复未完成历史产物校验，未重新发布选中结果"
        state["usage"]["elapsed_seconds"] = max(
            0, time.time() - (state["deadline"] - state["budget"]["max_seconds"])
        )
        state.update(
            status=status,
            phase="finished",
            stop_reason=reason,
            selected_candidate_id=select(state["candidates"]) if verified else None,
        )
        state["message"] = "搜索结束，开发候选与完整记录已保存"
        from .reporting import render

        try:
            await asyncio.to_thread(render, self.folder(state["id"]), state)
        except Exception as exc:
            state.update(
                status="failed",
                stop_reason="publication_failed",
                selected_candidate_id=None,
                error=f"结果发布失败：{type(exc).__name__}: {exc}",
            )
        self.save(state)

    def artifact(self, owner, identity, name):
        state = self.get(owner, identity)
        path = within(self.folder(identity), name)
        if (
            not path.is_file()
            or path.suffix in {".db", ".lock", ".tmp"}
            or path.name.endswith(("-wal", "-shm"))
        ):
            raise KeyError("artifact not found")
        if name in {"selection.json", "report.html", "files.json"} and (
            state["status"] in {"running", "preparing", "interrupted"}
            or state.get("stop_reason") == "publication_failed"
        ):
            raise KeyError("artifact not published")
        index = self.folder(identity) / "files.json"
        if index.is_file() and name not in {"search.json", "files.json"}:
            entry = next(
                (item for item in read(index)["files"] if item["name"] == name), None
            )
            if entry is not None and (
                path.stat().st_size != entry["bytes"]
                or file_hash(path) != entry["sha256"]
            ):
                raise ValueError("已发布产物的内容与校验记录不同")
        return path
