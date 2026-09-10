"""Report projection from persisted, checksum-verified assessment fixtures."""

from copy import deepcopy
from html.parser import HTMLParser
import json
from statistics import mean, pstdev
from urllib.parse import unquote, urlparse

import numpy as np
import pytest

from app.preprocessing.storage import file_hash, write_json
from app.search import assessment, reporting
from app.search.utility_contracts import UtilityReceipt
from tests.search.test_assessment import case, utility, quality, reconstruction


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links, self.rows, self.current, self.cell = [], [], None, None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs)["href"])
        elif tag == "tr":
            self.current = []
        elif tag in {"td", "th"}:
            self.cell = ""

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.current is not None:
            self.current.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.current is not None:
            self.rows.append(self.current)
            self.current = None


def distribution(values):
    return dict(mean=mean(values), lower_quartile=float(np.quantile(values, .25)), subject_sd=pstdev(values), n_subjects=len(values))


def eegnet_models(*args, missing=False):
    payload = utility(*args, missing="eegnet" if missing else None)
    for seed, output in payload["learners"]["eegnet"].get("seeds", {}).items():
        for fold in output["folds"]:
            path = args[-1] / f"seed-{seed}" / fold["fold_id"] / "model.pt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"report fixture, not a trained model")
            fold["model"] = dict(path=str(path), sha256=file_hash(path))
    payload = UtilityReceipt.model_validate(payload).model_dump(mode="json")
    write_json(args[-1] / "utility.json", payload)
    return payload


def measured_quality(*args):
    payload = quality(*args)
    row = payload["summary"]["metrics"]["oha"]
    row.update(value=[.1, .03, 0.], status="partial", applicability="partial", axes={"thresholds_uv": [10, 100, 1000]},
               reason="incomplete_member_or_metric_coverage", denominator=dict(expected_subjects=2, available_subjects=1,
                   finite_members_per_value=[1, 1, 1], status_counts={"ok": 1, "not_applicable": 1}, missing_reasons={"S2": "fixture missing"}))
    payload["summary"]["metrics"]["erds_mu"]["reason"] = "same_processed_baseline_unavailable"
    payload["summary"]["stages"] = {"source_raw": {"oha": deepcopy(row)}}
    write_json(args[-1] / "data-quality.json", payload["summary"])
    return payload


def measured_reconstruction(*args):
    payload = reconstruction(*args)
    payload["summary"].update(design="balanced", status="incomplete", aggregation="equal_assigned_subjects_per_condition",
        limitations=["cleanproxy, not neural truth"], status_counts={"evaluated": 1, "undefined": 1},
        by_case={"emg_high": dict(status="incomplete", subjects_expected=2, subjects_not_assigned=0, trial_cases_expected=8,
            status_counts={"evaluated": 1, "undefined": 1}, metrics={"paired_nrmse": dict(value=None, status="incomplete", n_valid=1, n_total=2),
                "paired_ser_improvement_db": dict(value=-2., status="ok", n_valid=2, n_total=2)}),
            "line_low": dict(status="not_assigned", subjects_expected=0, subjects_not_assigned=2, trial_cases_expected=0,
                status_counts={}, metrics={"paired_nrmse": dict(value=None, status="not_assigned", n_valid=0, n_total=0)})})
    write_json(args[-1] / "reconstruction_evaluation.json", {k: payload[k] for k in ("summary", "details")})
    payload["artifacts"] = [dict(name=p.relative_to(args[-1]).as_posix(), path=p.relative_to(args[-1]).as_posix(),
                                 sha256=file_hash(p), bytes=p.stat().st_size) for p in sorted(args[-1].rglob("*.json"))]
    return payload


