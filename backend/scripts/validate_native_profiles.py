"""Complete native entrypoint / graph comparisons on a declared real record.

The MATLAB file header and temporary working-directory names are transport
metadata. All decoded MATLAB fields, scientific diagnostics and arrays remain
in the comparison; non-repeatable author profiles may fail and stay visible.
"""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import re

import numpy as np
from scipy.io import loadmat

from app.preprocessing.artifact_codec import Codec, fingerprint
from app.preprocessing.assets import freeze_native, verify_native
from app.preprocessing.graph_planner import compile_graph
from app.preprocessing.graph_runtime import GraphExecutor, Packet, identity
from app.preprocessing.inputs import read_record, validate_record_files
from app.preprocessing.schemas import MethodSpec, PreprocessInput, Step
from app.preprocessing.storage import file_hash, write_json
from app.preprocessing.units.contracts_v2 import invoke_source, validate_parameters

OPERATIONS = {'prep_native', 'automagic_native', 'relax_native'}
_TEMPORARY_ROOT = re.compile(r"[A-Za-z]:[/\\][^\r\n'\"]*?[/\\](ba-native-pipeline-|ba-relax-)[A-Za-z0-9_]+")


def hdf_mat(payload):
    """Read v7.3 content, retaining fields, attributes and reference targets.

    HDF object addresses, compression and its user-block timestamp are storage
    details. Region references and external links are not silently discarded.
    """
    import h5py

    with h5py.File(BytesIO(payload), 'r') as handle:
        # Resolving .name separately for each object reference repeatedly walks
        # MATLAB's large #refs# table. Index all targets once instead.
        reference_names = {h5py.h5o.get_info(handle.id).addr: '/'}
        handle.visititems(lambda name, obj: reference_names.__setitem__(h5py.h5o.get_info(obj.id).addr, '/' + name))

        def value(item):
            if isinstance(item, h5py.RegionReference):
                raise ValueError('Unsupported MATLAB HDF region reference')
            if isinstance(item, h5py.Reference):
                return {'object_reference': reference_names[h5py.h5o.get_info(handle[item].id).addr] if item else None}
            if isinstance(item, np.ndarray) and item.dtype.hasobject:
                return {'shape': list(item.shape), 'items': [value(v) for v in item.flat]}
            if isinstance(item, np.ndarray) and item.dtype.names:
                return {'shape': list(item.shape), 'fields': {n: value(item[n]) for n in item.dtype.names}}
            return item

        def node(item, ancestors=()):
            address = h5py.h5o.get_info(item.id).addr
            if address in ancestors:
                raise ValueError('Unsupported cyclic MATLAB HDF group')
            result = {'attributes': {k: value(v) for k, v in item.attrs.items()}}
            if isinstance(item, h5py.Dataset):
                data = item[()]
                if item.attrs.get('MATLAB_class') == b'char' and isinstance(data, np.ndarray) and data.ndim == 2 and 1 in data.shape:
                    # MATLAB character vectors can contain generated work paths.
                    # Keep orientation; string normalization below only removes
                    # the declared temporary root, preserving the remaining text.
                    result.update(kind='char', orientation='column' if data.shape[1] == 1 else 'row',
                                  data=np.asarray(data.T, dtype='<u2').tobytes().decode('utf-16-le'))
                else:
                    result.update(kind='dataset', dtype=str(item.dtype), shape=item.shape, data=value(data))
            elif isinstance(item, h5py.Group):
                children = {}
                for name in item:
                    if not isinstance(item.get(name, getlink=True), h5py.HardLink):
                        raise ValueError('Unsupported linked MATLAB HDF content')
                    children[name] = node(item[name], (*ancestors, address))
                result.update(kind='group', children=children)
            else:
                raise ValueError('Unsupported MATLAB HDF object')
            return result

        return node(handle)


def comparable(value, key=None):
    if key in {'native_output_mat', 'native_all_stages_mat'}:
        payload = np.asarray(value, dtype=np.uint8).tobytes()
        try:
            value = loadmat(BytesIO(payload), simplify_cells=True)
        except NotImplementedError:
            value = hdf_mat(payload)
        else:
            value = {k:v for k,v in value.items() if k != '__header__'}
    if isinstance(value, dict):
        # This hash covers the raw MAT container, including its timestamp.
        # The decoded container itself is compared recursively instead.
        return {k:comparable(v, k) for k,v in value.items()
                if not (key is None and k == 'native_output_sha256')}
    if isinstance(value, str):
        return _TEMPORARY_ROOT.sub(lambda m: '$temporary/' + m.group(1), value)
    if isinstance(value, np.ndarray) and value.dtype.hasobject:
        out = np.empty(value.shape, dtype=object)
        for i,v in enumerate(value.flat):
            out.flat[i] = comparable(v)
        return out
    if isinstance(value, list):
        return [comparable(v) for v in value]
    if isinstance(value, tuple):
        return tuple(comparable(v) for v in value)
    return value


