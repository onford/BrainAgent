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
            reason=prior.rationale, matched_nodes={}, condition_values=[], conflicts_with=[])
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

        def predicate(p):
            values = ([context[p.key]] if p.key in context else []) if p.scope == 'context' else [
                {**operators[n.operator].bindings, **n.parameters}.get(p.key) for n in matches(p.operator)]
            if not values or any(v is None for v in values):
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
        first, *rest = prior.operators
        if not matched[first]:
            continue
        if prior.relation == 'before':
            pairs = [(a, b) for a in matched[first] for b in matched[rest[0]]
                     if a.id in signal[b.id] or b.id in signal[a.id]]
            if not pairs:
                continue
            violated = any(a.id not in signal[b.id] for a, b in pairs)
        elif prior.relation == 'requires':
            violated = any(not all(any(b.id in dependencies[a.id] for b in matched[k]) for k in rest)
                           for a in matched[first])
        elif prior.relation == 'incompatible':
            violated = all(matched[k] for k in rest)
        else:
            required = [predicate(p) for p in prior.requirements]
            row['requirement_values'] = required
            if any(v is None for v in required) and not any(v is False for v in required):
                row.update(status='unknown', reason='必要参数条件尚未取得：' + prior.rationale)
                continue
            violated = not all(required)
        row['status'] = 'violated' if violated else 'satisfied'

    by_id = {p.id: p for p in space.priors}
    applicable = [r for r in rows if r['status'] in {'satisfied', 'violated'}]
    for row in applicable:
        rule = by_id[row['prior_id']]
        if rule.relation == 'before':
            row['conflicts_with'] = [other['prior_id'] for other in applicable
                if by_id[other['prior_id']].relation == 'before'
                and by_id[other['prior_id']].operators == list(reversed(rule.operators))]
    return dict(schema_version='rule-audit-1',
                recipe_sha256=digest(recipe.model_dump(mode='json')),
                rules_sha256=digest([p.model_dump(mode='json') for p in space.priors]),
                decisions=rows)


def enforce(result):
    failures = [r for r in result['decisions'] if r['strength'] == 'hard' and r['status'] in {'violated', 'unknown'}]
    if failures:
        raise ValueError('; '.join(r['prior_id'] + ': ' + r['reason'] for r in failures))
    return [{k: r[k] for k in ('prior_id', 'reason', 'evidence_ids')}
            for r in result['decisions'] if r['status'] in {'violated', 'unknown'}]
