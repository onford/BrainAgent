"""Read-only intake inspection; deterministic disposition before BIDS creation."""

from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
import json
import re

from app.preprocessing.storage import file_hash, within
from .collection_contracts import (
    IntakeAudit,
    IntakeCheck,
    CheckProvenance,
    LiteratureExclusions,
)
from .formats import TABLE_MODELS, write_table
from .records import write_readable

POLICY = "仅排除已确认的结构性失败；资料缺失、参数差异和文献排除建议保留标记。未执行信号质量筛选。"


def table(folder, name, rows):
    write_table(folder / name, rows, list(TABLE_MODELS[name].model_fields))


def literature_matches(review, survey):
    records = []
    for item in review.literature_exclusions:
        matched, identified = [], []
        for identity in item.reported_ids:
            if item.object_type == "subject" and re.fullmatch(
                r"(?:S|sub-)?\d{1,3}", identity
            ):
                number = int(re.sub(r"\D", "", identity))
                subject = f"S{number:03}"
                identified.append(subject)
                matched.extend(
                    r["id"] for r in survey["records"] if r["subject"] == subject
                )
            elif item.object_type == "recording" and re.fullmatch(
                r"S\d{3}R\d{2}", identity
            ):
                identified.append(identity)
                matched.extend(
                    r["id"] for r in survey["records"] if r["id"] == identity
                )
        status = (
            "selected"
            if matched
            else "outside_selection"
            if identified
            else "unresolved"
        )
        records.append(
            {
                **item.model_dump(),
                "local_objects": sorted(set(matched)),
                "match_status": status,
                "action": "保留标记" if status != "outside_selection" else "不处理",
            }
        )
    return LiteratureExclusions(policy=POLICY, records=records)


