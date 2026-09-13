from copy import deepcopy

import numpy as np
import mne
import pytest
from scipy import sparse

from app.preprocessing.artifact_codec import Codec, fingerprint
from app.preprocessing.codec_contract import VERSION, schema, validate_node


def legacy(value):
    if isinstance(value, dict):
        return {k: legacy(v) for k,v in value.items() if k != 'schema_version'}
    if isinstance(value, list): return [legacy(v) for v in value]
    return value


def test_versioned_and_explicit_legacy_roundtrip(tmp_path):
    value = {'array': np.array([1., np.nan]), 'bytes': b'opaque',
             'objects': np.array([('C3', 1), None], dtype=object),
             'sparse': sparse.csr_matrix([[0., 2.], [3., 0.]]),
             'complex': complex(1, float('inf'))}
    codec = Codec(tmp_path)
    encoded = codec.verified_dump(value)
    assert encoded['schema_version'] == VERSION
    assert fingerprint(codec.load(legacy(encoded))) == fingerprint(value)
    jsonschema = pytest.importorskip('jsonschema')
    jsonschema.Draft202012Validator.check_schema(schema())
    jsonschema.validate(encoded, schema())


@pytest.mark.parametrize('mutate', [
    lambda v: v.update(unexpected='ignored before'),
    lambda v: v.update(schema_version='artifact-codec-future'),
    lambda v: v.update(schema_version=None),
    lambda v: v.pop('dtype'),
    lambda v: v.update(shape=[True]),
    lambda v: v.update(shape=[-1]),
    lambda v: v.update(sha256='not-a-hash'),
])
def test_bad_descriptors_rejected_before_loading_files(tmp_path, mutate):
    codec = Codec(tmp_path)
    value = codec.dump(np.ones(2))
    mutate(value)
    for p in tmp_path.iterdir(): p.unlink()  # If validation reads files first, this raises FileNotFoundError.
    with pytest.raises(ValueError): codec.load(value)


def test_object_array_cannot_silently_fill_missing_values(tmp_path):
    codec = Codec(tmp_path)
    value = codec.dump(np.array([None, 'C3'], dtype=object))
    value['items'].pop()
    with pytest.raises(ValueError, match='item count'): codec.load(value)


def test_duplicate_and_malformed_mapping_entries_rejected(tmp_path):
    codec = Codec(tmp_path)
    value = codec.dump({'gain': 1.})
    value['items'].append(['gain', 2.])
    with pytest.raises(ValueError, match='duplicate'): codec.load(value)
    value['items'] = [['gain']]
    with pytest.raises(ValueError, match='key/value'): codec.load(value)
    with pytest.raises(ValueError, match='primitive'): codec.load([1., 2.])
    with pytest.raises(ValueError, match='primitive'): codec.load(float('nan'))


def test_invalid_csr_indices_do_not_reach_sparse_operations(tmp_path):
    codec = Codec(tmp_path)
    value = codec.dump(sparse.csr_matrix([[1., 0.], [0., 2.]]))
    value['indices'] = codec.dump(np.array([0, 9]))
    with pytest.raises(ValueError, match='CSR'): codec.load(value)


def raw():
    return mne.io.RawArray(np.zeros((2,100)),mne.create_info(['C3','C4'],100,'eeg'),verbose='ERROR')


@pytest.mark.parametrize('field,alteration,match', [
    ('array', np.zeros((3,100)), 'array axes'),
    ('loc', [np.zeros(12)], 'channel/location'),
    ('times', np.arange(100)/100+1, 'sample/time'),
])
def test_signal_axes_checked_across_fif_and_exact_payload(tmp_path, field, alteration, match):
    codec = Codec(tmp_path)
    value = codec.verified_dump(raw())
    value[field] = codec.dump(alteration)
    with pytest.raises(ValueError, match=match): codec.load(value)


def test_epoch_event_axis_checked_and_legacy_optional_fields_remain_readable(tmp_path):
    codec = Codec(tmp_path)
    epochs = mne.EpochsArray(np.zeros((2,2,20)), raw().info, events=np.array([[0,0,1],[50,0,1]]), verbose='ERROR')
    value = codec.verified_dump(epochs)
    old = legacy(deepcopy(value))
    old.pop('info_exact'); old.pop('times')
    assert codec.load(old).get_data().shape == (2,2,20)
    value['events'] = codec.dump(np.array([[0,0,1]]))
    with pytest.raises(ValueError, match='event/selection'): codec.load(value)


def test_schema_requires_version_and_unknown_fields_are_closed():
    jsonschema = pytest.importorskip('jsonschema')
    document = schema()
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({'codec':'list', 'schema_version':VERSION,'items':[],'unrecognized':True}, document)
    with pytest.raises(ValueError, match='nonfinite'):
        validate_node({'codec':'nonfinite','value':'123'})


@pytest.mark.parametrize('offset', [0, 1, 2])
def test_offset_decimated_epoch_time_origin_is_lossless(tmp_path, offset):
    sfreq = 400.
    samples = np.arange(601)
    epochs = mne.EpochsArray(np.tile(samples, (2, 2, 1)) * 1e-8,
        mne.create_info(['C3', 'C4'], sfreq, 'eeg'), tmin=-.5,
        events=np.array([[200, 0, 1], [1200, 0, 2]]), verbose='ERROR')
    with epochs.info._unlock():
        epochs.info['lowpass'] = 40.
    epochs.decimate(3, offset=offset, verbose='ERROR')
    before = fingerprint(epochs)
    codec = Codec(tmp_path)
    encoded = codec.verified_dump(epochs)
    restored = codec.load(encoded)
    assert fingerprint(restored) == before
    np.testing.assert_array_equal(restored.times, epochs.times)
    np.testing.assert_array_equal(restored.get_data(), epochs.get_data())
    assert fingerprint(epochs) == before

    for altered in (epochs.times + 1, epochs.times.copy()):
        if altered[0] == epochs.times[0]:
            altered[3] += .0001
        invalid = deepcopy(encoded)
        invalid['times'] = codec.dump(altered)
        with pytest.raises(ValueError, match='sample/time'):
            codec.load(invalid)
