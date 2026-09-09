"""Deterministic report projection from search records; no generated conclusions."""

from html import escape
import json
from pathlib import Path
from urllib.parse import quote

from .io import write
from .catalog import BASELINE_ID, selection_score
from app.preprocessing.storage import digest, file_hash, within
from .utility_contracts import LEARNER_SUITE, PRIMARY_SUITE


LEARNER_LABELS = dict(zip(LEARNER_SUITE, ("CSP/LDA", "FBCSP", "TS/LR", "FgMDM", "逐频带 EA-FBCSP", "对数方差 LR")))
UTILITY_METRICS = ("ba", "accuracy", "f1", "kappa", "auc", "brier", "logloss")
RECON_UNITS = dict.fromkeys((
    "input_nrmse", "paired_nrmse", "paired_error_cleanproxy_ratio", "reconstruction_nrmse",
    "paired_correlation", "reconstruction_correlation", "artifact_residual_coefficient",
    "artifact_residual_rms_ratio", "clean_retention_nrmse", "clean_retention_rms_ratio",
    "clean_retention_correlation", "clean_retention_gain"), "无量纲")
RECON_UNITS.update(paired_ser_improvement_db="dB", reconstruction_ser_improvement_db="dB")


def _value(value):
    """Display observations without fabricating a scalar from an array or null."""
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, list):
        preview = ", ".join(_value(v) for v in value[:6])
        return f"数组/曲线（{len(value)} 项）：[{preview}{', …' if len(value) > 6 else ''}]"
    if isinstance(value, dict):
        return "; ".join(f"{k}={_value(v)}" for k, v in value.items()) or "未提供"
    return str(value)


def _table(headers, rows):
    return ('<div class="scroll"><table><thead><tr>'
            + "".join(f"<th>{escape(h)}</th>" for h in headers) + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(f"<td>{escape(_value(v))}</td>" for v in row) + "</tr>" for row in rows)
            + "</tbody></table></div>")


def _link(identity, relative, label=None):
    url = f"/api/searches/{quote(identity, safe='')}/artifacts/{quote(relative, safe='/')}?download=true"
    return f'<a href="{escape(url, quote=True)}">{escape(label or relative)}</a>'


def _notes(values):
    return "<ul>" + "".join(f"<li>{escape(str(v))}</li>" for v in values if v) + "</ul>"


def render_operator_usage(summary):
    """Render the native operator-usage-v1 summary without deriving success rates."""
    from .operator_usage import OperatorUsageSummary

    summary = OperatorUsageSummary.model_validate(summary).model_dump(mode="json")
    result = ("<p>按冻结计划的 record × method 对统计，包含未完成记录。applied 表示调用完成，"
              "不表示信号发生变化或质量改善；ASR 还须有实际应用证据。校准不足时的 identity 属于 "
              "not_applicable，不计入 applied。failed 与 not_reached 分别保留；原因计数按记录去重，"
              "同一记录可有多个原因，不能相加当作记录数。</p>")
    result += _table(["计划记录数", "记录执行状态", "存在证据问题的记录数"], [[
        summary["record_count"], summary["record_execution_counts"], summary["evidence_issue_records"]]])
    result += _table(["算子", "配置记录数", "固定记录分母", "applied", "not_applicable", "failed", "not_reached", "各状态原因计数"], [
        [identity, row["configured_records"], row["denominator"],
         *[row["counts"][status] for status in ("applied", "not_applicable", "failed", "not_reached")],
         row["reason_counts"]] for identity, row in summary["operators"].items()])
    return result


