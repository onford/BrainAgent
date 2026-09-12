from copy import deepcopy

import mne
import numpy as np
import pytest

from app.preprocessing.graph_runtime import GraphExecutor, Packet
from app.preprocessing.schemas import Evidence, MethodSpec, RecordSpec, Step
from app.preprocessing.scoring_window import project
from app.search.literature_space import shared_window_variant


def execute(tmp_path, *, annotations=None, onsets=(20, 300, 800), mutate=None):
    sfreq = 100.
    values = np.random.default_rng(72).normal(0, 1e-6, (2, 1000))
    raw = mne.io.RawArray(values, mne.create_info(['C3', 'C4'], sfreq, 'eeg'), verbose='ERROR')
    if annotations is not None:
        raw.set_annotations(annotations)
    events = np.array([[s, 0, 1] for s in onsets])
    method = MethodSpec(id='source', version='1', title='Source fixture', source='survey_literature',
        mechanism='numerical fixture', evidence=[Evidence(source_url='fixture://window', source_version='1',
            locator='test', text='Synthetic numerical fixture; no paper claim.')],
        recipe=[Step(id='native', unit_id='EEG-EPOCH', op='epoch', implementation_version='2',
            evidence_indices=[0], params=dict(events='$events', event_id={'task': 1}, picks=['C3', 'C4'], tmin=-1., tmax=4.))],
        output='native')
    original = deepcopy(method.model_dump())
    variant = shared_window_variant(method, None, dict(sfreq=sfreq, tmin=0., tmax=1.))
    assert method.model_dump() == original
    assert variant.recipe[0].model_dump() == original['recipe'][0]
    if mutate:
        mutate(variant)
    record = RecordSpec(id='fixture', bids_path='fixture.vhdr', files={'fixture.vhdr': '0'*64},
        sfreq=sfreq, samples=1000, channels={'C3': 'eeg', 'C4': 'eeg'}, channel_order=['C3', 'C4'], reference='acquisition')
    packet = Packet(raw, events, np.arange(len(events)), [str(i) for i in range(len(events))], 'acquisition')
    executor = GraphExecutor(record, variant.recipe, packet, tmp_path)
    for step in variant.recipe:
        executor.execute(step)
    return executor, variant, raw


def test_parallel_window_restores_only_boundary_context_and_preserves_source(tmp_path):
    executor, variant, raw = execute(tmp_path)
    final, source, audit = project(executor, variant.output, variant.evaluation_window)
    assert source.event_indices.tolist() == [1]
    assert final.event_indices.tolist() == [0, 1, 2]
    assert audit['restored_boundary_event_indices'] == [0, 2]
    assert source.data.tmin == -1 and source.data.tmax == 4
    for row, event in zip(final.data.get_data(), final.events):
        np.testing.assert_array_equal(row, raw.get_data()[:, event[0]:event[0]+101])


@pytest.mark.parametrize('annotations,onsets', [
    (mne.Annotations([1.5], [.1], ['BAD_artifact']), (20, 300, 800)),
    (mne.Annotations([3.], [.1], ['BAD_artifact']), (100, 500, 800)),
])
def test_parallel_window_never_bypasses_source_annotation_screening(tmp_path, annotations, onsets):
    executor, variant, _ = execute(tmp_path, annotations=annotations, onsets=onsets)
    with pytest.raises(ValueError, match='source rejection annotations'):
        project(executor, variant.output, variant.evaluation_window)


def test_parallel_window_rejects_non_window_contract_changes(tmp_path):
    executor, variant, _ = execute(tmp_path, mutate=lambda v: v.recipe[-1].params.update(picks=['C3']))
    with pytest.raises(ValueError, match='non-window epoch parameters'):
        project(executor, variant.output, variant.evaluation_window)


def test_projection_policy_requires_source_node():
    from app.preprocessing.schemas import EvaluationWindow
    with pytest.raises(ValueError, match='explicit source output'):
        EvaluationWindow(tmin=0, tmax=1, policy='parallel-final-epoch-scoring-v1')
