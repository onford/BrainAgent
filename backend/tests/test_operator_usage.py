from copy import deepcopy
import hashlib
import json

import pytest
from pydantic import ValidationError

from app.preprocessing.storage import digest
from app.search.operator_usage import (
    ASR,
    OperatorUsage,
    OperatorUsageReport,
    OperatorUsageSummary,
    aggregate_operator_usage,
)


def step(identity, unit, op, **params):
    return dict(id=identity, unit_id=unit, op=op, params=params)


def config(record, *, conditional=False):
    return dict(
        record_id=record,
        method_ref=dict(id="a" * 64, sha256="a" * 64),
        steps=[
            step("prepare", "EEG-FILTER", "filter"),
            step(
                "actual_asr_id",
                "EEG-ASR-AUTO",
                "asr_clean",
                min_clean_seconds=30.0,
                **({"on_insufficient_calibration": "identity"} if conditional else {}),
            ),
            step("cut", "EEG-EPOCH", "epoch"),
        ],
    )


def log(s, *, identity=False):
    return dict(
        step_id=s["id"],
        unit_id=s["unit_id"],
        op=s["op"],
        input_hash="1" * 64,
        output_hash=("1" if identity else "2") * 64,
        parameters=s["params"],
    )


class Store:
    def __init__(self, root, configs):
        self.root, self.plan = root, {"records": configs}
        self.result = dict(job_id="testjob", status="partial", records=[])

    def artifact(self, index, name, payload, attempt=1):
        path = f"runs/testjob/r{index:04}/a{attempt}/{name}"
        data = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload, allow_nan=False).encode()
        )
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return dict(
            name=name,
            path=path,
            bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            kind="provenance",
        )

    def row(
        self,
        index,
        status="completed",
        *,
        n=None,
        asr="applied",
        selected=True,
        version="brainagent-asrpy-complete-blocks-3",
        manifest_failure=False,
        attempt=1,
    ):
        cfg = self.plan["records"][index]
        n = len(cfg["steps"]) if n is None else n
        logs = [
            log(s, identity=asr == "not_applicable" and s["op"] == "asr_clean")
            for s in cfg["steps"][:n]
        ]
        artifacts = []
        if status == "completed" or manifest_failure:
            artifacts.append(
                self.artifact(
                    index,
                    "provenance.json",
                    dict(method_ref=cfg["method_ref"], steps=logs),
                    attempt,
                )
            )
        if any(s["op"] == "asr_clean" for s in cfg["steps"][:n]):
            identity = next(s["id"] for s in cfg["steps"] if s["op"] == "asr_clean")
            a = dict(
                algorithm_version=version,
                status=asr,
                asr_applied=asr == "applied",
                clean_seconds=40.0,
            )
            if version.endswith("-3"):
                actual = 40.0 if asr == "applied" else 12.0 if selected else None
                a.update(
                    on_insufficient_calibration="identity"
                    if cfg["steps"][1]["params"].get("on_insufficient_calibration")
                    == "identity"
                    else "error",
                    actual_calibration_seconds=actual,
                    clean_seconds=actual,
                    minimum_calibration_seconds=30.0,
                    available_record_seconds=120.0 if selected else 12.0,
                    calibration_selection_performed=selected,
                    not_applicable_code=None
                    if asr == "applied"
                    else "ASR_CALIBRATION_TOO_SHORT",
                    not_applicable_reason=None if asr == "applied" else "too short",
                )
            for name in (
                "calibration_sample_mask",
                "mixing_matrix",
                "threshold_matrix",
            ):
                if asr == "applied" or (name == "calibration_sample_mask" and selected):
                    ref = self.artifact(
                        index,
                        f"{identity}/{name}.npy",
                        b"hash-verified-array-fixture",
                        attempt,
                    )
                    artifacts.append(ref)
                    a[name] = dict(
                        file=f"{name}.npy",
                        sha256=ref["sha256"],
                        shape=[2],
                        dtype="float64",
                    )
            if asr == "not_applicable":
                a.update(model_created=False, data_action="identity")
                a.setdefault("calibration_sample_mask", None)
            artifacts.append(
                self.artifact(index, f"{identity}/artifacts.json", a, attempt)
            )
        if status in {"failed", "interrupted", "cancelled"}:
            if n < len(cfg["steps"]):
                (
                    self.root
                    / f"runs/testjob/r{index:04}/a{attempt}"
                    / cfg["steps"][n]["id"]
                ).mkdir(parents=True, exist_ok=True)
            failure = self.artifact(
                index,
                "failure.json",
                dict(
                    completed_steps=logs,
                    failure_code="ASR_CALIBRATION_TOO_SHORT",
                    failure_details={},
                    error="strict calibration failed",
                ),
                attempt,
            )
            if manifest_failure:
                artifacts.append(failure)
        row = dict(
            key=digest([cfg["method_ref"]["id"], cfg["record_id"]]),
            record_id=cfg["record_id"],
            status=status,
            attempt=attempt,
            error=None if status == "completed" else "failure",
            result={"artifacts": artifacts}
            if status == "completed" or manifest_failure
            else None,
        )
        self.result["records"].append(row)
        return row

    def run(self):
        self.result["plan_ref"] = dict(id=digest(self.plan), sha256=digest(self.plan))
        return aggregate_operator_usage(self.plan, self.result, self.root)

    def replace_json(self, row, name, change):
        ref = next(a for a in row["result"]["artifacts"] if a["name"] == name)
        path = self.root / ref["path"]
        value = json.loads(path.read_bytes())
        change(value)
        data = json.dumps(value).encode()
        path.write_bytes(data)
        ref.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def test_fixed_denominator_applied_identity_failed_not_reached_and_not_configured(
    tmp_path,
):
    configs = [config(str(i), conditional=i in {1, 2}) for i in range(7)]
    configs[-1]["steps"] = [configs[-1]["steps"][0]]
    store = Store(tmp_path, configs)
    store.row(0, version="brainagent-asrpy-complete-blocks-2")
    store.row(1, asr="not_applicable", selected=True)
    store.row(2, asr="not_applicable", selected=False)
    store.row(3, status="failed", n=1)
    store.row(4, status="failed", n=0)
    store.row(6)
    report = store.run()
    summary = report["summary"]["operators"][ASR]
    assert summary["denominator"] == 7 and summary["configured_records"] == 6
    assert summary["counts"] == dict(
        applied=1, not_applicable=3, failed=1, not_reached=2
    )
    assert summary["reason_counts"]["not_applicable"] == {
        "ASR_CALIBRATION_TOO_SHORT": 2,
        "OPERATOR_NOT_IN_RECIPE": 1,
    }
    assert summary["reason_counts"]["failed"] == {"ASR_CALIBRATION_TOO_SHORT": 1}
    assert report["summary"]["record_execution_counts"] == dict(
        completed=4, failed=2, missing=1
    )
    assert (
        report["records"][2]["operators"][ASR]["steps"][0]["asr"][
            "actual_calibration_seconds"
        ]
        is None
    )
    assert OperatorUsageReport.model_validate_json(json.dumps(report, allow_nan=False))


