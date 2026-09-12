from types import SimpleNamespace

import pytest

from app.workflows.cognition_contracts import ResearchAction, ResearchSources, ToolObservation, Finding
from app.workflows.research_journal import ResearchJournal
from app.workflows.research_progress import progress
from app.workflows.evidence_grades import grade_review
from app.workflows.survey_contracts import LiteratureEntry
from tests.workflows.fakes import Reader, TEXT


@pytest.mark.asyncio
async def test_reused_content_has_zero_gain_and_budget_stop_preserves_gaps(tmp_path):
    sources = ResearchSources(documents=[], observations=[])
    journal = ResearchJournal(tmp_path / 'journal.json', sources)
    journal.bind_budget('literature_review', 2, {}, 90)
    action = ResearchAction(action='read', url='https://example.org/paper', rationale='read',
        purpose='literature_review', target='preprocessing_methods', medium='paper')
    ticket = journal.reserve([action])[0]
    document = await Reader().read(action.url, 'paper')
    journal.complete(ticket, ResearchSources(documents=[document], observations=[ToolObservation(
        sequence=ticket['sequence'], action=action, success=True, output={'source_id':document.id}, error=None)]))
    journal.reserve([action])
    result = progress(journal, 'literature_review', ['unread implementation'], stop_reason='action_budget_exhausted')
    assert result['unique_document_contents'] == 1
    assert [r['new_document_contents'] for r in result['actions']] == [1, 0]
    assert result['remaining_actions'] == 0 and result['systematic_review_complete'] is False
    assert result['missing_requirements'] == ['unread implementation']


@pytest.mark.asyncio
async def test_popular_source_and_literal_quote_do_not_claim_parameter_support_or_execution():
    doc = await Reader().read('https://example.org/paper', 'paper')
    entry = LiteratureEntry(id='entry', source_id=doc.id, target='preprocessing_methods',
        medium='paper', decision='included', reason='Source methods', reading_scope='full_text',
        findings=[Finding(id='f', topic='methods', statement='A source observation', source_id=doc.id, quote=TEXT)],
        related_urls=[], quality={'stars':1000000, 'citations':1000000, 'observation_ids':[]})
    review = SimpleNamespace(entries=[entry], model_dump=lambda **kwargs: {'entries':[entry.model_dump()]})
    sources = ResearchSources(documents=[doc], observations=[])
    row = grade_review(review, sources)['rows'][0]
    assert row['access_grade'] == 'located_source_text'
    assert row['scientific_parameter_support'] == 'requires_method_parameter_review'
    assert row['execution_grade'] == 'not_established_by_literature_screening'
    assert row['independent_reproduction'] == 'not_established'
    assert doc.text[row['finding_spans'][0]['start']:row['finding_spans'][0]['end']] == TEXT
    entry.findings[0].quote = 'Invented source text.'
    with pytest.raises(ValueError, match='located source findings'):
        grade_review(review, sources)
