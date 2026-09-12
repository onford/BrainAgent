"""Export an immutable selected Collection record for full native pipeline audits.

Run from backend: python -m scripts.prepare_classic_input --input INPUT.json
--record RECORD_ID --line-frequency 60 --output NEW_DIRECTORY
"""
import argparse
from pathlib import Path
import numpy as np
from scipy.io import savemat

from app.preprocessing.inputs import read_record, validate_record_files
from app.preprocessing.schemas import PreprocessInput
from app.preprocessing.storage import file_hash, write_json


def prepare(input_path, record_id, output, line_frequency):
    data = PreprocessInput.model_validate_json(Path(input_path).read_text(encoding='utf-8'))
    if record_id not in data.collection.selected_record_ids:
        raise ValueError('Native audit must select a record in the frozen Collection selection')
    record = next(r for r in data.collection.records if r.id == record_id)
    if not 0 < line_frequency < record.sfreq / 2:
        raise ValueError('Explicit native mains frequency must be below Nyquist')
    output = Path(output).resolve()
    source = Path(data.collection.root).resolve()
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('Native audit output must be new and disjoint from the source')
    validate_record_files(source, record)
    raw, target_events, mapping = read_record(source, record, data.survey.event_id, data.survey.context_event_id)
    try:
        if any(kind != 'eeg' for kind in raw.get_channel_types()):
            raise ValueError('This native bridge requires EEG-only input; declare a separate auxiliary-channel adapter')
        raw.load_data()
        positions = np.array([ch['loc'][:3] for ch in raw.info['chs']])
        if not np.isfinite(positions).all() or np.any(np.linalg.norm(positions, axis=1) == 0):
            raise ValueError('Native spatial pipeline requires actual finite electrode coordinates')
        indices = list(range(1, len(raw.ch_names) + 1))
        configuration = {k: indices for k in ('referenceChannels', 'evaluationChannels', 'rereferencedChannels', 'lineNoiseChannels')}
        configuration.update(lineFrequencies=[line_frequency], errorMsgs='verbose')
        annotations = list(raw.annotations)
        events = np.array([[round((float(a['onset'])-raw.first_time)*raw.info['sfreq']) + raw.first_samp, 0, i+1]
                           for i, a in enumerate(annotations)], dtype=float).reshape(-1, 3)
        output.mkdir(parents=True)
        savemat(output/'bridge-input.mat', {'signal_V':raw.get_data(), 'sfreq':float(raw.info['sfreq']),
            'first_sample':float(raw.first_samp), 'channels':np.array(raw.ch_names, dtype=object),
            'positions':positions, 'events':events,
            'event_labels':np.array([a['description'] for a in annotations],dtype=object),
            'event_durations_samples':np.array([a['duration'] * raw.info['sfreq'] for a in annotations]),
            'configuration':configuration})
        validate_record_files(source, record)
        write_json(output/'input.json', {'record':record.model_dump(mode='json'), 'source_root':str(source),
            'input_snapshot_sha256':file_hash(Path(input_path)), 'bridge_sha256':file_hash(output/'bridge-input.mat'),
            'target_event_mapping':mapping, 'target_events':target_events.tolist(),
            'all_annotation_labels':[a['description'] for a in annotations],
            'configuration':configuration, 'configuration_origin':'native defaults with explicit target channels and declared mains frequency',
            'geometry_adapter':'MNE head X/Y/Z to EEGLAB Y/-X/Z; coordinates remain in meters',
            'units':'Input physical V; native EEGLAB bridge multiplies by 1e6 to uV exactly once',
            'original_data_unchanged':True})
    finally:
        raw.close()


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',required=True)
    parser.add_argument('--record',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--line-frequency',type=float,required=True)
    args=parser.parse_args()
    prepare(args.input,args.record,args.output,args.line_frequency)
