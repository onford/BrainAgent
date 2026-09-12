"""Six fixed survey reports projected from validated records, without another LLM call."""

from collections import Counter, defaultdict
from pathlib import Path
from string import Template
from urllib.parse import urlsplit

from app.preprocessing.storage import file_hash
from .cognition_contracts import ResearchSources
from .contracts import SurveyOutput
from .reporting import (
    FIELD_LABELS,
    STATUS_LABELS,
    TARGET_LABELS,
    escape,
    rows,
    identifiers,
)
from .survey_contracts import DatasetVerification, LiteratureReview, LocalInspection

REPORTS = {
    "dataset-basic.html": "数据集基本信息",
    "data-information.html": "数据信息与三方核对",
    "statistics.html": "数据集统计信息",
    "literature-usage.html": "使用该数据集的文献与仓库",
    "literature-discussion.html": "讨论数据集本身的文献与仓库",
    "literature-preprocessing.html": "同类数据预处理的文献与仓库",
}
TEMPLATE = Path(__file__).parent / "templates/survey-report.html"
READING = {
    "abstract": "摘要",
    "partial_text": "部分正文",
    "full_text": "完整正文",
    "repository_docs": "仓库文档",
    "code": "代码",
}
STATISTICS = {
    "subjects": "被试数",
    "recordings": "可读取记录数",
    "trials": "目标任务 Trial 数",
    "duration_s": "已读取总时长（秒）",
    "unknown_recordings": "无法读取统计的记录数",
    "sessions": "显式 Session 数",
    "runs": "被试 × Run 记录数",
    "channels": "不同通道名称数",
    "channel_observations": "各记录通道数合计",
    "events": "全部事件数",
    "rest_segments": "静息段数",
    "files": "原始 EDF 数",
    "behavior_records": "行为记录数",
}


def report_format():
    return {
        "version": "2",
        "format": "HTML",
        "template_sha256": file_hash(TEMPLATE),
        "files": ["survey/reports/" + name for name in REPORTS],
    }


def table(headers, values):
    return (
        '<div class="table"><table><thead><tr>'
        + "".join(f"<th>{escape(h)}</th>" for h in headers)
        + "</tr></thead><tbody>"
        + rows(values)
        + "</tbody></table></div>"
    )


def listing(values):
    return "<ul>" + "".join(f"<li>{escape(v)}</li>" for v in values) + "</ul>"


def link(url, label):
    # External source text is untrusted, including its URL scheme.
    if urlsplit(url).scheme not in {"http", "https"}:
        return escape(label)
    return f'<a href="{escape(url)}" target="_blank" rel="noopener noreferrer">{escape(label)}</a>'


def evidence(findings, sources):
    result = []
    for f in findings:
        source = sources.get(f.source_id)
        origin = link(source.url, source.title) if source else escape(f.source_id)
        result.append(
            f'<article id="{escape(f.id)}"><strong>{escape(f.topic)}</strong>'
            f'<p>{escape(f.statement)}</p><p class="muted">结论编号：{escape(f.id)} · 来源：{origin}</p>'
            f"<details><summary>查看原文证据</summary><blockquote>{escape(f.quote)}</blockquote></details></article>"
        )
    return "".join(result) or '<p class="muted">未取得可引用的结论。</p>'


def basic(survey, verification, sources):
    labels = {
        "name": "名称",
        "version": "版本",
        "doi": "DOI",
        "publisher": "发布方",
        "published": "发布日期",
        "license": "许可",
    }
    body = "<h2>经资料核对的基本信息</h2>" + table(
        ["字段", "内容", "证据编号"],
        [
            (labels[m.field], m.value or "未知", ", ".join(m.finding_ids) or "未取得")
            for m in verification.metadata
        ],
    )
    body += "<h2>本轮用途与选择范围</h2>" + table(
        ["项目", "内容"],
        [
            ("最终用途", "模型训练"),
            ("任务配置", survey.profile.task),
            ("本地目录", survey.source_root),
            (
                "扫描发现的被试 / EDF 记录",
                f"{survey.available_subjects} / {survey.available_recordings}",
            ),
            ("选择被试", identifiers(survey.selected_subjects)),
            (
                "本地全部 Run",
                ", ".join(map(str, sorted({r.run for r in survey.records}))),
            ),
            ("统计范围", survey.scope),
            ("资料核对日期", survey.profile.profile_reviewed),
        ],
    )
    body += (
        "<h2>来源与未确认信息</h2><p>数据集入口："
        + link(survey.profile.source_url, survey.profile.source_url)
        + "</p>"
    )
    body += listing(survey.profile.unknown_fields)
    ids = {i for m in verification.metadata for i in m.finding_ids}
    return (
        body
        + "<h2>基本信息的依据</h2>"
        + evidence([f for f in verification.facts if f.id in ids], sources)
    )


