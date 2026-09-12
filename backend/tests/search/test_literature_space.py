"""Extraction doubles are separate from real numerical execution below."""

from copy import deepcopy

import pytest

from app.preprocessing.literature import LiteratureExtraction, materialize
from app.preprocessing.schemas import Evidence, MethodSpec, Ref
from app.preprocessing.storage import digest
from app.search.literature_space import build_workflow_space, check_execution
from app.search.method_space import edited_entry, seed_entries, verify_registry
from app.search.recipe_compiler import compile_recipe
from app.search.method_provenance import validate_stop, method_status
from tests.preprocessing.conftest import make_dataset


EVIDENCE = [
    Evidence(source_url="fixture://paper", source_version="1", locator="Methods/classification", text="Classification uses a 6 to 32 Hz fourth order Butterworth filter and common average reference."),
    Evidence(source_url="fixture://paper", source_version="1", locator="Methods/ERP", text="The separate ERP branch uses a 0.5 to 20 Hz filter followed by common average reference."),
]


def branch(identity="classification", index=0, low=6., high=32.):
    def provenance(origin, indices):
        return {"origin": origin, "evidence_indices": indices, "rationale": "Located test passage or explicit engine choice"}
    return {"branch_id": identity, "analysis": identity, "evidence_indices": [index],
        "shared_evidence_indices": [], "prerequisites": [], "method": {
            "id": identity, "title": identity, "version": "1", "source": "survey_literature",
            "mechanism": "filter-reference", "recipe": [
                {"id": "filter", "unit_id": "EEG-FILTER", "op": "filter", "evidence_indices": [index],
                 "params": {"l_freq": low, "h_freq": high, "method": "iir", "phase": "zero", "picks": "$eeg_channels"},
                 "parameter_sources": {k: provenance("paper" if k in {"l_freq", "h_freq"} else "target_binding" if k == "picks" else "engineering", [index]) for k in ["l_freq", "h_freq", "method", "phase", "picks"]}},
                {"id": "car", "unit_id": "EEG-REREFERENCE", "op": "reference", "input": "filter", "evidence_indices": [index],
                 "params": {"ref_channels": "average"}, "parameter_sources": {"ref_channels": provenance("paper", [index])}}
            ], "output": "car", "issues": [{"severity": "validation", "code": "effect", "message": "Measure utility; no inherited paper result"}],
            "adaptations": ["zero-phase filtering is an explicit engineering implementation"]}}


def extract(data, branches=None):
    extraction = LiteratureExtraction.model_validate({"branches": branches or [branch()]})
    import asyncio
    from app.preprocessing.literature_verification import verify_extraction
    async def ask(operation, model, inputs, instruction):
        return review_double(model, inputs)
    review = asyncio.run(verify_extraction(ask, extraction, EVIDENCE))
    return materialize(extraction, EVIDENCE, data, {"workflow_id": "test-workflow", "source_id": "read-paper", 'semantic_verification':review})


def review_double(model, inputs):
    """Explicit semantic-review double; never used by production acceptance."""
    from app.preprocessing.literature_verification import parameter_unit
    return model(claims=[dict(claim_id=c['claim_id'],status='supported',
        source_unit=parameter_unit(c.get('parameter','')),target_unit=parameter_unit(c.get('parameter','')),
        evidence_index=c['evidence_indices'][0], quote=inputs['evidence'][c['evidence_indices'][0]]['text'],
        reason='Test double: source-review transport fixture, numerical evidence checks still run.') for c in inputs['claims']])


def refs(methods):
    return [({"id": digest(m.model_dump(mode="json")), "sha256": digest(m.model_dump(mode="json"))}, m) for m in methods]


@pytest.fixture
def data(tmp_path):
    return make_dataset(tmp_path / "bids", subjects=3)


OUTPUT = {"sfreq": 160., "tmin": -.2, "tmax": .5}


def test_multibranch_parameter_boundaries(data):
    methods = extract(data, [branch(), branch("erp", 1, .5, 20.)])
    assert len(methods) == 2
    assert [m.recipe[0].params["l_freq"] for m in methods] == [6., .5]
    wrong = branch()
    wrong["method"]["recipe"][0]["parameter_sources"]["l_freq"]["evidence_indices"] = [1]
    with pytest.raises(ValueError, match="cross-branch"):
        extract(data, [wrong])


