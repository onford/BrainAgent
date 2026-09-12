"""Versioned rule decisions over actual signal and artifact ancestry.

Research prose is not an executable predicate. Cross-implementation matching
requires an explicit declaration in the frozen prior, never an inferred alias.
"""
import operator

from app.preprocessing.storage import digest

COMPARE = dict(eq=operator.eq, ne=operator.ne, lt=operator.lt, le=operator.le,
               gt=operator.gt, ge=operator.ge, **{'in': lambda a, b: a in b})


def _ancestry(recipe):
    signal, dependencies, previous = {'raw': set()}, {'raw': set()}, 'raw'
    for node in recipe.nodes:
        parent = node.input_from or previous
        if parent not in signal or node.id in signal:
            raise ValueError('rule audit requires unique nodes and preceding signal dependencies')
        signal[node.id] = {parent} | signal[parent]
        refs = {parent, *[r for r in (node.model_from, node.decision_from) if r]}
        if node.graph:
            from app.preprocessing.ports import sources
            refs.update(p.step for p in node.graph.artifact_inputs.values())
            refs.update(p.step for expression in node.graph.parameter_inputs.values() for p in sources(expression))
        dependencies[node.id] = set(refs)
        for ref in refs:
            if ref not in dependencies or ref == node.id:
                raise ValueError('rule audit requires preceding model/decision/artifact dependencies')
            dependencies[node.id].update(dependencies[ref])
        previous = node.id
    return signal, dependencies


