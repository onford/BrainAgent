"""Compile checked operator recipes into the existing numerical engine contract."""

from copy import deepcopy

from app.preprocessing.schemas import Evidence, MethodSpec, Step
from .pipeline_space import validate_recipe
from .space_contracts import ExplorationSpace


def compile_recipe(entry, space, panel, context=None):
    space = ExplorationSpace.model_validate(space)
    recipe, warnings = validate_recipe(entry["recipe"], space, context)
    operators = {o.id: o for o in space.operators}
    evidence_ids = list(
        dict.fromkeys(
            entry.get("evidence_ids", [])
            + [e for n in recipe.nodes for e in operators[n.operator].evidence_ids]
        )
    )
    evidence = [space.evidence[key] for key in evidence_ids]
    evidence.append(
        Evidence(
            source_url="brainagent:offline-search:operator-space:1",
            source_version="1",
            locator=entry["id"],
            text="冻结算子合同中的受约束组合；方法来源、参数编辑及先验偏离记录于候选配方。工程适配不等同于原文复现。",
        )
    )
    fallback = len(evidence) - 1
    interface = panel["output_contract"]

    def bind(value):
        if isinstance(value, str) and value.startswith("$output."):
            return deepcopy(interface[value.removeprefix("$output.")])
        if isinstance(value, dict):
            return {k: bind(v) for k, v in value.items()}
        if isinstance(value, list):
            return [bind(v) for v in value]
        return deepcopy(value)

    steps, previous = [], "raw"
    for i, node in enumerate(recipe.nodes):
        operator = operators[node.operator]
        # Executable IDs are canonical and do not depend on cosmetic edit handles.
        identity = f"s{i:02d}"
        indices = [evidence_ids.index(e) for e in operator.evidence_ids]
        steps.append(
            Step(
                id=identity,
                unit_id=operator.unit_id,
                op=operator.op,
                input=previous,
                params={**bind(operator.bindings), **deepcopy(node.parameters)},
                evidence_indices=indices or [fallback],
            )
        )
        if operator.op == "detect_bad_channels":
            # The exploration operator is diagnosis AND marking. Bind the
            # decision to the exact signal on which detection was performed.
            cap = next(
                (n.parameters["max_fraction"] for n in recipe.nodes
                 if n.operator == "interpolate_bad_channels"),
                0.25,
            )
            mark_id = f"{identity}m"
            steps.append(Step(
                id=mark_id, unit_id="EEG-BAD-CHANNEL-MARK", op="mark_channels",
                input=previous, decision_from=identity,
                params={"max_fraction": cap}, evidence_indices=indices or [fallback],
            ))
            previous = mark_id
            continue
        previous = identity
    return MethodSpec(
        id=entry["id"],
        version="3",
        title=entry["title"],
        source="classic" if entry.get("origin") == "basic" else "survey_literature",
        mechanism=" -> ".join(n.operator for n in recipe.nodes),
        recipe=steps,
        output=previous,
        evidence=evidence,
        applicability={"dataset_id": "eegmmidb", "task": "left_right_motor_imagery"},
        adaptations=entry.get("deviations", [])
        + [
            "个体无标签适配在数值配方后执行，保存实际评分表示和拟合产物。",
        ]
        + [w["reason"] for w in warnings],
    )
