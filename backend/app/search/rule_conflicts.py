"""Conservative contradictions between requirements on the same bound variable."""
import math


def impossible(clauses):
    from .rule_engine import COMPARE
    equal = [c['value'] for c in clauses if c['comparison']=='eq']
    finite = next((c['value'] for c in clauses if c['comparison']=='in' and isinstance(c['value'], (list,tuple))), None)
    choices = equal[:1] if equal else finite
    if choices is not None:
        for value in choices:
            try:
                if all(COMPARE[c['comparison']](value, c['value']) for c in clauses):
                    return False
            except (TypeError, ValueError):
                return False  # Not proven contradictory.
        return True
    if any(type(c['value']) not in (int,float) or not math.isfinite(c['value']) for c in clauses):
        return False
    lo, hi, lo_closed, hi_closed = -math.inf, math.inf, False, False
    excluded = set()
    for c in clauses:
        op, value = c['comparison'], c['value']
        if op in ('gt','ge'):
            if value > lo:
                lo, lo_closed = value, op=='ge'
            elif value == lo:
                lo_closed &= op=='ge'
        elif op in ('lt','le'):
            if value < hi:
                hi, hi_closed = value, op=='le'
            elif value == hi:
                hi_closed &= op=='le'
        elif op=='ne':
            excluded.add(value)
        else:
            return False
    return lo > hi or lo == hi and (not lo_closed or not hi_closed or lo in excluded)


def parameter_conflicts(left, right):
    def grouped(row):
        groups = {}
        for clause in row.get('requirement_constraints', []):
            key = (clause['scope'], clause['node_id'], clause['key'])
            groups.setdefault(key, []).append(clause)
        return groups
    a, b = grouped(left), grouped(right)
    return [dict(scope=key[0], node_id=key[1], key=key[2], requirements=a[key]+b[key])
            for key in sorted(a.keys() & b.keys()) if impossible(a[key]+b[key])]
