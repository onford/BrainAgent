import json
import hashlib
import shutil
import zipfile
from collections import Counter
from contextlib import contextmanager
from math import prod
from pathlib import Path
from uuid import uuid4

from app.file_publish import replace_file

from app.preprocessing.runner import verify_result
from app.preprocessing.schemas import Ref
from app.preprocessing.storage import digest, file_hash, within
from app.search.catalog import entries_at, select, selection_score
from app.search.evaluation_contracts import EvaluationReceipt, EvaluationRepresentation
from .contracts import EvaluationOutput
from .records import write_readable as write_json
from .dataset import check_sources, write_tsv
from .formats import ARRAY_FORMATS, PROVENANCE_FILES, delivery_members


def choose(search_state, plan, store):
    """Project a terminal search winner; the supplied store is search/engine."""
    if search_state["status"] not in {"completed", "stopped"}:
        raise ValueError("搜索尚未正常结束，不能交付候选")
    candidates = search_state["candidates"]
    registered = entries_at(store.root.parent)
    if len({c["id"] for c in candidates}) != len(candidates):
        raise ValueError("搜索候选编号重复")
    # Validate every measured receipt before catalog.select compares its score.
    for candidate in candidates:
        if candidate["status"] == "evaluated":
            receipt = EvaluationReceipt.model_validate(candidate["receipt"])
            if receipt.status != "evaluated" or receipt.candidate_id != candidate["id"]:
                raise ValueError("候选身份或评价状态与回执不同")
            if search_state["protocol"].get("assessment") and receipt.assessment is None:
                raise ValueError("开发效用选择缺少 assessment")
        entry = registered.get(candidate["id"])
        if entry is None or (candidate.get("parameters") is not None and candidate["parameters"] != entry["parameters"]):
            raise ValueError("候选参数与冻结动态配方不同")
    winner = select([{**c, "parameters": registered[c["id"]]["parameters"]} for c in candidates])
    if winner is None or winner != search_state["selected_candidate_id"]:
        raise ValueError("选中候选与固定开发指标及平局规则不一致")
    selected = next(c for c in candidates if c["id"] == winner)
    receipt = selected["receipt"]
    candidate_root = within(store.root.parent, "candidates/" + winner)
    persisted = EvaluationReceipt.model_validate_json(
        (candidate_root / "receipt.json").read_text(encoding="utf-8")
    ).model_dump(mode="json")
    if persisted != EvaluationReceipt.model_validate(receipt).model_dump(mode="json"):
        raise ValueError("选中评价回执与搜索快照不同")
    predictions = candidate_root / "originalpredictions.tsv"
    recorded_predictions = Path(receipt["predictions_path"])
    if not recorded_predictions.is_absolute():
        recorded_predictions = within(candidate_root, receipt["predictions_path"])
    if (
        recorded_predictions.resolve() != predictions.resolve()
        or file_hash(predictions) != receipt["predictions_sha256"]
    ):
        raise ValueError("选中预测记录完整性核验失败")
    plan = plan.model_dump(mode="json") if hasattr(plan, "model_dump") else plan
    plan_ref = Ref.model_validate(receipt["plan_ref"])
    if (
        receipt["panel_hash"] != search_state["panel"]["panel_hash"]
        or selected.get("job_id") != receipt["job_id"]
        or selected.get("plan_ref") != plan_ref.model_dump()
        or digest(plan) != plan_ref.sha256
        or store.get("offline-search", plan_ref, "plan") != plan
    ):
        raise ValueError("选中结果与冻结面板或数值计划不一致")
    methods = plan["request"]["methods"]
    if len(methods) != 1:
        raise ValueError("搜索候选必须对应唯一数值方法")
    method_ref = Ref.model_validate(methods[0]).model_dump()
    method = store.get("offline-search", Ref.model_validate(method_ref), "method")
    if digest(method) != method_ref["sha256"]:
        raise ValueError("选中数值方法校验失败")
    result = store.status("offline-search", receipt["job_id"])
    required = set(plan["input_snapshot"]["collection"]["selected_record_ids"])
    if (
        result.status != "completed"
        or result.plan_ref != plan_ref
        or len(result.records) != len(required)
        or {r["record_id"] for r in result.records} != required
        or any(
            r["method_id"] != method_ref["id"]
            or r["status"] != "completed"
            or not verify_result(store.root, r["result"])
            for r in result.records
        )
    ):
        raise ValueError("选中候选未完整执行或产物校验失败")
    selection = EvaluationOutput.model_validate(
        {
            "selection_policy": "development_score",
            "quality_evaluated": True,
            "search_id": search_state["id"],
            "selected_candidate_id": winner,
            "score": selection_score(receipt),
            "evaluation_scope": "development",
            "seed": search_state["request"]["seed"],
            "candidate_summary": [
                {
                    "candidate_id": c["id"],
                    "status": c["status"],
                    "score": selection_score(c.get("receipt")),
                    "error": c.get("error"),
                }
                for c in candidates
            ],
            "selected_method_ref": method_ref,
            "reason": "按冻结协议中的完整训练效用和精确平局规则选择；分类、质量及重建各有独立含义，开发结果未经独立确认。",
            "evaluation_protocol": search_state["protocol"],
            "panel": search_state["panel"],
            "selected_receipt": receipt,
            "representation": receipt.get("representation"),
        }
    ).model_dump(mode="json")
    _representation_files(selection, store, result.records)
    if search_state["protocol"].get("assessment") or receipt.get("assessment"):
        _evaluation_evidence(selection, store)
    return selection


