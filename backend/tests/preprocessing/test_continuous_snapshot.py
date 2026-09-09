import json

import mne
import numpy as np
import pytest

from app.preprocessing.methods import baseline_methods
from app.preprocessing.schemas import Step
from app.preprocessing.runner import verify_result
from app.preprocessing.worker import Worker
from .conftest import OWNER
from .test_execution import prepare


@pytest.mark.parametrize('reference_after_epoch', [False, True])
def test_snapshot_is_output_ancestor_and_records_post_epoch_reference(service, dataset, reference_after_epoch):
    method = baseline_methods()[0]
    method.id = 'continuous-snapshot-test'
    highpass, reference, epochs, _ = method.recipe
    epochs.params.update(tmin=0, tmax=.5)
    recipe = [highpass]
    if reference_after_epoch:
        epochs.input = highpass.id
        reference.input = epochs.id
        recipe.extend([epochs, reference])
        method.output = reference.id
    else:
        recipe.extend([reference, epochs])
        method.output = epochs.id
    # An unrelated executed Raw branch must not become the saved baseline source.
    recipe.append(Step(id='unrelated', unit_id='EEG-DETREND', op='detrend', input='raw',
                       params={'type': 'linear', 'picks': '$eeg_channels'}, evidence_indices=[0]))
    method.recipe = recipe
    job, _, _ = prepare(service, dataset, [method])
    result = Worker(service.store, service.allowed_roots).run_once()
    assert result.status == 'completed', result.model_dump()
    for row in result.records:
        output = row['result']
        assert len([a for a in output['artifacts'] if a['kind'] == 'data']) == 1
        files = [a for a in output['artifacts'] if a['kind'] == 'continuous_data']
        assert len(files) == 1 and files[0]['name'] == 'continuous-raw.fif'
        path = service.store.root / files[0]['path']
        continuous = mne.io.read_raw_fif(path, preload=True, verbose='ERROR')
        provenance = json.loads(service.store.artifact(OWNER, job.job_id, row['key'], 'provenance.json').read_text())
        meta = provenance['continuous_raw']
        assert meta['sha256'] == files[0]['sha256']
        assert meta['bytes'] == path.stat().st_size
        assert meta['unit'] == 'V' and meta['before_epoch_step_id'] == 'epochs'
        assert meta['source_node_id'] == ('filter' if reference_after_epoch else 'reference')
        assert meta['main_chain_step_ids'] == (['filter'] if reference_after_epoch else ['filter', 'reference'])
        assert meta['post_epoch_step_ids'] == (['reference'] if reference_after_epoch else [])
        assert meta['post_epoch_operations_applied'] is False
        assert meta['first_sample'] == continuous.first_samp
        signal = np.load(service.store.artifact(OWNER, job.job_id, row['key'], 'signal_V.npy'))
        events = np.array(meta['target_events'])
        extracted = mne.Epochs(continuous, events, event_id={'left': 1, 'right': 2},
                               tmin=0, tmax=.5, baseline=None, proj=False, preload=True, verbose='ERROR')
        if reference_after_epoch:
            extracted.set_eeg_reference('average', verbose='ERROR')
        np.testing.assert_allclose(extracted.get_data(), signal, rtol=3e-7, atol=1e-15)
        assert verify_result(service.store.root, output)
        # Snapshot participates in verification even though it is not final data.
        with path.open('r+b') as stream:
            stream.seek(-1, 2)
            stream.write(b'X')
        assert not verify_result(service.store.root, output)
