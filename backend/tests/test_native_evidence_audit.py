from copy import deepcopy

import mne
import numpy as np
import pytest

from app.preprocessing.artifact_codec import Codec, fingerprint
from app.preprocessing.graph_runtime import Packet, identity, transition
from app.preprocessing.schemas import Step
from app.preprocessing.storage import write_json
from scripts.audit_native_profile_evidence import saved_outputs
from scripts.validate_native_profiles import comparable


def fixture(tmp_path):
    raw = mne.io.RawArray(np.arange(20).reshape(2, 10) * 1e-6,
                         mne.create_info(['C3', 'C4'], 10., 'eeg'), verbose='ERROR')
    packet = Packet(raw, np.array([[2, 0, 1], [5, 0, 2]]), np.arange(2), ['t0', 't1'], 'acquisition')
    step = Step(id='native', unit_id='EEG-CLASSIC-NATIVE', op='prep_native',
                implementation_version='2', profile='source', params={}, adaptation_scope='record_unlabeled',
                evidence_indices=[0])
    row = dict(effect='native_pipeline', op='prep_native')
    expected = dict(data=raw.copy().crop(tmin=.3), model=None,
                    artifacts=dict(kept_event_indices=np.array([1]), events=packet.events[1:].copy(),
                                   reference_id='average', quality={'removed_channels': [], 'window_seconds': 2.}))
    actual = deepcopy(expected)
    out = transition(packet, actual['data'], actual['artifacts'], row, step.params, node_id=step.id)
    receipt = dict(input_sha256=identity(packet), output_sha256=identity(out), event_indices=[1],
                   trial_ids=['t1'], shape=[2, 7], model_sha256=fingerprint(None), max_abs_error=0.,
                   diagnostics_sha256=fingerprint(comparable(expected['artifacts'])))
    log = dict(step_contract=step.model_dump(mode='json'), input_hash=receipt['input_sha256'],
               output_hash=receipt['output_sha256'], event_indices=[1], trial_ids=['t1'])

    def save():
        for relative, data in [('direct-source', expected), ('graph/native', actual)]:
            folder = tmp_path / relative
            write_json(folder / 'artifacts.json', Codec(folder).verified_dump(data))
        write_json(tmp_path / 'graph/native/execution.json', log)
    return packet, step, row, receipt, expected, actual, log, save


def test_read_only_decoded_outputs_reconstruct_dropped_event_lineage(tmp_path):
    packet, step, row, receipt, *rest = fixture(tmp_path)
    rest[-1]()
    original = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    before = identity(packet)
    result = saved_outputs(tmp_path, packet, step, row, receipt)
    assert result['retained_event_indices'] == [1]
    assert result['retained_trial_ids'] == ['t1']
    assert result['max_abs_error'] == 0.
    assert identity(packet) == before
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == original


@pytest.mark.parametrize('change, message', [
    ('data', 'data/MNE'), ('metadata', 'data/MNE'), ('diagnostics', 'diagnostics'),
    ('lineage', 'event/trial'), ('output_hash', 'output identity'), ('log', 'execution log'),
    ('descriptor', 'Missing saved'),
])
def test_saved_evidence_cannot_claim_pass_after_tampering(tmp_path, change, message):
    packet, step, row, receipt, expected, actual, log, save = fixture(tmp_path)
    if change == 'data':
        actual['data']._data[0, 0] += 1e-9
    elif change == 'metadata':
        actual['data'].info['bads'] = ['C3']
    elif change == 'diagnostics':
        actual['artifacts']['quality']['window_seconds'] = 3.
    elif change == 'lineage':
        receipt['event_indices'] = [0]
    elif change == 'output_hash':
        receipt['output_sha256'] = 'forged'
    elif change == 'log':
        log['input_hash'] = 'forged'
    save()
    if change == 'descriptor':
        (tmp_path / 'direct-source/artifacts.json').unlink()
    with pytest.raises(ValueError, match=message):
        saved_outputs(tmp_path, packet, step, row, receipt)


def test_even_agreeing_saved_outputs_cannot_change_original_event_identities(tmp_path):
    packet, step, row, receipt, expected, actual, log, save = fixture(tmp_path)
    for value in (expected, actual):
        value['artifacts']['events'][0, 2] = 1
    save()
    with pytest.raises(ValueError, match='retained event identities'):
        saved_outputs(tmp_path, packet, step, row, receipt)