def make_report_case(tmp_path, monkeypatch, missing=False, identity="candidate", search_root=None):
    args, probe = case(tmp_path)
    args[4]["id"] = identity
    root = search_root or tmp_path / "search"
    candidate_root = root / "candidates" / identity
    candidate_root.mkdir(parents=True)
    monkeypatch.setattr(assessment, "evaluate_dataset_utility", lambda *a: eegnet_models(*a, missing=missing))
    monkeypatch.setattr(assessment, "evaluate_dataset_quality", measured_quality)
    monkeypatch.setattr(assessment, "evaluate_dataset_reconstruction", measured_reconstruction)
    summary = assessment.assess_candidate(*args, candidate_root / "assessment/a1", probe)
    write_json(candidate_root / "core-receipts/a1.json", args[5])
    receipt = dict(status="evaluated", macro_ba=.91, secondary_macro_ba=.5, assessment=summary,
                   assessment_path="assessment/a1", core_receipt_path="core-receipts/a1.json", subjects={})
    write_json(candidate_root / "receipt.json", receipt)
    state = dict(id="a"*32, selected_candidate_id=None if missing else identity, protocol=dict(version=3, utility_version=2, assessment={"version": 2}),
        stop_reason="candidate_budget_exhausted", panel={"panel_hash": args[3]["panel_hash"], "evaluation_mode": args[3]["evaluation_mode"], "folds": args[3]["folds"]},
        usage=dict(elapsed_seconds=1., candidates=1, proposals=0, evidence_reads=0), budget=dict(max_candidates=1, max_proposals=1, max_evidence_reads=1),
        actions=[], candidates=[dict(id=identity, title='<script>alert("x")</script>', status="evaluated", receipt=receipt, cost_seconds=1.)])
    return root, state, summary


def test_eegnet_seed_mean_two_model_statistics_and_all_verified_links(tmp_path, monkeypatch):
    root, state, summary = make_report_case(tmp_path, monkeypatch)
    before = {p: file_hash(p) for p in root.rglob("*") if p.is_file()}
    reporting.render(root, state)
    text = (root / "report.html").read_text(encoding="utf-8")
    document = Document(text)
    selection = json.loads((root / "selection.json").read_text(encoding="utf-8"))
    # The prediction fixture makes 2, 1, then 0 errors per subject across seeds.
    assert selection["score"] == pytest.approx(5 / 6)
    assert selection["score"] != state["candidates"][0]["receipt"]["macro_ba"]
    assert selection["assessment"] == summary
    assert "EEGNet 三种子训练效用主指标" in text and "核心 CSP 锚点" in text
    assert selection["primary_learner"] == "EEGNet: mean subject-macro BA across seeds 17, 42, 2026"
    assert "FBCSP" not in text
    assert '<script>alert' not in text and "&lt;script&gt;" in text
    statistics = [r for r in document.rows if len(r) == 9 and r[0] in reporting.LEARNER_LABELS.values()]
    assert len(statistics) == 14
    assert next(r for r in statistics if r[:3] == ["EEGNet", "主模型", "ba"])[3:7] == ["0.833333", "0.833333", "0", "2/2"]
    assert next(r for r in statistics if r[:3] == ["CSP/LDA", "独立对照", "ba"])[3] == "1"
    assert next(r for r in statistics if r[0] == "CSP/LDA" and r[2] == "auc")[3:7] == ["N/A", "N/A", "N/A", "0/2"]
    names = {unquote(urlparse(link).path.split("/artifacts/", 1)[1]) for link in document.links}
    for item in summary["artifacts"]:
        assert "candidates/candidate/assessment/a1/" + item["path"] in names
    assert "candidates/candidate/core-receipts/a1.json" in names
    indexed = {f["name"]: f for f in json.loads((root / "files.json").read_text(encoding="utf-8"))["files"]}
    for name in names - {"files.json"}:
        assert (root / name).is_file() and indexed[name]["sha256"] == file_hash(root / name)
    assert before == {p: file_hash(p) for p in before}


