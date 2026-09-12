import pytest

from app.workflows.collection_contracts import ReportedExclusion
from app.workflows.exclusion_evidence import subject_numbers, validate_claim
from app.workflows.intake import literature_matches
from types import SimpleNamespace


def claim(text, ids, claim_type='exclusion'):
    value = ReportedExclusion(entry_id='paper', object_type='subject', reported_ids=ids,
        finding_ids=['f'], reason='Source report', object_quote=text, claim_type=claim_type)
    return value, {'findings': [{'id': 'f', 'quote': text}]}


def test_explicit_ranges_are_supported_but_other_numbers_are_not_subject_ids():
    text = 'Subjects 88–90 and S100 were excluded because of artifacts above 32 Hz.'
    assert subject_numbers(text) == {88, 89, 90, 100}
    validate_claim(*claim(text, ['88', 'S089', '90', '100']))
    with pytest.raises(ValueError, match='subject IDs'):
        validate_claim(*claim(text, ['32']))
    assert subject_numbers('20 subjects, sampled at 160 Hz, were excluded.') == set()
    assert subject_numbers('Subjects 81+ were excluded.') == set()


@pytest.mark.parametrize('text', [
    'Subjects: 1-10. We evaluated an included subset.',
    'Subjects 1-10 were included; others were excluded.',
    'No subjects 1-10 were excluded.',
    'Subjects 1-10 were not excluded.',
])
def test_inclusion_mixed_and_negated_claims_cannot_be_exclusion_flags(text):
    with pytest.raises(ValueError):
        validate_claim(*claim(text, ['1']))


def test_scope_claim_is_retained_without_flagging_local_data():
    value, entry = claim('Subjects: 1-10.', [str(i) for i in range(1, 11)], 'inclusion_scope')
    validate_claim(value, entry)
    result = literature_matches(SimpleNamespace(literature_exclusions=[value]),
        {'records': [{'id': 'S001R04', 'subject': 'S001'}]})
    row = result.records[0]
    assert row.reported_ids == value.reported_ids
    assert row.match_status == 'scope_only' and row.local_objects == []
    assert row.action == '不处理'


def test_object_span_must_be_literal_and_uncertain_ids_remain_empty():
    value, entry = claim('Subjects 88 and 89 were excluded.', ['88'])
    value.object_quote = 'Subjects 88 to 99 were excluded.'
    with pytest.raises(ValueError, match='exact short span'):
        validate_claim(value, entry)
    value, entry = claim('Twenty subjects were excluded.', ['20'], 'unspecified')
    with pytest.raises(ValueError, match='reported_ids empty'):
        validate_claim(value, entry)
