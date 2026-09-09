"""Read-only observation builder for EEGMMIDB; no model-generated measurements."""

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.preprocessing.storage import file_hash
from .local_contracts import LocalObservation, EDFHeader, LocalEvent


def read_edf_header(path):
    with path.open("rb") as stream:
        fixed = stream.read(256)
        if len(fixed) != 256 or fixed[:8].strip() != b"0":
            raise ValueError("未识别为 EDF 原始文件头")
        count = int(fixed[252:256])
        size = int(fixed[184:192])
        if not 1 <= count <= 4096 or size != 256 + 256 * count:
            raise ValueError("EDF 头长度与信号数不匹配")
        data = stream.read(size - 256)
        if len(data) != size - 256:
            raise ValueError("EDF 信号头不完整")
    fields, offset = {}, 0
    for name, width, cast in [
        ("label", 16, str),
        ("transducer", 80, str),
        ("physical_dimension", 8, str),
        ("physical_min", 8, float),
        ("physical_max", 8, float),
        ("digital_min", 8, int),
        ("digital_max", 8, int),
        ("prefilter", 80, str),
        ("samples_per_record", 8, int),
    ]:
        fields[name] = [
            cast(
                data[offset + i * width : offset + (i + 1) * width]
                .decode("ascii")
                .strip()
            )
            for i in range(count)
        ]
        offset += count * width

    def text(a, b):
        return fixed[a:b].decode("ascii").strip()

    reserved = text(192, 236)
    return EDFHeader(
        format=reserved[:5] if reserved.startswith(("EDF+C", "EDF+D")) else "EDF",
        header_bytes=size,
        data_records=int(text(236, 244)),
        record_duration_s=float(text(244, 252)),
        signals=[{k: v[i] for k, v in fields.items()} for i in range(count)],
        patient_identification=text(8, 88),
        recording_identification=text(88, 168),
        start_date=text(168, 176),
        start_time=text(176, 184),
    )


def shared_key(prefix, value):
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return prefix + "-" + hashlib.sha256(raw).hexdigest()[:16]