def test_quality_and_reconstruction_boundaries_and_denominators(tmp_path, monkeypatch):
    root, state, _ = make_report_case(tmp_path, monkeypatch)
    reporting.render(root, state)
    text = (root / "report.html").read_text(encoding="utf-8")
    rows = Document(text).rows
    row = next(r for r in rows if r[0] == "oha")
    assert "数组/曲线" in row[1] and row[2] == "ratio" and row[3] == "partial"
    assert "expected_subjects=2" in row[6] and "available_subjects=1" in row[6]
    assert "thresholds_uv" in row[8]
    assert "same_processed_baseline_unavailable" in text
    assert "processed_task" in text and "物理电压" in text and "不折算为质量总分" in text
    assert ["paired_nrmse", "N/A", "无量纲", "incomplete", "1/2"] in rows
    assert ["paired_nrmse", "N/A", "无量纲", "not_assigned", "0/0"] in rows
    assert ["paired_ser_improvement_db", "-2", "dB", "ok", "2/2"] in rows
    assert "不同被试子集" in text and "不是神经真值" in text


def test_incomplete_primary_shows_na_without_core_fallback(tmp_path, monkeypatch):
    root, state, _ = make_report_case(tmp_path, monkeypatch, missing=True)
    reporting.render(root, state)
    text = (root / "report.html").read_text(encoding="utf-8")
    assert "assessment.selection_score：N/A" in text
    assert "fixture missing primary" in text
    assert json.loads((root / "selection.json").read_text(encoding="utf-8"))["score"] is None
    comparison = next(r for r in Document(text).rows if len(r) == 7 and r[0].startswith("<script>"))
    assert comparison[2] == "—" and comparison[3] == "91.00%"


