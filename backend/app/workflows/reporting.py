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


def render_report(folder):
    data = report_data(folder.parent)
    # This small projection is the template input, not another process archive.
    write_readable(
        folder / "report.json", data.model_dump(mode="json")
    )
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
