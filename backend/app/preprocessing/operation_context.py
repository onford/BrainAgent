"""Lossless factoring of repeated operation contracts in model inputs."""
from copy import deepcopy
from .storage import digest


def factor(operations):
    shared = {}
    rows = deepcopy(operations)
    for row in rows:
        for key in ('source_contract', 'ports'):
            if key not in row:
                continue
            value = row[key]
            identity = key + '-' + digest(value)[:20]
            if identity in shared and shared[identity] != value:
                raise ValueError('operation context digest collision')
            shared[identity] = value
            row[key] = {'$ref': '#/shared_operation_contracts/' + identity}
    return dict(enabled_operations=rows, shared_operation_contracts=shared,
        operation_context_format='source_contract and ports use exact JSON pointers into shared_operation_contracts. Resolve these shared definitions; every operation parameter/profile and all source contract text are retained verbatim.')


def expand(context):
    rows = deepcopy(context['enabled_operations'])
    for row in rows:
        for key in ('source_contract', 'ports'):
            value = row.get(key)
            if isinstance(value, dict) and set(value) == {'$ref'}:
                prefix = '#/shared_operation_contracts/'
                if not value['$ref'].startswith(prefix):
                    raise ValueError('unknown operation context pointer')
                row[key] = deepcopy(context['shared_operation_contracts'][value['$ref'][len(prefix):]])
    return rows