def test_space_has_real_literature_and_basic_and_nonblocking_validation(data):
    space, context, report = build_workflow_space(data, OUTPUT, refs(extract(data)))
    assert report["methods"][0]["status"] == "eligible", report
    entries = seed_entries(space, context)
    assert {e["origin"] for e in entries} >= {"basic", "literature"}
    literary = next(e for e in entries if e["origin"] == "literature")
    compiled = compile_recipe(literary, space, {"output_contract": OUTPUT}, context)
    check_execution(compiled, data, OUTPUT)
    assert compiled.lineage["sources"][0]["branch_id"] == "classification"
    assert any(s.parameter_sources.get("l_freq").origin == "paper" for s in compiled.recipe if "l_freq" in s.params)


@pytest.mark.parametrize("problem", ["parameter", "operation", "prerequisite", "output", "version"])
def test_blockers_preserved(data, problem):
    source = branch()
    if problem == "parameter":
        source["method"]["recipe"][0]["params"]["l_freq"] = "$profile.missing"
        source["method"]["recipe"][0]["parameter_sources"]["l_freq"]["origin"] = "unresolved"
    elif problem == "operation":
        source["method"]["recipe"][0]["unit_id"] = "EEG-ICA"
        source["method"]["recipe"][0]["op"] = "ica_fit"
    elif problem == "prerequisite":
        source["prerequisites"] = [{"description": "EMG screening", "status": "missing", "evidence_indices": [0], "target_basis": "No EMG channels in target"}]
    elif problem == "version":
        source["method"]["recipe"][0]["implementation_version"] = "2"
    else:
        source["method"]["recipe"].append({"id": "epochs", "unit_id": "EEG-EPOCH", "op": "epoch", "input": "car", "evidence_indices": [0],
            "params": {"events": "$events", "event_id": "$event_id", "picks": "$eeg_channels", "tmin": .5, "tmax": 2.5},
            "parameter_sources": {k: {"origin": "engineering", "evidence_indices": [], "rationale": "fixture"} for k in ["events", "event_id", "picks", "tmin", "tmax"]}})
        source["method"]["output"] = "epochs"
    methods = extract(data, [source])
    space, _, report = build_workflow_space(data, OUTPUT, refs(methods))
    assert report["methods"][0]["status"] == "blocked"
    assert report["methods"][0]["reasons"]
    if problem == "output":
        adapted = next(r for r in report["methods"] if r["status"] == "eligible")
        assert adapted["lineage"]["fidelity"] == "engineering_adaptation"
        assert adapted["lineage"]["adaptation"]["original"] == {"tmin": .5, "tmax": 2.5}
        assert adapted["lineage"]["adaptation"]["replacement"] == {"tmin": -.2, "tmax": .5}
        assert adapted["compiled_method"]["recipe"][-1]["parameter_sources"]["tmin"]["origin"] == "target_binding"
    else:
        assert report["absence_reasons"]
        assert all(m.origin == "basic" for m in space.methods)
    assert methods[0].recipe[0].unit_id == source["method"]["recipe"][0]["unit_id"]


