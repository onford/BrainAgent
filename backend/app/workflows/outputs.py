import json
import random
import shutil
import zipfile
from collections import Counter
from pathlib import Path

from app.preprocessing.runner import verify_result
from app.preprocessing.schemas import Ref
from app.preprocessing.storage import file_hash
from .records import write_readable as write_json
from .dataset import check_sources, write_tsv
from .formats import ARRAY_FORMATS, PROVENANCE_FILES, delivery_members


def choose(result, plan, store, seed):
    required = set(plan["input_snapshot"]["collection"]["selected_record_ids"])
    candidates, excluded = [], []
    for method_ref in plan["request"]["methods"]:
        records = [r for r in result.records if r["method_id"] == method_ref["id"]]
        valid = {
            r["record_id"]
            for r in records
            if r["status"] == "completed" and verify_result(store.root, r["result"])
        }
        if valid == required:
            candidates.append(method_ref)
        else:
            excluded.append(
                {
                    "method_ref": method_ref,
                    "missing_or_invalid_records": sorted(required - valid),
                }
            )
    if not candidates:
        raise ValueError("没有覆盖全部保留记录且产物完整的候选方法")
    candidates.sort(key=lambda r: r["id"])
    selected = random.Random(seed).choice(candidates)
    return {
        "selection_policy": "random",
        "quality_evaluated": False,
        "seed": seed,
        "eligible_candidates": candidates,
        "excluded_candidates": excluded,
        "selected_method_ref": selected,
        "best_output": None,
        "reason": "从完整执行且产物核验通过的候选方法中随机选择；未进行质量排名。",
    }


def report(state, folder, store):
    from .reporting import render_report

    return render_report(folder)


