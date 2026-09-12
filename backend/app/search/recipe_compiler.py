"""Compile checked operator recipes into the existing numerical engine contract."""

from copy import deepcopy

from app.preprocessing.schemas import Evidence, MethodSpec, Step
from .pipeline_space import validate_recipe
from .space_contracts import ExplorationSpace


def compile_recipe(entry, space, panel, context=None):
    if entry.get('schema_version')=='unit_graph_v2':
        from .unit_graph_space import candidates
        resolved=candidates(MethodSpec.model_validate(entry['method']),entry.get('grid',{}),1)
        if panel:
            from .graph_evaluation import check_method
            from app.preprocessing.schemas import PreprocessInput
            if not context or 'preprocess_input' not in context:
                raise ValueError('graph evaluation requires the frozen target input for alignment')
            check_method(resolved[0], PreprocessInput.model_validate(context['preprocess_input']), panel['output_contract'])
        # Route direct source graphs through the same frozen rule evaluator.
        from .graph_recipe import graph_operator
        from types import SimpleNamespace
        from .rule_engine import audit, enforce
        bound_space = deepcopy(space.model_dump(mode='json') if isinstance(space, ExplorationSpace) else space)
        nodes = []
        for step in resolved[0].recipe:
            op, parameters, _ = graph_operator(step, bound_space)
            nodes.append(SimpleNamespace(id=step.id, operator=op, parameters=parameters,
                input_from=step.input, model_from=step.model_from,
                decision_from=step.decision_from, graph=step))
        # The source MethodSpec is already validated. Auditing must not impose
        # the editable recipe's node-count or cosmetic identifier restrictions.
        projection = SimpleNamespace(nodes=nodes, model_dump=lambda **_: dict(
            nodes=[{**vars(n), 'graph': n.graph.model_dump(mode='json')} for n in nodes],
            output=resolved[0].output))
        result = audit(projection, ExplorationSpace.model_validate(bound_space), context)
        warnings = enforce(result)
        resolved[0].lineage['rule_audit'] = result
        resolved[0].adaptations.extend(w['reason'] for w in warnings)
        return resolved[0]
    space = ExplorationSpace.model_validate(space)
    recipe, warnings = validate_recipe(entry["recipe"], space, context)
    from .rule_engine import audit
    rule_audit = audit(recipe, space, context)
    operators = {o.id: o for o in space.operators}
    evidence_ids = list(
        dict.fromkeys(
            entry.get("evidence_ids", [])
            + [e for n in recipe.nodes for e in operators[n.operator].evidence_ids]
            + [e for n in recipe.nodes for trace in n.trace for e in trace.get("evidence_ids", [])]
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
    names = {"raw": "raw", **{node.id: f"s{i:02d}" for i, node in enumerate(recipe.nodes)}}
    for i, node in enumerate(recipe.nodes):
        operator = operators[node.operator]
        # Executable IDs are canonical and do not depend on cosmetic edit handles.
        identity = f"s{i:02d}"
        indices = list(dict.fromkeys(evidence_ids.index(e) for e in
            [*operator.evidence_ids, *[e for trace in node.trace for e in trace.get("evidence_ids", [])]]))
        parameter_sources = {}
        for trace in node.trace:
            for key, source in trace.get("parameter_sources", {}).items():
                source = deepcopy(source)
                source["evidence_indices"] = [evidence_ids.index(e) for e in source.pop("evidence_ids", [])]
                parameter_sources[key] = source
        parameters = {**bind(operator.bindings), **deepcopy(node.parameters)}
        # Derived parameter values cannot retain a parent's published-value label.
        for key, value in parameters.items():
            originals = [t.get("parameters", {}).get(key) for t in node.trace if key in t.get("parameters", {})]
            if key not in parameter_sources or originals and all(v != value for v in originals):
                parameter_sources[key] = {"origin": "target_binding" if str(operator.bindings.get(key, "")).startswith("$") else "engineering",
                    "evidence_indices": [], "rationale": "冻结输出绑定或受约束配方参数；不声明为原论文值。"}
        steps.append(
            Step(
                **({k: v for k, v in node.graph.model_dump(mode='json').items() if k in {
                    'profile','implementation_version','artifact_inputs','parameter_inputs','asset_inputs',
                    'decision','adaptation_scope','input_representation','input_channels','record_decisions','decision_target'}} if node.graph else {}),
                id=identity,
                unit_id=operator.unit_id,
                op=operator.op,
                input=names[node.input_from] if node.input_from else previous,
                model_from=names[node.model_from] if node.model_from else None,
                decision_from=names[node.decision_from] if node.decision_from else None,
                fit_scope=node.fit_scope,
                params=parameters,
                evidence_indices=indices or [fallback],
                parameter_sources=parameter_sources,
                optional=node.optional,
            )
        )
        if operator.op == "detect_bad_channels" and operator.emit_mark and operator.implementation_version == '1':
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
        if operator.op != "eog_fit":
            previous = identity
    from .graph_evaluation import graph_method, promote
    from .graph_recipe import rename_ports
    for step in steps:
        rename_ports(step, names)
    if graph_method(steps):
        steps = promote(steps)
    return MethodSpec(
        id=entry["id"],
        version="3",
        title=entry["title"],
        source="survey_literature" if any(t.get("kind") == "literature" for t in entry.get("lineage", [])) or entry.get("origin") in {"literature", "literature_adaptation"} else "classic",
        mechanism=" -> ".join(n.operator for n in recipe.nodes),
        recipe=steps,
        output=names[recipe.output] if recipe.output else previous,
        evaluation_window=recipe.evaluation_window,
        output_roles={role:names[node] for role,node in recipe.output_roles.items()},
        evidence=evidence,
        applicability={"dataset_id": "eegmmidb", "task": "left_right_motor_imagery"},
        adaptations=entry.get("deviations", [])
        + [w["reason"] for w in warnings],
        lineage={"kind": entry.get("origin"), "sources": entry.get("lineage", []),
                 "parent_ids": entry.get("parent_ids", []), "edits": entry.get("edits", []),
                 "candidate_id": entry["id"], "recipe_hash": entry.get("recipe_hash"),
                 "rule_audit": rule_audit},
        issues=entry.get("issues", []),
    )