def test_completed_record_is_not_proof_of_asr_application(tmp_path):
    store = Store(tmp_path, [config("r")])
    row = store.row(0)
    row["result"]["artifacts"] = [
        a
        for a in row["result"]["artifacts"]
        if a["name"] != "actual_asr_id/artifacts.json"
    ]
    usage = store.run()["records"][0]["operators"][ASR]
    assert usage["status"] == "failed"
    assert usage["steps"][0]["evidence_issue"] is True


@pytest.mark.parametrize(
    "target",
    [
        "provenance.json",
        "actual_asr_id/artifacts.json",
        "actual_asr_id/mixing_matrix.npy",
    ],
)
def test_tampered_consumed_artifacts_cannot_certify_application(tmp_path, target):
    store = Store(tmp_path, [config("r")])
    row = store.row(0)
    ref = next(a for a in row["result"]["artifacts"] if a["name"] == target)
    path = tmp_path / ref["path"]
    raw = path.read_bytes()
    path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    report = store.run()
    assert report["summary"]["operators"][ASR]["counts"]["failed"] == 1
    assert "ARTIFACT_HASH_MISMATCH" in report["records"][0]["evidence_issues"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda a: a.update(asr_applied=True),
        lambda a: a.update(not_applicable_code="ASR_FULL_RANK_REQUIRED"),
        lambda a: a.update(model_created=True),
        lambda a: a.update(actual_calibration_seconds=40.0, clean_seconds=40.0),
        lambda a: a.update(on_insufficient_calibration="error"),
        lambda a: a.update(mixing_matrix={}),
        lambda a: a.pop("calibration_selection_performed"),
    ],
)
def test_conditional_rule_does_not_hide_other_failures_or_invalid_flags(
    tmp_path, mutation
):
    store = Store(tmp_path, [config("r", conditional=True)])
    row = store.row(0, asr="not_applicable")
    store.replace_json(row, "actual_asr_id/artifacts.json", mutation)
    assert store.run()["records"][0]["operators"][ASR]["status"] == "failed"


def test_identity_must_preserve_the_exact_step_input_hash(tmp_path):
    store = Store(tmp_path, [config("r", conditional=True)])
    row = store.row(0, asr="not_applicable")
    store.replace_json(
        row, "provenance.json", lambda p: p["steps"][1].update(output_hash="3" * 64)
    )
    assert store.run()["records"][0]["operators"][ASR]["status"] == "failed"


