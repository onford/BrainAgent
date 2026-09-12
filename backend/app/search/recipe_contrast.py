"""Describe frozen recipe differences without inferring their measured effects."""

from collections import Counter
from copy import deepcopy


def contrast(parent, candidate, space):
    operators = {op["id"]: op for op in space["operators"]}

    def describe(entry):
        counts, rows, names = Counter(), {}, {'raw': 'raw'}
        order = []
        for node in entry["recipe"]["nodes"]:
            op = operators[node["operator"]]
            name = op["unit_id"] + "/" + op["op"]
            counts[name] += 1
            key = f"{name}#{counts[name]}"
            names[node['id']] = key
            order.append(key)
            rows[key] = {"parameters": {**op["bindings"], **node["parameters"]},
                         "model_port": node.get("model_from"), "decision_port": node.get("decision_from"),
                         "fit_scope": node.get("fit_scope")}
        previous = 'raw'
        for node, key in zip(entry['recipe']['nodes'], order):
            row = rows[key]
            row.update(data_port=names.get(node.get('input_from'), previous),
                       model_port=names.get(row['model_port']), decision_port=names.get(row['decision_port']))
            graph = deepcopy(node.get('graph') or {})
            if graph:
                from app.preprocessing.schemas import Step
                from .graph_recipe import rename_ports
                step = Step.model_validate(graph)
                rename_ports(step, names)
                graph = {k:v for k,v in step.model_dump(mode='json').items() if k not in {
                    'id','input','model_from','decision_from','params','evidence_indices','parameter_sources','optional','fit_scope'}}
            row['graph_contract'] = graph
            previous = key
        return rows, order

    before, first = describe(parent)
    after, second = describe(candidate)
    shared = set(before) & set(after)
    changes = []
    for key in first:
        if key not in shared:
            continue
        for parameter in sorted(before[key]["parameters"].keys() | after[key]["parameters"].keys()):
            a, b = before[key]["parameters"].get(parameter), after[key]["parameters"].get(parameter)
            if a != b:
                changes.append({"operation": key, "parameter": parameter, "before": a, "after": b})
    return {"base_candidate_id": parent["id"], "candidate_id": candidate["id"],
        "removed_operations": [key for key in first if key not in after],
        "added_operations": [key for key in second if key not in before], "parameter_changes": changes,
        "shared_operation_order_changed": [k for k in first if k in shared] != [k for k in second if k in shared],
        "before_order": first, "after_order": second,
        "scope_changes": [key for key in sorted(shared) if any(before[key][k] != after[key][k] for k in ("data_port", "model_port", "decision_port", "fit_scope", "graph_contract"))],
        "changed_contracts": {key:{'before':before[key],'after':after[key]} for key in sorted(shared) if before[key]!=after[key]},
        "evaluation_window_before": parent['recipe'].get('evaluation_window'),
        "evaluation_window_after": candidate['recipe'].get('evaluation_window'),
        "interpretation": "配置差异清单，不证明数值差异、因果效应或单因素设计；模型/决策端口的完整连线以原配方为准。"}


def contrasts_to_reference(state):
    registry = state.get("registry", [])
    reference = next((e for e in registry if e["id"] == state["protocol"].get("baseline_id", "bp8-30-average")), None)
    return {e["id"]: contrast(reference, e, state["protocol"]["space"]) for e in registry if e != reference} if reference else {}
