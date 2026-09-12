"""Frozen, evidence-linked advisory priors. Never a substitute for measured utility."""

from copy import deepcopy
import math
from typing import Any, Literal

from pydantic import Field, model_validator

from app.preprocessing.schemas import Contract
from app.preprocessing.storage import digest


class NeuroRule(Contract):
    id: str
    title: str
    observation: str
    comparison: Literal["gt", "lt", "eq", "present"]
    threshold: float | bool | None = None
    threshold_origin: Literal["engineering_screen", "metadata", "descriptive"]
    source_ids: list[str] = Field(min_length=1)
    knowledge_rule_ids: list[str] = Field(default_factory=list)
    implication: str
    alternative: str
    protection: str
    diagnostic: Literal["signal_profile", "paired_comparison"] = "signal_profile"


class NeuroBundle(Contract):
    schema_version: Literal["neural-priors-1"] = "neural-priors-1"
    task_profile: dict[str, Any]
    capabilities: dict[str, Any]
    sources: list[dict[str, Any]]
    rules: list[NeuroRule]
    research_coverage: list[dict[str, Any]]
    limitations: list[str]

    @model_validator(mode="after")
    def links(self):
        ids = {s["id"] for s in self.sources}
        if len(ids) != len(self.sources) or len({r.id for r in self.rules}) != len(self.rules):
            raise ValueError("duplicate neural prior/source identifiers")
        if any(not set(r.source_ids) <= ids for r in self.rules):
            raise ValueError("unresolved neural prior source")
        return self


def freeze_bundle(data, space, research, guide):
    from app.preprocessing.units import catalog, OPERATIONS

    selected = [r for r in data.collection.records if r.id in data.collection.selected_record_ids]
    cards = {c["id"]: c for c in guide["cards"]}
    sources = [{**s, "id": "guide:" + s["id"]} for s in guide["sources"]]
    units = catalog()
    rows = [
        ("mains50", "50 Hz 工频候选", "line_ratio_50hz", "gt", 3.0, "mains", [],
         "在可测宽带视图比较无陷波与50 Hz陷波；先检查现有滤波是否已足够。",
         "窄带神经活动、谱估计或已有滤波也会影响比值；3 dB仅为工程筛查值。",
         "同时检查任务频带与滤波时间失真，不能因残余下降就确认神经保留。"),
        ("mains60", "60 Hz 工频候选", "line_ratio_60hz", "gt", 3.0, "mains", [],
         "在可测宽带视图比较无陷波与60 Hz陷波，不从地区推测工频。",
         "不可测频段不是无污染；已有任务带通可能使新增陷波冗余。",
         "匹配候选只改变待检验步骤，核对任务信息与效用。"),
        ("low-correlation", "低相关需要联合诊断", "low_correlation_fraction", "gt", 0.1, "correlation", ["R11", "R26"],
         "联合平坦、持续偏离与空间邻域区分坏道和共同活动，不直接插值所有低相关通道。",
         "参考、强局部生理活动和瞬态污染均可改变相关性；0.1为工程筛查比例。",
         "保护通道语义和任务ROI；高相关也可能由共同污染或插值造成。"),
        ("flat", "持续平坦候选", "flat_fraction", "gt", 0.0, "flat", [],
         "核对原始连续片段及采集故障，再考虑标记与修复。",
         "短任务窗无法满足持续时长条件，缺失不能记为0。",
         "记录受影响时间、通道与修复范围，不改变固定试次分母。"),
        ("eog-missing", "真实EOG是否在所有记录齐备", "has_eog", "eq", False, "amplitude", ["R40", "R68"],
         "至少部分记录缺少真实EOG时，不对所有记录统一使用EOG回归；额区EEG代理必须单独标识。",
         "额区瞬变本身不能证明眼动来源，也不能证明全部相关成分应删除。",
         "继续适用的无辅助通道诊断，保留眼动原因未确认。"),
        ("iclabel-domain", "成分分类输入域", "minimum_nyquist_hz", "lt", 100.0, "spectrum", ["R68"],
         "原始带宽不足1–100 Hz时记录ICLabel输入域偏离，需要额外验证。",
         "上采样只改变网格，不能恢复原始高频信息。",
         "只有显式声明的原生图拟合与决策权限可授权成分清理，不把来源目录当作执行权限。"),
        ("mu-observation", "μ频带是观测而非合格标准", "mu_mean_psd", "present", None, "task", [],
         "结合真实基线、时序和感觉运动ROI解释μ活动，必要时比较合理频带。",
         "功率差异可能来自非周期成分或个体峰频；无典型μ不等于坏数据。",
         "不能为制造教科书式ERD/侧化而清理或剔除被试。"),
        ("beta-observation", "β频带与高频污染", "beta_mean_psd", "present", None, "task", [],
         "将β任务调制与肌电代理分开观察，联合检查时空模式。",
         "高频或大幅活动并不全是肌电；单个比值不能识别来源。",
         "同时报告任务变化、污染代理及实际处理作用。"),
        ("rank", "有效空间与参考", "numerical_rank", "present", None, "rank", ["R17", "R60"],
         "检查参考、插值及ASR的有效子空间和拟合兼容。",
         "平均参考的秩下降可能是预期代数结果，不是清理失败。",
         "评价使用共享预处理的物理电压，阈值必须对应单位、参考和频带。"),
        ("erds", "真实基线支持的任务调制", "erds_mu", "present", None, "task", [],
         "只用同处理且事件支持的真实基线解释ERDS；可请求配对诊断。",
         "零相位滤波、基线污染和不同参考可造成变化；方向符合不是机制确认。",
         "保留有效试次分母和缺失原因，不要求人人具有同一方向。"),
    ]
    rules = []
    for identity, title, observation, comparison, threshold, card, refs, implication, alternative, protection in rows:
        rules.append(NeuroRule(
            id=identity, title=title, observation=observation, comparison=comparison,
            threshold=threshold, threshold_origin="metadata" if observation in {"has_eog", "minimum_nyquist_hz"}
            else "descriptive" if comparison == "present" else "engineering_screen",
            source_ids=["guide:" + s for s in cards[card]["source_ids"]], knowledge_rule_ids=refs,
            implication=implication, alternative=alternative, protection=protection,
        ))
    # Include precise research anchors when a rule needs evidence beyond its interpretation card.
    referenced = {i for r in rules for i in r.knowledge_rule_ids}
    research_rules = {r["id"]: r for r in research["rules"]}
    for rid in referenced:
        if rid not in research_rules:
            raise ValueError("missing frozen research rule: " + rid)
    extra = {s for rid in referenced for s in research_rules[rid]["source_ids"]}
    sources += [{**s, "id": "research:" + s["id"]} for s in research["sources"] if s["id"] in extra]
    for rule in rules:
        rule.source_ids += sorted({"research:" + s for rid in rule.knowledge_rule_ids for s in research_rules[rid]["source_ids"]})
    task = {
        "dataset_id": data.survey.dataset_id, "task": data.survey.task,
        "record_count": len(selected), "has_eog": all("eog" in r.channels.values() for r in selected) if selected else None,
        "eog_record_count": sum("eog" in r.channels.values() for r in selected),
        "minimum_nyquist_hz": min((r.sfreq / 2 for r in selected), default=None),
        "protection_targets": ["task_time_frequency_structure", "sensorimotor_roi", "event_timing", "channel_reference_semantics"],
        "individual_pattern_required": False, "sensorimotor_roi": ["C3", "Cz", "C4"],
        "target_signal_permission": "record_local_unlabelled_under_explicit_graph_permission",
        "recipe_scope": "shared_all_records",
        "target_labels": "scoring_only", "independent_confirmation": False,
        "baseline": "verified_precue_same_processing_only", "unknown_facts": ["individual_peak_frequency", "true_neural_sources", "individual_head_model"],
    }
    capabilities = {"catalog_units": len(units), "enabled_units": len({u for u, _ in OPERATIONS}),
                    "enabled_operations": len(OPERATIONS), "search_operators": len(space.operators),
                    "units": [{"id": u.id, "operations": sorted(o for unit, o in OPERATIONS if unit == u.id),
                               "search_operators": [o.id for o in space.operators if o.unit_id == u.id],
                               "status": u.validation["integration"]} for u in units]}
    coverage = [{"topic": c["id"], "source_ids": ["guide:" + s for s in c["source_ids"]],
                 "status": "curated_interpretation_not_exhaustive_review", "next_checks": c["checks"],
                 "counter_explanations": c["alternatives"]} for c in guide["cards"]]
    return NeuroBundle(task_profile=task, capabilities=capabilities, sources=sources, rules=rules,
                       research_coverage=coverage, limitations=[
                           "Conditional suggestions, not validated physiological decision thresholds.",
                           "Source linkage is not evidence that every claim is empirically validated.",
                           "No automatic promotion of new literature or changes to EEGNet selection.",
                       ]).model_dump(mode="json")