class Audit:
    def __init__(self, folder, survey):
        self.folder, self.survey, self.checks = folder, survey, []
        verification = folder.parent / "survey/verification.json"
        self.expectations = {}
        if verification.exists():
            for i, row in enumerate(
                json.loads(verification.read_text(encoding="utf-8"))["comparisons"]
            ):
                statements = [
                    row[side]["statement"]
                    for side in ("official_sources", "official_paper")
                    if row[side]["statement"]
                ]
                if statements:
                    self.expectations[row["field"]] = (
                        f"survey/verification.json#/comparisons/{i}: "
                        + "; ".join(statements)
                    )
        self.provenance = CheckProvenance(
            checked_at=datetime.now(timezone.utc).isoformat(),
            implementation="eegmmidb-intake-v2",
            code_sha256={
                name: file_hash(Path(__file__).parent / name)
                for name in ("intake.py", "dataset.py")
            },
            versions={name: version(name) for name in ("mne", "mne-bids", "numpy")},
            parameters={"roundtrip_rtol": 3e-7, "roundtrip_atol_V": 1e-12},
            output="collection/audit.json",
        )

    def add(
        self,
        category,
        obj,
        expected,
        observed,
        status="一致",
        severity="information-only",
        action="不处理",
    ):
        field = {
            "scope_files": "directory_structure",
            "directory_identity": "task_runs",
            "format_readability": "file_format",
            "subjects_groups": "subjects",
            "acquisition_parameters": "sampling_rate",
            "channels_auxiliary": "channels",
            "electrodes_coordinates": "acquisition",
            "dimensions_units_values": "signal_arrays",
            "timing": "recording_duration",
            "events": "events",
            "trial_protocol": "task_runs",
        }.get(category)
        if field in self.expectations:
            expected += "; 已取得的来源表述：" + self.expectations[field]
        self.checks.append(
            IntakeCheck(
                check_category=category,
                object_key=obj,
                expected_statement=expected,
                observed_evidence=observed,
                status=status,
                severity=severity,
                action=action,
                provenance="collection/audit.json#/provenance",
            )
        )

    def save(self):
        audit = IntakeAudit(
            scope=self.survey["scope"],
            policy=POLICY,
            provenance=self.provenance,
            checks=self.checks,
        )
        write_readable(self.folder / "audit.json", audit.model_dump())
        table(self.folder, "anomalies.tsv", [c.model_dump() for c in self.checks])

    def scan(self):
        import mne
        import numpy as np

        root = Path(self.survey["source_root"])
        accepted, excluded = [], []
        self.add(
            "scope_files",
            "dataset/selection",
            "扫描完整源目录；仅核查所选被试与 Run 的数据内容",
            f"available_subjects={self.survey['available_subjects']}; available_recordings={self.survey['available_recordings']}; selected={len(self.survey['records'])}; survey/source-inventory.tsv",
        )
        for category, expected, observed in [
            (
                "subjects_groups",
                "人口学/分组表应可关联到被试",
                "所选记录按目录编号关联；未取得可核对的人口学与分组表",
            ),
            (
                "electrodes_coordinates",
                "区分实测坐标与模板坐标",
                "未取得个体实测坐标；转换采用 standard_1005 模板并在坐标元数据标明来源",
            ),
            (
                "behavior",
                "行为记录应关联 Trial",
                "本适配器未解析行为记录；数量未知，不能记为零",
            ),
            (
                "stimulus_sync",
                "刺激与同步记录应有时间对齐依据",
                "仅有 EDF 事件时间；未取得独立刺激/同步日志",
            ),
            (
                "notes_exclusions",
                "核对文献报告的排除对象与本地编号",
                "collection/literature-exclusions.json；文献建议保留标记，不自动套用",
            ),
            (
                "raw_processed",
                "源与标准副本的数值、通道、时间和事件须对应",
                "转换前只读扫描；转换后逐记录复读核验，见本类别后续条目",
            ),
        ]:
            self.add(
                category,
                "dataset/selection",
                expected,
                observed,
                "无法核查" if category != "notes_exclusions" else "部分一致",
                "retain-with-flag",
                "保留标记",
            )
        for item in self.survey["records"]:
            obj = item["id"]
            failures = []

            def check(category, condition, expected, observed, hard=True):
                self.add(
                    category,
                    obj,
                    expected,
                    observed,
                    "一致" if condition else "不一致",
                    "information-only"
                    if condition
                    else "structural-hard-fail"
                    if hard
                    else "retain-with-flag",
                    "不处理" if condition else "排除" if hard else "保留标记",
                )
                if not condition and hard:
                    failures.append(f"{category}: {observed}")

            path = root / item["source_path"]
            linked = any(
                p.is_symlink() or getattr(p, "is_junction", lambda: False)()
                for p in [path, *path.parents]
                if p != root.parent
            )
            check(
                "directory_identity",
                not linked and item["source_path"] == f"{item['subject']}/{obj}.edf",
                "被试目录、记录编号与文件名一致；数据为实际文件",
                item["source_path"],
            )
            try:
                if linked:
                    raise ValueError("linked source entry")
                if item["status"] == "excluded":
                    raise ValueError(item["reason"])
                with mne.io.read_raw_edf(
                    within(root, item["source_path"]), preload=True, verbose="ERROR"
                ) as raw:
                    values = raw.get_data()
                    check(
                        "format_readability",
                        True,
                        "完整解码所选 EDF",
                        f"decoded={values.shape}",
                    )
                    check(
                        "acquisition_parameters",
                        raw.info["sfreq"] == self.survey["profile"]["expected_sfreq"],
                        "采样率应与适配器已核对的 160 Hz 配置一致；其他硬件元数据另列未知",
                        f"sfreq={raw.info['sfreq']}",
                        hard=False,
                    )
                    check(
                        "channels_auxiliary",
                        len(raw.ch_names) == 64
                        and len(set(raw.ch_names)) == len(raw.ch_names),
                        "EEGMMIDB 适配器使用 64 个唯一通道",
                        f"names={raw.ch_names}; types={raw.get_channel_types()}",
                    )
                    check(
                        "dimensions_units_values",
                        values.shape == (64, raw.n_times)
                        and values.size > 0
                        and bool(np.isfinite(values).all()),
                        "二维非空、有限信号；MNE 解码电压单位 V",
                        f"shape={values.shape}; dtype={values.dtype}; finite={bool(np.isfinite(values).all())}; unit=V",
                    )
                    flat = [
                        raw.ch_names[i]
                        for i in np.flatnonzero(np.ptp(values, axis=1) == 0)
                    ]
                    if flat:
                        self.add(
                            "dimensions_units_values",
                            obj,
                            "标记整段常量通道，暂不执行质量排除",
                            str(flat),
                            "不一致",
                            "retain-with-flag",
                            "保留标记",
                        )
                    check(
                        "timing",
                        raw.n_times == item["samples"]
                        and raw.info["sfreq"] == item["sfreq"]
                        and bool(np.all(np.diff(raw.times) > 0)),
                        "采样点、采样率与扫描一致，时间轴递增",
                        f"samples={raw.n_times}; duration_s={raw.n_times / raw.info['sfreq']}; first_samp={raw.first_samp}",
                    )
                    onsets = raw.annotations.onset - raw.first_time
                    durations = raw.annotations.duration
                    codes = set(raw.annotations.description)
                    valid = (
                        np.isfinite(onsets).all()
                        and np.isfinite(durations).all()
                        and np.all(onsets >= 0)
                        and np.all(durations >= 0)
                        and np.all(
                            onsets + durations
                            <= raw.n_times / raw.info["sfreq"] + 1 / raw.info["sfreq"]
                        )
                        and np.all(np.diff(np.round(onsets * raw.info["sfreq"])) > 0)
                    )
                    check(
                        "events",
                        bool(valid) and codes <= {"T0", "T1", "T2"},
                        "事件码已定义、样点有序唯一、时间和持续时长有效",
                        f"codes={sorted(codes)}; valid_timing={bool(valid)}",
                    )
                    check(
                        "trial_protocol",
                        {"T1", "T2"} <= codes,
                        "左右手训练任务必须具有两类事件；保留 T0 上下文",
                        f"events={item['event_counts']}",
                    )
            except (OSError, ValueError, RuntimeError) as exc:
                check("format_readability", False, "完整解码所选 EDF", str(exc))
            if failures:
                excluded.append({"object_key": obj, "reason": "; ".join(failures)})
            else:
                accepted.append(item)
        # If nothing was readable, all categories still have an explicit outcome.
        from .collection_contracts import CATEGORIES

        for category in set(CATEGORIES) - {c.check_category for c in self.checks}:
            self.add(
                category,
                "dataset/selection",
                "需要可读数据进行检查",
                "没有可读记录",
                "无法核查",
                "retain-with-flag",
                "保留标记",
            )
        self.save()
        return accepted, excluded