def information(local, verification, sources):
    from .local_contracts import LocalObservation
    from .local_reporting import observation_html

    structured = isinstance(local, LocalObservation)
    facts = {f.id: f for f in local.facts}

    def local_values(ids, field):
        if structured:
            from .local_reporting import comparison_value

            return comparison_value(local, field)
        grouped = defaultdict(list)
        for identity in ids:
            fact = facts.get(identity)
            if fact:
                value = fact.value
                grouped[value].append(fact.scope)
        return (
            "\n\n".join(
                f"{', '.join(scopes)}：{value}" for value, scopes in grouped.items()
            )
            or "未取得"
        )

    def statement(value):
        return (
            value.statement + " [" + ", ".join(value.finding_ids) + "]"
            if value.statement
            else "未说明 / 未取得"
        )

    body = observation_html(local) if structured else ""
    body += f'<h2>外部资料核对</h2><p>{escape(verification.summary)}</p><p class="muted">本地观测范围：{escape(local.scope_text if structured else local.scope)}</p>'
    body += "<h2>本地文件 / 官网与仓库 / 官方论文</h2>" + table(
        ["项目", "本地实际观测", "官网 / 官方仓库", "官方论文", "核对结果", "结论"],
        [
            (
                FIELD_LABELS[r.field],
                local_values(r.local_fact_ids, r.field),
                statement(r.official_sources),
                statement(r.official_paper),
                STATUS_LABELS[r.status],
                r.conclusion,
            )
            for r in verification.comparisons
        ],
    )
    body += (
        "<h2>官方论文的身份与适用范围</h2><p>"
        + escape(verification.official_publication.explanation)
        + "</p>"
    )
    body += "<h2>冲突与待补信息</h2>" + listing(
        verification.conflicts + verification.gaps
    )
    if not structured:
        body += (
            "<details><summary>本地观测明细与定位</summary>"
            + table(
                ["编号", "项目", "范围", "观测", "定位"],
                [
                    (f.id, FIELD_LABELS[f.field], f.scope, f.value, f.locator)
                    for f in local.facts
                ],
            )
            + "</details>"
        )
    return (
        body + "<h2>外部资料的结论与原文</h2>" + evidence(verification.facts, sources)
    )


