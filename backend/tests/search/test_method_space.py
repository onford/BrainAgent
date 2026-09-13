from copy import deepcopy

import pytest

from app.preprocessing.methods import check_mapping
from app.preprocessing.storage import digest
from app.search.method_space import (
    basic_space,
    seed_entries,
    verify_registry,
)
from app.search.recipe_compiler import compile_recipe








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






def test_selection_tie_counts_actual_operators():
    from app.search.catalog import select

    common = {"status": "evaluated", "receipt": {"status": "evaluated", "assessment": {"selection_score": .7}}}
    assert select([
        {**common, "id": "a-longer", "parameters": {"operators": [{}, {}, {}, {}]}},
        {**common, "id": "z-simple", "parameters": {"operators": [{}, {}, {}]}},
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
