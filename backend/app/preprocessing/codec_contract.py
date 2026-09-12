"""Shared closed descriptor contract, including explicitly bounded legacy reads."""
from math import isfinite, prod
import re

VERSION = 'artifact-codec-2'
FILE = {'file', 'sha256'}
SIGNAL = FILE | {'array', 'info_exact', 'times', 'loc', 'projs', 'annotations',
                 'selection', 'events', 'drop_log', 'baseline', 'highpass',
                 'lowpass', 'custom_ref_applied'}
FIELDS = {
    'ndarray': FILE | {'shape', 'dtype'}, 'bytes': FILE | {'size'},
    'raw': SIGNAL, 'epochs': SIGNAL, 'ica': FILE | {'exact'},
    'eog': FILE | {'exact'}, 'autoreject': FILE,
    'sparse_csr': {'shape', 'data', 'indices', 'indptr'},
    'object_array': {'shape', 'items'}, 'complex': {'real', 'imag'},
    'nonfinite': {'value'}, 'datetime': {'value'},
    'annotations': {'onset', 'duration', 'description', 'ch_names', 'orig_time'},
    **{kind: {'items'} for kind in ('dict', 'projection', 'info', 'forward', 'list', 'tuple', 'source_spaces')},
    **{kind: {'state'} for kind in ('asr', 'autoreject_state', 'random_state')},
    'cv_folds': {'folds'},
}
LEGACY_OPTIONAL = {'raw': {'info_exact', 'times'}, 'epochs': {'info_exact', 'times'}, 'eog': {'exact'}}
MAPPINGS = {'dict', 'projection', 'info', 'forward'}


def validate_node(value):
    """Check this node before file reads or allocation; children use the same rule."""
    if not isinstance(value, dict):
        if value is None or type(value) in (str, int, bool) or type(value) is float and isfinite(value):
            return None
        raise ValueError('codec primitive must be finite JSON; arrays and nonfinite values need descriptors')
    kind = value.get('codec')
    if not isinstance(kind, str) or kind not in FIELDS:
        raise ValueError('unregistered artifact codec')
    version = value.get('schema_version')
    if 'schema_version' in value and version != VERSION:
        raise ValueError('unsupported artifact codec schema version')
    if version is not None and kind == 'autoreject':
        raise ValueError('legacy autoreject HDF5 codec cannot be newly versioned')
    required = FIELDS[kind] | {'codec'}
    if version is not None:
        required |= {'schema_version'}
    optional = LEGACY_OPTIONAL.get(kind, set()) if version is None else set()
    if not required - optional <= value.keys() or value.keys() - required:
        raise ValueError('artifact codec has missing or unknown fields: ' + kind)
    if 'file' in value:
        if (not isinstance(value['file'], str) or not value['file']
                or not isinstance(value['sha256'], str)
                or re.fullmatch(r'[0-9a-f]{64}', value['sha256']) is None):
            raise ValueError('artifact file reference requires a path and SHA256')
    if 'shape' in value:
        shape = value['shape']
        if not isinstance(shape, list) or len(shape) > 32 or any(type(n) is not int or n < 0 for n in shape):
            raise ValueError('artifact shape must contain nonnegative integer dimensions')
        if kind == 'sparse_csr' and len(shape) != 2:
            raise ValueError('CSR shape must have two axes')
    if kind == 'ndarray' and not isinstance(value['dtype'], str):
        raise ValueError('array dtype must be explicit')
    if kind == 'bytes' and (type(value['size']) is not int or value['size'] < 0):
        raise ValueError('byte size must be a nonnegative integer')
    if 'items' in value:
        items = value['items']
        if not isinstance(items, list):
            raise ValueError('codec items must be a list')
        if kind in MAPPINGS and any(not isinstance(pair, list) or len(pair) != 2 for pair in items):
            raise ValueError('mapping items must be complete key/value pairs')
        if kind == 'object_array' and len(items) != prod(value['shape']):
            raise ValueError('object array item count differs from its complete shape')
    if kind == 'nonfinite' and value['value'] not in ('nan', 'inf', '-inf'):
        raise ValueError('nonfinite codec requires an explicit nonfinite token')
    if kind == 'datetime' and not isinstance(value['value'], str):
        raise ValueError('datetime codec requires an ISO string')
    if kind in {'raw', 'epochs'}:
        for field in ('highpass', 'lowpass'):
            number = value[field]
            if type(number) not in (int, float) or not isfinite(number) or number < 0:
                raise ValueError('signal passband must be finite and nonnegative')
        if value['highpass'] > value['lowpass'] or type(value['custom_ref_applied']) is not int:
            raise ValueError('signal measurement metadata is inconsistent')
        unused = ('selection', 'events', 'drop_log', 'baseline') if kind == 'raw' else ('annotations',)
        if any(value[name] is not None for name in unused):
            raise ValueError('signal descriptor has metadata for the wrong data kind')
    return kind


def schema():
    """JSON Schema of newly written descriptors, published with capabilities."""
    ref = {'$ref': '#/$defs/value'}
    choices = [{'type': ['null', 'string', 'number', 'boolean']}]
    for kind, fields in FIELDS.items():
        if kind == 'autoreject':
            continue  # Only legacy HDF5 reads; new writes use autoreject_state.
        properties = {key: dict(ref) for key in fields}
        properties.update(codec={'const': kind}, schema_version={'const': VERSION})
        for key in fields & {'file', 'sha256', 'dtype'}:
            properties[key] = {'type': 'string', 'minLength': 1}
        if 'sha256' in fields: properties['sha256']['pattern'] = '^[0-9a-f]{64}$'
        if 'shape' in fields:
            properties['shape'] = {'type': 'array', 'maxItems': 32, 'items': {'type': 'integer', 'minimum': 0}}
        if 'size' in fields: properties['size'] = {'type': 'integer', 'minimum': 0}
        if 'items' in fields:
            item = {'type': 'array', 'prefixItems': [ref, ref], 'items': False, 'minItems': 2, 'maxItems': 2} if kind in MAPPINGS else ref
            properties['items'] = {'type': 'array', 'items': item}
        if kind == 'nonfinite': properties['value'] = {'enum': ['nan', 'inf', '-inf']}
        if kind == 'datetime': properties['value'] = {'type': 'string', 'format': 'date-time'}
        for key in fields & {'highpass', 'lowpass'}: properties[key] = {'type': 'number', 'minimum': 0}
        if 'custom_ref_applied' in fields: properties['custom_ref_applied'] = {'type': 'integer'}
        if kind in {'raw', 'epochs'}:
            unused = ('selection', 'events', 'drop_log', 'baseline') if kind == 'raw' else ('annotations',)
            for key in unused: properties[key] = {'type': 'null'}
        choices.append({'type': 'object', 'properties': properties,
                        'required': sorted(properties), 'additionalProperties': False})
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema',
            '$id': 'urn:brainagent:' + VERSION, '$ref': '#/$defs/value',
            '$defs': {'value': {'oneOf': choices}}}