def deliver(state, folder, store):
    import numpy as np

    survey = state["outputs"]["data_survey"]
    check_sources(survey)
    selection = state["outputs"]["data_evaluation"]
    job = store.status(state["owner"], state["outputs"]["data_preprocessing"]["job_id"])
    result_records = [
        r
        for r in job.records
        if r["method_id"] == selection["selected_method_ref"]["id"]
    ]
    source_records = {r["id"]: r for r in survey["records"]}
    folder.mkdir(parents=True, exist_ok=True)
    arrays, labels, groups, rows = [], [], [], []
    channels, sfreq = None, None
    for r in sorted(result_records, key=lambda r: r["record_id"]):
        if r["status"] != "completed" or not verify_result(store.root, r["result"]):
            raise ValueError("交付前产物完整性核验失败")
        artifacts = {
            a["name"]: store.root / a["path"] for a in r["result"]["artifacts"]
        }
        values = np.load(artifacts["signal_V.npy"], allow_pickle=False)
        info = r["result"]["delta"]["after"]
        if values.ndim != 3 or len(values) == 0 or not np.isfinite(values).all():
            raise ValueError("训练输出必须为有限值 Epoch 数组")
        if channels is not None and (
            channels != info["channels"]
            or sfreq != info["sfreq"]
            or arrays[0].shape[1:] != values.shape[1:]
        ):
            raise ValueError("候选记录的通道、采样率或时间长度不同")
        channels, sfreq = info["channels"], info["sfreq"]
        events = sorted(
            (
                e
                for e in json.loads(
                    artifacts["events.json"].read_text(encoding="utf-8")
                )
                if e["retained"]
            ),
            key=lambda e: e["epoch_index"],
        )
        if len(events) != len(values) or [e["epoch_index"] for e in events] != list(
            range(len(values))
        ):
            raise ValueError("事件与训练数组未逐行对齐")
        subject = source_records[r["record_id"]]["subject"]
        for event in events:
            if event["label"] not in {"left_hand", "right_hand"}:
                raise ValueError("交付发现未定义类别")
            labels.append(0 if event["label"] == "left_hand" else 1)
            groups.append(subject)
            rows.append(
                {
                    "index": len(rows),
                    "record_id": r["record_id"],
                    "subject": subject,
                    "label": event["label"],
                    "source_event": event["event_id"],
                    "source_sample": event["original_sample"],
                    "epoch_index": event["epoch_index"],
                }
            )
        arrays.append(values.astype(np.float32))
        provenance = folder / "provenance" / r["record_id"]
        provenance.mkdir(parents=True, exist_ok=True)
        for name in PROVENANCE_FILES:
            shutil.copy2(artifacts[name], provenance / name)
    if not arrays:
        raise ValueError("没有可交付的 Epoch")
    X, y, subjects = (
        np.concatenate(arrays),
        np.asarray(labels, dtype=np.int64),
        np.asarray(groups, dtype=ARRAY_FORMATS["subjects.npy"]["dtype"]),
    )
    unique = sorted(set(groups))
    random.Random(state["request"]["seed"]).shuffle(unique)
    roles = {s: "train" for s in unique}
    if len(unique) >= 2:
        roles[unique[-1]] = "test"
    if len(unique) >= 3:
        roles[unique[-2]] = "validation"
    splits = np.asarray(
        [roles[s] for s in groups], dtype=ARRAY_FORMATS["split.npy"]["dtype"]
    )
    for row, split in zip(rows, splits):
        row["split"] = str(split)
    folder.mkdir(parents=True, exist_ok=True)
    for name, value in {"X": X, "y": y, "subjects": subjects, "split": splits}.items():
        if value.dtype != np.dtype(
            ARRAY_FORMATS[f"{name}.npy"]["dtype"]
        ) or value.ndim != len(ARRAY_FORMATS[f"{name}.npy"]["axes"]):
            raise ValueError(f"{name}.npy does not match the training array format")
        np.save(folder / f"{name}.npy", value, allow_pickle=False)
        reread = np.load(folder / f"{name}.npy", allow_pickle=False)
        if not np.array_equal(reread, value):
            raise ValueError("训练数组保存后读取不一致")
    write_json(folder / "labels.json", {"0": "left_hand", "1": "right_hand"})
    write_json(
        folder / "channels.json",
        {
            "names": channels,
            "sfreq": sfreq,
            "unit": "V",
            "dtype": "float32",
            "layout": ["epochs", "channels", "samples"],
            "tmin_s": state["request"]["tmin"],
            "tmax_s": state["request"]["tmax"],
            "time_endpoint": "inclusive",
        },
    )
    write_tsv(
        folder / "trial-index.tsv",
        rows,
        [
            "index",
            "record_id",
            "subject",
            "label",
            "source_event",
            "source_sample",
            "epoch_index",
            "split",
        ],
    )
    method = store.get(
        state["owner"], Ref.model_validate(selection["selected_method_ref"]), "method"
    )
    write_json(folder / "method.json", method)
    write_json(folder / "selection.json", selection)
    write_json(
        folder / "sources.json",
        {
            "profile": survey["profile"],
            "files": [
                {"path": r["source_path"], "sha256": r["sha256"]}
                for r in survey["records"]
                if r.get("sha256")
            ],
        },
    )
    shutil.copy2(folder.parent / "report/report.html", folder / "report.html")
    shutil.copy2(
        Path(__file__).parent / "templates/train_example.py",
        folder / "train_example.py",
    )
    readme = """# EEG 训练数据

X.npy: float32，Epoch × EEG 通道 × 时间点，单位 V。
y.npy: int64，0=left_hand，1=right_hand。
subjects.npy / split.npy: 每行对应的被试与 train / validation / test 分组。
trial-index.tsv: 每一行到原始事件、记录和样点的映射。
同一被试只进入一个分组；标准化或模型拟合应仅使用 train。
候选方法随机选择，selection.json 保存随机种子；没有进行质量排名。
数据来源 EEGMMIDB 1.0.0，DOI 10.13026/C28G6P，ODC Attribution License v1.0。
来源与引用见 sources.json，操作与参数见 method.json，统计和限制见 report.html。
provenance/ 保存每条记录的实际执行参数、版本、事件对应和前后统计。
train_example.py: 安装 numpy、scikit-learn 后执行 python train_example.py，
仅用 train 拟合标准化与逻辑回归并检查预测可用性，不输出质量排名。

```python
import numpy as np
X = np.load('X.npy', allow_pickle=False)
y = np.load('y.npy', allow_pickle=False)
split = np.load('split.npy', allow_pickle=False)
X_train, y_train = X[split == 'train'], y[split == 'train']
```
"""
    (folder / "README.md").write_text(readme, encoding="utf-8")
    limitations = [
        "工程预设；尚未验证模型性能或候选质量",
        "样本范围由 subjects/runs 明确限定",
    ]
    missing_splits = sorted({"train", "validation", "test"} - set(splits))
    if missing_splits:
        limitations.append("被试数不足，以下分组为空：" + ", ".join(missing_splits))
    members = delivery_members(folder, [r["record_id"] for r in result_records])
    counts = Counter(map(str, y))
    manifest = {
        "workflow_id": state["id"],
        "shape": list(X.shape),
        "classes": {label: counts[label] for label in ["0", "1"]},
        "split_counts": {
            role: int(np.sum(splits == role))
            for role in ["train", "validation", "test"]
        },
        "subject_split": roles,
        "unit": "V",
        "selection_policy": "random",
        "quality_evaluated": False,
        "selected_method_ref": selection["selected_method_ref"],
        "files": [
            {
                "name": p.relative_to(folder).as_posix(),
                "sha256": file_hash(p),
                "bytes": p.stat().st_size,
            }
            for p in members
        ],
        "limitations": limitations,
    }
    write_json(folder / "manifest.json", manifest)
    archive = folder.parent / "training-data.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in [*members, folder / "manifest.json"]:
            z.write(p, p.relative_to(folder).as_posix())
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError("交付压缩包完整性校验失败")
    check_sources(survey)
    return {
        "archive": "training-data.zip",
        "manifest": "delivery/manifest.json",
        **{
            k: manifest[k]
            for k in [
                "shape",
                "classes",
                "split_counts",
                "subject_split",
                "selection_policy",
                "quality_evaluated",
            ]
        },
        "sha256": file_hash(archive),
        "source_unchanged": True,
    }
