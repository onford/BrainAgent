"""Evidence access and execution are separate dimensions, never a popularity score."""
from app.preprocessing.storage import digest
from .source_reader import abstract_only
from .research_audit_contracts import EvidenceGrades


def grade_review(review, sources):
    documents = {d.id: d for d in sources.documents}
    rows = []
    for entry in review.entries:
        doc = documents[entry.source_id]
        located = []
        for finding in entry.findings:
            start = doc.text.find(finding.quote)
            if start < 0 or finding.source_id != doc.id:
                raise ValueError('evidence grade requires located source findings')
            located.append(dict(finding_id=finding.id, source_sha256=doc.sha256,
                start=start, end=start+len(finding.quote), quote_sha256=digest(finding.quote),
                duplicate_span_count=doc.text.count(finding.quote)))
        abstract = abstract_only(doc) or entry.reading_scope == 'abstract'
        access = 'abstract_only' if abstract else 'located_source_text' if located else 'source_text_without_located_findings'
        rows.append(dict(entry_id=entry.id, source_id=doc.id, source_url=doc.url,
            source_sha256=doc.sha256, retrieved_at=doc.retrieved_at,
            reading_scope=entry.reading_scope, access_grade=access, source_truncated=doc.truncated,
            decision=entry.decision, finding_spans=located,
            scientific_parameter_support='requires_method_parameter_review',
            execution_grade='not_established_by_literature_screening',
            independent_reproduction='not_established',
            observed_popularity=entry.quality.model_dump(mode='json')))
    return EvidenceGrades(schema_version='evidence-grades-1', review_sha256=digest(review.model_dump(mode='json')),
        rows=rows, interpretation='Exact source access, semantic support, execution and independent reproduction are separate. Citations, venue and stars do not promote any evidence grade. Duplicate literal passages retain ambiguity; offsets locate the first occurrence and its count, not a fabricated unique passage.').model_dump(mode='json')
