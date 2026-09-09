"""The finite controls obey the same registry contract as adaptive candidates."""

from copy import deepcopy
import json

import pytest

from app.preprocessing.storage import digest
from app.preprocessing.methods import check_mapping
from app.search.control_design import control_entries
from app.search.exploration_coverage import EDIT_FAMILIES
from app.search.method_space import basic_space, seed_entries, verify_registry
from app.search.pipeline_space import apply_edits, recipe_hash
from app.search.recipe_compiler import compile_recipe
from app.search.scientific_space import build_space
from app.search.space_contracts import ExplorationSpace


FACTS = dict(at_least_four_eeg=True, electrode_positions=True, asr_dependency=True)


@pytest.fixture(scope="module")
def scientific():
    space = build_space(FACTS)
    return space, control_entries(space, FACTS, seed=42)


def test_all_real_seeds_form_a_bounded_verified_and_compilable_registry(scientific):
    space, frozen = scientific
    registry = frozen["registry"]
    assert len(frozen["seeds"]) == len(space.methods)
    assert 64 < len(registry) <= 256
    assert frozen["seeds"] == seed_entries(space, FACTS)
    assert registry == frozen["seeds"] + frozen["edited_entries"]
    verified = verify_registry({"space": space, "space_context": FACTS}, registry)
    assert len(verified) == len(registry)
    seen = set()
    for i, entry in enumerate(registry):
        assert entry["order"] == i
        if entry["parent_id"]:
            assert entry["parent_id"] in seen
            assert len(entry["edits"]) == 1
        seen.add(entry["id"])
        method = compile_recipe(
            entry,
            space,
            {
                "output_contract": {
                    "sfreq": 160.0,
                    "tmin": 0.0,
                    "tmax": 4.0,
                }
            },
            FACTS,
        )
        assert method.recipe
        assert method.recipe[-1].id == method.output
        assert check_mapping(method) == []
    assert {e["edits"][0]["action"] for e in frozen["edited_entries"]} == set(
        EDIT_FAMILIES
    )
    assert {e["seed_id"] for e in frozen["edited_entries"]} == {
        e["id"] for e in frozen["seeds"]
    }


def test_bandpass_can_supply_asr_input_highpass_without_named_highpass_node(scientific):
    space, frozen = scientific
    alternatives = [
        row
        for row in frozen["proposals"]
        if row["parent_id"] == "bp8-30-average"
        and row["action"] == "insert_operator"
        and row["edit"]["node"]["operator"] == "asr"
        and row["edit"]["after_node_id"] == "bandpass"
    ]
    assert alternatives
    parent = next(e for e in frozen["seeds"] if e["id"] == "bp8-30-average")
    for row in alternatives:
        assert row["status"] != "rejected"
        recipe, _ = apply_edits(parent["recipe"], [row["edit"]], space, FACTS)
        assert all(node.operator != "highpass" for node in recipe.nodes)
        assert any(node.operator == "asr" for node in recipe.nodes)


def test_all_legal_adjacent_seed_swaps_are_represented(scientific):
    space, frozen = scientific
    hashes = {e["recipe_hash"] for e in frozen["registry"]}
    expected, rejected = set(), 0
    for parent in frozen["seeds"]:
        nodes = parent["recipe"]["nodes"]
        for a, b in zip(nodes, nodes[1:]):
            try:
                recipe, _ = apply_edits(
                    parent["recipe"],
                    [
                        dict(
                            action="swap_adjacent",
                            first_node_id=a["id"],
                            second_node_id=b["id"],
                        )
                    ],
                    space,
                    FACTS,
                )
            except ValueError:
                rejected += 1
            else:
                expected.add(recipe_hash(recipe))
    assert rejected > 0 and len(expected) > 5
    assert expected <= hashes
    assert frozen["coverage"]["all_legal_adjacent_swaps_represented"] is True
    assert frozen["coverage"]["by_edit_type"]["swap_adjacent"]["legal_unique"] == len(
        expected
    )


