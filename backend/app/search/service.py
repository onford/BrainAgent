import asyncio
from app.owned_thread import _owned_thread
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sys
import time
from uuid import uuid4


from app.llm.client import OpenAICompatibleClient
from app.llm.budget import BudgetExceeded
from app.preprocessing.resources import budget as resource_budget
from app.preprocessing.schemas import PreprocessInput, MethodSpec, Ref
from app.preprocessing.storage import digest, file_hash, within
from app.preprocessing.units import engine_hash, environment
from .catalog import BASELINE_ID, method, search_engine_hash, select
from .contracts import ActionRecord, Candidate, SearchRequest, SearchState
from .io import directory_bytes, read, write
from .processes import ProcessTree
from .initial_recommendation import recommend
from .evaluation_contracts import FrozenPanel, EvaluationReceipt
from .method_space import seed_entries, verify_registry
from .scientific_space import build_space, input_context, knowledge
from .space_contracts import ExplorationSpace
from .knowledge_contracts import ScientificKnowledge
from .neural_priors import freeze_bundle


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
        from .metric_reading import MetricReader
        self.metric_reader = MetricReader(self.llm,
            budget_path=lambda state: self.workflows.folder(state['workflow_id']) / 'llm-budget.json')
        if isinstance(self.llm, OpenAICompatibleClient):
            # Every actual provider request is charged by the search ledger.
            self.llm = OpenAICompatibleClient(
                self.llm.config, self.llm._transport, max_retries=0
            )
        self.tasks = {}
        self.children = {}
        self.cancelled = set()
        self.verified = set()
        from .knowledge_registry import KnowledgeRegistry
        self.knowledge_registry=KnowledgeRegistry(self.root.parent/'knowledge-registry',knowledge())
        if getattr(workflows,'preprocessing',None) is not None:
            workflows.preprocessing.knowledge_registry=self.knowledge_registry

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
        from .method_provenance import method_status
        write(self.folder(state["id"]) / "method-status.json", method_status(value))

    def describe(self, owner, identity, include_artifacts=True):
        state = self.get(owner, identity)
        from .run_control import Controls
        state['cancellation_requested'] = state['status'] in {'preparing', 'running', 'interrupted'} and Controls(self.folder(identity)).snapshot().pending is not None
        from .method_provenance import participation
        state["literature_participation"] = participation(state)
        from .recipe_contrast import contrasts_to_reference
        state["candidate_contrasts_to_reference"] = contrasts_to_reference(state)
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
            "sources.json": "首次推荐可用的冻结资料",
            "input.json": "标准化输入及校验清单",
            "files.json": "全部搜索与数值执行产物索引",
            "limits.json": "冻结资源预算",
            "control.json": "跨执行器停止请求与恢复代次历史",
            "space.json": "算子、参数域、方法起点及可检查的科学先验",
            "registry.json": "冻结的完整配方与方法来源",
            "method-intake.json": "本轮文献方法的可执行性检查、原始草案及编译结果",
            "method-extraction.json": "本轮来源到多分支方法的拆解清单",
            "method-status.json": "基础与文献方法的来源关系和固定执行状态",
            "initial-recommendation.json": "数值评价前冻结的首次推荐、理由和执行顺序",
            "probe-panel.json": "覆盖全部被试的固定重建探针与污染条件分配",
            "scientific-knowledge.json": "顺序、参数及适用条件的来源与证据缺口",
            "knowledge-coverage.json": "研究规则的有限执行绑定、条件建议和未解决议题队列",
            "knowledge-revision.json": "本轮冻结知识修订、来源状态变更及影响范围",
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
                descriptions[name] = "该次评价输入的核心模型原始回执"
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
                            "utility.json": "保存协议的逐被试成绩、逐种子明细（如有）与拟合证据",
                            "data-quality.json": "全部记录在不同信号阶段的质量指标、单位和分母",
                            "reconstruction_evaluation.json": "已知污染的去除效果与原信号保留，含失败及适用性",
                            "artifact-manifest.json": "本次多维评价的完整文件、大小与校验清单",
                            "core-receipt.json": "保存协议的核心模型原始数值回执",
                            "model.joblib": "仅由该折训练数据拟合的可复算模型",
                            "model.pt": "EEGNet 对应种子与折的训练模型",
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

    def knowledge_impact(self, owner):
        from .knowledge_registry import impact, verify_snapshot
        current = self.knowledge_registry.get(owner)
        runs = []
        for path in self.root.glob('*/search.json'):
            state = read(path)
            if state['owner'] != owner:
                continue
            row = dict(search_id=state['id'], status=state['status'], historical_artifacts_modified=False)
            protocol = state.get('protocol', {})
            snapshot_path = path.parent / 'knowledge-revision.json'
            catalog_path = path.parent / 'scientific-knowledge.json'
            try:
                if protocol.get('knowledge_revision_hash'):
                    snapshot = verify_snapshot(read(snapshot_path))
                    if digest(snapshot) != protocol['knowledge_revision_hash']:
                        raise ValueError('frozen knowledge hash differs from protocol')
                    previous = snapshot['catalog']
                    row['frozen_revision_sha256'] = snapshot['sha256']
                else:
                    previous = read(catalog_path)
                    if digest(previous) != protocol.get('scientific_knowledge_hash'):
                        raise ValueError('legacy knowledge hash differs from protocol')
                    row['frozen_revision_sha256'] = None
                row.update(review_status='compared', impact=impact(previous,current['catalog']))
            except (KeyError, ValueError, OSError) as exc:
                row.update(review_status='unverifiable', reason=str(exc))
            runs.append(row)
        return dict(current_revision_sha256=current['sha256'], runs=runs,
                    policy='Read-only comparison; historical measurements and frozen execution are never rewritten.')

    def create(self, owner, request: SearchRequest, *, start=True):
        from .interpretation import interpretation_guide, evidence_document
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
        # Freeze the approved CPU EEGNet defaults; the utility protocol records device/runtime.
        utility_config = utility_execution({
            "eegnet_training": {"max_epochs": 100, "patience": 15, "validation_fraction": 0.2},
            "max_workers": min(2, os.cpu_count() or 1),
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
        from .literature_space import build_workflow_space

        intake_path = folder / "preprocessing/literature-methods/manifest.json"
        review_path = folder / "survey/literature.json"
        if not intake_path.exists() and review_path.exists() and any(
            e["decision"] == "included" for e in read(review_path).get("entries", [])
        ):
            raise ValueError("本轮纳入文献尚未完成方法拆解；先运行 preprocessing 的文献拆解子阶段。")
        intake = read(intake_path) if intake_path.exists() else {
            "methods": [], "absence_reasons": ["本轮没有已注册的文献拆解产物。"]}
        registered = [(ref, MethodSpec.model_validate(self.workflows.preprocessing.store.get(
            owner, Ref.model_validate(ref), "method"))) for ref in intake["methods"]]
        from .source_evidence import freeze_evidence
        source_evidence = freeze_evidence(root, [m for _, m in registered], self.workflows.preprocessing.store, owner) if registered else {}
        output_contract = {k: panel_request[k] for k in ("sfreq", "tmin", "tmax")}
        knowledge_revision=self.knowledge_registry.get(owner,require_current=True)
        research=knowledge_revision['catalog']
        space, space_context, method_intake = build_workflow_space(
            data, output_contract, registered, intake.get("absence_reasons", []),knowledge_book=research)
        for row in method_intake["methods"]:
            if "compiled_method" in row:
                compiled = row.pop("compiled_method")
                row["compiled_method_path"] = f"method-compilation/{digest(compiled)[:24]}.json"
                row["compiled_method_hash"] = digest(compiled)
                write(root / row["compiled_method_path"], compiled)
        seeds = seed_entries(space, space_context)
        registry = seeds
        research_text = "\n\n".join(
            f"{r['id']} · {r['claim']}\n"
            + (f"知识状态：{r['status']}；{r.get('status_reason') or ''}\n" if r.get('status','active')!='active' else '')
            + f"条件：{r['condition']}\n解释：{r['implication']}\n来源："
            + ", ".join(r["source_ids"])
            for r in research["rules"]
        )
        research_text += "\n\n来源索引\n" + "\n".join(
            f"{s['id']}: {s['title']} · {s['url']}"
            + (f" · 状态 {s['status']} · {s.get('status_reason') or ''}" if s.get('status','active')!='active' else '')
            for s in research["sources"]
        )
        research_text += '\n知识目录默认状态仅表示本修订启用；关联来源停用时其依赖规则不可作为新候选依据。'
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
        guide = interpretation_guide()
        neural = freeze_bundle(data, space, research, guide)
        from .knowledge_coverage import coverage as knowledge_coverage
        knowledge_audit = knowledge_coverage(research, space, neural, data.survey.task)
        documents.append(evidence_document(guide))
        metric_text = evaluation_evidence["interpretation"] + "\n\n" + "\n\n".join(
            f"{m['id']} · {m['name']}\n定义：{m['formula']}\n边界：{m['overCleaningAndLeakageRisk']}\n选择角色：{m['selectionRole']}"
            for m in evaluation_evidence["quality"]["metrics"]
        )
        documents.append({"id": "evaluation-evidence", "title": "评价指标定义与解释边界（研究目录）",
                          "url": "brainagent:evaluation-evidence:1", "text": metric_text, "sha256": digest(metric_text)})
        protocol = {
            "source_evidence": source_evidence,
            "business_version": "fixed-recommendation-2026-09-13.1",
            "literature_adaptation_policy": "shared-final-epoch-window-v1",
            "selection_requires_complete_assessment": True,
            "scheduling_policy": "initial_recommendation_frozen_before_evaluation; no feedback-driven changes",
            "version": "4",
            "request": request.model_dump(mode="json"),
            "deadline": started + request.budget.max_seconds,
            "input_hash": digest(data_json),
            "source_workflow_id": request.workflow_id,
            "scope": "offline_development_panel",
            "evaluator": "fixed-eegnet-three-seed-subject-macro-utility-v2",
            "anchor_evaluator": "csp-shrinkage-lda-v2",
            "benchmark_evaluators": ["csp_lda"],
            "utility_version": 2,
            "evaluation_mode": "subject_holdout"
            if request.train_subjects
            else "group_cross_validation",
            "split_rationale": "Explicit subject roles"
            if request.train_subjects
            else "Seeded subject folds, min(5, n_subjects); every subject has out-of-fold predictions. Engineering evaluation protocol, not a dataset optimum.",
            "metric": "mean_subject_macro_ba_across_eegnet_seeds_17_42_2026",
            "selection": "highest_complete_eegnet_three_seed_utility",
            "tie_break": ["reference", "fewer_operators", "candidate_id"],
            "assessment": {
                "version": 2,
                "schema_version": "assessment-v2",
                "primary_suite": ["eegnet"],
                "seeds": [17, 42, 2026],
                "weighting": "equal_subjects_then_equal_seeds",
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
            "method_intake": method_intake,
            "method_extraction": intake,
            "catalog_hash": digest(seeds),
            "registry_hash": digest(registry),
            "space": space.model_dump(mode="json"),
            "space_hash": digest(space.model_dump(mode="json")),
            "space_context": space_context,
            "scientific_knowledge_hash": digest(research),
            "knowledge_coverage_hash": digest(knowledge_audit),
            "knowledge_revision_hash": digest(knowledge_revision),
            "evaluation_evidence_hash": digest(evaluation_evidence),
            "interpretation_guide_hash": digest(guide),
            "neural_priors": neural,
            "neural_priors_hash": digest(neural),
            "environment": environment(),
            "numeric_engine_hash": engine_hash(),
            "search_engine_hash": search_engine_hash(),
            "sources_hash": digest(documents),
            "panel_request_hash": digest(panel_request),
            "limits": limits.model_dump(),
            "numeric_threads": 1,
            "record_workers": min(4, max(1, (os.cpu_count() or 1) // 2)),
            "preprocessing_scope": "shared_recipe_all_records",
            "information_permissions": {
                "target_signals": "record_local_algorithm_input",
                "target_labels": "scoring_only",
                "policy_selection": "initial_recommendation_before_evaluation",
                "independent_confirmation": False,
            },
            "parameter_provenance": {
                "domains": "operator-specific bounded domains with source or engineering provenance in space.json",
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
        write(root / "method-intake.json", method_intake)
        write(root / "method-extraction.json", intake)
        for ref, registered_method in registered:
            write(root / "source-methods" / (ref["id"][:24] + ".json"), registered_method.model_dump(mode="json"))
        # Include the exact model inputs and original branch responses in search exports.
        extraction_root = folder / "preprocessing/literature-methods"
        if extraction_root.exists():
            for path in extraction_root.rglob("*.json"):
                write(root / "literature-methods" / path.relative_to(extraction_root), read(path))
        write(root / "scientific-knowledge.json", research)
        write(root / "knowledge-coverage.json", knowledge_audit)
        write(root / "knowledge-revision.json", knowledge_revision)
        write(root / "evaluation-evidence.json", evaluation_evidence)
        write(root / "interpretation-guide.json", guide)
        write(root / "neural-priors.json", neural)
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
        state = self.get(owner, identity)
        self.require_current(state)
        self.verify_runtime(state)
        if identity not in self.tasks or self.tasks[identity].done():
            self.tasks[identity] = asyncio.create_task(self.run(owner, identity))

    async def resume(self):
        for path in self.root.glob("*/search.json"):
            state = read(path)
            if state["status"] in {"preparing", "running", "interrupted"}:
                try:
                    self.start(state["owner"], state["id"])
                except (IntegrityFailure, OSError, KeyError, ValueError):
                    continue

    @staticmethod
    def require_current(state):
        if state.get('protocol', {}).get('version') != '4':
            raise ValueError('旧版自主搜索仅供只读查看；新流程使用首次推荐后固定执行协议')

    async def close(self):
        active = [t for t in self.tasks.values() if not t.done()]
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)

    def cancel(self, owner, identity):
        import portalocker
        from .run_control import Controls
        self.require_current(self.get(owner, identity))
        controls = Controls(self.folder(identity))
        with controls.transaction() as control:
            state = self.get(owner, identity)
            if state["status"] not in {"preparing", "running", "interrupted"}:
                raise ValueError("只有正在进行的搜索可以取消")
            controls.request(control, owner)
        self.cancelled.add(identity)
        task = self.tasks.get(identity)
        if task and not task.done():
            task.cancel()
        else:
            try:
                with portalocker.Lock(self.folder(identity) / 'search.lock', timeout=0):
                    state = self.get(owner, identity)
                    if state['status'] in {'preparing', 'running', 'interrupted'}:
                        self.interrupt_pending(state, '用户已请求取消，尚未产生完整评价')
                        state.update(status="cancelled", stop_reason="cancelled_by_user")
                        self.save(state)
            except portalocker.exceptions.LockException:
                pass
        return self.describe(owner, identity)

    def retry(self, owner, identity):
        import portalocker
        from .run_control import Controls
        self.require_current(self.get(owner, identity))
        try:
            with portalocker.Lock(self.folder(identity) / 'search.lock', timeout=0):
                with Controls(self.folder(identity)).transaction() as control:
                    self._retry_locked(owner, identity)
                    Controls.resume(control)
        except portalocker.exceptions.LockException as exc:
            raise ValueError('搜索仍由执行器处理，待停止后再重试') from exc
        self.start(owner, identity)
        return self.describe(owner, identity)

    def _retry_locked(self, owner, identity):
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
        return state

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
                        # Durable writes may stall on busy storage. Keep API
                        # requests responsive while retaining execution ownership
                        # until the checkpoint has finished, including cancellation.
                        await _owned_thread(self.save, state)
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

    async def recommend_initial(self, state, documents):
        if state["candidates"] or state.get("recommendation") is not None:
            raise IntegrityFailure("首次推荐已冻结或数值评价已开始，不能再次调用推荐模型")
        if self.llm is None:
            raise RuntimeError("首次推荐需要配置模型")
        self.guard(state)
        self.verify_runtime(state)
        state["usage"]["llm_calls"] += 1
        action = self.action(
            state,
            "initial_recommendation",
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
                from app.llm.usage import usage_scope
                with usage_scope(self.folder(state["id"]) / "llm-calls.json", action["action"],
                                 budget_path=self.workflows.folder(state['workflow_id']) / 'llm-budget.json'):
                    result = await recommend(self.llm, state, documents, capture=capture)
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
        self.verify_recommendation(state)
        if identity not in [BASELINE_ID, *state["schedule"]]:
            raise IntegrityFailure("候选不在首次冻结推荐中")
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
        self.require_current(self.get(owner, identity))
        lock = portalocker.Lock(root / 'search.lock', timeout=0)
        try:
            lock.acquire()
        except portalocker.exceptions.LockException:
            return
        try:
            task = asyncio.current_task()
            control_errors = []
            monitor = asyncio.create_task(self._watch_cancellation(identity, task, control_errors))
            try:
                await self._run_locked(owner, identity, control_errors)
            finally:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
        finally:
            lock.release()

    async def _watch_cancellation(self, identity, owner_task, errors):
        from .run_control import Controls
        controls = Controls(self.folder(identity))
        while True:
            await asyncio.sleep(.1)
            try:
                requested = controls.snapshot().pending is not None
            except Exception as exc:
                errors.append(f'{type(exc).__name__}: {exc}')
                owner_task.cancel()
                return
            if requested:
                self.cancelled.add(identity)
                owner_task.cancel()
                return

    async def _run_locked(self, owner, identity, control_errors):
        from .run_control import Controls
        state = self.get(owner, identity)
        self.verified.discard(identity)
        self.cancelled.discard(identity)
        try:
            if state['status'] in {'completed', 'stopped', 'failed', 'cancelled'}:
                return
            await self._run_outcome(state)
        except asyncio.CancelledError:
            try:
                requested = Controls(self.folder(identity)).snapshot().pending is not None
            except Exception as exc:
                control_errors.append(f'{type(exc).__name__}: {exc}')
                requested = False
            self.interrupt_pending(state, "搜索已中断，尚未产生完整评价")
            state["usage"]["elapsed_seconds"] = max(
                0, time.time() - (state["deadline"] - state["budget"]["max_seconds"])
            )
            state.update(
                status="cancelled" if requested else "interrupted",
                selected_candidate_id=None,
                stop_reason="cancelled_by_user"
                if requested
                else "service_interrupted",
            )
            if control_errors:
                state.update(status='failed', stop_reason='integrity_failure',
                             error='Cancellation control unavailable: ' + control_errors[0],
                             selected_candidate_id=None)
                for candidate in state['candidates']:
                    if candidate['status'] == 'evaluated':
                        candidate['status'] = 'invalidated'
            self.save(state)

    async def _run_outcome(self, state):
        try:
            from .run_control import Controls
            try:
                pending = Controls(self.folder(state['id'])).snapshot().pending
            except Exception as exc:
                raise IntegrityFailure(f'Cancellation control unavailable: {exc}') from exc
            if pending is not None:
                raise asyncio.CancelledError()
            await self._run(state)
        except BudgetStop as exc:
            await self.stop(state, "stopped", str(exc))
        except BudgetExceeded as exc:
            state['unresolved'].append(str(exc))
            await self.stop(state, 'stopped', 'model_budget_exhausted')
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
        if protocol.get('knowledge_coverage_hash') and digest(read(root/'knowledge-coverage.json')) != protocol['knowledge_coverage_hash']:
            raise IntegrityFailure('冻结研究覆盖与未解决议题队列已改变')
        if protocol.get('knowledge_revision_hash') and digest(read(root/'knowledge-revision.json')) != protocol['knowledge_revision_hash']:
            raise IntegrityFailure('冻结知识修订已改变')
        if protocol.get("interpretation_guide_hash") and digest(read(root / "interpretation-guide.json")) != protocol["interpretation_guide_hash"]:
            raise IntegrityFailure("冻结图表解读知识库已改变")
        if protocol.get("neural_priors_hash") and (
            digest(read(root / "neural-priors.json")) != protocol["neural_priors_hash"]
            or digest(protocol["neural_priors"]) != protocol["neural_priors_hash"]
        ):
            raise IntegrityFailure("冻结神经先验已改变")
        if digest(state["registry"]) != protocol["registry_hash"]:
            raise IntegrityFailure("执行目录与首次冻结的完整方法集合不同")
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
        await self.freeze_recommendation(state, documents)
        scheduled = [BASELINE_ID, *state['schedule']]
        for identity in scheduled:
            self.guard(state)
            self.verify_recommendation(state)
            previous = next((c for c in state['candidates'] if c['id'] == identity), None)
            if previous and previous['status'] == 'evaluated':
                continue
            if previous is None and state['usage']['candidates'] >= state['budget']['max_candidates']:
                await self.stop(state, 'stopped', 'candidate_budget_exhausted')
                return
            state.update(phase='candidate', message='按首次冻结推荐执行并评价固定流程')
            self.save(state)
            candidate = await self.candidate(state, identity)
            if identity == BASELINE_ID and candidate['status'] != 'evaluated':
                state['error'] = candidate.get('error') or '固定参考未能完成共同面板评价'
                await self.stop(state, 'failed', 'reference_failed')
                return
        await self.stop(state, 'completed', 'schedule_exhausted')

    async def freeze_recommendation(self, state, documents):
        if state.get('recommendation') is None:
            if state['candidates']:
                raise IntegrityFailure('数值评价已开始但缺少首次冻结推荐')
            completed = [a['result'] for a in state['actions']
                         if a['action'] == 'initial_recommendation' and a['status'] == 'completed']
            if len(completed) > 1:
                raise IntegrityFailure('首次推荐出现多个已完成结果')
            if completed:
                plan = completed[0]
            else:
                while True:
                    try:
                        plan = await self.recommend_initial(state, documents)
                        break
                    except (BudgetStop, BudgetExceeded, IntegrityFailure):
                        raise
                    except (ValueError, RuntimeError):
                        if state['usage']['retries'] >= state['budget']['max_retries']:
                            raise
                        state['usage']['retries'] += 1
                        self.save(state)
            proposed = plan['candidate_ids']
            available = {c['id'] for c in state['registry']}
            ids = [i for i in proposed if i != BASELINE_ID]
            if (len(proposed) != len(set(proposed)) or not set(proposed) <= available
                    or len(ids) > state['budget']['max_candidates'] - 1):
                raise ValueError('首次推荐须为预算内、不重复的冻结目录候选')
            state['schedule'] = ids
            state['recommendation'] = dict(schema_version='fixed-recommendation-1', candidate_ids=ids,
                reason=plan['reason'], registry_hash=digest(state['registry']), recommended_at=now())
            state['usage']['recommended_candidates'] = len(ids)
            self.save(state)
        path = self.folder(state['id']) / 'initial-recommendation.json'
        if not path.exists():
            if state['candidates']:
                raise IntegrityFailure('已执行流程的冻结推荐文件缺失')
            write(path, state['recommendation'])
        self.verify_recommendation(state)

    def verify_recommendation(self, state):
        recommendation = state.get('recommendation')
        if (not recommendation or state['schedule'] != recommendation['candidate_ids']
                or digest(state['registry']) != recommendation['registry_hash']
                or digest(state['registry']) != state['protocol']['registry_hash']
                or read(self.folder(state['id']) / 'initial-recommendation.json') != recommendation):
            raise IntegrityFailure('首次推荐、固定配方或执行顺序已改变')

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
            selected_candidate_id=select(state["candidates"], require_complete_assessment=bool(state["protocol"].get("selection_requires_complete_assessment") and state["protocol"].get("assessment"))) if verified else None,
        )
        state["message"] = "固定流程评价结束，首次推荐与测量记录已保存"
        from .reporting import render

        try:
            await _owned_thread(render, self.folder(state["id"]), state)
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
