"""One cached extraction, verification and recovery path for both public entries."""
import asyncio
from time import monotonic

from app.preprocessing.literature import INSTRUCTION, LiteratureExtraction, materialize
from app.preprocessing.schemas import Evidence
from app.preprocessing.storage import digest, write_json
from app.search.io import read
from .literature_recovery import recover


def validate_extraction(value, evidence, data, identity):
    # A malformed port is a correctable output-contract error, not an unknown
    # scientific prerequisite. Return it to the model before registering drafts.
    for branch in value.branches:
        method = branch.method
        ids = {step.id for step in method.recipe}
        for role, node in method.output_roles.items():
            if node not in ids:
                raise ValueError(
                    f'{branch.branch_id}: output_roles[{role!r}] must be an exact recipe step ID, '
                    'not a description. Use {} when no additional named outputs are required.')
    return materialize(value, evidence, data, identity)


async def extract_source(cognition, inputs, evidence, data, identity, root, budget):
    request_hash = digest(inputs)
    write_json(root / 'input.json', inputs)
    resolved = root / 'resolved-extraction.json'
    if resolved.exists():
        cached = read(resolved)
        if cached['input_hash'] != request_hash:
            raise ValueError('cached extraction input differs')
        extraction = LiteratureExtraction.model_validate(cached['extraction'])
        evidence = [Evidence.model_validate(e) for e in cached['evidence']]
        identity['semantic_verification'] = cached.get('semantic_verification', {})
        # materialize rechecks the review digest and current deterministic facts.
        materialize(extraction, evidence, data, identity)
        return extraction, evidence, cached.get('recovery', [])
    draft = root / 'extraction.json'
    if draft.exists():
        cached = read(draft)
        if cached['input_hash'] != request_hash:
            raise ValueError('cached extraction input differs')
        extraction = LiteratureExtraction.model_validate(cached['extraction'])
    else:
        remaining = budget['deadline'] - monotonic()
        if remaining <= 0:
            raise TimeoutError('method research time budget exhausted before extraction')
        async with asyncio.timeout(remaining):
            extraction = await cognition.ask('拆解文献预处理方法', LiteratureExtraction, inputs,
                INSTRUCTION + '\noutput_roles maps a safe role name to an EXACT data step ID in recipe '
                '(for example {"source_epochs":"epoch_source"}); values are never prose descriptions. '
                'Return {} when there are no additional named outputs. output itself is also an exact step ID.',
                lambda value: validate_extraction(value, evidence, data, identity))
        write_json(draft, {'input_hash': request_hash, 'extraction': extraction.model_dump(mode='json')})
    extraction, evidence, recovery = await recover(
        cognition, extraction, inputs, evidence, data, identity, root, budget)
    write_json(resolved, {'input_hash': request_hash, 'extraction': extraction.model_dump(mode='json'),
        'evidence': [e.model_dump(mode='json') for e in evidence],
        'semantic_verification': identity.get('semantic_verification', {}), 'recovery': recovery})
    return extraction, evidence, recovery