def statistics(survey, local):
    readable = [r for r in survey.records if r.status == "readable"]
    body = f"<p>{escape(survey.scope)}</p><p>目录扫描发现 {survey.available_subjects} 个被试、{survey.available_recordings} 个 EDF 记录；以下信号与事件统计仅覆盖本轮选择并成功读取的文件。</p>"
    body += "<h2>总体规模</h2>" + table(
        ["指标", "值"],
        [
            (STATISTICS[k], v if v is not None else "未知 / 未取得")
            for k, v in survey.statistics.model_dump().items()
        ],
    )
    by_subject = defaultdict(list)
    for r in readable:
        by_subject[r.subject].append(r)
    body += "<h2>按被试统计</h2>" + table(
        ["被试", "选择记录数", "可读取记录数", "时长（秒）", "全部事件", "目标 Trial"],
        [
            (
                s,
                sum(r.subject == s for r in survey.records),
                len(by_subject[s]),
                round(sum(r.duration_s for r in by_subject[s]), 4),
                sum(sum(r.event_counts.values()) for r in by_subject[s]),
                sum(r.task_trials for r in by_subject[s]),
            )
            for s in survey.selected_subjects
        ],
    )
    events = Counter()
    for r in readable:
        events.update(r.event_counts)
    body += (
        '<h2>事件分布</h2><p class="muted">标记含义采用当前适配器的任务配置，其跨来源核对结果见数据信息报告；Trial 数不等于预处理后保留数。</p>'
        + table(
            ["原始标记", "配置含义", "数量"],
            [
                (k, survey.profile.trigger_map.get(k, "未知"), v)
                for k, v in sorted(events.items())
            ],
        )
    )
    body += "<h2>采样率分布</h2>" + table(
        ["采样率（Hz）", "记录数"], sorted(Counter(r.sfreq for r in readable).items())
    )
    body += "<h2>逐记录统计</h2>" + table(
        [
            "记录",
            "被试",
            "Run",
            "采样率（Hz）",
            "样点数",
            "通道数",
            "时长（秒）",
            "目标 Trial",
        ],
        [
            (
                r.id,
                r.subject,
                r.run,
                r.sfreq,
                r.samples,
                len(survey.channel_sets[r.channel_set]),
                round(r.duration_s, 4),
                r.task_trials,
            )
            for r in readable
        ],
    )
    body += (
        "<details><summary>通道集合</summary>"
        + table(
            ["集合", "通道数", "顺序"],
            [(k, len(v), ", ".join(v)) for k, v in survey.channel_sets.items()],
        )
        + "</details>"
    )
    from .local_contracts import LocalObservation

    if isinstance(local, LocalObservation):
        body += "<h2>已记录的数组检查</h2>" + table(
            ["记录", "通道 × 样点", "解码类型", "解码单位", "非有限值数量"],
            [
                (
                    key,
                    f"{r.decoded_signal.shape[0]} × {r.decoded_signal.shape[1]}",
                    r.decoded_signal.dtype,
                    r.decoded_signal.unit,
                    r.decoded_signal.nonfinite_count,
                )
                for key, r in local.recordings.items()
                if r.decoded_signal
            ],
        )
    else:
        body += "<h2>已记录的数组检查</h2>" + table(
            ["记录范围", "检查结果"],
            [(f.scope, f.value) for f in local.facts if f.field == "signal_arrays"],
        )
    body += "<h2>无法读取的记录与检查事项</h2>" + table(
        ["记录", "原因"],
        [(r.id, r.reason) for r in survey.records if r.status == "excluded"],
    )
    body += table(
        ["对象", "检查", "状态", "处理", "观测依据"],
        [
            (c.object_key, c.check_category, c.status, c.action, c.observed_evidence)
            for c in survey.checks
        ],
    )
    return (
        body
        + '<p class="muted">年龄、性别等人口统计，以及频谱、信噪比等尚未测量的指标不作推算。</p>'
    )


def literature(review, targets, grades=None):
    sources = {s.id: s for s in review.sources}
    entries = [e for e in review.entries if e.target in targets]
    coverage = [c for c in review.coverage if c.target in targets]
    grade_rows = {r['entry_id']: r for r in (grades or {}).get('rows', [])}
    body = "<h2>用途与调研覆盖</h2>" + table(
        ["用途", "资料类型", "下游章节", "状态", "纳入记录", "检索编号", "说明"],
        [
            (
                TARGET_LABELS[c.target],
                "论文" if c.medium == "paper" else "仓库",
                ", ".join(c.destinations),
                STATUS_LABELS[c.status],
                ", ".join(c.included_entry_ids) or "无",
                ", ".join(map(str, c.search_observation_ids)) or "无",
                c.explanation,
            )
            for c in coverage
        ],
    )
    body += '<p class="muted">覆盖表示已有纳入条目，不表示调研充分。同一来源可针对不同用途分别筛选；暂缓与排除条目不作为后续操作的已采纳依据。</p>'
    body += (
        "<details><summary>筛选标准</summary>" + listing(review.criteria) + "</details>"
    )
    for status in ("included", "deferred", "excluded"):
        selected = [e for e in entries if e.decision == status]
        body += f"<h2>{STATUS_LABELS[status]}（{len(selected)} 条）</h2>"
        for e in selected:
            source = sources[e.source_id]
            q = e.quality
            body += f'<section><h3>{link(source.url, source.title)}</h3><p class="muted">{escape(e.id)} · {escape(TARGET_LABELS[e.target])} · {"论文" if e.medium == "paper" else "仓库"} · 阅读范围：{READING[e.reading_scope]}</p><p>{escape(e.reason)}</p>'
            body += table(
                ["期刊 / 会议", "被引次数", "Star 数", "指标检索编号"],
                [
                    (
                        q.venue or "未知",
                        q.citations if q.citations is not None else "未知",
                        q.stars if q.stars is not None else "未知",
                        ", ".join(map(str, q.observation_ids)) or "未取得",
                    )
                ],
            )
            body += evidence(e.findings, sources)
            if e.id in grade_rows:
                grade = grade_rows[e.id]
                label = {'abstract_only': '仅摘要', 'located_source_text': '已定位来源正文',
                         'source_text_without_located_findings': '取得文本但无定位论据'}[grade['access_grade']]
                body += '<p class="muted">证据访问：' + label + '。参数语义、流程执行及独立复现须查看对应方法的后续证据；引用量与星数不提升证据等级。</p>'
            if e.exclusions:
                body += (
                    '<h3>资料报告的排除事项</h3><p class="muted">需在数据接入阶段核对，不自动剔除本地对象。</p>'
                    + listing(e.exclusions)
                )
            body += (
                "<p>"
                + " · ".join(
                    link(u, f"关联资料 {i + 1}") for i, u in enumerate(e.related_urls)
                )
                + "</p></section>"
            )
    body += "<h2>本用途待补内容</h2>" + listing(
        [
            f"{TARGET_LABELS[c.target]} / {c.medium}：{c.explanation}"
            for c in coverage
            if c.status == "gap"
        ]
    )
    return (
        body
        + "<details><summary>文献调研总体缺口（跨用途）</summary>"
        + listing(review.gaps)
        + "</details>"
    )


