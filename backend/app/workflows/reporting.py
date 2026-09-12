"""Render the report solely from validated process data and an HTML template."""

import html
from pathlib import Path
from string import Template

from .records import report_data, write_readable


def escape(value):
    return html.escape(str(value), quote=True)


def evaluation_summary(selection):
    if selection is None:
        return "未取得开发评价回执"
    from app.search.catalog import selection_score

    receipt = selection.selected_receipt
    if selection_score(receipt) != selection.score:
        raise ValueError("报告分数与选中评价回执不同")
    assessment = receipt.get("assessment")
    if not assessment:
        if selection.evaluation_protocol.get("assessment"):
            raise ValueError("报告缺少冻结协议要求的 assessment")
        return f"CSP/LDA 开发被试平均平衡准确率：{selection.score:.4f}；该面板参与候选选择，无独立确认。"
    utility = assessment["utility"]
    scores = utility["learner_scores"]
    anchor = assessment["core_csp_macro_ba"]
    if assessment["schema_version"] == "assessment-v2":
        seed = utility["seed_summary"]
        coverage = utility["learner_coverage"]["eegnet"]
        description = (
            f"EEGNet 三种子训练效用 selection_score：{selection.score:.4f}；"
            "分别计算种子 17、42、2026 的开发被试平均平衡准确率，再对三个种子等权平均。"
            "不是平均概率的集成分数；任一种子缺失都不产生选择分数。"
            f"种子 BA 标准差={seed['seed_sd']:.4f}，范围 [{seed['minimum_ba']:.4f}, {seed['maximum_ba']:.4f}]。"
            "被试指标按三个种子平均，试次分母保留 N，完整预测证据为 3×N 行。"
            f"开发覆盖：{coverage['subjects_available']}/{coverage['subjects_expected']} 被试、"
            f"{coverage['trials_available']}/{coverage['eligible_trials_expected']} eligible trial。"
        )
        csp = scores["csp_lda"]
        description += f"CSP/LDA 基准={csp:.4f}，不参与选择分数。" if csp is not None else "CSP/LDA 基准未取得，不参与选择分数。"
    else:
        coverage = utility["learner_coverage"]["csp_lda"]
        description = (
            f"历史三模型训练效用 selection_score：{selection.score:.4f}；"
            f"CSP/LDA={scores['csp_lda']:.4f}、FBCSP={scores['fbcsp']:.4f}、TS/LR={scores['ts_lr']:.4f}。"
            "按历史冻结协议，先计算各模型的开发被试平均平衡准确率，再对三个模型等权平均。"
            f"每模型开发分母：{coverage['subjects_available']}/{coverage['subjects_expected']} 被试、"
            f"{coverage['trials_available']}/{coverage['eligible_trials_expected']} eligible trial。"
        )
    return (
        description
        + (f"核心 CSP 锚点 macro_ba={anchor:.4f}。" if anchor is not None else "核心 CSP 锚点未取得。")
        + f"质量状态：{assessment['quality']['status']}；重建状态：{assessment['reconstruction']['status']}；二者不加入选择总分。"
        + f"搜索 {selection.search_id}；该面板参与候选选择，无独立确认。"
    )


def identifiers(values):
    values = list(values)
    return ", ".join(values[:8]) + (
        f" …（共 {len(values)} 项；完整名单见记录明细）" if len(values) > 8 else ""
    )


def rows(values):
    return "".join(
        "<tr>" + "".join(f"<td>{escape(v)}</td>" for v in row) + "</tr>"
        for row in values
    )


TARGET_LABELS = {
    "usage_analysis": "使用数据集的分析",
    "usage_algorithm": "使用数据集的算法",
    "dataset_discussion": "讨论数据集本身",
    "preprocessing_methods": "同类数据的预处理",
}
FIELD_LABELS = dict(
    zip(
        (
            "directory_structure",
            "file_format",
            "file_header",
            "signal_arrays",
            "channels",
            "sampling_rate",
            "events",
            "task_runs",
            "subjects",
            "recording_duration",
            "acquisition",
            "license",
            "dataset_version",
        ),
        (
            "目录结构",
            "文件格式",
            "文件头",
            "实际数组",
            "通道",
            "采样率",
            "事件",
            "任务与 Run",
            "被试",
            "记录时长",
            "采集设置",
            "许可",
            "版本",
        ),
    )
)
STATUS_LABELS = {
    "consistent": "一致",
    "partial": "部分一致",
    "conflict": "不一致",
    "not_stated": "未说明",
    "unverifiable": "无法核查",
    "not_applicable": "不适用",
    "covered": "已覆盖",
    "gap": "缺口",
    "included": "纳入",
    "excluded": "排除",
    "deferred": "待补充",
}


