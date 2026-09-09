"""Fixed engineering search space; no model-generated operations or code."""

from pathlib import Path

from app.preprocessing.schemas import Evidence, MethodSpec, Step
from app.preprocessing.storage import digest, file_hash

BASELINE_ID = "bp8-30-average"
BANDS = ((8, 30), (1, 40), (4, 40), (8, 40))


def catalog():
    return [
        {
            "id": f"bp{lo}-{hi}-{ref}",
            "title": f"{lo}–{hi} Hz · "
            + ("平均参考" if ref == "average" else "保留采集参考"),
            "parameters": {"l_freq": lo, "h_freq": hi, "reference": ref},
            "operator_count": 4 if ref == "average" else 3,
            "order": i * 2 + j,
        }
        for i, (lo, hi) in enumerate(BANDS)
        for j, ref in enumerate(("average", "original"))
    ]


def search_engine_hash():
    root = Path(__file__).parent
    return digest({p.name: file_hash(p) for p in sorted(root.glob("*.py"))})


def method(entry, panel):
    interface = panel["output_contract"]
    params = entry["parameters"]
    evidence = Evidence(
        source_url="brainagent:offline-search:catalog:1",
        locator=entry["id"],
        text="冻结的工程比较目录；固定零相位带通、固定参考、重采样与切窗，效用由开发评价器测量。",
        source_version="1",
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
        version="1",
        title=entry["title"],
        source="classic",
        mechanism="fixed-bandpass-reference",
        recipe=steps,
        output="epochs",
        evidence=[evidence],
        applicability={"dataset_id": "eegmmidb", "task": "left_right_motor_imagery"},
        adaptations=[
            "离线完整记录处理；开发面板上的流程效用，不是独立泛化或神经信号保真结论。"
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
