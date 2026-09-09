from copy import deepcopy

import pytest

from app.preprocessing.methods import check_mapping
from app.preprocessing.storage import digest
from app.search.method_space import (
    basic_space,
    edited_entry,
    seed_entries,
    verify_registry,
)
from app.search.recipe_compiler import compile_recipe


def test_seed_and_edited_recipes_compile_to_enabled_engine_operations():
    space = basic_space()
    seeds = seed_entries(space)
    panel = {"output_contract": {"sfreq": 160.0, "tmin": 0.0, "tmax": 2.0}}
    edited = edited_entry(
        seeds[0],
        [
            {
                "action": "set_parameter",
                "node_id": "bandpass",
                "parameter": "l_freq",
                "value": 4.0,
            },
            {
                "action": "insert_operator",
                "after_node_id": None,
                "node": {
                    "id": "drift",
                    "operator": "detrend",
                    "parameters": {"type": "linear"},
                },
            },
        ],
        space,
        title="detrend and wider band",
        order=len(seeds),
    )
    for entry in seeds + [edited]:
        compiled = compile_recipe(entry, space, panel)
        assert check_mapping(compiled) == []
        assert compiled.recipe[-1].op == "epoch"
        assert compiled.recipe[-1].params["tmax"] == 2.0
        assert compiled.output == compiled.recipe[-1].id
    assert seeds[0]["recipe"]["nodes"][1]["parameters"]["l_freq"] == 8


def test_registry_rebuilds_lineage_and_rejects_tampering():
    space = basic_space()
    seeds = seed_entries(space)
    protocol = {"space": space.model_dump(mode="json")}
    edited = edited_entry(
        seeds[0],
        [
            {
                "action": "set_parameter",
                "node_id": "bandpass",
                "parameter": "l_freq",
                "value": 4.0,
            },
        ],
        space,
        title="4–30",
        order=len(seeds),
    )
    registry = seeds + [edited]
    assert len(verify_registry(protocol, registry)) == 4
    before = digest(registry)
    verify_registry(protocol, registry)
    assert digest(registry) == before
    bad = deepcopy(registry)
    bad[-1]["recipe"]["nodes"][1]["parameters"]["l_freq"] = 5.0
    with pytest.raises(ValueError, match="lineage"):
        verify_registry(protocol, bad)
    with pytest.raises(ValueError, match="duplicate"):
        verify_registry(protocol, registry + [edited])


def test_unused_adaptation_gate_does_not_create_a_new_candidate():
    space = basic_space()
    with pytest.raises(ValueError, match="do not change"):
        edited_entry(
            seed_entries(space)[0],
            [
                {
                    "action": "set_adaptation",
                    "policy": {"adaptation": "none", "alignment_threshold": 30.0},
                },
            ],
            space,
            title="no operation",
            order=3,
        )


def test_unknown_priors_are_rejected_before_execution():
    space = basic_space().model_dump(mode="json")
    space["priors"][0]["operators"][0] = "invented_ica"
    from app.search.space_contracts import ExplorationSpace

    with pytest.raises(ValueError, match="unknown operator"):
        ExplorationSpace.model_validate(space)


def test_cleaning_detections_feed_explicit_marks_before_repair():
    from app.search.scientific_space import build_space

    context = {"at_least_four_eeg": True, "electrode_positions": True, "asr_dependency": True}
    space = build_space(context)
    panel = {"output_contract": {"sfreq": 160.0, "tmin": 0.0, "tmax": 2.0}}
    cleaning = [s for s in seed_entries(space, context) if "repair" in s["id"]]
    assert len(cleaning) == 3
    for entry in cleaning:
        compiled = compile_recipe(entry, space, panel, context)
        assert check_mapping(compiled) == []
        detection = next(s for s in compiled.recipe if s.op == "detect_bad_channels")
        marking = next(s for s in compiled.recipe if s.op == "mark_channels")
        repair = next(s for s in compiled.recipe if s.op == "interpolate_bad_channels")
        assert marking.decision_from == detection.id
        assert marking.input == detection.input
        assert marking.params["max_fraction"] == repair.params["max_fraction"]
        following = compiled.recipe[compiled.recipe.index(marking) + 1]
        assert following.input == marking.id


def test_selection_uses_complete_fixed_utility_not_the_best_single_model():
    from app.search.catalog import select

    candidates = [
        {"id": "single-high", "status": "evaluated", "receipt": {
            "status": "evaluated", "macro_ba": .95, "assessment": {"selection_score": .6}}},
        {"id": "balanced", "status": "evaluated", "receipt": {
            "status": "evaluated", "macro_ba": .7, "assessment": {"selection_score": .72}}},
        {"id": "incomplete", "status": "evaluated", "receipt": {
            "status": "evaluated", "macro_ba": .99, "assessment": {"selection_score": None}}},
    ]
    assert select(candidates) == "balanced"
    assert select(candidates[-1:]) is None


def test_filter_domain_rejects_band_too_narrow_for_frozen_utility_suite():
    space = basic_space()
    with pytest.raises(ValueError, match="FBCSP"):
        edited_entry(seed_entries(space)[0], [
            {"action": "set_parameter", "node_id": "bandpass", "parameter": "l_freq", "value": 15.0},
            {"action": "set_parameter", "node_id": "bandpass", "parameter": "h_freq", "value": 20.0},
        ], space, title="too narrow", order=3)


def test_selection_tie_counts_adaptation_as_an_operator():
    from app.search.catalog import select

    common = {"status": "evaluated", "receipt": {"status": "evaluated", "assessment": {"selection_score": .7}}}
    assert select([
        {**common, "id": "a-aligned", "parameters": {"operators": [{}, {}, {}], "adaptation": "euclidean_alignment"}},
        {**common, "id": "z-simple", "parameters": {"operators": [{}, {}, {}], "adaptation": "none"}},
    ]) == "z-simple"


def test_asr_highpass_support_comes_from_actual_preceding_filters():
    from app.search.scientific_space import build_space
    from app.search.pipeline_space import validate_recipe

    context = {"at_least_four_eeg": True, "electrode_positions": True, "asr_dependency": True}
    space = build_space(context)
    recipe = {"nodes": [{"id": op, "operator": op} for op in ("resample", "bandpass", "asr", "epoch")]}
    _, warnings = validate_recipe(recipe, space, context)
    assert any(w["prior_id"] == "asr-before-analysis-band" for w in warnings)
    recipe["nodes"][1]["parameters"] = {"l_freq": .5, "h_freq": 40.0}
    with pytest.raises(ValueError, match="窗口"):
        validate_recipe(recipe, space, context)
    recipe["nodes"][2]["parameters"] = {"win_len": 1.0}
    validate_recipe(recipe, space, context)
    recipe["nodes"].pop(1)
    with pytest.raises(ValueError, match="ASR输入"):
        validate_recipe(recipe, space, context)