class ObservationBuilder:
    def __init__(
        self, root, chosen, runs, inventory, discovered_subjects, discovered_recordings
    ):
        self.root = root
        self.scope = dict(
            source_root=str(root),
            discovered_files=len(inventory),
            discovered_subjects=discovered_subjects,
            discovered_recordings=discovered_recordings,
            selected_subjects=chosen,
            selected_runs=runs,
            selection_basis="从被试目录发现全部 Run；对象身份按 EEGMMIDB 目录和文件名解析",
        )
        self.records, self.channels, self.acquisition, self.events = {}, {}, {}, []

    def add(self, record, raw, values):
        import numpy as np

        path = self.root / record["source_path"]
        header, header_error = None, None
        try:
            header = read_edf_header(path)
        except (OSError, ValueError, UnicodeError) as exc:
            header_error = str(exc)
        channels = list(raw.ch_names)
        channel_key = shared_key("channels", channels)
        config = dict(
            transducers=sorted({s.transducer for s in header.signals if s.transducer})
            if header
            else [],
            prefilters=sorted({s.prefilter for s in header.signals if s.prefilter})
            if header
            else [],
        )
        acquisition_key = shared_key("acquisition", config)
        self.channels[channel_key] = channels
        self.acquisition[acquisition_key] = config
        local_events = [
            LocalEvent(
                record_id=record["id"],
                event_index=i,
                label=str(label),
                onset_s=float(onset),
                duration_s=float(duration),
                sample_position=float(onset) * float(raw.info["sfreq"]),
            )
            for i, (onset, duration, label) in enumerate(
                zip(
                    raw.annotations.onset,
                    raw.annotations.duration,
                    raw.annotations.description,
                    strict=True,
                )
            )
        ]
        self.events.extend(local_events)
        self.records[record["id"]] = dict(
            subject_id=record["subject"],
            run_id=record["run"],
            source_file=record["source_path"],
            sha256=record["sha256"],
            read_status="readable",
            storage=header.model_dump() if header else None,
            storage_error=header_error,
            form="discontinuous"
            if header and header.format == "EDF+D"
            else "continuous"
            if header and header.format == "EDF+C"
            else None,
            decoded_signal=dict(
                shape=values.shape,
                dtype=str(values.dtype),
                nonfinite_count=int((~np.isfinite(values)).sum()),
            ),
            sampling_rate_hz=float(raw.info["sfreq"]),
            duration_s=record["duration_s"],
            channel_set_ref=channel_key,
            acquisition_set_ref=acquisition_key,
            events=dict(
                record_key=record["id"],
                counts=dict(Counter(e.label for e in local_events)),
            ),
        )

    def finish(self, survey, folder):
        import mne
        from .records import write_readable
        from .formats import write_table

        for r in survey["records"]:
            if r["status"] != "readable":
                self.records[r["id"]] = dict(
                    subject_id=r["subject"],
                    run_id=r["run"],
                    source_file=r["source_path"],
                    sha256=r.get("sha256"),
                    read_status="read_error",
                    error=r["reason"],
                )
        good = {k: r for k, r in self.records.items() if r["read_status"] == "readable"}
        total, read = len(self.records), len(good)
        coverage = {}

        def add(key, group, label, checked, total, reason, refs=(), status=None):
            coverage[key] = dict(
                group=group,
                label=label,
                checked=checked,
                total=total,
                reason=reason,
                refs=list(refs),
                status=status
                or (
                    "observed"
                    if checked == total
                    else "partial"
                    if checked
                    else "read_error"
                ),
            )

        add(
            "scope.inventory",
            "scope",
            "目录扫描",
            1,
            1,
            "包含文件路径和大小；不代表全部内容已读取",
            ["#/scope"],
        )
        add(
            "organization.records",
            "organization",
            "所选记录读取",
            read,
            total,
            "逐条读取所选被试实际存在的全部 Run",
            ["#/recordings"],
        )
        add(
            "signal.header",
            "signal",
            "原始 EDF 头",
            sum(r["storage"] is not None for r in good.values()),
            total,
            "原始头与解码后的数组分别保存",
            ["#/recordings"],
        )
        add(
            "signal.arrays",
            "signal",
            "解码数组与有限性",
            read,
            total,
            "数值有限不代表信号质量合格",
            ["#/recordings"],
        )
        add(
            "signal.channels",
            "signal",
            "通道名称及顺序",
            read,
            total,
            "共享集合保留原始名称；未推断实际电极坐标",
            ["#/channel_sets"],
        )
        add(
            "events.timeline",
            "events",
            "逐事件时间轴",
            read,
            total,
            "时间原点为记录开始，保存秒和未取整样点位置",
            ["#/recordings"],
        )
        invalid = [
            e
            for e in self.events
            if e.onset_s < 0
            or e.onset_s + e.duration_s
            > good[e.record_id]["duration_s"]
            + 1 / good[e.record_id]["sampling_rate_hz"]
        ]
        add(
            "events.bounds",
            "events",
            "事件时间界限",
            read,
            total,
            f"发现 {len(invalid)} 个越界事件；该项表示已检查，差异数见说明",
            ["#/recordings"],
        )
        for key, group, label, reason in [
            (
                "organization.entities",
                "organization",
                "Session / Task / Condition / Acquisition",
                "尚未从本地元数据确认，Run 和被试仅按文件名解析",
            ),
            (
                "organization.bids",
                "organization",
                "源 BIDS 根信息",
                "当前是 EEGMMIDB EDF 适配器；未执行通用 BIDS 元数据发现",
            ),
            (
                "signal.acquisition",
                "signal",
                "设备 / 参考 / 接地 / 电极介质 / 电源频率",
                "EDF 自由文本保留原值；上述含义尚未解析确认",
            ),
            (
                "signal.coordinates",
                "signal",
                "电极布局与实测坐标",
                "目录中的电极图和 PDF 尚未提取核对",
            ),
            (
                "events.sidecars",
                "events",
                "辅助 .event 文件与 EDF 注释对照",
                "已枚举辅助文件；WFDB 二进制注释内容尚未核对",
            ),
            (
                "events.protocol",
                "events",
                "刺激 / 任务 / 间隔的完整流程",
                "本地事件时间不能直接推定实验语义；需来源解释后核对",
            ),
            (
                "metadata.subjects",
                "metadata",
                "年龄 / 性别 / 健康 / 惯用手 / 分组",
                "原始患者标识保存在文件头；尚未解析人口学表",
            ),
            (
                "metadata.dataset",
                "metadata",
                "本地名称 / 版本 / 许可声明",
                "未执行本地说明文档的语义提取，不能断言不存在",
            ),
            (
                "metadata.behavior",
                "metadata",
                "行为 / 刺激 / 同步记录",
                "尚未实现对应本地检查器",
            ),
        ]:
            add(key, group, label, 0, total, reason, status="not_checked")
        add(
            "statistics.aggregate",
            "statistics",
            "已读取记录汇总",
            read,
            total,
            "统计分母是成功读取的记录，失败记录单列",
            ["#/statistics"],
        )
        value = LocalObservation(
            scope=self.scope,
            subjects={s: {} for s in self.scope["selected_subjects"]},
            recordings=self.records,
            channel_sets=self.channels,
            acquisition_sets=self.acquisition,
            coverage=coverage,
            statistics=dict(
                selected_records=total,
                readable_records=read,
                failed_records=total - read,
                duration_s=sum(r["duration_s"] for r in good.values()),
                events=len(self.events),
                sampling_rates=dict(
                    Counter(str(r["sampling_rate_hz"]) for r in good.values())
                ),
                channel_counts=dict(
                    Counter(str(r["decoded_signal"]["shape"][0]) for r in good.values())
                ),
            ),
            provenance=dict(
                inspector="local-observation-v2:" + file_hash(Path(__file__)),
                inspected_at=datetime.now(timezone.utc).isoformat(),
                mne_version=mne.__version__,
                field_sources={
                    "storage": "source_file: EDF fixed header bytes 0..255 and per-signal header blocks",
                    "decoded_signal": "MNE get_data(); shape, dtype, V, count of nonfinite values",
                    "sampling_rate_hz": "MNE info.sfreq",
                    "duration_s": "decoded samples / sampling rate",
                    "channel_sets": "MNE ch_names in original order",
                    "local-events.tsv": "MNE annotations; recording start in seconds",
                    "identity": "EEGMMIDB adapter filename convention, not independently verified subject identity",
                },
            ),
        )
        # Check inputs again after the independent raw-header read.
        for r in survey["records"]:
            if (
                r.get("sha256")
                and file_hash(self.root / r["source_path"]) != r["sha256"]
            ):
                from .dataset import SourceChangedError

                raise SourceChangedError("源文件在观测期间发生变化")
        write_table(
            folder / "local-events.tsv",
            [e.model_dump() for e in self.events],
            list(LocalEvent.model_fields),
        )
        write_readable(folder / "local-inspection.json", value.model_dump(mode="json"))
        return value
