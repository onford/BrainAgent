"""Compact navigation context; evidence extraction still reads saved source text."""
from app.preprocessing.storage import digest
from .screening import urls


def navigation_context(sources):
    documents = [{**d.model_dump(exclude={'text'}),
        'preview': d.text[:1200], 'preview_characters': min(len(d.text), 1200),
        'available_source_characters': len(d.text), 'preview_is_full_source': len(d.text) <= 1200}
        for d in sources.documents]
    observations = []
    for observation in sources.observations:
        output = observation.output or {}
        items = []
        for item in output.get('items', []):
            if not isinstance(item, dict):
                continue
            row = {k: item[k] for k in ('title','venue','citations','stars','year','published','doi') if k in item}
            row['urls'] = sorted(urls(item))
            abstract = item.get('abstract') or item.get('summary') or ''
            if isinstance(abstract, str):
                row.update(abstract_preview=abstract[:600], abstract_characters=len(abstract))
            items.append(row)
        observations.append({**observation.model_dump(exclude={'output'}), 'output': {
            'source_id': output.get('source_id'), 'items': items,
            'urls': sorted(urls(output)), 'raw_output_sha256': digest(output),
            'raw_output_location': 'survey/sources.json',
        }})
    return dict(sources=documents, observations=observations,
        navigation_context_policy=('These are literal previews and observed navigation metadata, not full evidence or scientific summaries. '
            'All source IDs, source hashes, discovered URLs, queries and action outcomes are retained. '
            'Full text remains in saved sources and is supplied separately to verification, screening and method extraction. '
            'Do not infer full reading from a preview. Request a focused read.query to resolve an uncovered question.'))
