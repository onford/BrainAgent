"""Shared preprocessing policies with declared, label-free individual fitting."""

from pathlib import Path

from app.preprocessing.schemas import Evidence, MethodSpec, Step
from app.preprocessing.storage import digest, file_hash

BASELINE_ID = "bp8-30-average"
BANDS = ((8, 30), (1, 40), (4, 40), (8, 40))


def catalog():
    fixed = [
        {
            "id": f"bp{lo}-{hi}-{ref}",
            "title": f"{lo}–{hi} Hz · "
            + ("平均参考" if ref == "average" else "保留采集参考"),
            "parameters": {
                "l_freq": lo,
                "h_freq": hi,
                "reference": ref,
                "adaptation": "none",
            },
            "operator_count": 4 if ref == "average" else 3,
            "order": i * 2 + j,
        }
        for i, (lo, hi) in enumerate(BANDS)
        for j, ref in enumerate(("average", "original"))
    ]
    policies = []
    for lo, hi in BANDS:
        for adaptation, suffix, threshold, title in (
            ("subject_scale", "scale", 10.0, "逐被试统一尺度"),
            ("euclidean_alignment", "ea", 10.0, "逐被试无标签对齐"),
            ("conditional_alignment", "conditional-ea-3", 3.0, "诊断条件对齐 · 阈值 3"),
            (
                "conditional_alignment",
                "conditional-ea-10",
                10.0,
                "诊断条件对齐 · 阈值 10",
            ),
        ):
            policies.append(
                {
                    "id": f"bp{lo}-{hi}-original-{suffix}",
                    "title": f"{lo}–{hi} Hz · {title}",
                    "parameters": {
                        "l_freq": lo,
                        "h_freq": hi,
                        "reference": "original",
                        "adaptation": adaptation,
                        "alignment_threshold": threshold,
                    },
                    "operator_count": 4,
                    "order": len(fixed) + len(policies),
                }
            )
    return fixed + policies


def search_engine_hash():
    root = Path(__file__).parent
    hashes = {p.name: file_hash(p) for p in sorted(root.glob("*.py"))}
    hashes["../file_publish.py"] = file_hash(root.parent / "file_publish.py")
    return digest(hashes)


def method(entry, panel):
    interface = panel["output_contract"]
    params = entry["parameters"]
    evidence = Evidence(
        source_url="brainagent:offline-search:catalog:2",
        locator=entry["id"],
        text="共享策略目录：连续信号处理后，按声明策略从各被试无标签试次拟合个体表示；共同学习器按被试隔离评价。频带和条件阈值为工程候选，非文献最优参数。",
        source_version="2",
    )
    steps = [
        Step(
            id="resample",
            unit_id="EEG-RESAMPLE",
            op="resample",
            params={"sfreq": interface["sfreq"]},
            evidence_indices=[0],
        ),
        Step(
            id="bandpass",
            unit_id="EEG-FILTER",
            op="filter",
            input="resample",
            params={
                "l_freq": params["l_freq"],
                "h_freq": params["h_freq"],
                "method": "iir",
                "phase": "zero",
                "picks": "$eeg_channels",
            },
            evidence_indices=[0],
        ),
    ]
    previous = "bandpass"
    if params["reference"] == "average":
        steps.append(
            Step(
                id="reference",
                unit_id="EEG-REREFERENCE",
                op="reference",
                input=previous,
                params={"ref_channels": "average"},
                evidence_indices=[0],
            )
        )
        previous = "reference"
    steps.append(
        Step(
            id="epochs",
            unit_id="EEG-EPOCH",
            op="epoch",
            input=previous,
            params={
                "events": "$events",
                "event_id": "$event_id",
                "picks": "$eeg_channels",
                "tmin": interface["tmin"],
                "tmax": interface["tmax"],
            },
            evidence_indices=[0],
        )
    )
    return MethodSpec(
        id=entry["id"],
        version="2",
        title=entry["title"],
        source="classic",
        mechanism="fixed-bandpass-reference; adaptation=" + params["adaptation"],
        recipe=steps,
        output="epochs",
        evidence=[evidence],
        applicability={"dataset_id": "eegmmidb", "task": "left_right_motor_imagery"},
        adaptations=[
            "离线完整记录处理；开发面板上的流程效用，不是独立泛化或神经信号保真结论。",
            "个体适配策略及拟合产物由 policy.json 与 representation 回执记录；数值配方输出适配前的伏特数据。",
        ],
    )


def select(candidates):
    entries = {c["id"]: c for c in catalog()}
    eligible = [
        c
        for c in candidates
        if (c.get("receipt") or {}).get("status") == "evaluated"
        and c.get("status", "evaluated") == "evaluated"
    ]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda c: (
            -c["receipt"]["macro_ba"],
            c["id"] != BASELINE_ID,
            entries[c["id"]]["operator_count"],
            entries[c["id"]]["order"],
        ),
    )["id"]
