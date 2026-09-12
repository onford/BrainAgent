"""Reconstruct measured retrieval progress from durable tool observations."""
from time import time

from app.preprocessing.storage import digest
from .screening import urls
from .research_audit_contracts import RetrievalProgress


def progress(journal, purpose, missing, *, stop_reason=None, rationale=None):
    data = journal.read()
    content, result_urls, excerpts, actions = set(), set(), set(), []
    for row in data['actions']:
        if row['action'].get('purpose') != purpose:
            continue
        result = row.get('result') or {}
        observation = (result.get('observations') or [{}])[0]
        output = observation.get('output') or {}
        hashes = {d['sha256'] for d in result.get('documents', [])}
        found_urls = urls(output.get('items', [])) if observation.get('success') else set()
        found_excerpts = {digest([output.get('source_id'), text]) for text in output.get('excerpts', [])}
        actions.append(dict(sequence=row['sequence'], action=row['action']['action'],
            target=row['action'].get('target'), medium=row['action'].get('medium'),
            status='outcome_unknown' if not row.get('result') or row.get('uncertain') else
                'completed' if observation.get('success') else 'failed',
            reused=row.get('reused_sequence') is not None,
            new_document_contents=len(hashes-content), new_search_urls=len(found_urls-result_urls),
            new_returned_excerpts=len(found_excerpts-excerpts)))
        content.update(hashes)
        result_urls.update(found_urls)
        excerpts.update(found_excerpts)
    budget = data['budgets'][purpose]
    return RetrievalProgress(schema_version='research-progress-1', purpose=purpose, stop_reason=stop_reason or 'running',
        stop_rationale=rationale, max_actions=budget['max_actions'], reserved_actions=len(actions),
        remaining_actions=journal.remaining(purpose), expires_at=budget['expires_at'],
        seconds_left=max(0, budget['expires_at']-time()), missing_requirements=missing,
        unique_document_contents=len(content), unique_search_urls=len(result_urls),
        returned_excerpts=len(excerpts), actions=actions,
        systematic_review_complete=False,
        interpretation='Counts describe exact content/URL/excerpt novelty, not scientific novelty or sufficient evidence. Required attempts and explicit gaps govern stopping; no paper-count target.').model_dump(mode='json')
