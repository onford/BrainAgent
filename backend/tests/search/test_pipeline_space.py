from copy import deepcopy

import pytest

from app.search.pipeline_space import apply_edits, recipe_hash, validate_recipe
from app.search.space_contracts import ExplorationSpace


@pytest.fixture
def space():
    numeric = dict(
        kind="number",
        minimum=0.1,
        maximum=40,
        unit="Hz",
        rationale="bounded fixture",
        origin="engineering",
    )
    return ExplorationSpace.model_validate(
        {
            "operators": [
                dict(
                    id="filter",
                    title="filter",
                    unit_id="EEG-FILTER",
                    op="filter",
                    input_stage="continuous",
                    output_stage="same",
                    fit_scope="none",
                    domains={"low": numeric},
                    defaults={"low": 8.0},
                ),
                dict(
                    id="reference",
                    title="reference",
                    unit_id="EEG-REREFERENCE",
                    op="reference",
                    input_stage="either",
                    output_stage="same",
                    fit_scope="none",
                    domains={},
                    defaults={},
                ),
                dict(
                    id="epochs",
                    title="epoch",
                    unit_id="EEG-EPOCH",
                    op="epoch",
                    input_stage="continuous",
                    output_stage="epochs",
                    fit_scope="none",
                    domains={},
                    defaults={},
                    required=True,
                ),
            ],
            "methods": [],
            "priors": [],
            "evidence": {},
        }
    )


@pytest.fixture
def recipe():
    return {
        "nodes": [
            {"id": "band", "operator": "filter", "parameters": {"low": 8.0}},
            {"id": "ref", "operator": "reference"},
            {"id": "ep", "operator": "epochs"},
        ]
    }


def test_edits_are_composable_bounded_and_leave_parent_unchanged(space, recipe):
    before = deepcopy(recipe)
    result, warnings = apply_edits(
        recipe,
        [
            {
                "action": "set_parameter",
                "node_id": "band",
                "parameter": "low",
                "value": 4.0,
            },
            {
                "action": "swap_adjacent",
                "first_node_id": "band",
                "second_node_id": "ref",
            },
        ],
        space,
    )
    assert [n.id for n in result.nodes] == ["ref", "band", "ep"]
    assert result.nodes[1].parameters["low"] == 4
    assert recipe == before and not warnings


@pytest.mark.parametrize("value", [0, 41, True, "4", float("nan"), float("inf")])
def test_parameters_cannot_escape_frozen_domain(space, recipe, value):
    with pytest.raises(ValueError):
        apply_edits(
            recipe,
            [
                {
                    "action": "set_parameter",
                    "node_id": "band",
                    "parameter": "low",
                    "value": value,
                }
            ],
            space,
        )


def test_required_output_and_stage_boundaries_survive_edits(space, recipe):
    with pytest.raises(ValueError, match="epochs"):
        apply_edits(recipe, [{"action": "remove_operator", "node_id": "ep"}], space)
    with pytest.raises(ValueError, match="requires continuous"):
        apply_edits(
            recipe,
            [
                {
                    "action": "swap_adjacent",
                    "first_node_id": "ref",
                    "second_node_id": "ep",
                },
                {
                    "action": "swap_adjacent",
                    "first_node_id": "band",
                    "second_node_id": "ep",
                },
            ],
            space,
        )


def test_duplicate_operator_insert_and_unknown_operator_rejected(space, recipe):
    for op in ("filter", "arbitrary-code"):
        with pytest.raises(ValueError):
            apply_edits(
                recipe,
                [
                    {
                        "action": "insert_operator",
                        "after_node_id": None,
                        "node": {"id": "new", "operator": op},
                    }
                ],
                space,
            )


def test_semantic_identity_ignores_cosmetic_ids_and_defaults(space, recipe):
    canonical, _ = validate_recipe(recipe, space)
    renamed = deepcopy(recipe)
    for node in renamed["nodes"]:
        node["id"] += "_renamed"
    renamed["nodes"][0]["parameters"] = {}
    other, _ = validate_recipe(renamed, space)
    assert recipe_hash(canonical) == recipe_hash(other)
    with pytest.raises(ValueError, match="do not change"):
        apply_edits(
            recipe,
            [
                {
                    "action": "set_parameter",
                    "node_id": "band",
                    "parameter": "low",
                    "value": 8.0,
                }
            ],
            space,
        )


def test_soft_prior_is_visible_and_hard_prior_blocks(space, recipe):
    value = space.model_dump(mode="json")
    prior = dict(
        id="ref-first",
        strength="soft",
        relation="before",
        operators=["reference", "filter"],
        condition="both present",
        rationale="fixture sequencing constraint",
        origin="implementation",
    )
    value["priors"] = [prior]
    _, warnings = validate_recipe(recipe, value)
    assert warnings[0]["prior_id"] == "ref-first"
    prior["strength"] = "hard"
    with pytest.raises(ValueError, match="ref-first"):
        validate_recipe(recipe, value)


def test_conditional_prior_requires_actual_context(space, recipe):
    value = space.model_dump(mode="json")
    value["priors"] = [
        dict(
            id="conditional-order",
            strength="hard",
            relation="before",
            operators=["reference", "filter"],
            condition="bad sensor identified",
            rationale="fixture conditional order",
            origin="implementation",
            when=[dict(scope="context", key="bad_sensor", comparison="eq", value=True)],
        )
    ]
    validate_recipe(recipe, value, {"bad_sensor": False})
    with pytest.raises(ValueError, match="conditional-order"):
        validate_recipe(recipe, value, {"bad_sensor": True})


def test_new_operator_can_be_inserted_and_removed(space, recipe):
    stripped, _ = apply_edits(
        recipe, [{"action": "remove_operator", "node_id": "ref"}], space
    )
    restored, _ = apply_edits(
        stripped,
        [
            {
                "action": "insert_operator",
                "after_node_id": "band",
                "node": {"id": "newref", "operator": "reference"},
            }
        ],
        space,
    )
    original, _ = validate_recipe(recipe, space)
    assert recipe_hash(original) == recipe_hash(restored)