def test_coverage_ledger_reconciles_exactly_including_cap_and_aliases(scientific):
    _, frozen = scientific
    rows = frozen["proposals"]
    coverage = frozen["coverage"]
    assert coverage["truncated"] is True
    assert len(rows) == len({r["proposal_id"] for r in rows})
    lookup = {e["id"]: e for e in frozen["registry"]}
    for r in rows:
        if r["status"] in {"selected", "deduplicated"}:
            assert lookup[r["candidate_id"]]["recipe_hash"] == r["recipe_hash"]
        else:
            assert r["candidate_id"] is None
        if r["status"] == "rejected":
            assert r["reason"] and r["recipe_hash"] is None
    assert coverage["selected"] == len(frozen["edited_entries"])
    assert coverage["proposed"] == sum(
        coverage[s] for s in ("selected", "deduplicated", "rejected", "capped")
    )
    assert coverage["deduplicated"] > 0 and coverage["capped"] > 0
    assert coverage["finite_neighbourhood_unique"] > coverage["entry_count"]
    for grouping in (coverage["by_seed"], coverage["by_edit_type"]):
        for key in ("proposed", "selected", "deduplicated", "rejected", "capped"):
            assert sum(v[key] for v in grouping.values()) == coverage[key]


def test_freeze_is_json_stable_score_blind_and_does_not_mutate_inputs(scientific):
    space, frozen = scientific
    raw = space.model_dump(mode="json")
    context = {**FACTS, "score": 1.0, "labels": [1, 2], "results": {"winner": "asr"}}
    before = deepcopy((raw, context))
    rebuilt = control_entries(json.loads(json.dumps(raw, sort_keys=True)), context, 42)
    assert rebuilt == frozen
    assert (raw, context) == before
    assert "score" not in rebuilt["design"]["context"]
    parsed = json.loads(json.dumps(frozen, allow_nan=False))
    design_hash = parsed.pop("design_hash")
    assert digest(parsed) == design_hash
    assert frozen["registry_hash"] == digest(frozen["registry"])


def test_seed_changes_ties_but_not_uncapped_neighbourhood():
    space = basic_space()
    a, b = [control_entries(space, {}, s) for s in (1, 2)]
    assert not a["coverage"]["truncated"] and not b["coverage"]["truncated"]
    assert {e["recipe_hash"] for e in a["registry"]} == {
        e["recipe_hash"] for e in b["registry"]
    }
    assert a["registry_hash"] != b["registry_hash"]
    # Exhaustive prefixes share opportunities across types and starting families.
    first_round = a["edited_entries"][: len(EDIT_FAMILIES) * len(space.methods)]
    assert {e["edits"][0]["action"] for e in first_round} == set(EDIT_FAMILIES)
    assert {e["seed_id"] for e in first_round} == {s.id for s in space.methods}


def test_quantiles_integer_choice_and_inserted_operator_variants():
    value = basic_space().model_dump(mode="json")
    detrend = next(o for o in value["operators"] if o["id"] == "detrend")
    detrend["domains"]["order"] = dict(
        kind="integer",
        minimum=1.2,
        maximum=7.8,
        unit="count",
        rationale="test integer rounding",
        origin="engineering",
    )
    detrend["defaults"]["order"] = 2
    frozen = control_entries(value, {}, 42)
    insertions = [
        r["edit"]["node"]["parameters"]
        for r in frozen["proposals"]
        if r["action"] == "insert_operator"
        and r["edit"]["node"]["operator"] == "detrend"
    ]
    assert {p["order"] for p in insertions} == {2, 3, 5, 6}
    assert {p["type"] for p in insertions} == {"constant", "linear"}
    # Insertions change at most one default parameter: no hidden factorial grid.
    assert all(
        sum(p[k] != v for k, v in detrend["defaults"].items()) <= 1 for p in insertions
    )
    low = {
        r["edit"]["value"]
        for r in frozen["proposals"]
        if r["action"] == "set_parameter" and r["edit"]["parameter"] == "l_freq"
    }
    assert low == {4.125, 7.75, 11.375}