def render_survey_reports(folder, value=None):
    folder = Path(folder)

    def load(name, model):
        if name == "local-inspection.json":
            from .local_contracts import read_local

            return read_local(folder / name)
        return model.model_validate_json((folder / name).read_text(encoding="utf-8"))

    survey = (
        SurveyOutput.model_validate(value)
        if value is not None
        else load("survey.json", SurveyOutput)
    )
    local = load("local-inspection.json", LocalInspection)
    verification = load("verification.json", DatasetVerification)
    review = load("literature.json", LiteratureReview)
    grades = None
    if (folder / 'evidence-grades.json').exists():
        from .research_audit_contracts import EvidenceGrades
        from app.preprocessing.storage import digest
        grades = load('evidence-grades.json', EvidenceGrades).model_dump(mode='json')
        if grades['review_sha256'] != digest(review.model_dump(mode='json')):
            raise ValueError('evidence grade snapshot differs from the literature review')
    sources = {d.id: d for d in load("sources.json", ResearchSources).documents}
    bodies = [
        basic(survey, verification, sources),
        information(local, verification, sources),
        statistics(survey, local),
        literature(review, {"usage_analysis", "usage_algorithm"}, grades),
        literature(review, {"dataset_discussion"}, grades),
        literature(review, {"preprocessing_methods"}, grades),
    ]
    template = Template(TEMPLATE.read_text(encoding="utf-8"))
    navigation = " ".join(
        f'<a href="{name}?download=false">{title}</a>'
        for name, title in REPORTS.items()
    )
    output = folder / "reports"
    output.mkdir(exist_ok=True)
    for (name, title), body in zip(REPORTS.items(), bodies, strict=True):
        record_links = " · ".join(
            f'<a href="../{name}?download=true">{name}</a>'
            for name in (
                "survey.json",
                "verification.json",
                "local-inspection.json",
                "literature.json",
                "sources.json",
                *[name for name in ('evidence-grades.json', 'dataset_verification-progress.json', 'literature_review-progress.json') if (folder / name).exists()],
            )
        )
        text = template.substitute(
            title=title,
            subtitle=escape(survey.profile.name),
            navigation=navigation,
            body=body + "<h2>结构化原始记录</h2><p>" + record_links + "</p>",
        )
        temporary = output / ("." + name + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(output / name)
    return ["survey/reports/" + name for name in REPORTS]


if __name__ == "__main__":
    import argparse

    from .records import check_format

    parser = argparse.ArgumentParser(description="从已有调研记录生成六份 HTML 报告")
    parser.add_argument("survey_folder", type=Path)
    args = parser.parse_args()
    check_format(args.survey_folder.parent)
    for report in render_survey_reports(args.survey_folder):
        print(report)
