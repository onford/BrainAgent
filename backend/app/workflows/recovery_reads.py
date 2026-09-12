"""Shared intake/workflow supplementary reads with durable result reuse."""
from .cognition_contracts import ResearchAction, ResearchSources, ToolObservation
from .research_journal import ResearchJournal


async def read_source(reader, url, kind, root):
    action = ResearchAction(action='read', url=url, kind=kind,
        purpose='literature_review', target='preprocessing_methods',
        medium='repository' if kind=='code' else 'paper', rationale='Read a source-linked dependency to resolve a recorded method blocker')
    journal = ResearchJournal(root / 'recovery-tools.json', ResearchSources(documents=[], observations=[]))
    # The caller reserves the shared recovery action budget first. A known
    # failed response may be retried by a later explicit action; an uncertain
    # interrupted request is never silently resent.
    ticket = journal.reserve([action], reuse_failures=False)[0]
    if ticket['result']:
        result = ResearchSources.model_validate(ticket['result'])
        if not result.observations[0].success:
            raise ValueError(result.observations[0].error)
        source_id = (result.observations[0].output or {}).get('source_id')
        return next(d for d in result.documents if d.id == source_id)
    try:
        document = await reader.read(url, kind)
    except Exception as exc:
        journal.complete(ticket, ResearchSources(documents=[], observations=[ToolObservation(
            sequence=ticket['sequence'], action=action, success=False, output=None,
            error=f'{type(exc).__name__}: {str(exc)[:1000]}')]))
        raise
    journal.complete(ticket, ResearchSources(documents=[document], observations=[ToolObservation(
        sequence=ticket['sequence'], action=action, success=True,
        output={'source_id':document.id}, error=None)]))
    return document
