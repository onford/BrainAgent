"""Dependency closure for replaying a fit inside its declared partition."""
from .ports import sources


def dependencies(step):
    names = [step.input, step.model_from, step.decision_from]
    names.extend(p.step for p in step.artifact_inputs.values())
    names.extend(p.step for expression in step.parameter_inputs.values() for p in sources(expression))
    return [name for name in names if name and name != 'raw']


def replay_ancestors(step, steps):
    by_id = {s.id: s for s in steps}
    selected, visiting = set(), set()

    def visit(name):
        if name in selected:
            return
        if name == step.id or name in visiting or name not in by_id:
            raise ValueError('partition replay requires a closed acyclic dependency graph')
        visiting.add(name)
        ancestor = by_id[name]
        if ancestor.fit_scope and ancestor.fit_scope != step.fit_scope:
            raise ValueError('partition replay cannot reinterpret a different explicit fit partition')
        if ancestor.decision and ancestor.decision.mode == 'manual':
            raise ValueError('partition replay cannot reuse a manual decision bound to another data context')
        for dependency in dependencies(ancestor):
            visit(dependency)
        visiting.remove(name)
        selected.add(name)

    for name in dependencies(step):
        visit(name)
    return [ancestor for ancestor in steps if ancestor.id in selected]


def replay_work(steps):
    """Conservative extra operation inventory for memory/disk reservations."""
    return [ancestor for step in steps if step.implementation_version == '2' and step.fit_scope
            for ancestor in replay_ancestors(step, steps)]
