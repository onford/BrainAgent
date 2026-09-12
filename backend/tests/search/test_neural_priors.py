from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from app.preprocessing.storage import digest, file_hash
from app.search.contracts import Decision, RequestDiagnostic
from app.search.interpretation import interpretation_guide
from app.search.io import write
from app.search.neural_diagnostics import comparison, quality_input, run_diagnostic
from app.search.neural_priors import freeze_bundle, evaluate_priors
from app.search.neural_signal import task_tfr
from app.search.scientific_space import build_space, knowledge
from app.search.service import SearchService
from app.search.rule_engine import audit
from app.search.space_contracts import ExplorationSpace, PipelineRecipe
from tests.search.test_pipeline_space import space, recipe  # noqa: F401
from app.search.reasoning import numeric_metric_index
from app.search.contracts import MechanismHypothesis


@pytest.fixture
def bundle():
    data = SimpleNamespace(collection=SimpleNamespace(records=[SimpleNamespace(id="r", sfreq=160, channels={"C3": "eeg"})],
                                                       selected_record_ids=["r"]),
                           survey=SimpleNamespace(dataset_id="eegmmidb", task="left_right_motor_imagery"))
    return freeze_bundle(data, build_space({}), knowledge().model_dump(mode="json"), interpretation_guide())


@pytest.mark.parametrize("value,status,expected", [(4, "ok", "true"), (1, "ok", "false"),
    (None, "ok", "unknown"), (5, "partial", "unknown"), (float("nan"), "ok", "unknown"), (True, "ok", "unknown")])
def test_conditional_evidence_is_three_valued(bundle, value, status, expected):
    result = evaluate_priors(bundle, {"line_ratio_50hz": {"value": value, "status": status}})
    rules = {r["id"]: r for r in result["rules"]}
    assert rules["mains50"]["condition_state"] == expected
    assert rules["mu-observation"]["condition_state"] == "unknown"
    assert rules["eog-missing"]["condition_state"] == "true"
    assert rules["iclabel-domain"]["condition_state"] == "true"
    assert bundle["task_profile"]["individual_pattern_required"] is False


def test_unknown_applicability_is_not_false(space, recipe):
    value = space.model_dump(mode='json')
    value['priors'] = [dict(id='known-order', strength='hard', relation='before',
        operators=['reference', 'filter'], condition='known input', rationale='fixture',
        origin='implementation', when=[dict(scope='context', key='known', comparison='eq', value=True)])]
    frozen = ExplorationSpace.model_validate(value)
    candidate = PipelineRecipe.model_validate(recipe)
    assert audit(candidate, frozen, {})['decisions'][0]['status'] == 'unknown'
    assert audit(candidate, frozen, {'known': False})['decisions'][0]['status'] == 'not_applicable'


def test_diagnostic_and_rule_ids_cannot_be_invented(bundle):
    state = {"protocol": {"neural_priors": bundle}, "diagnostics": []}
    for proposal in ({"diagnostic_ids": ["fake"]}, {"prior_rule_ids": ["mains50"]}):
        with pytest.raises(ValueError):
            SearchService.validate_prior_evidence(state, proposal)
    d = {"id": "d1", "prior_evaluation": evaluate_priors(bundle, {})}
    state["diagnostics"].append(d)
    with pytest.raises(ValueError, match="prior_claims"):
        SearchService.validate_prior_evidence(state, {"diagnostic_ids": ["d1"], "prior_rule_ids": ["mains50"], "prior_claims": {"mains50": "true"}})
    trace = SearchService.validate_prior_evidence(state, {"diagnostic_ids": ["d1"], "prior_rule_ids": ["mains50"], "prior_claims": {"mains50": "unknown"}})
    assert trace["condition_evidence"][0]["condition_state"] == "unknown"


def test_verified_receipt_and_duplicate_diagnostic_identity(tmp_path, bundle):
    recipe = {"nodes": []}
    q = {"candidate_id": "c", "input_hash": "input", "panel_hash": "panel", "candidate_recipe_hash": digest(recipe),
         "stages": {"source_raw": {"line_ratio_50hz": {"value": 5, "status": "ok"}}}}
    path = tmp_path / "candidates/c/assessment/quality/data-quality.json"
    write(path, q)
    ref = {"path": "quality/data-quality.json", "sha256": file_hash(path)}
    state = {"candidates": [{"id": "c", "status": "evaluated", "receipt": {
        "assessment_path": "assessment", "assessment": {"quality": {"receipt_artifact": ref}}}}],
        "registry": [{"id": "c", "recipe": recipe}], "panel": {"panel_hash": "panel"},
        "protocol": {"neural_priors": bundle, "input_hash": "input"}}
    request = RequestDiagnostic(action="request_diagnostic", kind="signal_profile", candidate_id="c", question="why", reason="inspect").model_dump()
    a = run_diagnostic(tmp_path, state, request)
    b = run_diagnostic(tmp_path, state, {**request, "question": "rephrased", "reason": "other"})
    assert a["id"] == b["id"] and a["prior_evaluation"]["rules"][0]["condition_state"] == "true"
    q["input_hash"] = "tampered"
    write(path, q)
    with pytest.raises(ValueError, match="哈希"):
        quality_input(tmp_path, state, "c")
    ref["sha256"] = file_hash(path)
    with pytest.raises(ValueError, match="冻结"):
        quality_input(tmp_path, state, "c")


