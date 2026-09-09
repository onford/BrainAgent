"""Research-derived method starts and conditional priors for integrated operators."""

from copy import deepcopy
from importlib import metadata
from pathlib import Path

from app.preprocessing.schemas import Evidence
from .io import read
from .knowledge_contracts import ScientificKnowledge
from .method_space import basic_space
from .space_contracts import ExplorationSpace


def knowledge():
    return ScientificKnowledge.model_validate(
        read(Path(__file__).parent / "resources/scientific-knowledge.json")
    )


def input_context(data):
    selected = [
        r
        for r in data.collection.records
        if r.id in data.collection.selected_record_ids
    ]
    try:
        asr = metadata.version("asrpy") == "0.0.8"
    except metadata.PackageNotFoundError:
        asr = False
    return {
        "at_least_four_eeg": all(
            sum(t == "eeg" for t in r.channels.values()) >= 4 for r in selected
        ),
        "electrode_positions": all(
            any(p.endswith("electrodes.tsv") for p in r.files) for r in selected
        ),
        "asr_dependency": asr,
    }


def build_space(context):
    value = basic_space().model_dump(mode="json")
    book = knowledge()
    sources = {s.id: s for s in book.sources}
    for key in ("S06", "S08", "S20", "S21", "S38"):
        source = sources[key]
        value["evidence"][key] = Evidence(
            source_url=source.url,
            source_version=source.version or source.accessed_at,
            locator=source.locator,
            text={
                "S06": "MNE支持显式频率的陷波滤波；本实现固定FIR零相位与过渡带。选择50/60 Hz须结合实测线噪，窄任务带之外的陷波可能冗余。",
                "S08": "PREP提出结合幅度、相关性等诊断检测坏道，并处理坏道与参考之间的相互影响。这里采用有明确差异的检测及插值适配，不宣称完整复现PREP。",
                "S20": "ASR校准从适合的片段估计稳健统计；校准空间、采样率和频谱处理必须与应用相容。具体Python实现由ASRpy固定版本合同约束。",
                "S21": "ASR应用利用已校准统计修复异常子空间；连续窗口和状态有明确参数，不能等同于逐试次任意删样本。",
                "S38": "EA从各域未标注样本的平均协方差构造对齐变换；本项目采用逐被试完整批次及正则化适配。",
            }[key],
        ).model_dump(mode="json")

    def numeric(lo, hi, unit, rationale):
        return dict(
            kind="number",
            minimum=lo,
            maximum=hi,
            unit=unit,
            rationale=rationale,
            origin="engineering",
        )

    def choices(options, unit, rationale):
        return dict(
            kind="choice",
            choices=options,
            unit=unit,
            rationale=rationale,
            origin="engineering",
        )

    def op(
        identity,
        title,
        unit,
        operation,
        domains,
        defaults,
        bindings,
        requires,
        evidence,
        fitted=False,
    ):
        return dict(
            id=identity,
            title=title,
            unit_id=unit,
            op=operation,
            input_stage="continuous",
            output_stage="same",
            fit_scope="record_unlabelled" if fitted else "none",
            domains=domains,
            defaults=defaults,
            bindings=bindings,
            requires=requires,
            evidence_ids=evidence,
        )

    value["operators"] += [
        op(
            "notch", "工频陷波", "EEG-FILTER", "notch",
            {"freqs": choices([[50.0], [60.0], [50.0, 60.0]], "Hz",
                              "线噪频率的显式候选；由实测频谱支持，不将国家地区推测当作观测。")},
            {"freqs": [60.0]}, {"picks": "$eeg_channels"}, [], ["S06"],
        ),
        op(
            "highpass",
            "宽带去漂移",
            "EEG-FILTER",
            "filter",
            {
                "l_freq": numeric(
                    1,
                    2,
                    "Hz",
                    "ASR拟合视图的工程范围；保证最短0.5秒窗口至少跨半个高通周期",
                )
            },
            {"l_freq": 1.0},
            {
                "h_freq": None,
                "method": "iir",
                "phase": "zero",
                "picks": "$eeg_channels",
            },
            [],
            ["S20"],
        ),
        op(
            "detect_bad_channels",
            "坏道诊断与标记",
            "EEG-AUTO-BAD-CHANNEL",
            "detect_bad_channels",
            {
                "deviation_z": numeric(
                    3,
                    10,
                    "robust z",
                    "围绕来源检测原则探索灵敏度，不能解释为标准正态概率",
                ),
                "correlation_threshold": numeric(
                    0.1,
                    0.8,
                    "correlation",
                    "当前实现的相关性诊断范围，不套用其他检测器阈值",
                ),
                "bad_window_fraction": numeric(
                    0.01, 0.5, "fraction", "异常窗口比例的工程敏感性分析"
                ),
                "flat_duration_s": numeric(1, 10, "s", "持续平坦检测时间尺度"),
                "persistent_low_corr_fraction": numeric(0.3, 0.8, "fraction", "持续低相关的窗口覆盖；工程联合诊断，非PREP原始规则"),
                "persistent_low_corr_seconds": numeric(3, 10, "s", "持续低相关须满足的连续时长"),
                "shared_correlation_threshold": numeric(0.6, 0.9, "correlation", "高幅且相关的共同活动仅作伪迹候选，避免直接当坏电极插值"),
            },
            {
                "deviation_z": 5.0,
                "correlation_threshold": 0.4,
                "bad_window_fraction": 0.1,
                "flat_duration_s": 5.0,
                "persistent_low_corr_fraction": 0.5,
                "persistent_low_corr_seconds": 5.0,
                "shared_correlation_threshold": 0.7,
            },
            {
                "adaptation_scope": "record_unlabeled",
                "window_s": 1.0,
                "flat_ptp_V": 1e-7,
                "selection_policy": "consensus_v2",
            },
            ["at_least_four_eeg"],
            ["S08"],
            fitted=True,
        ),
        op(
            "interpolate_bad_channels",
            "坏道空间插值",
            "EEG-AUTO-BAD-CHANNEL",
            "interpolate_bad_channels",
            {
                "max_fraction": numeric(
                    0.05,
                    0.25,
                    "fraction",
                    "允许修复的最大通道比例；超过上限须失败，不能只修复最容易的通道",
                )
            },
            {"max_fraction": 0.1},
            {},
            ["at_least_four_eeg", "electrode_positions"],
            ["S08"],
        ),
        op(
            "asr",
            "ASR异常子空间重建",
            "EEG-ASR-AUTO",
            "asr_clean",
            {
                "cutoff": numeric(
                    10,
                    100,
                    "ASR cutoff",
                    "来源实现支持的阈值范围；阈值更低不代表方法更好",
                ),
                "win_len": choices(
                    [0.5, 1.0, 2.0], "s", "保持校准窗口有效并允许比较时间尺度"
                ),
                "lookahead": choices(
                    [0.125, 0.25],
                    "s",
                    "在128/160 Hz均为整数采样点，且不超过最短窗口一半",
                ),
                "maxdims": numeric(
                    0.1, 0.8, "fraction", "可重建子空间比例的工程探索上限"
                ),
                "on_insufficient_calibration": choices(
                    ["error", "identity"], "policy",
                    "校准不足时严格失败或显式保留ASR输入；只针对校准时长不足，数值错误仍失败。",
                ),
            },
            {"cutoff": 20.0, "win_len": 0.5, "lookahead": 0.25, "maxdims": 0.66,
             "on_insufficient_calibration": "error"},
            {
                "adaptation_scope": "record_unlabeled",
                "win_overlap": 0.66,
                "min_clean_seconds": 30.0,
                "stepsize": 32,
                "mem_splits": 3,
            },
            ["at_least_four_eeg", "asr_dependency"],
            ["S20", "S21"],
            fitted=True,
        ),
    ]

    next(o for o in value["operators"] if o["id"] == "asr")["input_highpass"] = {
        "minimum_hz": 0.5, "window_parameter": "win_len", "minimum_cycles": 0.5,
        "rationale": "ASR输入须已高通至少0.5 Hz，且高通频率乘窗口秒数至少0.5；可由之前的高通或带通满足，无须重复滤波。",
    }

    def prior(identity, strength, relation, operators, rationale, evidence, origin):
        return dict(
            id=identity,
            strength=strength,
            relation=relation,
            operators=operators,
            condition="所列算子均用于当前同一连续数据主链",
            rationale=rationale,
            evidence_ids=evidence,
            origin=origin,
        )

    value["priors"] += [
        prior(
            "notch-before-diagnosis", "soft", "before",
            ["notch", "detect_bad_channels"],
            "存在明显工频污染时，优先在幅度/相关性诊断前抑制线噪；无明显污染时可能没有收益。",
            ["S06", "S08"], "engineering",
        ),
        prior(
            "notch-before-asr", "soft", "before", ["notch", "asr"],
            "若需要工频处理，优先让ASR校准和应用共同使用处理后的输入；该次序是待验证工程先验。",
            ["S06", "S20"], "engineering",
        ),
        prior(
            "repair-needs-detection",
            "hard",
            "requires",
            ["interpolate_bad_channels", "detect_bad_channels"],
            "插值必须有同一主链的显式坏道诊断。",
            [],
            "implementation",
        ),
        prior(
            "detect-before-repair",
            "hard",
            "before",
            ["detect_bad_channels", "interpolate_bad_channels"],
            "先确定坏道与供体，再恢复固定通道网格。",
            [],
            "implementation",
        ),
        prior(
            "asr-before-car",
            "hard",
            "before",
            ["asr", "average_reference"],
            "当前ASR实现要求满秩原参考；不能把该实现约束外推到所有ASR方法。",
            [],
            "implementation",
        ),
        prior(
            "asr-before-interpolation",
            "hard",
            "before",
            ["asr", "interpolate_bad_channels"],
            "插值可能引入冗余，当前ASR校准在未插值好道上完成。",
            [],
            "implementation",
        ),
        prior(
            "repair-before-car",
            "soft",
            "before",
            ["interpolate_bad_channels", "average_reference"],
            "坏道和参考相互影响；完成修复后再形成最终平均参考是优先比较路线。",
            ["S08"],
            "literature",
        ),
        prior(
            "diagnose-before-analysis-band",
            "soft",
            "before",
            ["detect_bad_channels", "bandpass"],
            "分析频带可能隐藏异常幅度或高频污染，优先保留较宽诊断视图。",
            ["S08"],
            "literature",
        ),
        prior(
            "asr-before-analysis-band",
            "soft",
            "before",
            ["asr", "bandpass"],
            "优先在去漂移的宽带信号完成ASR，再选择任务频带；窄带ASR属于需要验证的适配。",
            ["S20", "S21"],
            "engineering",
        ),
    ]
    original = deepcopy(value["methods"][2]["recipe"])
    original["nodes"][1]["parameters"] = {"l_freq": 4.0, "h_freq": 40.0}
    original["adaptation"] = {"adaptation": "euclidean_alignment"}
    value["methods"].append(
        dict(
            id="literature-ea",
            title="宽频带 · 个体无标签EA",
            origin="literature_adaptation",
            recipe=original,
            evidence_ids=["S38"],
            deviations=[
                "4–40 Hz与0.1协方差正则为工程适配；逐被试整批无标签拟合，非在线归纳条件。 "
            ],
        )
    )
    if context.get("at_least_four_eeg") and context.get("electrode_positions"):
        nodes = [
            dict(id=k, operator=k)
            for k in [
                "resample",
                "highpass",
                "detect_bad_channels",
                "interpolate_bad_channels",
                "average_reference",
                "bandpass",
                "epoch",
            ]
        ]
        nodes[-2]["parameters"] = {"l_freq": 1.0, "h_freq": 40.0}
        value["methods"].append(
            dict(
                id="literature-channel-repair",
                title="坏道诊断 · 插值 · 宽频带",
                origin="literature_adaptation",
                recipe={"nodes": nodes},
                evidence_ids=["S08"],
                deviations=[
                    "借鉴PREP坏道诊断原则；当前检测器为明确简化的工程适配，不是完整PREP复现。",
                    "保持固定trial分母，输出修复与质量标记，不按分类成绩剔除试次。 ",
                ],
            )
        )
        if context.get("asr_dependency"):
            nodes = deepcopy(nodes)
            nodes.insert(3, dict(id="asr", operator="asr"))
            value["methods"].append(
                dict(
                    id="literature-asr-repair",
                    title="ASR · 坏道修复 · 宽频带",
                    origin="literature_adaptation",
                    recipe={"nodes": nodes},
                    evidence_ids=["S08", "S20", "S21"],
                    deviations=[
                        "ASRpy固定实现；逐记录整批未标注校准，不是原文数据集或在线实验复现。",
                        "未达到校准时长、秩或修复比例条件时保留失败原因，不静默跳过算子。 ",
                    ],
                )
            )
            conditional = deepcopy(value["methods"][-1])
            conditional.update(
                id="literature-conditional-asr-repair",
                title="条件ASR · 坏道修复 · 宽频带",
                deviations=[
                    "ASRpy固定实现，逐记录整批未标注校准；工程条件策略。",
                    "仅校准时长不足时保持ASR步骤输入，继续其余算子；记录ASR未应用及真实原因。",
                    "完整保留固定被试与试次分母；其他ASR错误不转为恒等处理。",
                ],
            )
            next(n for n in conditional["recipe"]["nodes"] if n["operator"] == "asr")["parameters"] = {
                "on_insufficient_calibration": "identity"
            }
            value["methods"].append(conditional)
    return ExplorationSpace.model_validate(value)