def test_failure_after_asr_preserves_application_when_step_artifacts_are_verified(
    tmp_path,
):
    store = Store(tmp_path, [config("r")])
    store.row(0, status="failed", n=2, manifest_failure=True)
    report = store.run()
    assert report["records"][0]["operators"][ASR]["status"] == "applied"
    assert report["records"][0]["operators"]["EEG-EPOCH/epoch"]["status"] == "failed"


def test_failure_snapshot_without_manifest_does_not_fake_applied_asr(tmp_path):
    store = Store(tmp_path, [config("r")])
    store.row(0, status="failed", n=2)
    report = store.run()
    assert report["records"][0]["operators"][ASR]["status"] == "failed"
    assert report["records"][0]["operators"]["EEG-FILTER/filter"]["status"] == "applied"
    assert (
        report["records"][0]["evidence"][0]["verification"]
        == "current_attempt_snapshot"
    )


def test_failure_before_input_loading_does_not_blame_first_operator(tmp_path):
    store = Store(tmp_path, [config("r")])
    store.row(0, status="failed", n=0)
    (tmp_path / "runs/testjob/r0000/a1/prepare").rmdir()
    report = store.run()
    assert all(
        op["status"] == "not_reached"
        for op in report["records"][0]["operators"].values()
    )
    assert report["records"][0]["execution_failure_code"] == "ASR_CALIBRATION_TOO_SHORT"


def test_scoped_fit_replays_do_not_inflate_record_or_step_counts(tmp_path):
    store = Store(tmp_path, [config("r")])
    row = store.row(0)
    store.replace_json(
        row,
        "provenance.json",
        lambda p: p["steps"].insert(
            1,
            dict(
                step_id="prepare",
                branch="fit",
                input_hash="1" * 64,
                output_hash="2" * 64,
            ),
        ),
    )
    report = store.run()
    assert report["summary"]["operators"][ASR]["counts"]["applied"] == 1
    assert report["summary"]["operators"]["EEG-FILTER/filter"]["counts"]["applied"] == 1


def test_retry_never_reads_old_attempt_failure_or_old_step_artifacts(tmp_path):
    store = Store(tmp_path, [config("r")])
    row = store.row(0, status="failed", n=1)
    row["attempt"] = 2
    report = store.run()
    assert report["records"][0]["operators"][ASR]["status"] == "not_reached"
    assert report["records"][0]["evidence"] == []
    row["status"] = "completed"
    row["result"] = {"artifacts": [store.artifact(0, "provenance.json", {})]}
    assert "ARTIFACT_ATTEMPT_MISMATCH" in store.run()["records"][0]["evidence_issues"]


def test_completed_steps_must_match_exact_planned_prefix(tmp_path):
    store = Store(tmp_path, [config("r")])
    row = store.row(0)
    store.replace_json(
        row, "provenance.json", lambda p: p["steps"][1].update(step_id="asr")
    )
    assert "INVALID_COMPLETED_STEPS" in store.run()["records"][0]["evidence_issues"]


def test_duplicate_instances_count_records_once_and_keep_step_detail(tmp_path):
    cfg = config("r")
    cfg["steps"] = [
        step("a", "EEG-FILTER", "filter"),
        step("b", "EEG-FILTER", "filter"),
    ]
    store = Store(tmp_path, [cfg])
    store.row(0)
    report = store.run()
    assert report["summary"]["operators"]["EEG-FILTER/filter"]["counts"]["applied"] == 1
    assert len(report["records"][0]["operators"]["EEG-FILTER/filter"]["steps"]) == 2


@pytest.mark.parametrize("status", ["queued", "running", "interrupted", "cancelled"])
def test_unfinished_records_do_not_invent_failed_or_applied_operators(tmp_path, status):
    store = Store(tmp_path, [config("r")])
    row = dict(key=digest(["a" * 64, "r"]), status=status, attempt=0, result=None)
    store.result["records"] = [row]
    assert store.run()["summary"]["operators"][ASR]["counts"]["not_reached"] == 1


def test_schema_strictness_receipt_shape_and_read_only_inputs(tmp_path):
    store = Store(tmp_path, [config("r")])
    store.row(0)
    report = store.run()
    before = deepcopy((store.plan, store.result))
    files = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert store.run() == report
    assert before == (store.plan, store.result)
    assert files == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert OperatorUsage(
        summary=report["summary"],
        artifact=dict(path="candidate/operator-usage.json", sha256="b" * 64, bytes=100),
    )
    for bad in (True, "1", -1):
        with pytest.raises(ValidationError):
            OperatorUsageSummary.model_validate(
                {**report["summary"], "record_count": bad}
            )
    with pytest.raises(ValidationError):
        OperatorUsageSummary.model_validate({**report["summary"], "extra": 1})