def report(state, folder, store):
    from .reporting import render_report

    return render_report(folder)


_ARRAY_BLOCK_BYTES = 8 * 1024 * 1024


def _utility_export_index(assessment_root, utility, prefix, artifacts):
    """Project native schema-bound references into portable archive paths.

    Never discover checkpoints with a glob: every seed/fold file must be in
    the trusted assessment inventory with the same digest as its native ref.
    """
    from app.search.utility_contracts import UtilityReceipt

    native = UtilityReceipt.model_validate(utility).model_dump(mode="json")
    root = Path(assessment_root).resolve()
    inventory = {a["path"]: a["sha256"] for a in artifacts}

    def project(value):
        if isinstance(value, dict):
            if set(value) == {"path", "sha256"}:
                path = Path(value["path"])
                path = path.resolve() if path.is_absolute() else within(root / "utility", value["path"])
                if not path.is_relative_to(root):
                    raise ValueError("效用产物引用越出 assessment 目录")
                relative = path.relative_to(root).as_posix()
                if inventory.get(relative) != value["sha256"] or file_hash(path) != value["sha256"]:
                    raise ValueError("效用产物引用与 assessment 文件清单不同")
                return {"path": prefix + relative, "sha256": value["sha256"]}
            return {k: project(v) for k, v in value.items()}
        if isinstance(value, list):
            return [project(v) for v in value]
        return value

    # Include all provenance refs, even those not directly displayed in the index.
    portable = project(native)
    return {
        "utility_version": portable["utility_version"],
        "seed_summary": portable.get("seed_summary"),
        "learners": {
            name: {key: learner[key] for key in
                   ("status", "predictions", "metadata", "folds", "seeds", "seed_summary")
                   if key in learner}
            for name, learner in portable["learners"].items()
        },
    }


