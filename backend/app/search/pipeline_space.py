"""Deterministic, bounded edits of method recipes; no generated code execution."""

from copy import deepcopy
import math
import operator as comparisons

from pydantic import TypeAdapter

from app.preprocessing.storage import digest
from .space_contracts import ExplorationSpace, PipelineEdit, PipelineRecipe


_EDIT = TypeAdapter(PipelineEdit)
_COMPARE = {
    "eq": comparisons.eq,
    "ne": comparisons.ne,
    "lt": comparisons.lt,
    "le": comparisons.le,
    "gt": comparisons.gt,
    "ge": comparisons.ge,
    "in": lambda a, b: a in b,
}


def _check_value(value, domain, location):
    if domain.kind == "choice":
        if not any(type(value) is type(v) and value == v for v in domain.choices):
            raise ValueError(f"{location}: value is not an allowed choice")
    else:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"{location}: finite numeric parameter required")
        if domain.kind == "integer" and type(value) is not int:
            raise ValueError(f"{location}: integer parameter required")
        if not domain.minimum <= value <= domain.maximum:
            raise ValueError(f"{location}: parameter outside frozen bounds")


def _predicate(predicate, recipe, context):
    if predicate.scope == "context":
        values = [context[predicate.key]] if predicate.key in context else []
    else:
        values = [
            n.parameters[predicate.key]
            for n in recipe.nodes
            if n.operator == predicate.operator and predicate.key in n.parameters
        ]
    if not values:
        return False
    try:
        return all(_COMPARE[predicate.comparison](v, predicate.value) for v in values)
    except (TypeError, ValueError):
        return False


def validate_recipe(recipe, space, context=None):
    """Return a canonical recipe and applicable soft-prior disagreements."""
    space = (
        space
        if isinstance(space, ExplorationSpace)
        else ExplorationSpace.model_validate(space)
    )
    recipe = PipelineRecipe.model_validate(
        recipe.model_dump(mode="json") if isinstance(recipe, PipelineRecipe) else recipe
    )
    context = context or {}
    operators = {o.id: o for o in space.operators}
    counts, positions = {}, {}
    stage = "continuous"
    input_highpass = 0.0
    for i, node in enumerate(recipe.nodes):
        if node.operator not in operators:
            raise ValueError(f"unknown executable operator: {node.operator}")
        spec = operators[node.operator]
        counts[spec.id] = counts.get(spec.id, 0) + 1
        positions.setdefault(spec.id, []).append(i)
        if counts[spec.id] > spec.max_instances:
            raise ValueError(f"{spec.id}: maximum instances exceeded")
        missing = [key for key in spec.requires if context.get(key) is not True]
        if missing:
            raise ValueError(
                f"{spec.id}: missing input requirements: {', '.join(missing)}"
            )
        if spec.input_stage not in {"either", stage}:
            raise ValueError(f"{spec.id}: requires {spec.input_stage}, got {stage}")
        unknown = node.parameters.keys() - spec.domains.keys()
        if unknown:
            raise ValueError(f"{spec.id}: unknown parameters: {sorted(unknown)}")
        node.parameters = {**deepcopy(spec.defaults), **node.parameters}
        for key, domain in spec.domains.items():
            _check_value(node.parameters[key], domain, f"{node.id}.{key}")
        for rule in spec.separations:
            if node.parameters[rule.upper_parameter] - node.parameters[rule.lower_parameter] < rule.minimum:
                raise ValueError(f"{node.id}: {rule.rationale}")
        if spec.input_highpass is not None:
            requirement = spec.input_highpass
            if input_highpass < requirement.minimum_hz or input_highpass * node.parameters[requirement.window_parameter] < requirement.minimum_cycles:
                raise ValueError(f"{node.id}: {requirement.rationale}")
        if spec.op == "filter":
            input_highpass = max(input_highpass, node.parameters.get("l_freq") or spec.bindings.get("l_freq") or 0.0)
        if spec.output_stage != "same":
            stage = spec.output_stage
    if stage != "epochs":
        raise ValueError("pipeline must produce epochs on the shared output grid")
    for spec in space.operators:
        if spec.required and counts.get(spec.id, 0) != 1:
            raise ValueError(f"required operator must occur exactly once: {spec.id}")
    warnings = []
    for prior in space.priors:
        if not all(_predicate(p, recipe, context) for p in prior.when):
            continue
        ids = prior.operators
        applies = ids[0] in positions
        if prior.relation == "before":
            violation = (
                applies
                and ids[1] in positions
                and max(positions[ids[0]]) >= min(positions[ids[1]])
            )
        elif prior.relation == "requires":
            violation = applies and not all(key in positions for key in ids[1:])
        elif prior.relation == "incompatible":
            violation = all(key in positions for key in ids)
        else:
            violation = applies and not all(
                _predicate(p, recipe, context) for p in prior.requirements
            )
        if violation:
            if prior.strength == "hard":
                raise ValueError(f"{prior.id}: {prior.rationale}")
            warnings.append(
                {
                    "prior_id": prior.id,
                    "reason": prior.rationale,
                    "evidence_ids": prior.evidence_ids,
                }
            )
    return recipe, warnings


def recipe_hash(recipe):
    recipe = (
        recipe
        if isinstance(recipe, PipelineRecipe)
        else PipelineRecipe.model_validate(recipe)
    )
    adaptation = recipe.adaptation.model_dump(mode="json")
    if adaptation["adaptation"] != "conditional_alignment":
        adaptation.pop("alignment_threshold")
    # Cosmetic node IDs and unused gate thresholds do not create experiments.
    return digest(
        {
            "operations": [
                {"operator": n.operator, "parameters": n.parameters}
                for n in recipe.nodes
            ],
            "adaptation": adaptation,
        }
    )


def apply_edits(recipe, edits, space, context=None):
    space = (
        space
        if isinstance(space, ExplorationSpace)
        else ExplorationSpace.model_validate(space)
    )
    if not 1 <= len(edits) <= space.max_edits_per_proposal:
        raise ValueError("edit count outside frozen proposal bounds")
    base, _ = validate_recipe(recipe, space, context)
    value = base.model_dump(mode="json")
    for raw_edit in edits:
        edit = _EDIT.validate_python(raw_edit)
        by_id = {node["id"]: i for i, node in enumerate(value["nodes"])}

        def locate(identity):
            if identity not in by_id:
                raise ValueError(f"edit references an unknown node: {identity}")
            return by_id[identity]

        if edit.action == "set_parameter":
            node = value["nodes"][locate(edit.node_id)]
            node["parameters"][edit.parameter] = deepcopy(edit.value)
        elif edit.action == "insert_operator":
            index = (
                locate(edit.after_node_id) + 1 if edit.after_node_id is not None else 0
            )
            value["nodes"].insert(index, edit.node.model_dump(mode="json"))
        elif edit.action == "remove_operator":
            value["nodes"].pop(locate(edit.node_id))
        elif edit.action == "swap_adjacent":
            a, b = locate(edit.first_node_id), locate(edit.second_node_id)
            if abs(a - b) != 1:
                raise ValueError("order edits must swap adjacent operators")
            value["nodes"][a], value["nodes"][b] = value["nodes"][b], value["nodes"][a]
        else:
            value["adaptation"] = edit.policy.model_dump(mode="json")
    result, warnings = validate_recipe(value, space, context)
    if recipe_hash(result) == recipe_hash(base):
        raise ValueError("edits do not change the executable recipe")
    return result, warnings