def test_paired_differences_refuse_mismatched_views_and_denominators():
    metric = {"value": 1, "unit": "u", "status": "ok", "axes": [], "denominator": {"n": 2}}
    q = {"bysubject": {"s": {"records": [{"record_id": "r"}], "coverage": {"eligible": 2},
                              "stages": {"processed_task": {"mu_mean_psd": metric}}}}}
    b = deepcopy(q); b["bysubject"]["s"]["stages"]["processed_task"]["mu_mean_psd"]["value"] = 3
    entry = {"recipe": {"nodes": [{"operator": "bandpass", "parameters": {"l_freq": 8}}]}}
    other = deepcopy(entry); other["recipe"]["nodes"][0]["parameters"]["l_freq"] = 4
    def result(e): return comparison(q, b, entry, e, "processed_task")["metrics"]["mu_mean_psd"]
    assert result(entry)["mean_subject_difference"] == 2
    assert result(other)["status"] == "not_comparable"
    b["bysubject"]["s"]["coverage"]["eligible"] = 1
    assert result(entry)["paired_subjects"] == 0


def test_tfr_preserves_known_change_scale_invariance_and_missing_support():
    fs = 160
    baseline = np.tile(np.sin(2*np.pi*10*np.arange(320)/fs)[None, None, :] * 1e-5, (3, 1, 1))
    task = baseline * 0.5
    kwargs = dict(sfreq=fs, channels=["C3"], trial_ids=["a", "b", "c"], history={"nominal_band_hz": [1, 40]})
    first = task_tfr(task, baseline, **kwargs)
    scaled = task_tfr(task * 3, baseline * 3, **kwargs)
    assert first["status"] == "ok"
    a = np.array(first["erds_percent"], dtype=float)
    assert np.allclose(a, np.array(scaled["erds_percent"], dtype=float), equal_nan=True)
    # Finite Morlet support causes a small periodic modulation around the analytic power ratio.
    assert np.nanmedian(a[0, 1]) == pytest.approx(-75, abs=0.02)
    assert np.isnan(a[:, :, 0]).all()
    task[0] = np.nan
    partial = task_tfr(task, baseline, **kwargs)
    assert partial["status"] == "partial" and partial["missing_trial_ids"] == ["a"]
    assert task_tfr(task, None, **kwargs)["status"] == "not_applicable"
    assert task_tfr(np.zeros_like(task), np.zeros_like(baseline), **kwargs)["reason"] == "nonpositive_or_nonfinite_baseline_power"


def test_diagnostic_schema_enforces_pair_requirements():
    with pytest.raises(ValueError):
        Decision.model_validate({"decision": {"action": "request_diagnostic", "kind": "paired_comparison",
                                "candidate_id": "a", "question": "q", "reason": "r"}})


def test_actual_metric_paths_and_scopes_prevent_live_api_path_guessing():
    receipt = {"assessment": {"selection_score": .5, "core_csp_macro_ba": .6, "quality": {"summary": {
        "metrics": {"numerical_rank": {"status": "ok", "value": 63}, "line_ratio_50hz": {"status": "not_applicable", "value": None}}}}},
        "diagnostics": {"summary": {"mean_anisotropy": 10}}}
    rows = numeric_metric_index(receipt)
    bypath = {r["path"]: r for r in rows}
    assert "quality.metrics.numerical_rank.value" not in bypath
    assert "physical_processed_task" in bypath["assessment.quality.summary.metrics.numerical_rank.value"]["measurement_scope"]
    assert "saved_physical_signal_diagnostics" in bypath["diagnostics.summary.mean_anisotropy"]["measurement_scope"]
    assert not any("line_ratio" in r["path"] for r in rows)
    h = dict(explanation="test", competing_explanation="test", observations=[{"candidate_id": "c", "metric": "assessment.selection_score"}],
             weakened_by="test", predictions=[{"kind": "utility", "metric": "assessment.core_csp_macro_ba", "direction": "increase", "explanation": "anchor"},
               {"kind": "signal", "metric": "diagnostics.summary.mean_anisotropy", "direction": "decrease", "explanation": "representation"}])
    assert MechanismHypothesis.model_validate(h)


def test_missing_aggregate_resolves_verified_record_causes(tmp_path):
    from app.search.neural_diagnostics import explain_missing, observations
    path = tmp_path / "quality/details/one.json"
    write(path, {"record_id": "r", "stages": {"source_raw": {"metrics": [
        {"metricID": "line_ratio_50hz", "status": "not_applicable", "reason": "acquisition_filter_history_incomplete_for_residual_proxy"}]}}})
    q = {"detail_artifacts": [{"record_id": "r", "path": "details/one.json", "sha256": file_hash(path)}]}
    reference = {"path": "quality/data-quality.json"}
    views = {"source_raw": observations(q, reference, "source_raw")}
    explain_missing(tmp_path, q, reference, views)
    reasons = views["source_raw"]["line_ratio_50hz"]["missing_detail"]
    assert reasons["record_reason_counts"] == {"acquisition_filter_history_incomplete_for_residual_proxy": 1}
    assert reasons["examples"][0]["reference"]["json_pointer"] == "/stages/source_raw/metrics/0"
    write(path, {"record_id": "changed"})
    with pytest.raises(ValueError, match="哈希"):
        explain_missing(tmp_path, q, reference, views)
