import pytest
from pydantic import TypeAdapter, ValidationError

from app.workflows.planning_contracts import verification_contract


def publication(ids):
    field = verification_contract(None, ids).model_fields['official_publication']
    return TypeAdapter(field.annotation)


def value(role, source):
    return dict(role=role, source_id=source, basis_finding_ids=['official-citation'],
                explanation='A citation alone does not establish a completed paper read.')


@pytest.mark.parametrize('role', ['dataset_paper', 'acquisition_system'])
@pytest.mark.parametrize('source', [None, 'official-website', 'unread-paper'])
def test_identified_publication_requires_an_actually_read_paper_id(role, source):
    with pytest.raises(ValidationError):
        publication(['read-paper-a', 'read-paper-b']).validate_python(value(role, source))


@pytest.mark.parametrize('role', ['dataset_paper', 'acquisition_system'])
def test_read_source_id_is_allowed_but_still_requires_semantic_verification(role):
    result = publication(['read-paper-a']).validate_python(value(role, 'read-paper-a'))
    assert result.source_id == 'read-paper-a'
    # This schema only checks identity. Existing validate_verification still
    # requires actual source quotes and the official citation evidence.


@pytest.mark.parametrize('ids', [[], ['read-paper-a']])
def test_unconfirmed_citation_has_explicit_null_source(ids):
    assert publication(ids).validate_python(value('not_identified', None)).source_id is None
    with pytest.raises(ValidationError):
        publication(ids).validate_python(value('not_identified', 'read-paper-a'))


@pytest.mark.parametrize('role', ['dataset_paper', 'acquisition_system'])
def test_no_read_papers_allows_only_unidentified(role):
    with pytest.raises(ValidationError):
        publication([]).validate_python(value(role, 'invented-paper'))


def test_model_schema_exposes_only_the_read_paper_choices():
    schema = verification_contract(None, ['read-paper-a', 'read-paper-b']).model_json_schema()
    identified = schema['$defs']['ReadOfficialPublication']['properties']
    assert identified['source_id']['enum'] == ['read-paper-a', 'read-paper-b']
    assert schema['$defs']['UnidentifiedPublication']['properties']['source_id']['type'] == 'null'