def _operator_usage_sections(root, state):
    """Receipt artifact paths are relative to the candidate directory."""
    sections = []
    for candidate in state["candidates"]:
        usage = (candidate.get("receipt") or {}).get("operator_usage")
        if usage is None:
            continue
        from .operator_usage import OperatorUsage, OperatorUsageReport

        usage = OperatorUsage.model_validate(usage).model_dump(mode="json")
        ref = usage["artifact"]
        path = within(within(root, "candidates/" + candidate["id"]), ref["path"])
        if not path.is_file() or path.stat().st_size != ref["bytes"] or file_hash(path) != ref["sha256"]:
            raise ValueError("report operator usage artifact checksum differs")
        native = OperatorUsageReport.model_validate_json(path.read_bytes())
        if native.summary.model_dump(mode="json") != usage["summary"]:
            raise ValueError("report operator usage summary differs from native artifact")
        body = render_operator_usage(usage["summary"])
        body += '<p>' + _link(state["id"], path.relative_to(root).as_posix(), "完整算子适用性与逐记录证据")
        body += f' — {ref["bytes"]} bytes · SHA256 <code>{ref["sha256"]}</code></p>'
        sections.append(f'<details><summary>{escape(candidate["title"])} · {escape(candidate["status"])}</summary>{body}</details>')
    return '<h2>算子适用性</h2>' + "".join(sections) if sections else ""


def _utility_section(assessment, native=None):
    utility = assessment["utility"]
    value = assessment["selection_score"]
    result = '<h3>训练效用：三主模型等权均值</h3>'
    result += f'<p><strong>assessment.selection_score：{escape(_value(value))}（{score(value)}）</strong>；状态：{escape(utility["status"])}。</p>'
    result += ("<p>先计算每个模型的开发被试平均平衡准确率，再对 CSP/LDA、FBCSP、TS/LR 等权平均。"
               "三个模型须完整覆盖同一开发分母；缺失模型不产生选择分数。其余三个模型为独立对照。"
               "核心 CSP macro_ba 仅保留为锚点；质量和重建不加入选择总分。</p>")
    result += _table(["主模型完整数", "主模型预测覆盖", "分母范围", "效用均值", "被试效用 Q25", "被试效用 SD"], [[
        f"{utility['primary_models_available']}/{utility['primary_models_expected']}",
        f"{utility['primary_trial_predictions_available']}/{utility['primary_trial_predictions_expected']}",
        utility["denominator_scope"] + " / " + utility["evaluation_mode"],
        (utility.get("summary") or {}).get("mean"), (utility.get("summary") or {}).get("lower_quartile"),
        (utility.get("summary") or {}).get("subject_sd")]])
    if native:
        result += _table(["模型", "实际输入表示", "状态", "原因"], [
            [LEARNER_LABELS[name], native["learners"][name]["input_representation"], native["learners"][name]["status"],
             native["learners"][name].get("error")] for name in LEARNER_SUITE])
        result += "<p>candidate_representation 指候选实际评分表示；pre_adaptation_phys_V 指适配前物理电压。逐频带 EA-FBCSP 为独立物理输入对照，不代表候选上游 EA 的效果。</p>"
    rows = []
    for name in LEARNER_SUITE:
        coverage = utility["learner_coverage"][name]
        for metric in UTILITY_METRICS:
            distribution = utility["learner_statistics"][name].get(metric)
            observed = distribution or {}
            rows.append([LEARNER_LABELS[name], "主模型" if name in PRIMARY_SUITE else "独立对照", metric,
                observed.get("mean"), observed.get("lower_quartile"), observed.get("subject_sd"),
                f"{observed.get('n_subjects', 0)}/{coverage['subjects_expected']}",
                f"{coverage['trials_available']}/{coverage['eligible_trials_expected']}",
                utility["learner_statuses"][name] if distribution else "N/A：未提供该指标；模型状态=" + utility["learner_statuses"][name]])
    result += '<h4>六模型各指标分布</h4><p>数值均为无量纲原值。BA、accuracy、F1、AUC、Brier 为 0–1；κ 可为负值；logloss 无上界。Q25 是被试指标的第 25 百分位，SD 为被试总体标准差，不是置信区间。概率指标缺失时保持 N/A，不由硬预测补算。指标被试数与模型 trial 覆盖分开显示。</p>'
    result += _table(["模型", "用途", "指标", "均值", "Q25", "SD", "指标被试覆盖", "模型 trial 覆盖", "状态"], rows)
    return result + _notes([utility.get("reason"), *utility["failure_reasons"], *utility["warnings"]])


