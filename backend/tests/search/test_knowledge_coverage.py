from copy import deepcopy

import pytest

from app.search.knowledge_coverage import coverage
from app.search.scientific_space import build_space, knowledge
from app.preprocessing.storage import digest
from tests.search.test_controller import factory  # noqa: F401


def test_catalog_coverage_keeps_every_rule_parameter_and_explicit_gap():
    book = knowledge().model_dump(mode='json')
    before = deepcopy(book)
    space = build_space({})
    result = coverage(book, space, {'rules':[{'id':'advisory', 'knowledge_rule_ids':['R17']}]}, 'motor_imagery')
    assert book == before
    assert {r['rule_id'] for r in result['rules']} == {r['id'] for r in book['rules']}
    assert result['counts']['operator_pairs'] == len(book['operators'])*(len(book['operators'])-1)//2
    assert result['counts']['relation_gaps'] == sum(bool(p['gap'] or not p['rule_ids']) for p in book['pair_coverage'])
    assert len({r['id'] for r in result['agenda']}) == len(result['agenda'])
    assert sum(r['kind']=='parameter_review' for r in result['agenda']) == len(book['parameters'])
    indexed = {r['rule_id']:r for r in result['rules']}
    assert indexed['R69']['status'] == 'partial_predicate_binding'
    assert indexed['R17']['status'] == 'conditional_advisory_binding'
    assert not result['stopping']['all_topics_resolved']
    assert not any(r['complete_claim_enforced'] for r in result['rules'])
    assert digest({k:v for k,v in result.items() if k!='coverage_sha256'}) == result['coverage_sha256']


def test_rule_link_requires_exact_catalog_identity():
    book = knowledge().model_dump(mode='json')
    space = build_space({})
    space.priors[0].knowledge_rule_ids = ['invented']
    with pytest.raises(ValueError, match='unknown research rule'):
        coverage(book, space, {'rules':[]}, 'fixture')


def test_revoked_binding_never_counts_as_an_active_predicate():
    space = build_space({})
    for rule in space.priors:
        if 'R69' in rule.knowledge_rule_ids:
            rule.status = 'revoked'
            rule.change_reason = 'Fixture revocation, not a claim about the real source'
    result = coverage(knowledge().model_dump(mode='json'), space, {'rules':[]}, 'fixture')
    row = next(r for r in result['rules'] if r['rule_id']=='R69')
    assert row['status'] == 'catalog_only'
    assert row['executable_bindings'] and all(b['status']=='revoked' for b in row['executable_bindings'])


@pytest.mark.asyncio
async def test_frozen_agenda_tampering_stops_before_candidate_execution(factory):
    from app.search.io import read, write
    service, _, state = factory()
    root = service.folder(state['id'])
    agenda = read(root/'knowledge-coverage.json')
    assert digest(agenda) == state['protocol']['knowledge_coverage_hash']
    agenda['stopping']['all_topics_resolved'] = True
    write(root/'knowledge-coverage.json', agenda)
    await service.run('owner', state['id'])
    outcome = service.get('owner', state['id'])
    assert outcome['status'] == 'failed'
    assert '研究覆盖' in outcome['error']
    assert not outcome['candidates']
