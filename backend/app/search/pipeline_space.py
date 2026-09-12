"""Deterministic, bounded edits of method recipes; no generated code execution."""

from copy import deepcopy
import math

from pydantic import TypeAdapter

from app.preprocessing.storage import digest
from .space_contracts import ExplorationSpace, PipelineEdit, PipelineRecipe


_EDIT = TypeAdapter(PipelineEdit)


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
    counts = {}
    stage = "continuous"
    input_highpass = 0.0
    seen = set()
    stages = {'raw': 'continuous'}
    highpasses = {'raw': 0.0}
    for i, node in enumerate(recipe.nodes):
        if node.operator not in operators:
            raise ValueError(f"unknown executable operator: {node.operator}")
        spec = operators[node.operator]
        input_stage = stages.get(node.input_from, stage) if node.input_from else stage
        if node.input_from is not None:
            input_highpass = highpasses.get(node.input_from, 0.0)
        for ref in (node.input_from, node.model_from, node.decision_from):
            if ref is not None and ref != "raw" and ref not in seen:
                raise ValueError(f"{node.id}: missing or forward data/model/decision dependency {ref}")
        seen.add(node.id)
        if node.graph is not None:
            from app.preprocessing.ports import sources
            ports = list(node.graph.artifact_inputs.values()) + [p for e in node.graph.parameter_inputs.values() for p in sources(e)]
            if any(p.step not in seen - {node.id} for p in ports):
                raise ValueError('missing or forward graph artifact/parameter dependency')
            if (node.graph.unit_id, node.graph.op, node.graph.profile, node.graph.implementation_version) != (spec.unit_id,spec.op,spec.profile,spec.implementation_version):
                raise ValueError('graph operation differs from frozen operator')
        counts[spec.id] = counts.get(spec.id, 0) + 1
        if counts[spec.id] > spec.max_instances:
            raise ValueError(f"{spec.id}: maximum instances exceeded")
        missing = [key for key in spec.requires if context.get(key) is not True]
        if missing:
            raise ValueError(
                f"{spec.id}: missing input requirements: {', '.join(missing)}"
            )
        if spec.input_stage not in {"either", input_stage}:
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
        stage = spec.output_stage if spec.output_stage != 'same' else input_stage
        stages[node.id] = stage
        highpasses[node.id] = input_highpass
    if recipe.output is not None:
        if recipe.output not in stages or recipe.output == 'raw':
            raise ValueError('unknown recipe output')
        stage = stages[recipe.output]
    if any(node_id not in seen for node_id in recipe.output_roles.values()):
        raise ValueError('output role references a missing node')
    if stage != "epochs":
        raise ValueError("pipeline must produce epochs on the shared output grid")
    for spec in space.operators:
        semantic_count = sum(counts.get(o.id, 0) for o in space.operators if (o.unit_id,o.op)==(spec.unit_id,spec.op))
        if any(n.graph for n in recipe.nodes) and spec.op in ('resample','epoch'):
            aliases={'resample':('resample','resample_fft','resample_fir','resample_eeglab'),'epoch':('epoch','epoch_with_nonfinite')}
            semantic_count=int(any(o.op in aliases[spec.op] and counts.get(o.id,0) for o in space.operators))
        if spec.required and semantic_count != 1:
            raise ValueError(f"required operator must occur exactly once: {spec.id}")
    from .rule_engine import audit, enforce
    warnings = enforce(audit(recipe, space, context))
    return recipe, warnings


