"""Read-only, evidence-based operator accounting. No evaluator/runner imports.

Applied means an invocation completed, not that its output changed or improved.
ASR additionally requires its own hash-verified artifacts.json application flags.
Current failed attempts may have no manifest: their failure.json is read as an
explicitly unanchored snapshot, never as hash-verified proof of ASR application.
"""

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.preprocessing.storage import digest, within

VERSION = "operator-usage-v1"
STATES = ("applied", "not_applicable", "failed", "not_reached")
Status = Literal["applied", "not_applicable", "failed", "not_reached"]
Count = Annotated[int, Field(ge=0)]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Seconds = Annotated[float, Field(ge=0)]
ASR = "EEG-ASR-AUTO/asr_clean"


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)


class UsageArtifact(StrictModel):
    path: str = Field(min_length=1)
    sha256: Hash
    bytes: Count

    @field_validator("path")
    @classmethod
    def relative_path(cls, value):
        path = PureWindowsPath(value)
        if path.drive or path.root or ".." in path.parts or value in {".", ""}:
            raise ValueError("artifact path must be a safe relative file path")
        return value


class UsageEvidence(UsageArtifact):
    verification: Literal["manifest_sha256", "current_attempt_snapshot"]


class UsageCounts(StrictModel):
    applied: Count = 0
    not_applicable: Count = 0
    failed: Count = 0
    not_reached: Count = 0


class OperatorSummary(StrictModel):
    unit_id: str
    op: str
    denominator: Count
    configured_records: Count
    counts: UsageCounts
    reason_counts: dict[Status, dict[str, Count]]

    @model_validator(mode="after")
    def totals(self):
        if sum(self.counts.model_dump().values()) != self.denominator:
            raise ValueError("operator counts must retain the record denominator")
        if self.configured_records > self.denominator or set(self.reason_counts) != set(
            STATES
        ):
            raise ValueError("invalid operator coverage")
        for state, reasons in self.reason_counts.items():
            if any(n > getattr(self.counts, state) for n in reasons.values()):
                raise ValueError("reason counts count records, not step instances")
        return self


class OperatorUsageSummary(StrictModel):
    schema_version: Literal["operator-usage-v1"] = VERSION
    record_count: Count
    record_execution_counts: dict[str, Count]
    evidence_issue_records: Count
    operators: dict[str, OperatorSummary]

    @model_validator(mode="after")
    def totals(self):
        if sum(self.record_execution_counts.values()) != self.record_count:
            raise ValueError("record execution counts do not match plan")
        if self.evidence_issue_records > self.record_count:
            raise ValueError("invalid evidence issue count")
        for key, row in self.operators.items():
            if key != f"{row.unit_id}/{row.op}" or row.denominator != self.record_count:
                raise ValueError("operator identity/denominator differs")
        return self


class OperatorUsage(StrictModel):
    """Compact receipt field. The caller writes the report and supplies its ref."""

    summary: OperatorUsageSummary
    artifact: UsageArtifact


class AsrApplication(StrictModel):
    algorithm_version: str | None
    asr_applied: bool
    on_insufficient_calibration: Literal["error", "identity"]
    actual_calibration_seconds: Seconds | None
    minimum_calibration_seconds: Seconds | None
    calibration_selection_performed: bool | None
    available_record_seconds: Seconds | None
    not_applicable_code: str | None
    not_applicable_reason: str | None


class StepUsage(StrictModel):
    step_id: str
    unit_id: str
    op: str
    status: Status
    reason_code: str
    reason: str | None = None
    evidence_issue: bool = False
    evidence: list[UsageEvidence] = Field(default_factory=list)
    asr: AsrApplication | None = None


class RecordOperatorUsage(StrictModel):
    status: Status
    reason_codes: list[str]
    steps: list[StepUsage]


class RecordUsage(StrictModel):
    key: str
    record_id: str
    method_id: str
    attempt: Count
    execution_status: str
    execution_error: str | None
    execution_failure_code: str | None
    evidence_issues: list[str]
    evidence: list[UsageEvidence]
    operators: dict[str, RecordOperatorUsage]


