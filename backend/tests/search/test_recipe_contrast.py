from copy import deepcopy

from app.search.method_space import basic_space, seed_entries
from app.search.recipe_contrast import contrast
from app.search.method_provenance import participation


def test_filter_change_does_not_hide_removed_reference():
    space = basic_space()
    baseline, _, acquisition = seed_entries(space)
    changed = deepcopy(acquisition)
    next(n for n in changed["recipe"]["nodes"] if n["operator"] == "bandpass")["parameters"]["l_freq"] = 7.
    result = contrast(baseline, changed, space.model_dump(mode="json"))
    assert result["removed_operations"] == ["EEG-REREFERENCE/reference#1"]
    assert result["parameter_changes"] == [{"operation": "EEG-FILTER/filter#1", "parameter": "l_freq", "before": 8., "after": 7.}]
    assert not result["shared_operation_order_changed"]


def test_titles_and_node_labels_are_not_configuration_differences():
    space = basic_space()
    baseline = seed_entries(space)[0]
    renamed = deepcopy(baseline)
    renamed["title"] = "New literature-looking title"
    for i, node in enumerate(renamed["recipe"]["nodes"]):
        node["id"] = f"renamed-{i}"
    result = contrast(baseline, renamed, space.model_dump(mode="json"))
    assert not result["added_operations"] and not result["removed_operations"] and not result["parameter_changes"]
    assert not result["shared_operation_order_changed"]


def test_output_adapter_alone_does_not_pass_literature_processing_gate():
    space = basic_space().model_dump(mode="json")
    entry = {"id": "from-current-source", "origin": "literature_adaptation",
        "lineage": [{"kind": "literature", "workflow_id": "current"}],
        "recipe": {"nodes": [{"operator": "resample", "trace": []},
                              {"operator": "epoch", "trace": [{"method_ref": {"id": "source"}}]}]}}
    state = {"registry": [entry], "candidates": [{"id": entry["id"], "status": "evaluated"}], "protocol": {"space": space}}
    assert participation(state)["distinct_from_controls_evaluated_ids"] == [entry["id"]]
    assert participation(state)["substantive_literature_evaluated_ids"] == []
    entry["recipe"]["nodes"].insert(0, {"operator": "bandpass", "trace": [{"method_ref": {"id": "source"}}]})
    assert participation(state)["substantive_literature_evaluated_ids"] == [entry["id"]]


def test_operation_alias_and_fixed_binding_do_not_manufacture_candidate_diversity():
    space = basic_space().model_dump(mode="json")
    space["semantic_identity"] = "operation_contracts_v1"
    alias = deepcopy(next(o for o in space["operators"] if o["id"] == "bandpass"))
    alias.update(id="source-filter", title="A new source title", domains={}, defaults={})
    alias["bindings"].update(l_freq=8., h_freq=30.)
    space["operators"].append(alias)
    clone = deepcopy(space["methods"][0])
    space["evidence"]["test-source"] = {"source_url": "fixture://deduplication", "source_version": "1", "locator": "test paragraph", "text": "Simulated source: 8 to 30 Hz filter, common average reference."}
    clone.update(id="source-copy", origin="literature", evidence_ids=["test-source"], lineage=[{"kind": "literature", "workflow_id": "current", "source_id": "read-1"}])
    node = next(n for n in clone["recipe"]["nodes"] if n["operator"] == "bandpass")
    node.update(operator="source-filter", parameters={})
    space["methods"].append(clone)
    entries = seed_entries(space)
    assert len(entries) == 3
    assert entries[0]["lineage"][0]["source_id"] == "read-1"
    # A genuine source parameter difference still creates an experiment.
    alias["bindings"]["l_freq"] = 7.
    assert len(seed_entries(space)) == 4
    # Frozen historical protocols retain their original identity semantics.
    space["semantic_identity"] = "operator_ids_v1"
    alias["bindings"]["l_freq"] = 8.
    assert len(seed_entries(space)) == 4