def recipe_hash(recipe, space=None):
    recipe = (
        recipe
        if isinstance(recipe, PipelineRecipe)
        else PipelineRecipe.model_validate(recipe)
    )
    names = {"raw": "raw", **{n.id: str(i) for i, n in enumerate(recipe.nodes)}}
    if space is not None:
        space = space if isinstance(space, ExplorationSpace) else ExplorationSpace.model_validate(space)
    if space is not None and space.semantic_identity == "operation_contracts_v1":
        from app.preprocessing.units import OPERATIONS
        definitions = {o.id: o for o in space.operators}
        operations, previous = [], "raw"
        for n in recipe.nodes:
            op = definitions[n.operator]
            params = {**op.bindings, **n.parameters}
            schema = OPERATIONS.get((op.unit_id, op.op))
            if schema is not None and op.implementation_version == '1':
                params = {**{key: field.get_default(call_default_factory=True)
                             for key, field in schema.model_fields.items() if not field.is_required()}, **params}
            operations.append({"unit_id": op.unit_id, "op": op.op, "parameters": params,
                "dependencies": [names[n.input_from] if n.input_from else previous,
                                 names.get(n.model_from), names.get(n.decision_from)],
                "fit_scope": n.fit_scope.model_dump() if n.fit_scope else None,
                "emit_mark": op.emit_mark if op.op == "detect_bad_channels" else None})
            if n.graph:
                from .graph_recipe import rename_ports
                graph = n.graph.model_copy(deep=True)
                rename_ports(graph, names)
                operations[-1]['graph'] = {k:v for k,v in graph.model_dump(mode='json').items() if k not in {
                    'id','input','model_from','decision_from','params','evidence_indices','parameter_sources','optional','fit_scope'}}
            if op.op != "eog_fit":
                previous = names[n.id]
        payload = {"identity": space.semantic_identity, "operations": operations}
        if recipe.output is not None: payload['output'] = names[recipe.output]
        if recipe.evaluation_window: payload['evaluation_window'] = recipe.evaluation_window.model_dump()
        if recipe.output_roles: payload['output_roles'] = {k:names[v] for k,v in recipe.output_roles.items()}
        return digest(payload)
    return digest(
        {
            "operations": [
                {"operator": n.operator, "parameters": n.parameters,
                 **({"dependencies": [names.get(r, r) for r in (n.input_from, n.model_from, n.decision_from)],
                     "fit_scope": n.fit_scope.model_dump() if n.fit_scope else None}
                    if any((n.input_from, n.model_from, n.decision_from, n.fit_scope)) else {})}
                for n in recipe.nodes
            ],
        }
    )


def apply_edits(recipe, edits, space, context=None, donors=None):
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
            if value.get('output') is not None and value['output'] == edit.after_node_id:
                value['output'] = edit.node.id
        elif edit.action == "remove_operator":
            node = value["nodes"][locate(edit.node_id)]
            if not node.get("optional", True):
                raise ValueError("cannot remove a required source step")
            if edit.node_id in value.get('output_roles', {}).values():
                raise ValueError('cannot remove a named source output')
            if value.get('output') == edit.node_id:
                index = locate(edit.node_id)
                previous = node.get('input_from') or (value['nodes'][index - 1]['id'] if index else 'raw')
                value['output'] = previous
            value["nodes"].pop(locate(edit.node_id))
        elif edit.action == "swap_adjacent":
            a, b = locate(edit.first_node_id), locate(edit.second_node_id)
            if abs(a - b) != 1:
                raise ValueError("order edits must swap adjacent operators")
            value["nodes"][a], value["nodes"][b] = value["nodes"][b], value["nodes"][a]
        elif edit.action == "combine_fragment":
            donor = (donors or {}).get(edit.donor_id)
            if donor is None:
                raise ValueError("combination requires a registered donor method")
            original = donor["recipe"]["nodes"]
            selected = [n for n in original if n["id"] in edit.node_ids]
            if [n["id"] for n in selected] != edit.node_ids:
                raise ValueError("fragment must preserve donor order and use existing nodes")
            prefix = "fragment_" + digest([edit.donor_id, edit.node_ids, len(value["nodes"])])[:8] + "_"
            names = {n["id"]: prefix + n["id"] for n in selected}
            fragment = deepcopy(selected)
            for node in fragment:
                node["id"] = names[node["id"]]
                for key in ("input_from", "model_from", "decision_from"):
                    ref = node.get(key)
                    if ref is not None:
                        if ref not in names:
                            raise ValueError("fragment has external data/model/decision dependencies; include its prerequisite nodes")
                        node[key] = names[ref]
                if node.get('graph'):
                    from app.preprocessing.schemas import Step
                    from .graph_recipe import rename_ports
                    graph = Step.model_validate(node['graph'])
                    rename_ports(graph, names)
                    node['graph'] = graph.model_dump(mode='json')
            index = locate(edit.after_node_id) + 1 if edit.after_node_id is not None else 0
            value["nodes"][index:index] = fragment
            if value.get('output') is not None and value['output'] == edit.after_node_id:
                value['output'] = fragment[-1]['id']
            for role, node_id in donor['recipe'].get('output_roles', {}).items():
                if node_id in names:
                    value.setdefault('output_roles', {})[prefix + role] = names[node_id]
        else:
            raise ValueError("unsupported recipe edit")
    result, warnings = validate_recipe(value, space, context)
    if recipe_hash(result, space) == recipe_hash(base, space):
        raise ValueError("edits do not change the executable recipe")
    return result, warnings
