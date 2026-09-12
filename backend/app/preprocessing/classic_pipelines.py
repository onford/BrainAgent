"""Versioned full-pipeline contracts, separate from primitive operation coverage."""
from pathlib import Path
import json
from .schemas import Contract, Ref
from .storage import digest
from pydantic import Field


def catalog():
    value=json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
    return {**value,'catalog_sha256':digest(value),
        'interpretation':'Source-locked complete author entrypoints. Primitive operator validation cannot establish native full-pipeline reproduction.'}


class PipelineConfiguration(Contract):
    pipeline_id: str
    source_commit: str
    identity_kind: str = Field(pattern='^(upstream_configured|project_derived)$')
    configuration: dict = Field(min_length=1)
    dependency_versions: dict[str,str] = Field(min_length=1)
    decisions: dict = Field(default_factory=dict)
    source_evidence: list[Ref] = Field(min_length=1)
    adaptations: list[str] = Field(default_factory=list)


def register_configuration(store, owner, request):
    contract=next((p for p in catalog()['pipelines'] if p['id']==request.pipeline_id),None)
    if contract is None or request.source_commit != contract['commit']:
        raise ValueError('classic pipeline must select a registered immutable source commit')
    if request.adaptations and request.identity_kind!='project_derived':
        raise ValueError('adapted native procedures require project_derived identity')
    for ref in request.source_evidence:store.get(owner,ref,'evidence')
    snapshot={'request':request.model_dump(mode='json'),'source_contract':contract,
        'configuration_sha256':digest(request.configuration),'status':'draft',
        'blockers':contract['blockers'],'numerical_validation':[],
        'claim':'Configuration recorded; complete native execution and numerical equivalence are not yet established.'}
    return store.put(owner,'classic_configuration',snapshot)