class OperatorUsageReport(StrictModel):
    schema_version: Literal["operator-usage-v1"] = VERSION
    plan_sha256: Hash
    result_sha256: Hash
    summary: OperatorUsageSummary
    records: list[RecordUsage]

    @model_validator(mode="after")
    def consistent(self):
        if len(self.records) != self.summary.record_count:
            raise ValueError("report record count differs")
        if len({r.key for r in self.records}) != len(self.records):
            raise ValueError("duplicate report records")
        if any(set(r.operators) != set(self.summary.operators) for r in self.records):
            raise ValueError("missing operator denominator row")
        for key, operator in self.summary.operators.items():
            actual = Counter(r.operators[key].status for r in self.records)
            if any(actual[s] != getattr(operator.counts, s) for s in STATES):
                raise ValueError("summary differs from record statuses")
            if operator.configured_records != sum(
                bool(r.operators[key].steps) for r in self.records
            ):
                raise ValueError("configured denominator differs from records")
            for status in STATES:
                reasons = Counter()
                for record in self.records:
                    row = record.operators[key]
                    if row.status == status:
                        reasons.update(set(row.reason_codes))
                if dict(reasons) != operator.reason_counts[status]:
                    raise ValueError("reason counts differ from record evidence")
        if (
            dict(Counter(r.execution_status for r in self.records))
            != self.summary.record_execution_counts
        ):
            raise ValueError("record execution summary differs")
        if (
            sum(bool(r.evidence_issues) for r in self.records)
            != self.summary.evidence_issue_records
        ):
            raise ValueError("evidence issue summary differs")
        return self


class EvidenceError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _require(value, code, message):
    if not value:
        raise EvidenceError(code, message)


def _plain(value):
    return (
        value.model_dump(mode="json")
        if isinstance(value, BaseModel)
        else deepcopy(value)
    )


def _read(root, ref, *, anchored=True):
    """Read a confined, stable snapshot; check manifest length and SHA before JSON."""
    try:
        path = within(root, ref["path"])
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if anchored:
            _require(
                type(ref.get("bytes")) is int and len(raw) == ref["bytes"],
                "ARTIFACT_BYTES_MISMATCH",
                ref["path"],
            )
            _require(sha == ref.get("sha256"), "ARTIFACT_HASH_MISMATCH", ref["path"])
        _require(path.read_bytes() == raw, "ARTIFACT_CHANGED_DURING_READ", ref["path"])
        value = json.loads(raw)
        digest(value)  # Strict JSON: reject NaN/Infinity in any nested field.
        evidence = dict(
            path=ref["path"],
            sha256=sha,
            bytes=len(raw),
            verification="manifest_sha256" if anchored else "current_attempt_snapshot",
        )
        return value, evidence
    except EvidenceError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise EvidenceError("ARTIFACT_UNREADABLE", str(exc)) from exc


def _artifact(root, artifacts, name):
    matches = [a for a in artifacts if a.get("name") == name]
    _require(len(matches) == 1, "ARTIFACT_MANIFEST_MISSING_OR_DUPLICATE", name)
    ref = matches[0]
    _require(ref.get("kind") == "provenance", "ARTIFACT_KIND_MISMATCH", name)
    value, evidence = _read(root, ref)
    return value, evidence