def _quality_section(part):
    result = f'<h3>信号质量</h3><p>状态：{escape(part["status"])}；{escape(part.get("reason") or "")}</p>'
    result += ("<p>以下为适配前物理电压的 processed_task 阶段摘要；先在被试内汇总记录，再对被试等权汇总。"
               "曲线预览不折算为质量总分，完整曲线和其他阶段见原生产物。频带、工频、漂移与肌电量为代理观测；"
               "滤波本身可以机械性降低这些值。ERD/ERS 仅在同处理 precue 和 task 配对验证通过时可计算。"
               "无量纲 EA 表示不能直接套用物理电压阈值。</p>")
    summary = part.get("summary")
    if summary is None:
        return result + "<p>未取得质量摘要；未记为零分。</p>"
    result += _table(["覆盖", "聚合", "precue 秒区间"], [[summary.get("coverage"), summary.get("aggregation"), summary.get("precue_seconds")]])
    rows = []
    for mid, row in summary["metrics"].items():
        rows.append([mid, row.get("value"), row.get("unit"), row.get("status"), row.get("applicability"),
                     row.get("direction"), row.get("denominator"), row.get("reason"), row.get("axes"), row.get("formula")])
    result += _table(["metricID", "观察值 / 曲线预览", "单位", "状态", "适用性", "方向（不等同选择目标）", "分母 / 缺失", "原因", "坐标轴", "定义"], rows)
    result += _table(["阶段", "指标状态计数"], list(summary.get("stage_status_counts", {}).items()))
    return result + _notes(summary.get("limitations", []))


def _reconstruction_section(part):
    result = f'<h3>半合成重建</h3><p>状态：{escape(part["status"])}；{escape(part.get("reason") or "")}</p>'
    result += ("<p>真实 EEG cleanproxy 不是神经真值；结论仅针对声明的注入污染、配对窗口及物理预处理，不评价父层 EA 保真。"
               "相关系数不能单独证明保留了神经信号。未分配、失败和未定义保持各自状态，不视为零，也不生成加权总分。</p>")
    summary = part.get("summary")
    if summary is None:
        return result + "<p>未取得重建摘要。</p>"
    if summary.get("design") == "balanced":
        result += "<p>均衡部分分配：每名被试仅接受一个条件；各条件覆盖不同被试子集，不能把条件间差异解释为配对比较。</p>"
    elif summary.get("design") == "full_factorial":
        result += "<p>全因子分配：每个被试接受每个条件；失败窗口仍保留在冻结分母。</p>"
    result += _table(["设计", "被试数", "条件实例数", "trial × 条件数", "状态计数", "聚合"], [[
        summary.get("design"), summary.get("subjects_expected"), summary.get("cases_expected"),
        summary.get("trial_cases_expected"), summary.get("status_counts"), summary.get("aggregation")]])
    for condition, row in summary.get("by_case", {}).items():
        result += f'<h4>{escape(condition)}</h4>'
        result += _table(["状态", "分配被试", "未分配被试", "trial × 条件数", "状态计数"], [[
            row.get("status"), row.get("subjects_expected"), row.get("subjects_not_assigned"), row.get("trial_cases_expected"), row.get("status_counts")]])
        result += _table(["指标", "等权均值", "单位", "状态", "有效 / 分配被试"], [
            [mid, metric.get("value"), RECON_UNITS.get(mid, "原生合同未声明"), metric.get("status"),
             f"{metric.get('n_valid', 0)}/{metric.get('n_total', 0)}"] for mid, metric in row.get("metrics", {}).items()])
    return result + _notes(summary.get("limitations", []))


