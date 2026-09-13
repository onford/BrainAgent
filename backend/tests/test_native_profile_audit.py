from io import BytesIO

import numpy as np
import pytest
from scipy.io import savemat

from app.preprocessing.artifact_codec import fingerprint
from scripts.validate_native_profiles import comparable, one


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