def one(row, directory, *, input_path, record_id, bindings_path):
    import json
    if not input_path or not record_id or not bindings_path:
        raise ValueError('Complete native profiles require explicit input, record and asset bindings')
    input_path, bindings_path = Path(input_path).resolve(strict=True), Path(bindings_path).resolve(strict=True)
    original_files = {str(p):file_hash(p) for p in (input_path, bindings_path)}
    source = PreprocessInput.model_validate_json(input_path.read_text(encoding='utf8'))
    root = Path(source.collection.root).resolve(strict=True)
    if directory.resolve().is_relative_to(root) or root.is_relative_to(directory.resolve()):
        raise ValueError('Native validation output must be disjoint from real source data')
    if record_id not in source.collection.selected_record_ids:
        raise ValueError('Native fixture record must be in the immutable selected input')
    record = next(r for r in source.collection.records if r.id == record_id)
    validate_record_files(root, record)
    raw, events, mapping = read_record(root, record, source.survey.event_id, source.survey.context_event_id)
    packet = Packet(raw, events, np.arange(len(events)), [m['trial_id'] for m in mapping], record.reference)
    bindings = json.loads(bindings_path.read_text(encoding='utf8'))
    params = validate_parameters(row['unit_id'], row['op'],
        {**bindings[row['op']], **row['profile_parameters']}, profile=row['profile'])
    step = Step(id='native', unit_id=row['unit_id'], op=row['op'], params=params,
        implementation_version='2', profile=row['profile'], evidence_indices=[0],
        adaptation_scope='record_unlabeled')
    method = MethodSpec(id='native-profile-audit', version='2', title=row['identity'],
        source='classic', mechanism='Complete pinned author entrypoint comparison',
        recipe=[step], output=step.id, evidence=[dict(source_url='brainagent:native-profile-audit',
            source_version='2', locator=row['identity'], text='Declared real-record source/graph comparison')])
    compile_graph(method, record, source, {})
    native = freeze_native([step])
    write_json(directory / 'native-inputs.json', dict(record_id=record_id, files=original_files,
        recipe=step.model_dump(mode='json'), native_files=native, input_sha256=identity(packet)))
    executor = GraphExecutor(record, [step], packet, directory / 'graph')
    runtime_params = executor.runtime_params(step, packet, None)
    before = identity(packet)
    expected = invoke_source(step.unit_id, step.op, deepcopy(raw), **runtime_params)
    direct = directory / 'direct-source'
    write_json(direct / 'artifacts.json', Codec(direct).verified_dump(expected))
    actual = executor.execute(step)
    np.testing.assert_allclose(actual.data.get_data(), expected['data'].get_data(), rtol=1e-11, atol=1e-16)
    if fingerprint(actual.data) != fingerprint(expected['data']):
        raise ValueError('Complete native data/MNE state differs between source and graph runs')
    actual_artifacts = executor.nodes[step.id]['artifacts']
    if fingerprint(comparable(actual_artifacts)) != fingerprint(comparable(expected['artifacts'])):
        raise ValueError('Decoded native diagnostics/container state differs between source and graph runs')
    invalid = raw.copy()
    invalid._data[0, 0] = np.inf
    invalid_before = fingerprint(invalid)
    try:
        invoke_source(step.unit_id, step.op, invalid, **runtime_params)
    except (ValueError, TypeError):
        pass
    else:
        raise ValueError('Complete native pipeline accepted an infinite input')
    if fingerprint(invalid) != invalid_before or identity(packet) != before:
        raise ValueError('Native validation changed its input')
    verify_native(native)
    validate_record_files(root, record)
    if any(file_hash(Path(p)) != sha for p,sha in original_files.items()):
        raise ValueError('Native fixture or bindings changed during validation')
    return dict(compiled_parameters=True, compiled_graph=True, executed=True,
        numerical_verified=True, boundary_passed=True, boundary_inf_rejected=True,
        real_verified=True, real_record_id=record_id,
        numerical_basis='Complete pinned native source versus graph: exact data/MNE state, all decoded '
            'MAT fields and diagnostics; only MAT timestamp header and temporary work-directory names '
            'normalized. Raw containers retained and individually losslessly verified. One real record; '
            'not independent algorithm validity or a deterministic guarantee for author-clock profiles.',
        max_abs_error=float(np.max(np.abs(actual.data.get_data()-expected['data'].get_data()))),
        shape=list(actual.data.get_data().shape), input_sha256=before, output_sha256=identity(actual),
        model_sha256=fingerprint(None), diagnostics_sha256=fingerprint(comparable(expected['artifacts'])),
        event_indices=actual.event_indices.tolist(), trial_ids=actual.trial_ids)
