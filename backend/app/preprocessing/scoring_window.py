"""Explicit scoring projections with preserved source context and trial screening."""
from copy import deepcopy

import mne

from .storage import digest


def project(executor, output, window):
    final = executor.nodes[output]['packet']
    source_id = window.source_output or output
    source = executor.nodes[source_id]['packet']
    if any(not isinstance(p.data, mne.BaseEpochs) or p.unit != 'V' for p in (source, final)):
        raise ValueError('scoring projection requires physical epochs')
    lo, hi = window.tmin, window.tmax
    if lo < source.data.tmin - 1e-12 or hi > source.data.tmax + 1e-12:
        raise ValueError('scoring projection cannot extend source window')
    restored = []
    if window.policy == 'parallel-final-epoch-scoring-v1':
        native, score = executor.steps[source_id], executor.steps[output]
        if source_id == output or any((s.unit_id, s.op, s.implementation_version) != ('EEG-EPOCH', 'epoch', '2') for s in (native, score)):
            raise ValueError('parallel scoring requires two explicit final epoch nodes')
        # Only the terminal window and an explicit synchronized resample may differ.
        for step in (native, score):
            if step.parameter_inputs or step.artifact_inputs or step.asset_inputs:
                raise ValueError('parallel scoring cannot rebind source epoch dependencies')
        omit = {'id', 'input', 'params', 'parameter_sources'}
        if digest(native.model_dump(exclude=omit)) != digest(score.model_dump(exclude=omit)):
            raise ValueError('parallel scoring changed the source epoch contract')
        params = lambda s: {k: v for k, v in s.params.items() if k not in ('tmin', 'tmax')}
        if digest(params(native)) != digest(params(score)) or any(score.params[k] != v for k, v in [('tmin', lo), ('tmax', hi)]):
            raise ValueError('parallel scoring changed non-window epoch parameters')
        cursor = score.input
        if cursor != native.input:
            adapter = executor.steps[cursor]
            if (adapter.unit_id, adapter.op, adapter.implementation_version, adapter.input) != ('EEG-RESAMPLE', 'resample', '2', native.input):
                raise ValueError('parallel scoring requires the same processed continuous signal')
        continuous = executor.nodes[native.input]['packet']
        positions = {int(v): i for i, v in enumerate(continuous.event_indices)}
        native_indices = set(source.event_indices.tolist())
        restored = [int(v) for v in final.event_indices if int(v) not in native_indices]
        if restored:
            # A boundary failure may precede annotation screening in MNE. Fail
            # conservatively if any potentially rejecting annotation is present.
            if any(str(d).lower().startswith(('bad', 'edge', 'boundary')) for d in continuous.data.annotations.description):
                raise ValueError('parallel scoring cannot restore events in a record with source rejection annotations')
            for event_index in restored:
                position = positions.get(event_index)
                reasons = source.data.drop_log[position] if position is not None and position < len(source.data.drop_log) else ()
                if not reasons or not set(reasons) <= {'NO_DATA', 'TOO_SHORT'}:
                    raise ValueError('parallel scoring cannot restore source-screened events')
        if final.reference != source.reference or final.data.ch_names != source.data.ch_names:
            raise ValueError('parallel scoring changed source channels or reference')
    final = deepcopy(final)
    final.data = final.data.copy().crop(tmin=lo, tmax=hi)
    final.epoch_template = final.data
    return final, source, dict(policy=window.policy, source_output_node=source_id,
        scoring_output_node=output, window={'tmin': lo, 'tmax': hi},
        source_parameters_unchanged=True, source_descriptor='source-output/data.json',
        restored_boundary_event_indices=restored,
        rejection_policy='retain source screening; only boundary context loss may be restored')
