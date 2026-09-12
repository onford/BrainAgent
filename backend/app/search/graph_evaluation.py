"""Explicit v2 graph to frozen voltage/EEGNet panel boundary."""
from copy import deepcopy
from types import SimpleNamespace

from app.preprocessing.schemas import MethodSpec, Step
from app.preprocessing.planner import compile_steps, training_grid
from app.preprocessing.units.operations_v2 import DEFINITIONS


def graph_method(steps):
    return any(s.implementation_version == '2' for s in steps)


def promote(steps):
    """Only exact v1 numerical kernels have a v2 promotion, never name matching."""
    exact = {'filter', 'notch', 'resample', 'reference', 'epoch', 'baseline', 'detrend'}
    result = []
    for s in steps:
        s = s.model_copy(deep=True)
        if s.implementation_version == '1':
            if s.op not in exact:
                raise ValueError(f'{s.id}: no verified v1-to-v2 numerical adapter')
            s.implementation_version = '2'
        result.append(s)
    return result


def check_config(config, record, contract):
    """Static admissibility; actual output maps/units are rechecked by consumers."""
    steps = config.steps
    if not steps or any(s.implementation_version != '2' for s in steps):
        raise ValueError('panel graph requires consistently versioned steps')
    by_id = {s.id: s for s in steps}
    chain, cursor = [], config.output
    while cursor != 'raw':
        if cursor not in by_id or cursor in [s.id for s in chain]:
            raise ValueError('invalid graph output dependency')
        chain.append(by_id[cursor]); cursor = by_id[cursor].input
    if any(DEFINITIONS[(s.unit_id, s.op)]['effect'] == 'csd' for s in chain):
        raise ValueError('CSD V/m^2 requires a separately versioned evaluation protocol')
    if any(s.input_representation != 'native' for s in chain):
        raise ValueError('array output needs an explicit physical representation adapter')
    expected_channels = tuple(contract.get('channels') or [n for n in record.channel_order if record.channels[n] == 'eeg'])
    expected = (expected_channels, contract['sfreq'], (round(contract['tmin']*contract['sfreq']), round(contract['tmax']*contract['sfreq'])))
    if training_grid(config, record) != expected:
        raise ValueError('graph output differs from frozen channels/sample/time grid')
    epochs = [s for s in chain if DEFINITIONS[(s.unit_id, s.op)]['effect'] == 'epoch']
    if len(epochs) != 1:
        raise ValueError('evaluation output must have one identifiable epoch ancestor')
    for s in steps:
        if s.decision and s.decision.mode == 'manual' and s.decision.status != 'confirmed':
            raise ValueError('graph is waiting for a bound human decision')
    return epochs[0]


def check_method(method, data, output):
    for record in data.collection.records:
        if record.id not in data.collection.selected_record_ids:
            continue
        steps = compile_steps(method, record, data, {})
        check_config(SimpleNamespace(steps=steps, output=method.output,evaluation_window=method.evaluation_window), record, output)


def check_log(log, step, directory=None):
    if step.implementation_version != '2':
        return all(log['parameters'].get(k) == v for k, v in step.params.items() if k != 'events')
    # JSON scientific inputs include models/arrays; compare the frozen Step and
    # its version, never a lossy string representation of runtime parameters.
    return (log.get('step_contract') == step.model_dump(mode='json')
            and log.get('implementation_version') == '2' and log.get('profile') == step.profile)