def _assessment_sections(root, state):
    """Verify and link every declared artifact, including non-selected candidates."""
    from .assessment import verify_assessment

    sections = []
    for candidate in state["candidates"]:
        receipt = candidate.get("receipt") or {}
        assessment = receipt.get("assessment")
        if assessment is None:
            if state["protocol"].get("assessment"):
                sections.append(f'<details><summary>{escape(candidate["title"])}：assessment 未完成</summary><p>{escape(candidate.get("error") or receipt.get("error") or "未取得完整多维回执；不显示三模型选择分数。")}</p></details>')
            continue
        if candidate["status"] != "evaluated":
            sections.append(f'<details><summary>{escape(candidate["title"])}：{escape(candidate["status"])}</summary><p>当前候选不作为可选择结果；原始文件保留于运行索引。</p></details>')
            continue
        candidate_root = within(root, "candidates/" + candidate["id"])
        attempt = within(candidate_root, receipt["assessment_path"])
        assessment = verify_assessment(attempt, assessment, candidate_id=candidate["id"], panel_hash=(state.get("panel") or {}).get("panel_hash"))
        title = candidate["title"] + (" · 暂选" if candidate["id"] == state["selected_candidate_id"] else "")
        opened = " open" if candidate["id"] == state["selected_candidate_id"] else ""
        native = None
        if assessment["utility"]["receipt_artifact"] is not None:
            native = json.loads(within(attempt, assessment["utility"]["receipt_artifact"]["path"]).read_text(encoding="utf-8"))
        body = _utility_section(assessment, native) + _quality_section(assessment["quality"]) + _reconstruction_section(assessment["reconstruction"])
        links = []
        for item in assessment["artifacts"]:
            relative = (attempt / item["path"]).relative_to(root).as_posix()
            links.append(f'<li>{_link(state["id"], relative, item["path"])} — {item["bytes"]} bytes · SHA256 <code>{item["sha256"]}</code></li>')
        for path, label in ((attempt / "assessment.json", "完整 assessment 摘要"),
                            (candidate_root / "receipt.json", "最终评价回执")):
            if path.is_file():
                links.append(f'<li>{_link(state["id"], path.relative_to(root).as_posix(), label)}</li>')
        if receipt.get("core_receipt_path"):
            path = within(candidate_root, receipt["core_receipt_path"])
            if not path.is_file():
                raise ValueError("report core receipt artifact is missing")
            if digest(json.loads(path.read_text(encoding="utf-8"))) != assessment["bindings"]["core_receipt_hash"]:
                raise ValueError("report core receipt checksum binding differs")
            links.append(f'<li>{_link(state["id"], path.relative_to(root).as_posix(), "该 attempt 的核心 CSP 回执")}</li>')
        body += '<h3>全部原生产物</h3><p>按 assessment 清单验证文件与哈希；包括预测、每折模型、协议、质量曲线、重建条件及失败记录。</p><ul>' + "".join(links) + "</ul>"
        sections.append(f'<details{opened}><summary>{escape(title)} · {escape(assessment["status"])}</summary>{body}</details>')
    return "".join(sections)


def score(value):
    return "—" if value is None else f"{value * 100:.2f}%"


def delta(value):
    return "—" if value is None else f"{value * 100:+.2f} 个百分点"