def local_comparison(data, row):
    from .local_contracts import LocalObservation
    from .local_reporting import comparison_value

    if isinstance(data.local_inspection, LocalObservation):
        return comparison_value(data.local_inspection, row.field)
    grouped = {}
    for fact in data.local_inspection.facts:
        if fact.id in row.local_fact_ids:
            value = (
                fact.value[:180] + "…（详见本地观测记录）"
                if len(fact.value) > 180
                else fact.value
            )
            grouped.setdefault(value, []).append(fact.scope)
    return (
        "; ".join(f"{', '.join(scopes)}: {value}" for value, scopes in grouped.items())
        or "未从本地取得"
    )


def literature_rows(review):
    if review is None:
        return ""
    sources = {s.id: s for s in review.sources}
    result = []
    for entry in review.entries:
        source = sources[entry.source_id]
        links = f"<a href='{escape(source.url)}'>{escape(source.title)}</a>"
        links += "".join(
            f"<br><a href='{escape(url)}'>关联资料 {i + 1}</a>"
            for i, url in enumerate(entry.related_urls)
            if url != source.url
        )
        q = entry.quality
        quality = (
            "; ".join(
                f"{name}: {value}"
                for name, value in (
                    ("期刊", q.venue),
                    ("被引", q.citations),
                    ("星标", q.stars),
                )
                if value is not None
            )
            or "未取得指标"
        )
        result.append(
            "<tr><td>"
            + escape(TARGET_LABELS[entry.target] + " · " + entry.medium)
            + "</td><td>"
            + links
            + "</td>"
            + "".join(
                f"<td>{escape(v)}</td>"
                for v in (
                    STATUS_LABELS[entry.decision],
                    entry.reading_scope,
                    entry.reason,
                    quality,
                )
            )
            + "</tr>"
        )
    return "".join(result)