def _evaluation_evidence(selection, store):
    """Resolve the original, hash-bound panel and selected trial predictions."""
    summary = selection["panel"]
    panel_path = within(store.root.parent, "panel.json")
    if file_hash(panel_path) != summary.get("file_sha256"):
        raise ValueError("冻结面板文件完整性核验失败")
    panel = json.loads(panel_path.read_text(encoding="utf-8"))
    if (
        not isinstance(panel.get("trials"), list)
        or not panel["trials"]
        or panel.get("panel_hash") != selection["selected_receipt"]["panel_hash"]
        or panel["panel_hash"]
        != digest({k: v for k, v in panel.items() if k != "panel_hash"})
        or any(
            panel.get(k) != v
            for k, v in summary.items()
            if k not in {"file_sha256", "trial_count", "eligible_count"}
        )
        or summary.get("trial_count") != len(panel["trials"])
        or summary.get("eligible_count") != sum(t["eligible"] for t in panel["trials"])
    ):
        raise ValueError("完整冻结面板与选中评价快照不同")
    receipt = selection["selected_receipt"]
    root = within(store.root.parent, "candidates/" + selection["selected_candidate_id"])
    predictions = within(root, "originalpredictions.tsv")
    recorded = Path(receipt["predictions_path"])
    if not recorded.is_absolute():
        recorded = within(root, receipt["predictions_path"])
    if (
        recorded.resolve() != predictions
        or file_hash(predictions) != receipt["predictions_sha256"]
    ):
        raise ValueError("选中预测记录完整性核验失败")
    files = [
        (panel_path, "evaluation/panel.json", summary["file_sha256"]),
        (
            predictions,
            "evaluation/originalpredictions.tsv",
            receipt["predictions_sha256"],
        ),
    ]
    if selection["evaluation_protocol"].get("assessment") and receipt.get("assessment") is None:
        raise ValueError("冻结协议要求完整 assessment，不能以 CSP 锚点评分替代")
    if receipt.get("assessment") is not None:
        from app.search.assessment import verify_assessment

        assessment_root = within(root, receipt["assessment_path"])
        assessed = verify_assessment(assessment_root, receipt["assessment"],
                                     panel_hash=panel["panel_hash"], candidate_id=selection["selected_candidate_id"])
        entry = entries_at(store.root.parent)[selection["selected_candidate_id"]]
        plan = store.get("offline-search", Ref.model_validate(receipt["plan_ref"]), "plan")
        result_path = root / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        actual = store.status("offline-search", receipt["job_id"]).model_dump(mode="json")
        if result != actual or digest(plan) != receipt["plan_ref"]["sha256"]:
            raise ValueError("assessment 执行结果或计划与交付不同")
        if not receipt.get("core_receipt_path"):
            raise ValueError("assessment 缺少选中 attempt 的核心回执路径")
        core_path = within(root, receipt["core_receipt_path"])
        core = json.loads(core_path.read_text(encoding="utf-8"))
        expected = dict(candidate_hash=digest(entry), plan_hash=digest(plan), result_hash=digest(result),
                        input_hash=panel["input_hash"], core_receipt_hash=digest(core))
        if any(assessed["bindings"][key] != value for key, value in expected.items()):
            raise ValueError("assessment 绑定与候选、计划或原始核心回执不同")
        if (core.get("predictions_sha256") != receipt["predictions_sha256"]
                or core.get("macro_ba") != assessed["core_csp_macro_ba"]):
            raise ValueError("assessment CSP 锚点或预测与核心回执不同")
        protocol_path = store.root.parent / "protocol.json"
        if json.loads(protocol_path.read_text(encoding="utf-8")) != selection["evaluation_protocol"]:
            raise ValueError("交付协议与冻结协议不同")
        utility_path = within(assessment_root, assessed["utility"]["receipt_artifact"]["path"])
        utility = json.loads(utility_path.read_text(encoding="utf-8"))
        protocol_ref = Path(utility["protocol"]["path"])
        protocol_ref = protocol_ref if protocol_ref.is_absolute() else within(assessment_root / "utility", str(protocol_ref))
        if json.loads(protocol_ref.read_text(encoding="utf-8")) != selection["evaluation_protocol"].get("utility_protocol"):
            raise ValueError("实际训练效用协议与冻结协议不同")
        files.extend((p, "evaluation/" + name, file_hash(p)) for p, name in (
            (core_path, receipt["core_receipt_path"]), (result_path, "result.json"),
            (protocol_path, "search-protocol.json"), (store.root.parent / "registry.json", "registry.json")))
        if assessed["bindings"]["probe_panel_hash"] is not None:
            probe_path = store.root.parent / "probe-panel.json"
            if digest(json.loads(probe_path.read_text(encoding="utf-8"))) != assessed["bindings"]["probe_panel_hash"]:
                raise ValueError("重建 probe 与 assessment 绑定不同")
            files.append((probe_path, "evaluation/probe-panel.json", file_hash(probe_path)))
        prefix = "evaluation/" + receipt["assessment_path"] + "/"
        _utility_export_index(assessment_root, utility, prefix, assessed["artifacts"])
        files += [
            (within(assessment_root, a["path"]), prefix + a["path"], a["sha256"])
            for a in assessed["artifacts"]
        ]
        files.append((assessment_root / "assessment.json", prefix + "assessment.json", file_hash(assessment_root / "assessment.json")))
    if receipt.get("operator_usage") is not None:
        from app.search.operator_usage import OperatorUsage, OperatorUsageReport

        usage = OperatorUsage.model_validate(receipt["operator_usage"])
        ref = usage.artifact
        path = within(root, ref.path)
        relative = path.relative_to(root).as_posix()
        if relative != ref.path:
            raise ValueError("算子适用性产物须使用规范的包内相对路径")
        raw = path.read_bytes()
        if len(raw) != ref.bytes or hashlib.sha256(raw).hexdigest() != ref.sha256:
            raise ValueError("算子适用性产物 SHA/bytes 核验失败")
        native = OperatorUsageReport.model_validate_json(raw)
        plan = store.get("offline-search", Ref.model_validate(receipt["plan_ref"]), "plan")
        result_path = root / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        actual = store.status("offline-search", receipt["job_id"]).model_dump(mode="json")
        if (native.summary != usage.summary or native.plan_sha256 != digest(plan)
                or native.result_sha256 != digest(result) or result != actual
                or digest(plan) != receipt["plan_ref"]["sha256"]):
            raise ValueError("算子适用性摘要或 plan/result 绑定与交付不同")
        destination = "evaluation/" + relative
        reserved = {"evaluation/" + name for name in (
            "receipt.json", "protocol.json", "folds.json", "candidate.json", "plan.json", "assessment-index.json")}
        if destination in reserved or destination in {name for _, name, _ in files}:
            raise ValueError("算子适用性产物与其他交付证据路径冲突")
        files.append((path, destination, ref.sha256))
    return files


