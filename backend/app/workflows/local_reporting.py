"""Readable projections of object-based local observations."""

from .reporting import escape, identifiers

GROUPS = {
    "scope": "范围与覆盖",
    "organization": "文件与记录组织",
    "signal": "信号与采集",
    "events": "事件与实验流程",
    "metadata": "被试与实验元数据",
    "statistics": "统计、差异与待办",
}
STATUS = {
    "observed": "已检查",
    "partial": "部分检查",
    "not_checked": "未检查",
    "not_found": "检查后未发现",
    "read_error": "读取失败",
    "not_applicable": "不适用",
}


def comparison_value(local, field):
    """Concise measured values, grouped by equality, for all report projections."""
    if field == "directory_structure":
        return local.scope_text
    if field == "subjects":
        return identifiers(local.scope.selected_subjects) + "（目录 / 文件名编号）"
    grouped = {}
    for key, r in local.recordings.items():
        if r.read_status != "readable":
            continue
        value = None
        if field == "file_format" and r.storage:
            value = r.storage.format
        elif field == "file_header" and r.storage:
            value = f"{r.storage.header_bytes} 字节；{len(r.storage.signals)} 路存储信号（包括注释）；完整字段见详情"
        elif field == "signal_arrays":
            v = r.decoded_signal
            value = f"{v.shape[0]} × {v.shape[1]}；{v.dtype} / {v.unit}；非有限值 {v.nonfinite_count}"
        elif field == "channels":
            names = local.channel_sets[r.channel_set_ref]
            value = (
                f"{len(names)} 通道："
                + ", ".join(names[:6])
                + (" …（完整顺序见共享配置）" if len(names) > 6 else "")
            )
        elif field == "sampling_rate":
            value = f"{r.sampling_rate_hz:g} Hz"
        elif field == "recording_duration":
            value = f"{r.duration_s:g} 秒"
        elif field == "events":
            value = "; ".join(f"{k}: {v}" for k, v in r.events.counts.items())
        elif field == "task_runs":
            value = f"Run {r.run_id}（文件名；任务语义未在本地确认）"
        elif field == "acquisition":
            c = local.acquisition_sets[r.acquisition_set_ref]
            value = (
                "传感器："
                + (", ".join(c.transducers) or "未填写")
                + "；预滤波："
                + (", ".join(c.prefilters) or "未填写")
                + "；设备、参考等尚未解析确认"
            )
        if value is not None:
            grouped.setdefault(value, []).append(key)
    return (
        "\n\n".join(
            (
                f"全部 {len(keys)} 条已读取记录"
                if len(keys) == local.statistics.readable_records
                else identifiers(keys)
            )
            + "："
            + value
            for value, keys in grouped.items()
        )
        or "尚未从本地确认，见检查覆盖"
    )