def audit(recipe, space, context=None):
    context = context or {}
    operators = {o.id: o for o in space.operators}
    signal, dependencies = _ancestry(recipe)
    rows = []
    for prior in space.priors:
        row = dict(prior_id=prior.id, revision=prior.revision,
            knowledge_rule_ids=prior.knowledge_rule_ids,
            rule_sha256=digest(prior.model_dump(mode='json')), strength=prior.strength,
            evidence_ids=prior.evidence_ids, status='not_applicable',
            reason=prior.rationale, matched_nodes={}, condition_values=[], conflicts_with=[],
            exceptions=[], required_edges=[], forbidden_pairs=[], requirement_constraints=[])
        rows.append(row)
        if prior.status == 'revoked':
            row.update(status='revoked', reason=prior.change_reason)
            continue

        def matches(identity):
            target = operators[identity]
            return [n for n in recipe.nodes
                if operators[n.operator].implementation_version in prior.implementation_versions
                and (n.operator == identity or (prior.operator_match == 'unit_operation'
                and (operators[n.operator].unit_id, operators[n.operator].op) == (target.unit_id, target.op)))]

        matched = {identity: matches(identity) for identity in prior.operators}
        row['matched_nodes'] = {k: [n.id for n in v] for k, v in matched.items()}
        if not any(matched.values()):
            # A related implementation is not equivalent to an explicit rule
            # selector; make this coverage gap visible instead of inventing it.
            units = {operators[k].unit_id for k in prior.operators}
            if any(operators[n.operator].unit_id in units for n in recipe.nodes):
                row.update(status='unbound_variant', reason='相关实现未绑定此规则的版本/算子选择器；不能声称已校验。' + prior.rationale)
            continue
        first, *rest = prior.operators
        if not matched[first] or prior.relation == 'before' and not matched[rest[0]]:
            continue

        def predicate(p):
            missing = object()
            def unresolved(value):
                if value is missing or isinstance(value, str) and value.startswith('$'):
                    return True
                if isinstance(value, (list, tuple)):
                    return any(unresolved(v) for v in value)
                if isinstance(value, dict):
                    return any(unresolved(v) for v in value.values())
                return False
            values = ([context[p.key]] if p.key in context and context[p.key] is not None else []) if p.scope == 'context' else [
                {**operators[n.operator].bindings, **n.parameters}.get(p.key, missing) for n in matches(p.operator)]
            if not values or any(unresolved(v) for v in values):
                return None
            try:
                return all(COMPARE[p.comparison](value, p.value) for value in values)
            except (TypeError, ValueError):
                return None

        conditions = [predicate(p) for p in prior.when]
        row['condition_values'] = conditions
        if any(v is False for v in conditions):
            continue
        if any(v is None for v in conditions):
            row.update(status='unknown', reason='适用条件未知，不能视为不适用：' + prior.rationale)
            continue
        for exception in prior.exceptions:
            values = [predicate(p) for p in exception.when]
            applies = False if any(v is False for v in values) else None if any(v is None for v in values) else True
            row['exceptions'].append(dict(id=exception.id, condition_values=values,
                applies=applies, reason=exception.reason, evidence_ids=exception.evidence_ids))
        if any(e['applies'] is True for e in row['exceptions']):
            row.update(status='exception_applies', reason='有已满足条件及证据绑定的经验规则例外；硬约束仍独立检查。')
            continue
        if prior.relation == 'before':
            pairs = [(a, b) for a in matched[first] for b in matched[rest[0]]
                     if a.id in signal[b.id] or b.id in signal[a.id]]
            if not pairs:
                continue
            row['required_edges'] = [[a.id, b.id] for a, b in pairs]
            violated = any(a.id not in signal[b.id] for a, b in pairs)
        elif prior.relation == 'requires':
            # A multi-instance requires clause offers alternatives; it does not
            # require every matching node. Only singleton obligations form edges.
            row['required_edges'] = [[matched[key][0].id, a.id] for a in matched[first] for key in rest if len(matched[key])==1]
            violated = any(not all(any(b.id in dependencies[a.id] for b in matched[k]) for k in rest)
                           for a in matched[first])
        elif prior.relation == 'incompatible':
            if len(prior.operators)==2:
                row['forbidden_pairs'] = [sorted((a.id,b.id)) for a in matched[first] for b in matched[rest[0]]]
            violated = all(matched[k] for k in rest)
        else:
            row['requirement_constraints'] = [dict(scope=p.scope, node_id=node_id, key=p.key,
                comparison=p.comparison, value=p.value) for p in prior.requirements
                for node_id in ([None] if p.scope=='context' else [n.id for n in matches(p.operator)])]
            required = [predicate(p) for p in prior.requirements]
            row['requirement_values'] = required
            if any(v is None for v in required) and not any(v is False for v in required):
                row.update(status='unknown', reason='必要参数条件尚未取得：' + prior.rationale)
                continue
            violated = not all(required)
        row['status'] = 'violated' if violated else 'satisfied'

    applicable = [r for r in rows if r['status'] in {'satisfied', 'violated'}]
    conflict_sets = []
    for i, row in enumerate(applicable):
        edges = {tuple(edge) for edge in row['required_edges']}
        forbidden = {tuple(pair) for pair in row['forbidden_pairs']}
        for other in applicable[i+1:]:
            other_edges = {tuple(edge) for edge in other['required_edges']}
            other_forbidden = {tuple(pair) for pair in other['forbidden_pairs']}
            conflicting = (edges & {(b,a) for a,b in other_edges})
            excluded = ({tuple(sorted(e)) for e in edges} & other_forbidden) | ({tuple(sorted(e)) for e in other_edges} & forbidden)
            from .rule_conflicts import parameter_conflicts
            parameters = parameter_conflicts(row, other)
            if not conflicting and not excluded and not parameters:
                continue
            row['conflicts_with'].append(other['prior_id'])
            other['conflicts_with'].append(row['prior_id'])
            hard = [r['prior_id'] for r in (row,other) if r['strength']=='hard']
            conflict_sets.append(dict(rule_ids=[row['prior_id'],other['prior_id']],
                node_pairs=sorted([list(p) for p in conflicting | excluded]), parameter_conflicts=parameters, hard_rule_ids=hard,
                resolution='hard_constraints_block' if len(hard)==2 else 'hard_constraint_precedence' if hard else 'diagnostic_or_explicit_challenge_required'))
    return dict(schema_version='rule-audit-1',
                recipe_sha256=digest(recipe.model_dump(mode='json')),
                rules_sha256=digest([p.model_dump(mode='json') for p in space.priors]),
                decisions=rows, conflict_sets=conflict_sets)


def enforce(result):
    failures = [r for r in result['decisions'] if r['strength'] == 'hard' and r['status'] in {'violated', 'unknown'}]
    if failures:
        raise ValueError('; '.join(r['prior_id'] + ': ' + r['reason'] for r in failures))
    return [{k: r[k] for k in ('prior_id', 'reason', 'evidence_ids')}
            for r in result['decisions'] if r['status'] in {'violated', 'unknown'}]