def render(root: Path, state):
    root = Path(root).resolve()
    modern = bool(state["protocol"].get("assessment"))

    def measured_score(receipt):
        if modern and (receipt or {}).get("assessment") is None:
            return None
        return selection_score(receipt)

    statuses = {
        "evaluated": "已评价",
        "completed": "已完成",
        "failed": "失败",
        "running": "执行中",
        "reserved": "待执行",
        "rejected": "已拒绝",
        "candidate_invalid": "候选无效",
        "execution_failure": "执行失败",
        "resource_failure": "资源不足",
        "data_unevaluable": "数据不可评价",
        "invalidated": "已失效",
        "interrupted": "已中断",
    }
    reasons = {
        "candidate_budget_exhausted": "候选预算耗尽",
        "proposal_budget_exhausted": "提案预算耗尽",
        "time_budget_exhausted": "时间预算耗尽",
        "memory_budget_exhausted": "内存预算耗尽",
        "disk_budget_exhausted": "磁盘预算耗尽",
        "resource_unavailable": "资源不足",
        "catalog_exhausted": "目录已遍历",
        "schedule_exhausted": "计划已执行完毕",
        "model_finished": "模型决定结束",
        "reference_failed": "固定参考失败",
        "integrity_failure": "冻结内容校验失败",
        "execution_conditions_unavailable": "执行条件不可用",
    }
    selected = next(
        (c for c in state["candidates"] if c["id"] == state["selected_candidate_id"]),
        None,
    )
    if selected is not None and (selected["status"] != "evaluated" or measured_score(selected.get("receipt")) is None):
        raise ValueError("selected candidate lacks a complete measured selection score")
    assessment_html = _assessment_sections(root, state)
    operator_usage_html = _operator_usage_sections(root, state)
    selection = {
        "schema_version": "3",
        "protocol_version": state["protocol"].get("version"),
        "search_id": state["id"],
        "selected_candidate_id": state["selected_candidate_id"],
        "selection_policy": state["protocol"].get("selection", "highest_development_subject_macro_ba"),
        "tie_break": ["reference", "fewer_operators", "candidate_id"],
        "panel_hash": state["panel"].get("panel_hash") if state["panel"] else None,
        "reference_candidate_id": BASELINE_ID,
        "stop_reason": state["stop_reason"],
        "development_evaluated": selected is not None,
        "independent_confirmation": False,
        "scientific_quality_certified": False,
        "job_id": selected.get("job_id") if selected else None,
        "plan_ref": selected.get("plan_ref") if selected else None,
        "policy": selected.get("parameters") if selected else None,
        "score": measured_score(selected.get("receipt")) if selected else None,
        "assessment": (selected.get("receipt") or {}).get("assessment") if selected else None,
        "assessment_path": (selected.get("receipt") or {}).get("assessment_path") if selected else None,
        "evaluation_mode": (state.get("panel") or {}).get("evaluation_mode"),
        "primary_learner": "equal CSP-LDA / FBCSP / TS-LR" if state["protocol"].get("assessment") else "CSP + shrinkage LDA",
        "representation": (selected.get("receipt") or {}).get("representation")
        if selected
        else None,
        "limitations": [
            "反复使用开发面板进行选择，分数不是独立泛化改善的证据。",
            "结论限于冻结算子空间、共同模型和离线信息权限；物理质量及半合成重建指标不能证明神经真值或实时部署能力。",
        ],
    }
    write(root / "selection.json", selection)
    rows = []
    for c in state["candidates"]:
        receipt = c.get("receipt") or {}
        rows.append(
            "<tr>"
            + "".join(
                f"<td>{escape(str(v))}</td>"
                for v in (
                    c["title"]
                    + (" · 暂选" if c["id"] == state["selected_candidate_id"] else ""),
                    statuses.get(c["status"], c["status"]),
                    score(measured_score(receipt)),
                    score(receipt.get("macro_ba") if modern else receipt.get("secondary_macro_ba")),
                    delta(receipt.get("mean_delta")),
                    f"{c['cost_seconds']:.1f} 秒",
                    c.get("error") or "",
                )
            )
            + "</tr>"
        )
    actions = []
    labels = {
        "propose_candidate": "候选提案",
        "request_evidence": "定向阅读",
        "finish": "结束搜索",
        "enumerate_remaining": "枚举剩余候选",
        "initial_schedule": "冻结一次性提案",
        "invalid_proposal": "提案校验未通过",
        "model_decision": "模型调用",
    }
    for a in state["actions"]:
        if a["action"] == "model_decision" and a["status"] == "completed":
            continue
        branches = a.get("decision_branches") or {}
        request, result = a.get("request") or {}, a.get("result") or {}
        hypothesis = request.get("hypothesis") or {}
        checks = (result.get("prediction_checks") or {}).get("checks", [])
        details = [
            ("候选", a.get("candidate_id")),
            ("依据候选", a.get("base_candidate_id")),
            ("理由", a["reason"] or result.get("reason")),
            ("预期", a.get("expected_result")),
            ("若改善", branches.get("improvement")),
            ("若未改善", branches.get("no_improvement")),
            ("阅读问题", request.get("question")),
            ("影响的选择", request.get("affects_choice")),
            ("来源", result.get("url")),
            ("摘录", "\n".join(result.get("excerpts", []))),
            ("候选顺序", ", ".join(result.get("candidate_ids", []))),
            ("未解决问题", "；".join(request.get("unresolved", []))),
            ("失败原因", a.get("error")),
            ("解释假设", hypothesis.get("explanation")),
            ("竞争解释", hypothesis.get("competing_explanation")),
            ("削弱该解释的结果", hypothesis.get("weakened_by")),
            (
                "预测核对",
                "；".join(
                    f"{c['metric']}：{ {'matched': '符合预测', 'contradicted': '未满足预测条件', 'unavailable': '未能测量'}.get(c['status'], c['status']) }（{c.get('before')} → {c.get('after')}）"
                    for c in checks
                ),
            ),
        ]
        actions.append(
            f"<details><summary>{a['index']} · {escape(labels.get(a['action'], a['action']))} · {escape(statuses.get(a['status'], a['status']))}</summary>"
            + "".join(
                f"<p><strong>{label}：</strong>{escape(str(value))}</p>"
                for label, value in details
                if value
            )
            + "</details>"
        )
    per_subject = []
    representation_rows = []
    if selected:
        for subject, row in (selected.get("receipt") or {}).get("subjects", {}).items():
            per_subject.append(
                f"<tr><td>{escape(subject)}</td><td>{score(row.get('ba'))}</td><td>{delta(row.get('delta'))}</td></tr>"
            )
        for subject, row in (
            ((selected.get("receipt") or {}).get("representation") or {})
            .get("subjects", {})
            .items()
        ):
            representation_rows.append(
                "<tr>"
                + "".join(
                    f"<td>{escape(str(v))}</td>"
                    for v in (
                        subject,
                        row.get("applied_adaptation"),
                        round(row["gate_metric_value"], 3),
                        row.get("fit_trials"),
                        row.get("unit"),
                        row.get("fallback_reason") or "",
                    )
                )
                + "</tr>"
            )
    panel = state.get("panel") or {}
    representation = ((selected or {}).get("receipt") or {}).get("representation") or {}
    gate_fraction = representation.get("gate_fraction")
    gate_note = (
        f"本次条件对齐触发 {representation['gate_passed_subject_count']}/{representation['gate_subject_count']} 位被试（{score(gate_fraction)}）。"
        if gate_fraction is not None
        else "本候选不使用条件门控。"
    )
    evaluation_mode = (
        "按被试分组交叉验证"
        if panel.get("evaluation_mode") == "group_cross_validation"
        else "指定训练与开发被试"
    )
    metric_note = ('训练、特征选择和内层参数选择仅使用每折训练组。当前协议的训练效用由 CSP-LDA、FBCSP、TS-LR 三个被试宏平均 BA 等权组成，缺少任一主模型则没有选择分数；FgMDM、逐频带 EA-FBCSP 和对数方差逻辑回归作为独立对照。CSP 明细保留为固定锚点。' if state["protocol"].get("assessment") else "保存协议的主指标为 CSP-LDA 的被试宏平均 BA，对数方差逻辑回归为次要对照。")
    comparison_metric = "三模型训练效用主指标" if modern else "CSP-LDA 主指标 BA"
    comparison_anchor = "CSP 锚点 BA" if modern else "对数方差 LR 次要 BA"
    subject_heading = "核心 CSP 锚点的开发被试明细" if modern else "暂选候选的 CSP-LDA 开发被试明细"
    multidimensional = ('<h2>多维评价与原生产物</h2>' + assessment_html if modern or assessment_html else
                       '<h2>评价覆盖</h2><p>该协议记录 CSP-LDA 主指标及次要对照；未执行六模型训练效用、独立信号质量或半合成重建评价。</p>')
    artifact_index = _link(state["id"], "files.json", "全部运行文件索引（包括中断残留；不表示全部可评分）")
    content = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>开发面板下的预处理搜索</title><style>