def observation_html(local):
    from .survey_reporting import table

    s = local.statistics
    body = "<p>" + escape(local.scope_text) + "</p>"
    body += (
        '<p class="muted">本地检查时间：'
        + escape(local.provenance.inspected_at)
        + "。下面只展示实际观测；任务含义与外部来源的核对另列。</p>"
    )
    body += table(
        [
            "成功读取",
            "读取失败",
            "信号时长（秒）",
            "原始事件数",
            "采样率分布（Hz → 记录数）",
            "通道数分布",
        ],
        [
            [
                s.readable_records,
                s.failed_records,
                round(s.duration_s, 4),
                s.events,
                "; ".join(f"{k} → {v}" for k, v in s.sampling_rates.items()),
                "; ".join(f"{k} → {v}" for k, v in s.channel_counts.items()),
            ]
        ],
    )
    sections = {"scope": body}
    coverage = {}
    for group, label in GROUPS.items():
        coverage[group] = table(
            ["检查项", "状态", "完成范围", "说明"],
            [
                [c.label, STATUS[c.status], f"{c.checked}/{c.total}", c.reason]
                for c in local.coverage.values()
                if c.group == group
            ],
        )
    body = "<h3>记录总表</h3>" + table(
        [
            "记录",
            "被试",
            "Run",
            "采样率 Hz",
            "通道",
            "样点",
            "时长 s",
            "事件数",
            "读取状态",
        ],
        [
            [
                key,
                r.subject_id,
                r.run_id,
                r.sampling_rate_hz,
                len(local.channel_sets[r.channel_set_ref])
                if r.channel_set_ref
                else "未知",
                r.decoded_signal.shape[1] if r.decoded_signal else "未知",
                r.duration_s,
                sum(r.events.counts.values()) if r.events else "未知",
                "已读取" if r.read_status == "readable" else "读取失败",
            ]
            for key, r in local.recordings.items()
        ],
    )
    body += '<h3>记录详情</h3><p class="muted">按被试展开记录，再选择记录查看信号、事件和原始头。</p><div class="subject-list">'
    active_subject = None
    for key, r in sorted(
        local.recordings.items(), key=lambda item: (item[1].subject_id, item[1].run_id)
    ):
        if active_subject != r.subject_id:
            if active_subject is not None:
                body += "</div></details>"
            active_subject = r.subject_id
            records = [
                k
                for k, item in local.recordings.items()
                if item.subject_id == active_subject
            ]
            body += (
                '<details class="subject-group" data-search="'
                + escape(" ".join(records))
                + '"><summary>'
                + escape(active_subject)
                + " · "
                + str(len(records))
                + ' 条记录</summary><div class="observation-grid">'
            )
        body += (
            '<details class="observation-record" name="observation-record"><summary><strong>'
            + escape(key)
            + "</strong> · 被试 "
            + escape(r.subject_id)
            + " · Run "
            + str(r.run_id)
            + '<span class="detail-open">查看详情</span><span class="detail-close">关闭详情 ×</span></summary><div class="observation-content">'
        )
        body += "<p>" + escape(r.source_file) + "</p>"
        if r.read_status == "read_error":
            body += "<p>读取失败：" + escape(r.error) + "</p></div></details>"
            continue
        body += table(
            ["项目", "观测"],
            [
                [
                    "记录形态",
                    {"continuous": "连续记录", "discontinuous": "非连续记录"}.get(
                        r.form, "未从原始头确认"
                    ),
                ],
                [
                    "解码数组",
                    f"{r.decoded_signal.shape[0]} 通道 × {r.decoded_signal.shape[1]} 样点",
                ],
                [
                    "解码类型 / 单位",
                    f"{r.decoded_signal.dtype} / {r.decoded_signal.unit}（MNE 输出）",
                ],
                ["非有限数值数量", r.decoded_signal.nonfinite_count],
                [
                    "通道集合",
                    f"{len(local.channel_sets[r.channel_set_ref])} 个通道；完整名称和顺序见共享配置",
                ],
                [
                    "事件分布",
                    "; ".join(f"{k}: {v}" for k, v in r.events.counts.items()),
                ],
                [
                    "标识依据",
                    "目录 / 文件命名约定；任务、Session、Condition 未独立确认",
                ],
            ],
        )
        if r.storage:
            h = r.storage
            body += (
                "<details><summary>原始 EDF 文件头（与解码数组分开）</summary>"
                + table(
                    ["字段", "原始值"],
                    [
                        ["格式", h.format],
                        ["头字节数", h.header_bytes],
                        ["数据块数", h.data_records],
                        ["每块时长 s", h.record_duration_s],
                        ["原始患者标识", h.patient_identification],
                        ["原始采集标识", h.recording_identification],
                        ["原始开始日期 / 时间", h.start_date + " " + h.start_time],
                    ],
                )
            )
            body += (
                table(
                    [
                        "信号名称",
                        "传感器",
                        "原始物理单位",
                        "物理最小/最大",
                        "数字最小/最大",
                        "原始预滤波说明",
                        "每块样点",
                    ],
                    [
                        [
                            c.label,
                            c.transducer or "未填写",
                            c.physical_dimension or "未填写",
                            f"{c.physical_min} / {c.physical_max}",
                            f"{c.digital_min} / {c.digital_max}",
                            c.prefilter or "未填写",
                            c.samples_per_record,
                        ]
                        for c in h.signals
                    ],
                )
                + "</details>"
            )
        else:
            body += "<p>原始头读取未完成：" + escape(r.storage_error) + "</p>"
        body += (
            "<details><summary>来源与定位</summary><p>输入 SHA-256："
            + escape(r.sha256)
            + "</p><p>通道集合键："
            + escape(r.channel_set_ref)
            + "</p><p>字段引用："
            + escape("#/recordings/" + key)
            + "</p></details></div></details>"
        )
    sections["organization"] = (
        body + ("</div></details>" if active_subject else "") + "</div>"
    )
    body = "<h3>共享通道与采集设置</h3>"
    for key, names in local.channel_sets.items():
        members = [k for k, r in local.recordings.items() if r.channel_set_ref == key]
        body += (
            "<details><summary>"
            + str(len(names))
            + " 个通道 · "
            + str(len(members))
            + " 条记录使用</summary><p>"
            + escape(identifiers(members))
            + "</p><p>"
            + escape(", ".join(names))
            + "</p></details>"
        )
    for key, c in local.acquisition_sets.items():
        body += table(
            ["共享配置", "原始传感器描述", "原始预滤波描述", "尚未确认"],
            [
                [
                    key,
                    ", ".join(c.transducers) or "未填写",
                    ", ".join(c.prefilters) or "未填写",
                    "设备、参考、接地、电极介质、电源频率",
                ]
            ],
        )
    sections["signal"] = body
    sections["events"] = (
        '<p>逐事件表保留记录编号、原始标签、起始秒、持续秒和未取整样点位置。事件含义仍需结合任务资料核对。</p><a href="../local-events.tsv?download=true">下载逐事件时间表</a>'
    )
    sections["metadata"] = (
        "<p>被试编号来自目录和文件名；原始患者标识保留在记录详情。年龄、性别、健康状态等未经解析确认的字段保持未知。</p>"
    )
    duration_groups = {}
    for key, r in local.recordings.items():
        if r.decoded_signal:
            duration_groups.setdefault(
                (r.decoded_signal.shape[1], r.duration_s), []
            ).append(key)
    sections["statistics"] = "<h3>记录长度差异</h3>" + table(
        ["样点数", "时长（秒）", "记录数", "对应记录"],
        [
            (n, duration, len(keys), identifiers(keys))
            for (n, duration), keys in duration_groups.items()
        ],
    )
    return (
        '<p class="muted">已检查表示取得观测，不代表信号质量合格。未检查不表示资料不存在。</p>'
        + "".join(
            "<h2>"
            + label
            + "</h2>"
            + sections[group]
            + "<h3>检查覆盖</h3>"
            + coverage[group]
            for group, label in GROUPS.items()
        )
    )