def evaluate_priors(bundle, observations, *, candidate_id=None):
    book = NeuroBundle.model_validate(bundle)
    context = {key: {"value": book.task_profile.get(key), "status": "ok", "reference": "frozen_task_profile"}
               for key in ("has_eog", "minimum_nyquist_hz")}
    context.update(deepcopy(observations))
    for row in context.values():
        value = row.get("value")
        if type(value) is float and not math.isfinite(value):
            row.update(value=None, status="not_computable", reason="nonfinite_observation")
    results = []
    for rule in book.rules:
        row = context.get(rule.observation) or {}
        value = row.get("value")
        known = row.get("status") == "ok" and type(value) in (int, float, bool) and math.isfinite(value)
        status = "unknown"
        if known:
            if rule.comparison == "present":
                matched = True
            elif rule.comparison == "eq":
                matched = type(value) is type(rule.threshold) and value == rule.threshold
            elif type(value) is bool:
                known = False
                matched = False
            else:
                matched = value > rule.threshold if rule.comparison == "gt" else value < rule.threshold
            status = ("true" if matched else "false") if known else "unknown"
        results.append({**rule.model_dump(mode="json"), "condition_state": status,
                        "observed": deepcopy(row), "reason": "condition_satisfied" if status == "true"
                        else "condition_not_satisfied" if status == "false" else row.get("reason") or "missing_or_partial_observation",
                        "role": "advisory_not_selection_score"})
    return {"schema_version": "prior-evaluation-1", "bundle_sha256": digest(bundle),
            "context_sha256": digest(context), "candidate_id": candidate_id, "rules": results,
            "counts": {s: sum(r["condition_state"] == s for r in results) for s in ("true", "false", "unknown")}}


def frozen_context(state):
    bundle = state.get("protocol", {}).get("neural_priors")
    if bundle is None:
        return {"status": "not_frozen_in_this_run"}
    diagnostics = state.get("diagnostics", [])
    return {"status": "frozen", "task_profile": bundle["task_profile"],
            "capabilities": {k: v for k, v in bundle["capabilities"].items() if k != "units"},
            "rules": bundle["rules"], "sources": bundle["sources"],
            "research_coverage": bundle["research_coverage"],
            "diagnostics": [{k: v for k, v in d.items() if k != "subjects"} for d in diagnostics[-8:]],
            "limits": bundle["limitations"],
            "available_diagnostics": ["signal_profile", "paired_comparison"]}