def _publish_archive(archive, folder, members, manifest, validate):
    """Publish only a fully checked ZIP; keep an earlier valid file on failure."""
    temporary = archive.with_name(f".{archive.name}.{uuid4().hex}.tmp")
    expected = {entry["name"]: entry["sha256"] for entry in manifest["files"]}
    expected["manifest.json"] = file_hash(folder / "manifest.json")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for path in [*members, folder / "manifest.json"]:
                z.write(path, path.relative_to(folder).as_posix())
        with zipfile.ZipFile(temporary) as z:
            if len(z.namelist()) != len(expected) or set(z.namelist()) != set(expected):
                raise ValueError("交付压缩包文件清单不一致")
            for name, checksum in expected.items():
                # Reading also checks each member's CRC; SHA binds the manifest.
                with z.open(name) as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != checksum:
                        raise ValueError("交付压缩包内容校验失败")
        validate()
        checksum = file_hash(temporary)
        replace_file(temporary, archive)
        return checksum
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _mapped_npy(path, mode="r", **kwargs):
    import numpy as np

    value = (
        np.lib.format.open_memmap(path, mode=mode, **kwargs)
        if mode == "w+"
        else np.load(path, mmap_mode=mode, allow_pickle=False)
    )
    try:
        yield value
    finally:
        # Release handles explicitly, including on failure, for Windows retries.
        value._mmap.close()