def render_report(folder):
    from .collection_contracts import CATEGORY_LABELS

    data = report_data(folder.parent)
    observed_rates = (
        sorted(
            {f.value for f in data.local_inspection.facts if f.field == "sampling_rate"}
        )
        if data.local_inspection
        else []
    )
    titles = {
        "subjects": "被试数",
        "recordings": "记录数",
        "trials": "任务 Trial 数",
        "duration_s": "已读取时长（秒）",
        "unknown_recordings": "无法读取统计的记录数",
        "sessions": "显式 Session 数",
        "runs": "被试 × Run 记录数",
        "channels": "不同通道名称数",
        "channel_observations": "各记录通道数合计",
        "events": "全部事件数",
        "rest_segments": "静息段数",
        "files": "对应的原始 EDF 数",
        "behavior_records": "行为记录数",
    }
    operations = {
        "filter": "频率滤波",
        "reference": "重参考",
        "epoch": "事件分段",
        "resample": "重采样",
    }
    recipe = []
    for i, step in enumerate(data.method.recipe):
        p = step.params
        if step.op == "filter":
            description = f"低频界 {p['l_freq']} / 高频界 {p['h_freq']} Hz；method={p.get('method', 'fir')}"
            description += f"；phase={p.get('phase', '未记录')}"
        elif step.op == "reference":
            description = f"参考通道：{p.get('ref_channels')}"
        elif step.op == "epoch":
            description = f"任务开始后 {p['tmin']:g}–{p['tmax']:g} 秒；保留左右手标签"
        elif step.op == "resample":
            description = f"统一至 {p['sfreq']:g} Hz；具体实现及事件映射见执行计划与逐记录输出"
        else:
            description = "; ".join(f"{k}={v}" for k, v in p.items())
        recipe.append([i + 1, operations.get(step.op, step.op), description])
    method_reasoning = (
        "实际处理顺序："
        + " → ".join(row[1] for row in recipe)
        + "。参数见上表；候选按冻结开发评价选择，未进行独立确认。"
    )
    selection = data.selection
    if selection and selection.literature_participation:
        method_reasoning += " " + selection.literature_participation["statement"]
    representation = selection.representation if selection else None
    if representation:
        method_reasoning += (
            " 数值预处理后应用选中策略的被试适配；变换与拟合范围见评价回执。"
        )
    unit = representation.get("unit", "V") if representation else "V"
    if data.narrative:
        # Free model prose must not override the executed step order. The raw
        # interpretation remains available in narrative.json and decisions.json.
        data.narrative.method_reasoning = method_reasoning
    write_readable(folder / "report.json", data.model_dump(mode="json"))
    template = Template(
        (Path(__file__).parent / "templates/report.html").read_text(encoding="utf-8")
    )
    document = template.substitute(
        intake_policy=escape(
            data.intake.policy if data.intake else "此历史运行未记录完整接入检查"
        ),
        standardization=escape(
            (
                data.standardization.supported_scope
                + "；"
                + data.standardization.validation
                + "。完整官方 BIDS validator 未运行。"
            )
            if data.standardization
            else "此历史运行未记录标准化验证范围"
        ),
        intake_rows=rows(
            [
                [
                    label,
                    sum(
                        c.check_category == category and c.status == "一致"
                        for c in data.intake.checks
                    ),
                    sum(
                        c.check_category == category and c.status == "不一致"
                        for c in data.intake.checks
                    ),
                    sum(
                        c.check_category == category
                        and c.status not in {"一致", "不一致"}
                        for c in data.intake.checks
                    ),
                ]
                for category, label in CATEGORY_LABELS.items()
            ]
            if data.intake
            else []
        ),
        exclusion_claim_rows=rows(
            [
                [
                    c.entry_id,
                    ", ".join(c.reported_ids) or "未明确",
                    ", ".join(c.local_objects)
                    or {
                        "outside_selection": "不在本轮范围",
                        "unresolved": "尚不能定位",
                    }.get(c.match_status, ""),
                    c.action,
                    c.reason,
                ]
                for c in data.literature_exclusions.records
            ]
            if data.literature_exclusions
            else []
        ),
        verification_rows=rows(
            [
                [
                    FIELD_LABELS[r.field],
                    local_comparison(data, r),
                    r.official_sources.statement or "未说明/未取得",
                    r.official_paper.statement or "未说明/未取得",
                    STATUS_LABELS[r.status],
                    r.conclusion,
                ]
                for r in data.verification.comparisons
            ]
            if data.verification and data.local_inspection
            else []
        ),
        official_publication=escape(
            data.verification.official_publication.explanation
            if data.verification
            else "此历史运行未记录三方核对"
        ),
        literature_rows=literature_rows(data.literature),
        literature_coverage_rows=rows(
            [
                [
                    TARGET_LABELS[c.target],
                    c.medium,
                    ", ".join(c.destinations),
                    STATUS_LABELS[c.status],
                    c.explanation,
                ]
                for c in data.literature.coverage
            ]
            if data.literature
            else []
        ),
        literature_criteria="".join(
            f"<li>{escape(c)}</li>" for c in data.literature.criteria
        )
        if data.literature
        else "",
        research_overview=escape(
            data.narrative.overview
            if data.narrative
            else "此历史运行未记录模型调研分析。"
        ),
        data_interpretation=escape(
            data.narrative.data_interpretation if data.narrative else ""
        ),
        method_reasoning=escape(method_reasoning),
        finding_rows=rows(
            [[f.topic, f.statement, f.source_id] for f in data.research.facts]
            if data.research
            else []
        ),
        dataset_name=escape(data.dataset_name),
        dataset_version=escape(data.dataset_version),
        subjects=data.after.subjects,
        recordings=data.after.recordings,
        evaluated_recordings=len(selection.panel.get("records", {})) if selection else "未评价",
        trials=data.after.trials,
        source_rows=rows(
            [
                ["用途", "模型训练"],
                ["任务", "左手 / 右手运动想象"],
                [
                    "采集",
                    f"{data.channel_count} EEG 通道；原始采样率："
                    + (
                        " / ".join(observed_rates)
                        if observed_rates
                        else f"适配器预期 {data.sfreq:g} Hz，未取得逐记录观测"
                    ),
                ],
                [
                    "范围",
                    identifiers(data.subjects)
                    + "；Run "
                    + ", ".join(map(str, data.runs)),
                ],
                ["许可", data.license],
            ]
        ),
        statistics_rows=rows(
            [
                [
                    titles[k],
                    value if value is not None else "未取得",
                    data.after.model_dump()[k]
                    if data.after.model_dump()[k] is not None
                    else "未取得",
                ]
                for k, value in data.before.model_dump().items()
            ]
        ),
        method_title=escape(data.method.title),
        recipe_rows=rows(recipe),
        record_rows=rows(
            [
                [r.record_id, r.events_before, r.events_retained, r.shape]
                for r in sorted(data.records, key=lambda r: r.record_id)
            ]
        ),
        selection_reason=escape(data.selection_reason),
        evaluation_summary=escape(evaluation_summary(selection)),
        candidate_rows=rows(
            [
                [
                    c["candidate_id"],
                    c["status"],
                    f"{c['score']:.4f}" if c.get("score") is not None else "未取得",
                ]
                for c in selection.candidate_summary
            ]
            if selection
            else []
        ),
        representation_summary=escape(
            f"X 按 Epoch × 空间坐标 × 时间点组织，单位：{unit}。"
            + "空间轴为预处理后的 EEG 通道。"
            + "y 为从 0 开始的类别编号。分组 CV 导出时全部被试标为 train，折成员另存；"
            "显式训练/开发划分映射为 train/validation。test 为空，不生成独立测试集。"
        ),
        seed=data.seed,
        references="".join(
            f"<li><a href='{escape(r.url)}'>{escape(r.title)}</a></li>"
            for r in data.references
        ),
        limitations="".join(
            f"<li>{escape(v)}</li>"
            for v in dict.fromkeys(
                data.limitations
                + (data.narrative.limitations if data.narrative else [])
                + (
                    data.research.gaps + data.research.conflicts
                    if data.research
                    else []
                )
            )
        ),
    )
    (folder / "report.html").write_text(document, encoding="utf-8")
    return {
        "report_path": "report/report.html",
        "format": "HTML",
        "quality_evaluated": True,
        "evaluation_scope": "development",
        "independent_confirmation": False,
    }
