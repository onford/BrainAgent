"""Render the report solely from validated process data and an HTML template."""

import html
from pathlib import Path
from string import Template

from .records import report_data, write_readable


def escape(value):
    return html.escape(str(value), quote=True)


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
    data = report_data(folder.parent)
    # This small projection is the template input, not another process archive.
    write_readable(folder / "report.json", data.model_dump(mode="json"))
    titles = {
        "subjects": "被试数",
        "recordings": "记录数",
        "trials": "任务 Trial 数",
        "duration_s": "已读取时长（秒）",
        "unknown_recordings": "无法读取统计的记录数",
    }
    operations = {"filter": "带通滤波", "reference": "平均参考", "epoch": "事件分段"}
    recipe = []
    for i, step in enumerate(data.method.recipe):
        p = step.params
        if step.op == "filter":
            description = f"低频界 {p['l_freq']} / 高频界 {p['h_freq']} Hz；method={p.get('method', 'fir')}"
            if p.get("method") == "iir":
                description += "；四阶 Butterworth 零相位"
        elif step.op == "reference":
            description = f"参考通道：{p.get('ref_channels')}"
        elif step.op == "epoch":
            description = f"任务开始后 {p['tmin']:g}–{p['tmax']:g} 秒；保留左右手标签"
        else:
            description = "; ".join(f"{k}={v}" for k, v in p.items())
        recipe.append([i + 1, operations.get(step.op, step.op), description])
    template = Template(
        (Path(__file__).parent / "templates/report.html").read_text(encoding="utf-8")
    )
    document = template.substitute(
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
        method_reasoning=escape(
            data.narrative.method_reasoning
            if data.narrative
            else "参数依据见方法记录。"
        ),
        finding_rows=rows(
            [[f.topic, f.statement, f.source_id] for f in data.research.facts]
            if data.research
            else []
        ),
        dataset_name=escape(data.dataset_name),
        dataset_version=escape(data.dataset_version),
        subjects=data.after.subjects,
        recordings=data.after.recordings,
        trials=data.after.trials,
        source_rows=rows(
            [
                ["用途", "模型训练"],
                ["任务", "左手 / 右手运动想象"],
                ["采集", f"{data.channel_count} EEG 通道，{data.sfreq:g} Hz"],
                [
                    "范围",
                    ", ".join(data.subjects)
                    + "；Run "
                    + ", ".join(map(str, data.runs)),
                ],
                ["许可", data.license],
            ]
        ),
        statistics_rows=rows(
            [
                [titles[k], value, data.after.model_dump()[k]]
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
        "quality_evaluated": False,
    }