def _array_blocks(value):
    # Bound conversion/comparison buffers; a single epoch is the minimum block.
    row_bytes = prod(value.shape[1:]) * max(value.dtype.itemsize, 4)
    step = max(1, _ARRAY_BLOCK_BYTES // max(1, row_bytes))
    for start in range(0, len(value), step):
        yield slice(start, min(start + step, len(value)))


def _write_epochs(path, sources, shape):
    import numpy as np

    dtype = np.dtype(ARRAY_FORMATS["X.npy"]["dtype"])
    with _mapped_npy(path, "w+", dtype=dtype, shape=shape) as target:
        offset = 0
        for source, source_shape in sources:
            with _mapped_npy(source) as values:
                if values.shape != source_shape:
                    raise ValueError("候选记录的训练数组形状已变化")
                for block in _array_blocks(values):
                    with np.errstate(over="ignore", invalid="ignore"):
                        converted = values[block].astype(dtype)
                    if not np.isfinite(converted).all():
                        raise ValueError("训练输出必须为有限值 Epoch 数组")
                    target[offset + block.start : offset + block.stop] = converted
            offset += source_shape[0]
        target.flush()
    # Reopen the persisted file and compare bounded blocks against each source.
    with _mapped_npy(path) as saved:
        if saved.shape != shape or saved.dtype != dtype:
            raise ValueError("X.npy does not match the training array format")
        offset = 0
        for source, source_shape in sources:
            with _mapped_npy(source) as values:
                if values.shape != source_shape:
                    raise ValueError("候选记录的训练数组形状已变化")
                for block in _array_blocks(values):
                    if not np.array_equal(
                        saved[offset + block.start : offset + block.stop],
                        values[block].astype(dtype),
                    ):
                        raise ValueError("训练数组保存后读取不一致")
            offset += source_shape[0]


def _subject_roles(groups, panel):
    subjects = set(groups)
    folds = panel.get("folds")
    if panel.get("evaluation_mode") == "group_cross_validation":
        if not folds:
            raise ValueError("交叉验证缺少折记录")
        covered = set()
        for fold in folds:
            train = set(fold["train_subjects"])
            development = set(fold["development_subjects"])
            if (
                not train
                or not development
                or train & development
                or train | development != subjects
            ):
                raise ValueError("交叉验证折与交付被试范围不一致")
            if covered & development:
                raise ValueError("交叉验证被试重复计分")
            covered.update(development)
        if covered != subjects:
            raise ValueError("交叉验证未覆盖全部交付被试")
        return {s: "train" for s in sorted(subjects)}
    train = set(panel.get("train_subjects", []))
    development = set(panel.get("development_subjects", []))
    if (
        not train
        or not development
        or train & development
        or train | development != subjects
    ):
        raise ValueError("冻结训练/开发被试与交付范围不一致")
    if folds and (
        len(folds) != 1
        or set(folds[0]["train_subjects"]) != train
        or set(folds[0]["development_subjects"]) != development
    ):
        raise ValueError("冻结 holdout 折与被试角色不一致")
    return {s: "train" if s in train else "validation" for s in sorted(subjects)}


def _representation_files(selection, store, records):
    """Resolve only checksummed files inside the selected candidate directory."""
    search_root = store.root.parent
    registered = entries_at(search_root).values()
    entry = next((c for c in registered if c["id"] == selection["selected_candidate_id"]), None)
    if entry is None:
        raise ValueError("选中策略不在冻结目录中")
    adaptation = entry["parameters"].get("adaptation", "none")
    representation = selection.get("representation")
    if representation is None:
        if adaptation != "none":
            raise ValueError("适配策略缺少表示回执，不能回退原始数组")
        return {}, [], "V", "physical EEG channels"
    if representation != selection["selected_receipt"].get("representation"):
        raise ValueError("交付表示与选中评价回执不同")
    representation = EvaluationRepresentation.model_validate(representation).model_dump(
        mode="json"
    )
    unit = representation["unit"]
    if unit not in {"V", "dimensionless"}:
        raise ValueError("交付不允许混合单位")
    if representation["policy"]["adaptation"] != adaptation or unit != (
        "V" if adaptation == "none" else "dimensionless"
    ):
        raise ValueError("表示策略或单位与选中目录候选不同")
    if (
        adaptation == "conditional_alignment"
        and representation["policy"]["alignment_threshold"]
        != entry["parameters"]["alignment_threshold"]
    ):
        raise ValueError("条件策略阈值与选中候选不同")
    semantics = {
        "V": "physical EEG channels",
        "dimensionless": "subject-specific transformed coordinates (EA or scale-only); names identify source-channel basis, not physical electrodes",
    }[unit]
    files = representation["records"]
    if set(files) != {r["record_id"] for r in records}:
        raise ValueError("适配数组未覆盖全部选中记录")
    root = within(store.root.parent, "candidates/" + selection["selected_candidate_id"])

    def resolve(name, checksum):
        candidate = Path(name)
        if candidate.is_absolute():
            try:
                name = candidate.resolve().relative_to(root).as_posix()
            except ValueError as exc:
                raise ValueError("适配产物路径越界") from exc
        path = within(root, name)
        if not path.is_file() or file_hash(path) != checksum:
            raise ValueError("适配产物完整性核验失败")
        return path

    arrays = {}
    for record in records:
        identity = record["record_id"]
        entry = files[identity]
        if adaptation == "none":
            # The evaluator deliberately reuses the verified numeric worker array
            # for no-adaptation policies. Authorize that exact record, not engine/.
            source = next(
                a for a in record["result"]["artifacts"] if a["name"] == "signal_V.npy"
            )
            path = within(store.root, source["path"])
            if (
                Path(entry["array_path"]).resolve() != path
                or entry["array_sha256"] != source["sha256"]
                or file_hash(path) != source["sha256"]
            ):
                raise ValueError("无适配表示与选中数值记录不同")
            arrays[identity] = path
        else:
            arrays[identity] = resolve(entry["array_path"], entry["array_sha256"])
    provenance = []
    subjects = representation["subjects"]
    if {entry["subject"] for entry in files.values()} != set(subjects):
        raise ValueError("适配数组与被试变换范围不同")
    units = {entry["unit"] for entry in subjects.values()}
    if units != {unit}:
        raise ValueError("适配总体单位与被试单位不一致")
    for entry in files.values():
        if entry["unit"] != subjects[entry["subject"]]["unit"]:
            raise ValueError("适配记录单位与被试单位不一致")
    for entry in subjects.values():
        if entry["unit"] == "dimensionless" and (
            not entry["transform_path"] or not entry["transform_sha256"]
        ):
            raise ValueError("无量纲适配数组缺少变换溯源")
        if entry["transform_path"]:
            path = resolve(entry["transform_path"], entry["transform_sha256"])
            provenance.append((path, path.relative_to(root).as_posix()))
    return arrays, provenance, unit, semantics


def _protect_delivery(folder, store, survey, selection, evidence):
    """Validate destinations before any mkdir, copy or array allocation."""
    folder = Path(folder).resolve()
    protected = [Path(survey["source_root"]).resolve(), store.root.resolve(),
                 within(store.root.parent, "candidates/" + selection["selected_candidate_id"])]
    if selection["selected_receipt"].get("assessment"):
        plan = store.get("offline-search", Ref.model_validate(selection["selected_receipt"]["plan_ref"]), "plan")
        protected.append(Path(plan["input_snapshot"]["collection"]["root"]).resolve())
    if any(folder.is_relative_to(p) or p.is_relative_to(folder) for p in protected):
        raise ValueError("交付目录与受保护来源或候选目录重叠")
    if any(Path(p).resolve().is_relative_to(folder) for p, _, _ in evidence):
        raise ValueError("交付目录包含受保护证据")
    for path in folder.rglob("*"):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError("交付目录含链接，可能覆盖来源")
    for record in selection["panel"]["records"]:
        if Path(record).name != record or any(c in record for c in ("/", "\\", ":")) or record in {".", ".."}:
            raise ValueError("交付记录编号不能包含路径")
    return folder


def deliver(state, folder, store):
    import numpy as np

    survey = state["outputs"]["data_survey"]
    check_sources(survey)
    selection = EvaluationOutput.model_validate(
        state["outputs"]["data_evaluation"]
    ).model_dump(mode="json")
    evidence_files = _evaluation_evidence(selection, store)
    folder = _protect_delivery(folder, store, survey, selection, evidence_files)
    if selection.get("representation") != selection["selected_receipt"].get(
        "representation"
    ):
        raise ValueError("交付表示与选中评价回执不同")
    job = store.status(state["owner"], state["outputs"]["data_preprocessing"]["job_id"])
    result_records = [
        r
        for r in job.records
        if r["method_id"] == selection["selected_method_ref"]["id"]
    ]
    receipt = selection["selected_receipt"]
    if (
        receipt.get("status") != "evaluated"
        or receipt.get("candidate_id") != selection["selected_candidate_id"]
        or receipt.get("job_id") != state["outputs"]["data_preprocessing"]["job_id"]
        or selection_score(receipt) != selection["score"]
        or receipt.get("panel_hash") != selection["panel"].get("panel_hash")
    ):
        raise ValueError("交付选择与评价回执不同")
    expected_records = set(selection["panel"].get("records", {}))
    if (
        not expected_records
        or len(result_records) != len(expected_records)
        or {r["record_id"] for r in result_records} != expected_records
    ):
        raise ValueError("交付记录与冻结面板不同")
    adapted, transforms, unit, spatial_semantics = _representation_files(
        selection, store, result_records
    )
    source_records = {r["id"]: r for r in survey["records"]}
    folder.mkdir(parents=True, exist_ok=True)
    epoch_sources, labels, groups, rows = [], [], [], []
    epoch_shape = None
    channels, sfreq = None, None
    for r in sorted(result_records, key=lambda r: r["record_id"]):
        if r["status"] != "completed" or not verify_result(store.root, r["result"]):
            raise ValueError("交付前产物完整性核验失败")
        artifacts = {
            a["name"]: store.root / a["path"] for a in r["result"]["artifacts"]
        }
        array_path = adapted.get(r["record_id"], artifacts["signal_V.npy"])
        with _mapped_npy(array_path) as values:
            if values.ndim != 3 or len(values) == 0:
                raise ValueError("训练输出必须为有限值 Epoch 数组")
            shape = values.shape
        info = r["result"]["delta"]["after"]
        if adapted and (
            list(shape)
            != selection["representation"]["records"][r["record_id"]]["shape"]
            or list(shape) != info["shape"]
            or selection["representation"]["channels"] != info["channels"]
        ):
            raise ValueError("适配数组形状与原始 Epoch 或回执不一致")
        if channels is not None and (
            channels != info["channels"]
            or sfreq != info["sfreq"]
            or epoch_shape != shape[1:]
        ):
            raise ValueError("候选记录的通道、采样率或时间长度不同")
        channels, sfreq = info["channels"], info["sfreq"]
        epoch_shape = shape[1:]
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
        if len(events) != shape[0] or [e["epoch_index"] for e in events] != list(
            range(shape[0])
        ):
            raise ValueError("事件与训练数组未逐行对齐")
        subject = source_records[r["record_id"]]["subject"]
        if (
            adapted
            and selection["representation"]["records"][r["record_id"]]["subject"]
            != subject
        ):
            raise ValueError("适配记录的被试身份与来源不同")
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
        epoch_sources.append((array_path, shape))
        provenance = folder / "provenance" / r["record_id"]
        provenance.mkdir(parents=True, exist_ok=True)
        for name in PROVENANCE_FILES:
            shutil.copy2(artifacts[name], provenance / name)
    if not epoch_sources:
        raise ValueError("没有可交付的 Epoch")
    X_shape = (len(rows), *epoch_shape)
    _write_epochs(folder / "X.npy", epoch_sources, X_shape)
    y, subjects = (
        np.asarray(labels, dtype=np.int64),
        np.asarray(groups, dtype=ARRAY_FORMATS["subjects.npy"]["dtype"]),
    )
    roles = _subject_roles(groups, selection["panel"])
    splits = np.asarray(
        [roles[s] for s in groups], dtype=ARRAY_FORMATS["split.npy"]["dtype"]
    )
    for row, split in zip(rows, splits):
        row["split"] = str(split)
    folder.mkdir(parents=True, exist_ok=True)
    for name, value in {"y": y, "subjects": subjects, "split": splits}.items():
        if value.dtype != np.dtype(
            ARRAY_FORMATS[f"{name}.npy"]["dtype"]
        ) or value.ndim != len(ARRAY_FORMATS[f"{name}.npy"]["axes"]):
            raise ValueError(f"{name}.npy does not match the training array format")
        np.save(folder / f"{name}.npy", value, allow_pickle=False)
        with _mapped_npy(folder / f"{name}.npy") as reread:
            if reread.shape != value.shape or reread.dtype != value.dtype:
                raise ValueError("训练数组保存后读取不一致")
            for block in _array_blocks(value):
                if not np.array_equal(reread[block], value[block]):
                    raise ValueError("训练数组保存后读取不一致")
    write_json(folder / "labels.json", {"0": "left_hand", "1": "right_hand"})
    write_json(
        folder / "channels.json",
        {
            "names": channels,
            "sfreq": sfreq,
            "unit": unit,
            "spatial_semantics": spatial_semantics,
            "representation": selection["representation"],
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
    for name, value in {
        "protocol": selection["evaluation_protocol"],
        "folds": selection["panel"].get("folds", []),
        "receipt": receipt,
    }.items():
        write_json(folder / "evaluation" / f"{name}.json", value)
    for source, relative, checksum in evidence_files:
        target = within(folder, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if file_hash(target) != checksum:
            raise ValueError("评价证据复制校验失败")
    representation_files = [within(folder, relative) for _, relative, _ in evidence_files
                            if relative not in {"evaluation/panel.json", "evaluation/originalpredictions.tsv"}]
    if receipt.get("assessment"):
        entry = entries_at(store.root.parent)[selection["selected_candidate_id"]]
        plan = store.get("offline-search", Ref.model_validate(receipt["plan_ref"]), "plan")
        for name, value in (("candidate.json", entry), ("plan.json", plan)):
            target = folder / "evaluation" / name
            write_json(target, value)
            representation_files.append(target)
        assessment_index = folder / "evaluation/assessment-index.json"
        prefix = "evaluation/" + receipt["assessment_path"] + "/"
        assessment_root = within(store.root.parent, "candidates/" + selection["selected_candidate_id"] + "/" + receipt["assessment_path"])
        native_utility = json.loads(within(assessment_root, receipt["assessment"]["utility"]["receipt_artifact"]["path"]).read_text(encoding="utf-8"))
        write_json(assessment_index, {
            **_utility_export_index(assessment_root, native_utility, prefix, receipt["assessment"]["artifacts"]),
            "selection_score": receipt["assessment"]["selection_score"],
            "primary_suite": receipt["assessment"]["utility"]["primary_suite"],
            "summary": prefix + "assessment.json",
            "core_receipt": "evaluation/" + receipt["core_receipt_path"],
            "utility_receipt": prefix + receipt["assessment"]["utility"]["receipt_artifact"]["path"],
            "operator_usage": "evaluation/" + receipt["operator_usage"]["artifact"]["path"]
            if receipt.get("operator_usage") is not None else None,
            "files": [{"path": relative, "sha256": checksum} for _, relative, checksum in evidence_files],
            "path_base": "archive_root",
        })
        representation_files.append(assessment_index)
    transform_map = []
    for source, relative in transforms:
        target = within(folder, "representation/" + relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if file_hash(target) != file_hash(source):
            raise ValueError("适配变换复制校验失败")
        representation_files.append(target)
        transform_map.append(
            {
                "source_ref": "selected_receipt.representation.subjects:transform_sha256",
                "archive_path": target.relative_to(folder).as_posix(),
                "sha256": file_hash(target),
            }
        )
    array_map = []
    offset = 0
    for record, (source, shape) in zip(
        sorted(result_records, key=lambda r: r["record_id"]), epoch_sources
    ):
        array_map.append(
            {
                "record_id": record["record_id"],
                "source_ref": "selected_receipt.representation.records:" + record["record_id"],
                "source_sha256": file_hash(source),
                "archive_path": "X.npy",
                "row_start": offset,
                "row_stop": offset + shape[0],
                "conversion": "float32",
                "event_index": "trial-index.tsv",
            }
        )
        offset += shape[0]
    write_json(
        folder / "evaluation/artifact-map.json",
        {"arrays": array_map, "transforms": transform_map},
    )
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

X.npy: float32，Epoch × 空间坐标 × 时间点；单位和坐标含义见 channels.json。
EA 或 scale-only 数组为无量纲变换坐标，不能解释为原电极位置的伏特测量；不应再次适配。
y.npy: int64，0=left_hand，1=right_hand。
subjects.npy / split.npy: 每行对应的被试与 train / validation / test 分组。
trial-index.tsv: 每一行到原始事件、记录和样点的映射。
同一被试只进入一个分组；标准化或模型拟合应仅使用 train。
交付保留搜索协议：分组交叉验证的被试全部标为 train，折成员见 evaluation/folds.json；
显式训练/开发划分映射为 train/validation。test 始终为空，不存在独立测试集。
assessment-v2 候选仅按 EEGNet 三种子（17、42、2026）的开发被试宏平均 BA 均值选择。
三个种子必须覆盖完整开发分母；缺失种子不产生选择分数。该分数不是平均概率的集成分数。
被试指标是各种子该被试指标的均值，n_trials 仍为原始试次数 N；预测证据共 3×N 行。
历史 assessment-v1 的选择含义以其冻结协议为准。
core CSP macro_ba 仅为锚点，质量和重建不加入总分。selection.json 保存分数与候选摘要。
反复用于选择的开发分数不是独立泛化结论；交叉验证折之间不得共享拟合的 CSP/LDA。
无标签整批适配仅使用协议允许的各被试信号，不能据此推断实时或前瞻有效。
evaluation/ 保存冻结协议、含全部原始 trial 的完整面板、折、选中评价回执，
以及 originalpredictions.tsv 核心 CSP 逐试次预测；面板和预测按原文件字节及哈希收录。
evaluation/assessment/aN/utility/ 保存 EEGNet 三种子的逐试次概率、每折 model.pt、
元数据和拟合/验证被试，以及 CSP/LDA 基准的模型与预测。完整分母与统计见 utility.json。
evaluation/assessment-index.json 提供逐模型、逐种子、逐折文件的包内相对路径和 SHA256。
EEGNet checkpoint 可使用 app.search.eegnet.predict_checkpoint(path, X) 安全加载并回放 [N,2] 概率；
回放使用 utility inputs.json 中的原始评价数组及预测行的 array_index。
assessment/ 同时保留质量与重建的完整指标、曲线或有原因的不可用状态，无任意加权总分。
representation/ 保存适配变换。
回执中的源路径保留原样用于溯源；evaluation/artifact-map.json 将源数组映射到
X.npy 的连续行区间及 trial-index.tsv，并列出变换在压缩包中的路径。
X.npy 是被评价数组的 float32 转换版本；该转换逐块保存后读取核对。
数据来源 EEGMMIDB 1.0.0，DOI 10.13026/C28G6P，ODC Attribution License v1.0。
来源与引用见 sources.json，操作与参数见 method.json，统计和限制见 report.html。
provenance/ 保存每条记录的实际执行参数、版本、事件对应和前后统计。
train_example.py: 安装 numpy、scikit-learn 后执行 python train_example.py，
仅用 train 拟合标准化与逻辑回归并检查预测可用性；实际评价模型与预测另附。

mmap 按需读取；基本切片为视图，布尔或整数数组索引会复制所选数据。
下面只选取前 32 条中的训练样本；完整训练使用 train_example.py 分块提取特征。

```python
import numpy as np
X = np.load('X.npy', mmap_mode='r', allow_pickle=False)
y = np.load('y.npy', mmap_mode='r', allow_pickle=False)
split = np.load('split.npy', mmap_mode='r', allow_pickle=False)
try:
    train_mask = split[:32] == 'train'
    X_batch, y_batch = X[:32][train_mask], y[:32][train_mask]
finally:
    for array in (X, y, split):
        array._mmap.close()
```
"""
    (folder / "README.md").write_text(readme, encoding="utf-8")
    limitations = [
        "候选已进行开发评价；没有独立确认，也未认证神经信号保真或实时有效性",
        "交付不生成独立测试集；CV 面板的全部被试均参与过候选选择",
        "全部本地 Run 已调研与接入；训练记录范围见 collection/input.json 的 selected_record_ids",
    ]
    missing_splits = sorted({"train", "validation", "test"} - set(splits))
    if missing_splits:
        limitations.append("按评价协议，以下分组为空：" + ", ".join(missing_splits))
    # Recheck adapted source hashes after streaming, before publishing the archive.
    _representation_files(selection, store, result_records)
    members = delivery_members(
        folder, [r["record_id"] for r in result_records], representation_files
    )
    names = [p.relative_to(folder).as_posix() for p in members]
    if len(names) != len(set(names)) or any(not p.resolve().is_relative_to(folder) for p in members):
        raise ValueError("交付成员重复或路径越界")
    counts = Counter(map(str, y))
    manifest = {
        "workflow_id": state["id"],
        "shape": list(X_shape),
        "classes": {label: counts[label] for label in ["0", "1"]},
        "split_counts": {
            role: int(np.sum(splits == role))
            for role in ["train", "validation", "test"]
        },
        "subject_split": roles,
        "unit": unit,
        "selection_policy": "development_score",
        "quality_evaluated": True,
        "evaluation_scope": "development",
        "independent_confirmation": False,
        "search_id": selection["search_id"],
        "selected_candidate_id": selection["selected_candidate_id"],
        "score": selection["score"],
        "representation": selection["representation"],
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

    def validate():
        check_sources(survey)
        _representation_files(selection, store, result_records)
        _evaluation_evidence(selection, store)

    archive_hash = _publish_archive(archive, folder, members, manifest, validate)
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
                "unit",
                "evaluation_scope",
                "independent_confirmation",
            ]
        },
        "sha256": archive_hash,
        "source_unchanged": True,
    }