def test_soft_challenges_are_explicit_falsifiable_and_hard_priors_not_overridden(
    scientific,
):
    _, frozen = scientific
    challenged = [e for e in frozen["edited_entries"] if e["prior_warnings"]]
    assert challenged
    for entry in challenged:
        assert set(entry["prior_challenges"]) == {
            w["prior_id"] for w in entry["prior_warnings"]
        }
        for reason in entry["prior_challenges"].values():
            assert entry["parent_id"] in reason
            assert "assessment.selection_score" in reason
            assert (
                "artifact_residual_rms_ratio" in reason
                and "clean_retention_nrmse" in reason
            )
            assert "缺指标" in reason and "削弱" in reason
    hard_rejected = [
        r
        for r in frozen["proposals"]
        if r["status"] == "rejected" and "asr-before-car" in r["reason"]
    ]
    assert hard_rejected


def test_label_free_adaptation_has_explicit_finite_threshold_grid():
    frozen = control_entries(basic_space(), {}, 42)
    policies = [e["recipe"]["adaptation"] for e in frozen["registry"]]
    assert {p["adaptation"] for p in policies} == {
        "none",
        "subject_scale",
        "euclidean_alignment",
        "conditional_alignment",
    }
    assert {
        p["alignment_threshold"]
        for p in policies
        if p["adaptation"] == "conditional_alignment"
    } == {2, 5, 10, 20}
    assert "engineering" in frozen["design"]["conditional_threshold_provenance"]


def test_tiny_cap_preserves_seeds_and_reports_omitted_legal_swaps():
    space = basic_space()
    frozen = control_entries(space, {}, 42, max_entries=len(space.methods))
    assert frozen["registry"] == frozen["seeds"]
    assert not frozen["edited_entries"]
    assert frozen["coverage"]["truncated"] is True
    assert frozen["coverage"]["all_legal_adjacent_swaps_represented"] is False
    assert set(frozen["coverage"]["missing_edit_types"]) == set(EDIT_FAMILIES)


def test_unavailable_operators_are_rejected_with_reasons():
    facts = {key: False for key in FACTS}
    frozen = control_entries(build_space(facts), facts, 42)
    assert len(frozen["seeds"]) == 4
    assert not any(
        n["operator"] in {"asr", "detect_bad_channels", "interpolate_bad_channels"}
        for e in frozen["registry"]
        for n in e["recipe"]["nodes"]
    )
    assert any(
        r["status"] == "rejected" and "missing input requirements" in r["reason"]
        for r in frozen["proposals"]
    )


def test_missing_context_predicate_fails_closed():
    value = basic_space().model_dump(mode="json")
    value["priors"][0]["when"] = [
        dict(scope="context", key="grid_frozen", comparison="eq", value=True)
    ]
    with pytest.raises(ValueError, match="grid_frozen"):
        control_entries(value, {}, 42)
    assert control_entries(value, {"grid_frozen": True}, 42)["registry"]


@pytest.mark.parametrize("limit", [0, 257, 1.5, True, 2])
def test_invalid_caps_fail_instead_of_dropping_seeds(limit):
    with pytest.raises(ValueError, match="max_entries"):
        control_entries(basic_space(), {}, 42, max_entries=limit)


@pytest.mark.parametrize("seed", [-1, 2**32, True, 1.5])
def test_invalid_seeds_fail(seed):
    with pytest.raises(ValueError, match="seed"):
        control_entries(basic_space(), {}, seed)


def test_duplicate_semantic_seeds_and_empty_seed_sets_are_explicit_errors():
    value = basic_space().model_dump(mode="json")
    duplicate = deepcopy(value["methods"][0])
    duplicate["id"] = "same-recipe"
    duplicate["recipe"]["nodes"][0]["id"] = "cosmetic"
    value["methods"].append(duplicate)
    with pytest.raises(ValueError, match="duplicate seed semantics"):
        control_entries(value, {}, 42)
    value["methods"] = []
    with pytest.raises(ValueError, match="at least one"):
        control_entries(ExplorationSpace.model_validate(value), {}, 42)