def _array_ref(root, artifacts, step_id, value):
    _require(
        isinstance(value, dict) and isinstance(value.get("file"), str),
        "ASR_INVALID_EVIDENCE",
        "missing ASR array reference",
    )
    name = value["file"]
    _require(
        Path(name).name == name and "/" not in name and "\\" not in name,
        "ASR_INVALID_EVIDENCE",
        "array reference must stay in its step directory",
    )
    matches = [a for a in artifacts if a.get("name") == f"{step_id}/{name}"]
    _require(
        len(matches) == 1 and matches[0].get("sha256") == value.get("sha256"),
        "ASR_ARRAY_MANIFEST_MISMATCH",
        name,
    )
    ref = matches[0]
    try:
        path = within(root, ref["path"])
        _require(
            type(ref.get("bytes")) is int and path.stat().st_size == ref["bytes"],
            "ARTIFACT_BYTES_MISMATCH",
            name,
        )
        with path.open("rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        _require(sha == ref["sha256"], "ARTIFACT_HASH_MISMATCH", name)
    except OSError as exc:
        raise EvidenceError("ARTIFACT_UNREADABLE", str(exc)) from exc
    return dict(
        path=ref["path"], sha256=sha, bytes=ref["bytes"], verification="manifest_sha256"
    )


def _asr(root, artifacts, log, step):
    # The step ID comes from the checked provenance log, never an operator alias.
    value, ref = _artifact(root, artifacts, f"{log['step_id']}/artifacts.json")
    evidence = [ref]
    _require(
        isinstance(value, dict),
        "ASR_INVALID_EVIDENCE",
        "ASR artifacts must be an object",
    )
    state, applied = value.get("status"), value.get("asr_applied")
    rule = step.get("params", {}).get("on_insufficient_calibration", "error")
    _require(
        rule in {"error", "identity"},
        "ASR_INVALID_EVIDENCE",
        "unknown calibration rule",
    )
    _require(
        value.get("on_insufficient_calibration", rule) == rule,
        "ASR_POLICY_MISMATCH",
        "ASR policy differs from planned step",
    )
    _require(
        (state == "applied" and applied is True)
        or (state == "not_applicable" and applied is False),
        "ASR_INVALID_EVIDENCE",
        "ASR status and boolean must agree",
    )
    conditional = value.get("algorithm_version") == "brainagent-asrpy-complete-blocks-3"
    if conditional or rule == "identity" or state == "not_applicable":
        required = {
            "algorithm_version",
            "on_insufficient_calibration",
            "status",
            "asr_applied",
            "actual_calibration_seconds",
            "minimum_calibration_seconds",
            "clean_seconds",
            "calibration_selection_performed",
            "available_record_seconds",
            "not_applicable_code",
            "not_applicable_reason",
        }
        _require(
            required <= value.keys(),
            "ASR_INVALID_EVIDENCE",
            "conditional ASR fields missing",
        )
        _require(
            conditional,
            "ASR_INVALID_EVIDENCE",
            "conditional contract requires complete-blocks-3",
        )
        selected = value["calibration_selection_performed"]
        actual = value["actual_calibration_seconds"]
        _require(
            type(selected) is bool
            and actual == value["clean_seconds"]
            and ((actual is not None) == selected),
            "ASR_INVALID_EVIDENCE",
            "inconsistent calibration selection",
        )
    else:
        actual = value.get(
            "clean_seconds"
        )  # Strict v4 run's complete-blocks-2 evidence.
        selected = None
    if state == "not_applicable":
        _require(
            rule == "identity"
            and value.get("not_applicable_code") == "ASR_CALIBRATION_TOO_SHORT"
            and value.get("model_created") is False
            and value.get("data_action") == "identity"
            and "mixing_matrix" not in value
            and "threshold_matrix" not in value
            and log.get("input_hash") == log.get("output_hash"),
            "ASR_INVALID_EVIDENCE",
            "identity is allowed only for insufficient calibration",
        )
        _require(
            (actual is not None and actual < value["minimum_calibration_seconds"])
            or (
                actual is None
                and value["available_record_seconds"]
                < value["minimum_calibration_seconds"]
            ),
            "ASR_INVALID_EVIDENCE",
            "insufficient calibration reason contradicts duration",
        )
        code = "ASR_CALIBRATION_TOO_SHORT"
        if selected:
            evidence.append(
                _array_ref(
                    root,
                    artifacts,
                    log["step_id"],
                    value.get("calibration_sample_mask"),
                )
            )
        else:
            _require(
                value.get("calibration_sample_mask") is None,
                "ASR_INVALID_EVIDENCE",
                "unselected calibration cannot have a mask",
            )
    else:
        _require(
            value.get("not_applicable_code") is None,
            "ASR_INVALID_EVIDENCE",
            "applied ASR has N/A code",
        )
        _require(
            all(
                isinstance(value.get(k), dict)
                and value[k].get("file")
                and value[k].get("sha256")
                for k in (
                    "calibration_sample_mask",
                    "mixing_matrix",
                    "threshold_matrix",
                )
            ),
            "ASR_INVALID_EVIDENCE",
            "applied ASR lacks model/calibration artifact references",
        )
        code = "ASR_APPLIED"
        if conditional:
            _require(
                selected is True and actual >= value["minimum_calibration_seconds"],
                "ASR_INVALID_EVIDENCE",
                "applied ASR has insufficient calibration",
            )
        for name in ("calibration_sample_mask", "mixing_matrix", "threshold_matrix"):
            evidence.append(_array_ref(root, artifacts, log["step_id"], value[name]))
    meta = AsrApplication(
        algorithm_version=value.get("algorithm_version"),
        asr_applied=applied,
        on_insufficient_calibration=rule,
        actual_calibration_seconds=actual,
        minimum_calibration_seconds=value.get(
            "minimum_calibration_seconds",
            step.get("params", {}).get("min_clean_seconds"),
        ),
        calibration_selection_performed=selected,
        available_record_seconds=value.get("available_record_seconds"),
        not_applicable_code=value.get("not_applicable_code"),
        not_applicable_reason=value.get("not_applicable_reason"),
    )
    return state, code, meta.model_dump(mode="json"), evidence


def _record(config, row, index, result, root, operator_ids):
    steps = config["steps"]
    key = digest([config["method_ref"]["id"], config["record_id"]])
    row = row or dict(status="missing", attempt=0, result=None)
    status, attempt = row["status"], row.get("attempt", 0)
    _require(type(attempt) is int and attempt >= 0, "INVALID_ATTEMPT", key)
    report = dict(
        key=key,
        record_id=config["record_id"],
        method_id=config["method_ref"]["id"],
        attempt=attempt,
        execution_status=status,
        execution_error=row.get("error"),
        execution_failure_code=None,
        evidence_issues=[],
        evidence=[],
        operators={},
    )
    artifacts = (row.get("result") or {}).get("artifacts", [])
    logs, failure, evidence_error = [], None, None
    try:
        prefix = f"runs/{result['job_id']}/r{index:04}/a{attempt}/"
        # Parallel workers also publish sibling aN-process.log artifacts. Those
        # logs are not operator evidence and need not be inside the data attempt.
        # Scope every manifest entry that this reader can consume, including
        # step arrays, without interpreting unrelated execution/delivery files.
        step_prefixes = tuple(s["id"] + "/" for s in steps)
        consumed = [
            a
            for a in artifacts
            if a.get("name") in {"provenance.json", "failure.json"}
            or (isinstance(a.get("name"), str) and a["name"].startswith(step_prefixes))
        ]
        _require(
            all(
                isinstance(a.get("path"), str)
                and a["path"].startswith(prefix)
                and within(root, a["path"]).is_relative_to(within(root, prefix))
                for a in consumed
            ),
            "ARTIFACT_ATTEMPT_MISMATCH",
            "artifact belongs to another record/attempt",
        )
        if any(a.get("name") == "provenance.json" for a in artifacts):
            provenance, ref = _artifact(root, artifacts, "provenance.json")
            report["evidence"].append(ref)
            _require(
                provenance.get("method_ref") == config["method_ref"],
                "PROVENANCE_BINDING_MISMATCH",
                "wrong method_ref",
            )
            for field in ("engine_sha256", "environment"):
                if field in result.get("_plan_bindings", {}):
                    _require(
                        provenance.get(field) == result["_plan_bindings"][field],
                        "PROVENANCE_BINDING_MISMATCH",
                        f"wrong {field}",
                    )
            logs = provenance["steps"]
        if any(a.get("name") == "failure.json" for a in artifacts):
            failure, ref = _artifact(root, artifacts, "failure.json")
            report["evidence"].append(ref)
        elif status in {"failed", "cancelled", "interrupted"} and attempt > 0:
            # Never scan old attempts or a guessed 'latest' directory.
            relative = f"runs/{result['job_id']}/r{index:04}/a{attempt}/failure.json"
            if within(root, relative).exists():
                failure, ref = _read(root, {"path": relative}, anchored=False)
                report["evidence"].append(ref)
                report["evidence_issues"].append(
                    "FAILURE_SNAPSHOT_NOT_MANIFEST_ANCHORED"
                )
        if failure is not None:
            _require(
                isinstance(failure.get("failure_code"), str)
                and bool(failure["failure_code"])
                and isinstance(failure.get("error"), str),
                "INVALID_FAILURE_EVIDENCE",
                "failure code/error must be strings",
            )
            report["execution_failure_code"] = failure["failure_code"]
            completed = failure["completed_steps"]
            _require(
                not logs or logs == completed,
                "PROVENANCE_FAILURE_CONFLICT",
                "completed steps disagree",
            )
            logs = completed
        _require(
            isinstance(logs, list), "INVALID_COMPLETED_STEPS", "logs must be a list"
        )
        _require(
            all(
                isinstance(item, dict)
                and item.get("branch", "main") in {"main", "fit"}
                and item.get("step_id") in {s["id"] for s in steps}
                for item in logs
            ),
            "INVALID_COMPLETED_STEPS",
            "unknown execution branch or step",
        )
        # Scoped model fitting may replay ancestors; those are not extra planned
        # operator instances and must not disturb the main execution prefix.
        logs = [item for item in logs if item.get("branch", "main") == "main"]
        _require(
            isinstance(logs, list) and len(logs) <= len(steps),
            "INVALID_COMPLETED_STEPS",
            "invalid completed prefix",
        )
        for step, log in zip(steps, logs):
            _require(
                all(
                    log.get(a) == step[b]
                    for a, b in (
                        ("step_id", "id"),
                        ("unit_id", "unit_id"),
                        ("op", "op"),
                    )
                ),
                "INVALID_COMPLETED_STEPS",
                "step IDs/operations do not match planned prefix",
            )
            _require(
                all(
                    isinstance(log.get(h), str)
                    and re.fullmatch(r"[a-f0-9]{64}", log[h])
                    for h in ("input_hash", "output_hash")
                ),
                "INVALID_COMPLETED_STEPS",
                "missing step input/output hashes",
            )
        if status == "completed":
            _require(
                len(logs) == len(steps),
                "COMPLETED_PROVENANCE_MISSING",
                "record completion is not step evidence",
            )
    except (EvidenceError, KeyError, TypeError, ValueError) as exc:
        evidence_error = getattr(exc, "code", "INVALID_EXECUTION_EVIDENCE")
        report["evidence_issues"].append(evidence_error)
        logs = []  # A broken provenance prefix cannot certify any operation.
    details = []
    for i, step in enumerate(steps):
        detail = dict(
            step_id=step["id"],
            unit_id=step["unit_id"],
            op=step["op"],
            status="not_reached",
            reason_code="UPSTREAM_NOT_COMPLETED",
            evidence=[],
        )
        if evidence_error:
            detail.update(
                status="failed", reason_code=evidence_error, evidence_issue=True
            )
        elif i < len(logs):
            detail.update(
                status="applied",
                reason_code="STEP_COMPLETED",
                evidence=report["evidence"][:1],
            )
            if f"{step['unit_id']}/{step['op']}" == ASR:
                try:
                    state, code, meta, refs = _asr(root, artifacts, logs[i], step)
                    detail.update(
                        status=state,
                        reason_code=code,
                        asr=meta,
                        evidence=detail["evidence"] + refs,
                    )
                except (EvidenceError, ValueError, KeyError, TypeError) as exc:
                    code = getattr(exc, "code", "ASR_INVALID_EVIDENCE")
                    detail.update(
                        status="failed",
                        reason_code=code,
                        reason=str(exc),
                        evidence_issue=True,
                    )
                    report["evidence_issues"].append(code)
        elif (
            failure is not None
            and i == len(logs)
            and status == "failed"
            and within(root, prefix + step["id"]).is_dir()
        ):
            detail.update(
                status="failed",
                reason_code=failure.get("failure_code") or "EXECUTION_FAILURE",
                reason=failure.get("error"),
                evidence=report["evidence"],
            )
        elif i == len(logs):
            code = {
                "queued": "RECORD_QUEUED",
                "missing": "RECORD_RESULT_MISSING",
                "running": "EXECUTION_PENDING",
                "cancelled": "EXECUTION_CANCELLED",
                "interrupted": "EXECUTION_INTERRUPTED",
                "failed": "FAILURE_LOCATION_UNAVAILABLE",
            }.get(status, "UPSTREAM_NOT_COMPLETED")
            detail.update(reason_code=code)
            if status == "failed":
                # No failure boundary: do not arbitrarily blame the first operator.
                report["evidence_issues"].append(code)
        details.append(detail)
    for identity in operator_ids:
        matching = [d for d in details if f"{d['unit_id']}/{d['op']}" == identity]
        if not matching:
            report["operators"][identity] = dict(
                status="not_applicable",
                reason_codes=["OPERATOR_NOT_IN_RECIPE"],
                steps=[],
            )
            continue
        state = next(
            s
            for s in ("failed", "not_reached", "applied", "not_applicable")
            if any(d["status"] == s for d in matching)
        )
        report["operators"][identity] = dict(
            status=state,
            reason_codes=sorted(
                {d["reason_code"] for d in matching if d["status"] == state}
            ),
            steps=matching,
        )
    report["evidence_issues"] = sorted(set(report["evidence_issues"]))
    return report


def aggregate_operator_usage(plan, result, store_root):
    """Return OperatorUsageReport JSON; never write files or invoke numeric code.

    Inputs accept models or their JSON dictionaries. Plan record/method pairs are
    the fixed denominator, including missing results. Duplicate/foreign records
    and invalid plan/result bindings raise ValueError. Artifact failures remain
    in the denominator with evidence reason codes, never fabricated application.
    For repeated instances: failed > not_reached > applied > not_applicable;
    reason_counts count each reason once per record, not once per step.
    """
    plan, result = _plain(plan), _plain(result)
    plan_hash, result_hash = digest(plan), digest(result)
    _require(
        result.get("plan_ref") == {"id": plan_hash, "sha256": plan_hash},
        "PLAN_HASH_MISMATCH",
        "result plan hash missing or belongs to another plan",
    )
    job_id = result.get("job_id")
    _require(
        isinstance(job_id, str)
        and job_id
        and all(c.isalnum() or c in "-_" for c in job_id),
        "INVALID_JOB_ID",
        "job ID cannot escape the current attempt directory",
    )
    configs, rows = plan["records"], result["records"]
    result["_plan_bindings"] = {
        k: plan[k] for k in ("engine_sha256", "environment") if k in plan
    }
    keys = [digest([c["method_ref"]["id"], c["record_id"]]) for c in configs]
    _require(
        len(keys) == len(set(keys)),
        "DUPLICATE_PLAN_RECORD",
        "plan record/method pairs must be unique",
    )
    indexed = {}
    for row in rows:
        key = row["key"]
        _require(
            key in keys and key not in indexed,
            "INVALID_RESULT_RECORD",
            "foreign or duplicate result record",
        )
        config = configs[keys.index(key)]
        _require(
            row.get("record_id", config["record_id"]) == config["record_id"],
            "RESULT_RECORD_MISMATCH",
            key,
        )
        indexed[key] = row
    operators = sorted(
        {f"{s['unit_id']}/{s['op']}" for c in configs for s in c["steps"]}
    )
    records = [
        _record(c, indexed.get(key), i, result, Path(store_root), operators)
        for i, (key, c) in enumerate(zip(keys, configs))
    ]
    summaries = {}
    for identity in operators:
        counts = Counter(r["operators"][identity]["status"] for r in records)
        reasons = {s: Counter() for s in STATES}
        for record in records:
            value = record["operators"][identity]
            reasons[value["status"]].update(set(value["reason_codes"]))
        unit, op = identity.split("/", 1)
        summaries[identity] = dict(
            unit_id=unit,
            op=op,
            denominator=len(records),
            configured_records=sum(
                bool(r["operators"][identity]["steps"]) for r in records
            ),
            counts={s: counts[s] for s in STATES},
            reason_counts={s: dict(sorted(reasons[s].items())) for s in STATES},
        )
    summary = dict(
        record_count=len(records),
        record_execution_counts=dict(Counter(r["execution_status"] for r in records)),
        evidence_issue_records=sum(bool(r["evidence_issues"]) for r in records),
        operators=summaries,
    )
    return OperatorUsageReport(
        plan_sha256=plan_hash,
        result_sha256=result_hash,
        summary=summary,
        records=records,
    ).model_dump(mode="json")