def test_edit_and_combination_trace_and_constraints(data):
    space, context, _ = build_workflow_space(data, OUTPUT, refs(extract(data)))
    entries = seed_entries(space, context)
    donor = next(e for e in entries if e["origin"] == "literature")
    base = next(e for e in entries if e["id"] == "basic-acquisition-reference")
    registry = {e["id"]: e for e in entries}
    modified = edited_entry(donor, [{"action": "set_parameter", "node_id": "filter", "parameter": "l_freq", "value": 7.}],
        space, title="modified", order=len(entries), context=context)
    assert modified["origin"] == "derived" and modified["parent_ids"] == [donor["id"]]
    compiled = compile_recipe(modified, space, {"output_contract": OUTPUT}, context)
    assert next(s for s in compiled.recipe if s.op == "filter").parameter_sources["l_freq"].origin == "engineering"
    combined = edited_entry(base, [{"action": "combine_fragment", "donor_id": donor["id"], "node_ids": ["car"], "after_node_id": "epochs"}],
        space, title="combined", order=len(entries), context=context, donors=registry)
    check_execution(compile_recipe(combined, space, {"output_contract": OUTPUT}, context), data, OUTPUT)
    assert combined["parent_ids"] == [base["id"], donor["id"]]
    assert {t["kind"] for t in combined["lineage"]} == {"basic", "literature"}
    verify_registry({"space": space.model_dump(), "space_context": context}, entries + [combined])
    with pytest.raises(ValueError, match="required source step"):
        edited_entry(donor, [{"action": "remove_operator", "node_id": "filter"}], space, title="invalid", order=len(entries), context=context)
    with pytest.raises(ValueError, match="requires continuous"):
        edited_entry(donor, [{"action": "swap_adjacent", "first_node_id": "shared_epoch", "second_node_id": "shared_resample"}], space, title="invalid", order=len(entries), context=context)


def test_early_stop_accounts_for_both_sources_and_deferred_status(data):
    space, context, report = build_workflow_space(data, OUTPUT, refs(extract(data)))
    entries = seed_entries(space, context)
    state = {"registry": entries, "candidates": [], "status": "stopped", "stop_reason": "candidate_budget_exhausted",
             "protocol": {"catalog": entries, "baseline_id": entries[0]["id"], "method_intake": report}}
    with pytest.raises(ValueError, match="untried_candidate_reasons"):
        validate_stop(state, {"untried_candidate_reasons": {}})
    validate_stop(state, {"untried_candidate_reasons": {e["id"]: "Explicit test-only reason" for e in entries}})
    assert {e["origin"] for e in entries} >= {"basic", "literature"}
    assert all(r["status"] == "deferred" and r["reason"] == "candidate_budget_exhausted" for r in method_status(state)["methods"])
    assert method_status(state)["literature_participation"]["status"] == "not_evaluated"
    state["actions"] = [{"action": "finish", "status": "completed", "request": {
        "untried_candidate_reasons": {e["id"]: "已保留此方向，等待追加预算" for e in entries}}}]
    assert all(r["reason"] == "已保留此方向，等待追加预算" for r in method_status(state)["methods"])


def test_dedup_retains_both_literature_sources(data):
    first, = extract(data)
    second = first.model_copy(deep=True)
    second.lineage["source_id"] = "another-read-paper"
    space, context, report = build_workflow_space(data, OUTPUT, refs([first, second]))
    literature = [e for e in seed_entries(space, context) if e["origin"] == "literature"]
    assert len(literature) == 1
    assert len(literature[0]["lineage"]) == 2
    assert report["methods"][0]["candidate_id"] == report["methods"][1]["candidate_id"]


@pytest.mark.parametrize('implementation_version', ['1', '2'])
def test_literature_real_execution_and_three_axis_evaluation(tmp_path, implementation_version):
    from tests.search.test_integrated_operator_evaluation import _synthetic_bids, _execute, _assess
    from app.search.panel import freeze_panel

    # Extraction is explicitly simulated; all signals, preprocessing, learners,
    # quality metrics and reconstruction below execute real numerical code.
    data = _synthetic_bids(tmp_path / "bids")
    output = {"sfreq": 160., "tmin": 0., "tmax": 2.}
    source = branch()
    for step in source['method']['recipe']:
        step['implementation_version'] = implementation_version
    space, context, report = build_workflow_space(data, output, refs(extract(data, [source])))
    assert report['methods'][0]['status']=='eligible', report
    entry = next(e for e in seed_entries(space, context) if e["origin"] == "literature")
    assert report["methods"][0]["status"] == "eligible"
    panel = freeze_panel(data, {r.id: r.id for r in data.collection.records}, seed=47, **output)
    run = _execute((tmp_path, data, context, panel, space, [], []), entry)
    summary = _assess(run)
    assert summary["selection_ready"]
    assert run[0].input_snapshot == data
    assert run[0].records[0].steps[0].parameter_sources["l_freq"].origin == "paper"