def test_workflow_summary_agrees_on_score_models_and_missingness(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.workflows.reporting import evaluation_summary

    root, state, summary = make_report_case(tmp_path, monkeypatch)
    reporting.render(root, state)
    receipt = state["candidates"][0]["receipt"]
    workflow_text = evaluation_summary(SimpleNamespace(selected_receipt=receipt, score=summary["selection_score"], search_id=state["id"]))
    assert "selection_score：0.8333" in workflow_text
    assert "EEGNet" in workflow_text and "FBCSP" not in workflow_text
    assert "核心 CSP 锚点 macro_ba=0.9100" in workflow_text
    assert "质量状态：evaluated；重建状态：partial" in workflow_text
    assert json.loads((root / "selection.json").read_text(encoding="utf-8"))["score"] == summary["selection_score"]


def test_nonselected_assessment_artifacts_are_also_linked(tmp_path, monkeypatch):
    root, state, _ = make_report_case(tmp_path, monkeypatch)
    # Keep an invalidated receipt for audit while the verified, nonselected
    # candidate's native artifacts remain downloadable.
    candidate = deepcopy(state["candidates"][0])
    candidate["status"] = "invalidated"
    candidate["id"] = "invalidated"
    candidate["title"] = "保留审计"
    state["candidates"].append(candidate)
    state["selected_candidate_id"] = None
    reporting.render(root, state)
    document = Document((root / "report.html").read_text(encoding="utf-8"))
    names = {unquote(urlparse(link).path.split("/artifacts/", 1)[1]) for link in document.links}
    assert "candidates/candidate/assessment/a1/utility/utility.json" in names
    text = (root / "report.html").read_text(encoding="utf-8")
    assert "保留审计：invalidated" in text and "不作为可选择结果" in text


@pytest.mark.parametrize("target", ["utility/protocol.json", "assessment.json", "core"])
def test_tampered_native_artifact_prevents_report_publication(tmp_path, monkeypatch, target):
    root, state, _ = make_report_case(tmp_path, monkeypatch)
    path = root / "candidates/candidate" / ("core-receipts/a1.json" if target == "core" else "assessment/a1/" + target)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        reporting.render(root, state)
    assert not (root / "report.html").exists() and not (root / "selection.json").exists()


def test_protocol_two_never_claims_three_model_assessment(tmp_path):
    state = dict(id="a"*32, selected_candidate_id="basic", protocol=dict(version=2), stop_reason="model_finished",
        panel={"evaluation_mode": "subject_holdout", "folds": []}, actions=[],
        usage=dict(elapsed_seconds=1., candidates=1, proposals=0, evidence_reads=0), budget=dict(max_candidates=1, max_proposals=1, max_evidence_reads=1),
        candidates=[dict(id="basic", title="Protocol 2", status="evaluated", cost_seconds=1.,
                         receipt=dict(status="evaluated", macro_ba=.63, secondary_macro_ba=.55, subjects={}))])
    reporting.render(tmp_path, state)
    text = (tmp_path / "report.html").read_text(encoding="utf-8")
    selection = json.loads((tmp_path / "selection.json").read_text(encoding="utf-8"))
    assert selection["score"] == .63 and selection["protocol_version"] == 2
    assert selection["assessment"] is None and selection["primary_learner"] == "CSP + shrinkage LDA"
    assert "CSP-LDA 主指标 BA" in text and "对数方差 LR 次要 BA" in text
    assert "63.00%" in text and "55.00%" in text
    assert "三模型训练效用主指标" not in text and "六模型各指标分布" not in text
    assert "未执行六模型训练效用" in text


def attach_operator_usage(root, state):
    from app.search.operator_usage import OperatorUsageReport, STATES, ASR

    codes = dict(applied="ASR_APPLIED", not_applicable="ASR_CALIBRATION_TOO_SHORT",
                 failed="EXECUTION_FAILURE", not_reached="UPSTREAM_NOT_COMPLETED")
    summary = dict(record_count=4, record_execution_counts={"completed": 2, "failed": 2},
        evidence_issue_records=0, operators={ASR: dict(unit_id="EEG-ASR-AUTO", op="asr_clean",
            denominator=4, configured_records=4, counts=dict.fromkeys(STATES, 1),
            reason_counts={s: {codes[s]: 1} for s in STATES})})
    records = [dict(key=str(i), record_id=f"R{i}", method_id="conditional", attempt=1,
        execution_status="completed" if i < 2 else "failed", execution_error=None, execution_failure_code=None,
        evidence_issues=[], evidence=[], operators={ASR: dict(status=s, reason_codes=[codes[s]], steps=[dict(step_id="asr", unit_id="EEG-ASR-AUTO", op="asr_clean", status=s, reason_code=codes[s])])})
        for i, s in enumerate(STATES)]
    native = OperatorUsageReport(plan_sha256="a"*64, result_sha256="b"*64,
                                 summary=summary, records=records).model_dump(mode="json")
    candidate = state["candidates"][0]
    relative = "operator-usage.json"
    path = root / "candidates" / candidate["id"] / relative
    write_json(path, native)
    candidate["receipt"]["operator_usage"] = dict(summary=native["summary"],
        artifact=dict(path=relative, sha256=file_hash(path), bytes=path.stat().st_size))
    return path


def test_seventh_dynamic_seed_and_native_operator_applicability(tmp_path, monkeypatch):
    root, state, _ = make_report_case(tmp_path, monkeypatch, identity="literature-conditional-asr-repair")
    state["candidates"][0]["title"] = "条件 ASR 修复"
    path = attach_operator_usage(root, state)
    state["candidates"] = [dict(id=f"seed-{i}", title=f"动态 seed {i}", status="reserved", cost_seconds=0.)
                           for i in range(6)] + state["candidates"]
    state["usage"]["candidates"] = state["budget"]["max_candidates"] = 7
    reporting.render(root, state)
    text = (root / "report.html").read_text(encoding="utf-8")
    doc = Document(text)
    assert len([r for r in doc.rows if len(r) == 7 and r[0].startswith("动态 seed")]) == 6
    assert json.loads((root / "selection.json").read_text(encoding="utf-8"))["selected_candidate_id"] == "literature-conditional-asr-repair"
    row = next(r for r in doc.rows if r[0] == "EEG-ASR-AUTO/asr_clean")
    assert row[1:7] == ["4", "4", "1", "1", "1", "1"]
    assert "ASR_CALIBRATION_TOO_SHORT=1" in row[7]
    assert "identity 属于 not_applicable，不计入 applied" in text
    assert "不表示信号发生变化或质量改善" in text
    names = {unquote(urlparse(link).path.split("/artifacts/", 1)[1]) for link in doc.links}
    assert path.relative_to(root).as_posix() in names
    indexed = {f["name"]: f for f in json.loads((root / "files.json").read_text(encoding="utf-8"))["files"]}
    assert indexed[path.relative_to(root).as_posix()]["sha256"] == file_hash(path)


@pytest.mark.parametrize("tamper", ["artifact", "summary", "escape"])
def test_operator_usage_binding_checked_before_report_publication(tmp_path, monkeypatch, tamper):
    root, state, _ = make_report_case(tmp_path, monkeypatch)
    path = attach_operator_usage(root, state)
    usage = state["candidates"][0]["receipt"]["operator_usage"]
    if tamper == "artifact":
        path.write_text("{}", encoding="utf-8")
    elif tamper == "summary":
        usage["summary"]["evidence_issue_records"] = 1
    else:
        usage["artifact"]["path"] = "../../../private.json"
    with pytest.raises(ValueError):
        reporting.render(root, state)
    assert not (root / "report.html").exists() and not (root / "selection.json").exists()


@pytest.mark.parametrize("missing", [False, True])
def test_v2_projection_seed_statistics_and_native_provenance(missing):
    stats = {"ba": distribution([.6, .8])}
    summary = dict(schema_version="assessment-v2", selection_score=None if missing else .7, utility=dict(
        status="incomplete" if missing else "evaluated", utility_version=2, primary_suite=["eegnet"],
        primary_models_available=0 if missing else 1, primary_models_expected=1,
        primary_trial_predictions_available=0 if missing else 24, primary_trial_predictions_expected=24,
        denominator_scope="frozen_development_subjects_and_eligible_development_trials", evaluation_mode="group_cross_validation",
        summary=None if missing else stats["ba"], seed_summary=None if missing else dict(
            seeds=[17, 42, 2026], mean_ba=.7, seed_sd=.08165, minimum_ba=.6, maximum_ba=.8),
        learner_coverage={n: dict(subjects_expected=2, trials_available=0 if missing and n == "eegnet" else 8, eligible_trials_expected=8) for n in ("eegnet", "csp_lda")},
        learner_statistics={"eegnet": {} if missing else stats, "csp_lda": stats},
        learner_statuses={"eegnet": "failed" if missing else "evaluated", "csp_lda": "evaluated"},
        failure_reasons=["seed incomplete"] if missing else [], warnings=[]))
    native = {"learners": {n: dict(input_representation="candidate_representation", status="evaluated", folds=[]) for n in ("eegnet", "csp_lda")}}
    native["learners"]["eegnet"]["seeds"] = {str(seed): dict(seed=seed, status="evaluated", summary={"ba": distribution([ba])},
        folds=[{"model": {"path": f"seed-{seed}/model.pt"}}], metadata={"path": f"seed-{seed}/metadata.json"},
        predictions={"path": f"seed-{seed}/predictions.json"}, subjects={"S1": {"ba": ba, "n_trials": 8}})
        for seed, ba in ((17, .6), (42, .7), (2026, .8))}
    text = reporting._utility_section(summary, native)
    rows = Document(text).rows
    assert "EEGNet" in text and "FBCSP" not in text and "三主模型" not in text
    assert any(r[0] == ("0/1" if missing else "1/1") and r[1] == ("0/24" if missing else "24/24") for r in rows)
    assert ["CSP/LDA", "独立对照", "ba"] == next(r[:3] for r in rows if len(r) == 9 and r[0] == "CSP/LDA")
    for seed in (17, 42, 2026):
        assert f"seed-{seed}/model.pt" in text
    if missing:
        assert "assessment.selection_score：N/A" in text and "seed incomplete" in text
    else:
        assert "0.08165" in text and "0.65" in text


def test_legacy_projection_does_not_depend_on_current_learner_contract():
    names = reporting.LEGACY_SUITE
    summary = dict(schema_version="assessment-v1", selection_score=.7, utility=dict(status="evaluated",
        primary_suite=list(names[:3]), primary_models_available=3, primary_models_expected=3,
        primary_trial_predictions_available=24, primary_trial_predictions_expected=24,
        denominator_scope="frozen", evaluation_mode="group_cross_validation", summary=distribution([.7]),
        learner_coverage={n: dict(subjects_expected=1, trials_available=8, eligible_trials_expected=8) for n in names},
        learner_statistics={n: {"ba": distribution([.7])} for n in names},
        learner_statuses=dict.fromkeys(names, "evaluated"), failure_reasons=[], warnings=[]))
    text = reporting._utility_section(summary)
    assert "EEGNet" not in text and "历史 v1" in text
    assert len([r for r in Document(text).rows if len(r) == 9 and r[0] in reporting.LEARNER_LABELS.values()]) == 42


def test_persisted_v1_report_keeps_historical_score_and_labels(tmp_path, monkeypatch):
    from app.search.assessment_contracts import AssessmentManifest, AssessmentSnapshot, AssessmentSummary, ArtifactEntry, LegacyUtilitySummary

    root, state, summary = make_report_case(tmp_path, monkeypatch)
    output = root / "candidates/candidate/assessment/a1"
    native = json.loads((output / "utility/utility.json").read_text(encoding="utf-8"))
    names = reporting.LEGACY_SUITE
    base = native["learners"]["csp_lda"]
    native.update(utility_version=1, primary_suite=list(names[:3]), seed_summary=None,
                  learners={name: dict(deepcopy(base), role="primary" if name in names[:3] else "benchmark") for name in names})
    # All six fixture models retain identical, fully covered CSP observations.
    historical_score = base["summary"]["ba"]["mean"]
    native["learner_scores"] = dict.fromkeys(names, historical_score)
    for row in native["subjects"].values():
        row.update(mean_ba=historical_score, learner_ba=dict.fromkeys(names, historical_score))
    native.update(selection_score=historical_score, summary=deepcopy(base["summary"]["ba"]))
    native = UtilityReceipt.model_validate(native).model_dump(mode="json")
    write_json(output / "utility/utility.json", native)
    part = summary["utility"]
    part.pop("seed_summary", None)
    coverage = part["learner_coverage"]["csp_lda"]
    part.update(primary_suite=list(names[:3]), learner_scores=native["learner_scores"],
        learner_statuses=dict.fromkeys(names, "evaluated"),
        learner_statistics={n: native["learners"][n]["summary"] for n in names},
        learner_coverage={n: deepcopy(coverage) for n in names}, summary=native["summary"],
        primary_models_expected=3, primary_models_available=3,
        receipt_artifact=assessment._ref(output / "utility/utility.json", output).model_dump(mode="json"))
    summary.update(schema_version="assessment-v1", selection_score=historical_score,
        selection_policy="utility_only_all_three_primary_models_all_frozen_subjects",
        utility=LegacyUtilitySummary.model_validate(part).model_dump(mode="json"))
    content = {k: v for k, v in summary.items() if k not in {"artifacts", "artifact_manifest"}}
    write_json(output / "_assessment/summary.json", AssessmentSnapshot(content=content).model_dump(mode="json"))
    artifacts = [a for a in assessment._inventory(output) if a.path != "artifact-manifest.json"]
    write_json(output / "artifact-manifest.json", AssessmentManifest(bindings=summary["bindings"], artifacts=artifacts).model_dump(mode="json"))
    ref = assessment._ref(output / "artifact-manifest.json", output)
    artifacts.append(ArtifactEntry(**ref.model_dump(), component="assessment"))
    summary = AssessmentSummary(**content, artifact_manifest=ref, artifacts=artifacts).model_dump(mode="json")
    write_json(output / "assessment.json", summary)
    state["protocol"] = dict(version=3, assessment={"version": 1})
    state["candidates"][0]["receipt"]["assessment"] = summary
    before = {p: file_hash(p) for p in output.rglob("*") if p.is_file()}
    reporting.render(root, state)
    text = (root / "report.html").read_text(encoding="utf-8")
    assert "EEGNet" not in text and "六模型各指标分布（历史 v1）" in text
    assert "三模型训练效用主指标" in text and "100.00%" in text
    assert before == {p: file_hash(p) for p in before}