body{{font:16px/1.7 system-ui,sans-serif;color:#20343a;background:#f5f7f8;margin:0;padding:36px}}
main{{max-width:1100px;margin:auto;background:white;padding:36px;border-radius:16px}}h1{{font-size:28px}}h2{{font-size:20px;margin-top:32px}}
.muted{{color:#62757c}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{text-align:left;border-bottom:1px solid #e0e8e9;padding:12px 8px}}
details{{border-bottom:1px solid #e0e8e9;padding:12px 0}}summary{{cursor:pointer}}.scroll{{overflow:auto;max-height:520px}}a{{color:#127e79}}
</style><main><p class="muted">离线预处理搜索 · 开发评价</p><h1>在指定学习器和开发面板下选出的候选方案</h1>
<p>暂选：<strong>{escape(selected["title"] if selected else "未得到可评价候选")}</strong></p>
<p class="muted">{escape(reasons.get(state["stop_reason"], state["stop_reason"] or ""))} · 累计 {state["usage"]["elapsed_seconds"]:.1f} 秒 ·
候选 {state["usage"]["candidates"]}/{state["budget"]["max_candidates"]} · 提案 {state["usage"]["proposals"]}/{state["budget"]["max_proposals"]} · 阅读 {state["usage"]["evidence_reads"]}/{state["budget"]["max_evidence_reads"]}</p>
<p>本结果用于当前开发条件下的流程选择。开发集被反复查看，没有进行独立确认，也不证明神经信号质量。</p>
<h2>候选比较</h2><div class="scroll"><table><thead><tr><th>候选</th><th>状态</th><th>{comparison_metric}</th><th>{comparison_anchor}</th><th>CSP 相对参考差值</th><th>实际耗时</th><th>原因</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
{multidimensional}
{operator_usage_html}
<h2>逐轮决定</h2>{"".join(actions)}<h2>{subject_heading}</h2><div class="scroll"><table><tr><th>被试</th><th>CSP BA</th><th>CSP 相对参考</th></tr>{"".join(per_subject)}</table></div>
<h2>逐被试处理</h2><p>{gate_note} 条件指标为归一化协方差经 0.1 收缩后的特征值 Q90/Q10；阈值是预先声明的工程参数。</p><div class="scroll"><table><tr><th>被试</th><th>实际适配</th><th>条件指标</th><th>无标签拟合试次</th><th>单位</th><th>选择依据</th></tr>{"".join(representation_rows)}</table></div>
<h2>数据与评价协议</h2><p>{evaluation_mode}，共 {len(panel.get("folds", []))} 折。完整 trial 清单见 panel.json；每折训练与开发被试隔离。{metric_note}</p>
<p>适配仅使用当前被试的无标签整批信号。条件策略未触发空间对齐时，只统一尺度；不按个人评分标签选方案。适配后的维度为原通道坐标中的线性表示，单位无量纲，不能当作原电极电压解释。</p>
<p>只有完整覆盖同一开发清单的候选可被选择；分数精确相同时优先参考，再按算子数和候选编号决定。无效候选、执行故障和资源不足分别记录。</p>
<h2>可下载文件</h2><p>{artifact_index}</p>
</main></html>"""
    (root / "report.html").write_text(content, encoding="utf-8")
    files = []
    for p in sorted(root.rglob("*")):
        if (
            not p.is_file()
            or p.name
            in {"files.json", "search.json", "search.lock", "preprocessing.db"}
            or p.name.endswith((".tmp", "-wal", "-shm", ".lock"))
            or p.suffix == ".db"
            or any(part.startswith(".verify-") for part in p.relative_to(root).parts)
        ):
            continue
        if not p.resolve().is_relative_to(root):
            raise ValueError("report artifact escapes search root")
        name = p.relative_to(root).as_posix()
        files.append(
            {
                "name": name,
                "bytes": p.stat().st_size,
                "sha256": file_hash(p),
                "url": f"/api/searches/{quote(state['id'], safe='')}/artifacts/{quote(name, safe='/')}?download=true",
            }
        )
    write(root / "files.json", {"schema_version": "1", "files": files})
