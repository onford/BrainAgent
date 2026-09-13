from io import BytesIO

import numpy as np
import pytest
from scipy.io import savemat

from app.preprocessing.artifact_codec import fingerprint
from scripts.validate_native_profiles import comparable, hdf_mat, one


def container(values, header):
    output = BytesIO()
    savemat(output, {'data': np.asarray(values), 'duration_seconds': 2.})
    data = bytearray(output.getvalue())
    data[:116] = header.encode().ljust(116, b' ')
    return np.frombuffer(data, dtype=np.uint8)


def test_native_container_comparison_ignores_header_but_retains_scientific_arrays():
    a = {'native_output_mat': container([1., 2.], 'header A'), 'native_output_sha256': 'raw-A'}
    b = {'native_output_mat': container([1., 2.], 'header B'), 'native_output_sha256': 'raw-B'}
    assert fingerprint(comparable(a)) == fingerprint(comparable(b))
    b['native_output_mat'] = container([1., 3.], 'header B')
    assert fingerprint(comparable(a)) != fingerprint(comparable(b))


def test_native_working_paths_normalize_without_dropping_time_or_qc_fields():
    a = dict(requested_configuration={'myPath': 'C:/Temp/ba-relax-abc/input.set'},
             native_qc={'time_window_seconds': 2., 'rejected': [1, 2]})
    b = dict(requested_configuration={'myPath': 'C:/Temp/ba-relax-xyz/input.set'},
             native_qc={'time_window_seconds': 2., 'rejected': [1, 2]})
    assert fingerprint(comparable(a)) == fingerprint(comparable(b))
    b['native_qc']['time_window_seconds'] = 3.
    assert fingerprint(comparable(a)) != fingerprint(comparable(b))
    assert comparable({'native_qc': {'native_output_sha256': 'scientific'}})['native_qc']['native_output_sha256'] == 'scientific'


def test_native_fixture_requires_explicit_inputs(tmp_path):
    with pytest.raises(ValueError, match='explicit'):
        one({}, tmp_path, input_path=None, record_id=None, bindings_path=None)


def hdf_container(*, changed=False, header='A', compression=None, path='C:/Temp/ba-relax-abc/input.set', reverse=False):
    import h5py
    output = BytesIO()
    with h5py.File(output, 'w', userblock_size=512) as handle:
        refs = handle.create_group('#refs#')
        a = refs.create_dataset('a', data=[1., 3. if changed else 2.], compression=compression)
        b = refs.create_dataset('b', data=[4., 5.], compression=compression)
        a.attrs['MATLAB_class'] = np.bytes_('double')
        refs_data = np.array([b.ref, a.ref] if reverse else [a.ref, b.ref], dtype=h5py.ref_dtype)
        handle.create_dataset('cells', data=refs_data)
        handle.create_dataset('duration_seconds', data=2.)
        chars = handle.create_dataset('path', data=np.frombuffer(path.encode('utf-16-le'), dtype='<u2')[:, None])
        chars.attrs['MATLAB_class'] = np.bytes_('char')
    data = bytearray(output.getvalue())
    data[:128] = ('MATLAB 7.3 MAT-file ' + header).encode().ljust(116, b' ') + bytes(8) + b'\x00\x02IM'
    return np.frombuffer(data, dtype=np.uint8)


def test_v73_storage_changes_and_declared_temporary_paths_preserve_content():
    a = hdf_container()
    b = hdf_container(header='B', compression='gzip', path='C:/Temp/ba-relax-longer/input.set')
    assert fingerprint(a) != fingerprint(b)
    assert fingerprint(comparable(a, 'native_all_stages_mat')) == fingerprint(comparable(b, 'native_all_stages_mat'))


@pytest.mark.parametrize('change', ['values', 'references', 'scientific_path'])
def test_v73_differences_in_arrays_reference_targets_and_path_remainders_are_retained(change):
    a = hdf_container()
    b = hdf_container(changed=change == 'values', reverse=change == 'references',
                      path='C:/Temp/ba-relax-abc/other.set' if change == 'scientific_path' else 'C:/Temp/ba-relax-abc/input.set')
    assert fingerprint(comparable(a, 'native_all_stages_mat')) != fingerprint(comparable(b, 'native_all_stages_mat'))


@pytest.mark.parametrize('kind', ['external', 'cycle', 'region'])
def test_v73_unsupported_links_cycles_and_regions_are_explicit_failures(kind):
    import h5py
    output = BytesIO()
    with h5py.File(output, 'w') as handle:
        if kind == 'external':
            handle['external'] = h5py.ExternalLink('outside.h5', '/data')
        elif kind == 'cycle':
            handle['cycle'] = handle
        else:
            data = handle.create_dataset('data', data=[1., 2.])
            handle.create_dataset('region', data=data.regionref[:1], dtype=h5py.regionref_dtype)
    with pytest.raises(ValueError, match='Unsupported'):
        hdf_mat(output.getvalue())
