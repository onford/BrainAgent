"""A frozen, finite research agenda; source links are not proof of completeness."""
from collections import Counter

from app.preprocessing.storage import digest
from .knowledge_contracts import ScientificKnowledge


def coverage(book, space, neural, task):
    book = ScientificKnowledge.model_validate(book).model_dump(mode='json')
    known = {r['id'] for r in book['rules']}
    from .knowledge_registry import inactive
    _, inactive_rules = inactive(book)
    predicates, advisories = {}, {}
    for prior in space.priors:
        if not set(prior.knowledge_rule_ids) <= known:
            raise ValueError('executable prior links to unknown research rule')
        for identity in prior.knowledge_rule_ids:
            predicates.setdefault(identity, []).append(dict(prior_id=prior.id, revision=prior.revision,
                status=prior.status, rule_sha256=digest(prior.model_dump(mode='json')),
                implementation_versions=prior.implementation_versions, operator_match=prior.operator_match))
    for prior in neural['rules']:
        if not set(prior['knowledge_rule_ids']) <= known:
            raise ValueError('neural advisory links to unknown research rule')
        for identity in prior['knowledge_rule_ids']:
            advisories.setdefault(identity, []).append(prior['id'])
    rows, agenda = [], []
    for rule in book['rules']:
        bindings = predicates.get(rule['id'], [])
        advisory = advisories.get(rule['id'], [])
        status = ('partial_predicate_binding' if any(b['status']=='active' for b in bindings)
                  else 'conditional_advisory_binding' if advisory else 'catalog_only')
        if rule['id'] in inactive_rules:
            status='inactive_research'
        row = dict(rule_id=rule['id'], rule_sha256=digest(rule), strength=rule['strength'],
            source_ids=rule['source_ids'], scope=rule['scope'], conditions=rule['condition'],
            status=status, executable_bindings=bindings, advisory_bindings=advisory,
            complete_claim_enforced=False, current_run_source_refresh='not_performed_by_catalog_compiler')
        rows.append(row)
        agenda.append(dict(id='rule:'+rule['id'], kind='rule_review', source_ids=rule['source_ids'],
            operator_ids=sorted({p[k] for p in rule['pairs'] for k in ('a','b')}),
            task=task, priority=1 if rule['strength'] in ('hard_math','hard_contract') else 2,
            question=rule['claim'], required_context=rule['condition'],
            next_checks=['核对任务、污染、参数语义、失效条件和反证',
                         '区分可测谓词、原生合同与只能保留的解释；补齐作用域后再绑定'],
            status='review_required', stop_reason='catalog_snapshot_not_new_evidence'))
    gaps = [p for p in book['pair_coverage'] if p['gap'] or not p['rule_ids']]
    for pair in gaps:
        agenda.append(dict(id='pair:'+':'.join(sorted((pair['a'],pair['b']))), kind='relation_gap',
            task=task, operator_ids=[pair['a'],pair['b']], source_ids=[], priority=3,
            related_rule_ids=pair['rule_ids'], question=pair['gap'] or '未找到已登记关系证据',
            next_checks=['查找任务及污染条件相符的直接比较、顺序例外和损伤测量；无证据时保持未知'],
            status='evidence_required', stop_reason='unresolved_catalog_gap'))
    for parameter in book['parameters']:
        agenda.append(dict(id='parameter:'+parameter['id'], kind='parameter_review', task=task,
            operator_ids=[parameter['operator']], source_ids=parameter['source_ids'], priority=2,
            question=parameter['parameter'], required_context=parameter['conditions'],
            next_checks=[parameter['validity_gates']], status='review_required',
            stop_reason='parameter_anchor_is_not_a_validated_search_range'))
    agenda.sort(key=lambda row: (row['priority'], row['id']))
    result = dict(schema_version='knowledge-coverage-1', knowledge_sha256=digest(book),
        task=task, rules=rows, agenda=agenda,
        counts=dict(sources=len(book['sources']), operators=len(book['operators']), rules=len(rows),
            operator_pairs=len(book['pair_coverage']), relation_gaps=len(gaps),
            parameter_topics=len(book['parameters']), binding_status=dict(Counter(r['status'] for r in rows)),
            complete_claims_enforced=0),
        stopping=dict(status='open', reason='finite_catalog_audit; no exhaustive research claim',
            unresolved_topics=len(agenda), all_topics_resolved=False),
        limitations=['关系有规则引用不等于条件充分或已被实测验证。',
                    '有限谓词和条件建议只覆盖原研究结论的一部分；执行回执仍须单独核验。',
                    '缺口队列没有在本步骤自动获得新证据，也不授权撤回目标。'])
    return {**result, 'coverage_sha256':digest(result)}