def test_foreign_duplicate_records_and_wrong_plan_hash_are_rejected(tmp_path):
    store = Store(tmp_path, [config("r")])
    row = store.row(0)
    store.result["records"].append(deepcopy(row))
    with pytest.raises(ValueError, match="duplicate"):
        store.run()
    store.result["records"] = [row]
    store.result["plan_ref"] = dict(id="f" * 64, sha256="f" * 64)
    with pytest.raises(ValueError, match="another plan"):
        aggregate_operator_usage(store.plan, store.result, tmp_path)


def test_artifact_path_escape_bytes_mismatch_and_duplicate_names(tmp_path):
    for mode in ("path", "bytes", "duplicate"):
        root = tmp_path / mode
        store = Store(root, [config("r")])
        row = store.row(0)
        ref = next(
            a
            for a in row["result"]["artifacts"]
            if a["name"] == "actual_asr_id/artifacts.json"
        )
        if mode == "path":
            ref["path"] = "../outside.json"
        elif mode == "bytes":
            ref["bytes"] += 1
        else:
            row["result"]["artifacts"].append(deepcopy(ref))
        assert store.run()["summary"]["operators"][ASR]["counts"]["failed"] == 1


def test_record_path_cannot_escape_attempt_using_parent_segments(tmp_path):
    store = Store(tmp_path, [config("r")])
    row = store.row(0)
    ref = row["result"]["artifacts"][0]
    ref["path"] = "runs/testjob/r0000/a1/../../r0001/a1/provenance.json"
    assert "ARTIFACT_ATTEMPT_MISMATCH" in store.run()["records"][0]["evidence_issues"]


def test_summary_reason_counts_and_arbitrary_safe_receipt_paths(tmp_path):
    store = Store(tmp_path, [config("r")])
    store.row(0)
    report = store.run()
    assert OperatorUsage(
        summary=report["summary"],
        artifact=dict(path="operator-usage/u17.json", sha256="b" * 64, bytes=10),
    )
    with pytest.raises(ValidationError):
        OperatorUsage(
            summary=report["summary"],
            artifact=dict(path="../u17.json", sha256="b" * 64, bytes=10),
        )
    report["summary"]["operators"][ASR]["reason_counts"]["applied"] = {}
    with pytest.raises(ValidationError, match="reason counts"):
        OperatorUsageReport.model_validate(report)


def test_parallel_worker_sibling_process_log_is_not_operator_evidence(tmp_path):
    store = Store(tmp_path, [config("r", conditional=True)])
    row = store.row(0, asr="not_applicable")
    row["result"]["artifacts"].append(
        dict(
            name="a1-process.log",
            path="runs/testjob/r0000/a1-process.log",
            bytes=0,
            sha256=hashlib.sha256(b"").hexdigest(),
            kind="execution_log",
        )
    )
    report = store.run()
    assert report["summary"]["evidence_issue_records"] == 0
    assert report["records"][0]["operators"][ASR]["status"] == "not_applicable"


def test_serialized_float32_arrays_use_manifest_hashes_not_names_or_dtype_assumptions(
    tmp_path,
):
    import io
    import numpy as np

    store = Store(tmp_path, [config("r")])
    row = store.row(0)
    refs = {}
    for i, name in enumerate(
        ("calibration_sample_mask", "mixing_matrix", "threshold_matrix")
    ):
        array = np.ones((1, 160), dtype=bool) if i == 0 else np.eye(4, dtype=np.float32)
        buffer = io.BytesIO()
        np.save(buffer, array, allow_pickle=False)
        filename = f"artifacts_{i + 7}.npy"
        artifact = store.artifact(0, f"actual_asr_id/{filename}", buffer.getvalue())
        row["result"]["artifacts"].append(artifact)
        refs[name] = dict(
            file=filename,
            sha256=artifact["sha256"],
            shape=list(array.shape),
            dtype=str(array.dtype),
        )
    store.replace_json(
        row, "actual_asr_id/artifacts.json", lambda value: value.update(refs)
    )
    report = store.run()
    assert report["summary"]["evidence_issue_records"] == 0
    assert report["summary"]["operators"][ASR]["counts"]["applied"] == 1
    target = next(
        a for a in row["result"]["artifacts"] if a["name"].endswith("artifacts_8.npy")
    )
    path = tmp_path / target["path"]
    raw = path.read_bytes()
    path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    assert "ARTIFACT_HASH_MISMATCH" in store.run()["records"][0]["evidence_issues"]
