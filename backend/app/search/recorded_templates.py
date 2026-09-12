"""Prespecified EOG template extraction; physical provenance, no class labels."""
from pathlib import Path

import numpy as np
from scipy.io import loadmat

from app.preprocessing.storage import file_hash
from .io import write
from .source_simulation import CHANNELS


def bnci_eog_template(source, destination, *, expected_source_sha256, source_evidence):
    """Four fixed six-second windows from the third baseline run of A01T MAT.

    The caller must independently establish the exact MAT release and units.
    No data-driven peak/window selection, MI label access, resampling or fit.
    """
    source, destination = Path(source), Path(destination)
    if len(expected_source_sha256) != 64 or file_hash(source) != expected_source_sha256:
        raise ValueError('template source file hash differs from the verified release')
    if not isinstance(source_evidence, dict) or not source_evidence.get('source_url') or not source_evidence.get('unit_and_channel_evidence'):
        raise ValueError('template requires source URL and explicit unit/channel evidence')
    if destination.exists() or destination.with_suffix('.json').exists():
        raise FileExistsError('template output already exists')
    records = loadmat(source, simplify_cells=True)['data']
    run = records[2]
    values = np.asarray(run['X'], dtype=float)
    if float(run['fs']) != 250 or values.ndim != 2 or values.shape[1] != 25 or np.size(run['trial']) != 0:
        raise ValueError('expected the declared 250 Hz, 25-channel non-task run')
    starts = [2500, 4000, 5500, 7000]
    windows = [values[start:start + 1500, 22] * 1e-6 for start in starts]
    if any(row.shape != (1500,) or not np.isfinite(row).all() for row in windows):
        raise ValueError('all fixed EOG template windows must be complete and finite')
    coupling = np.array([1., .9, .7, .6, .3, .2, .3, .1, .05, .1, 0., 0.])
    coupling -= coupling.mean()  # Same declared average reference as the simulated sensors.
    template = np.stack(windows)[:, None, :] * coupling[None, :, None]
    if file_hash(source) != expected_source_sha256:
        raise ValueError('template source changed during extraction')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive publication also protects against a concurrent extraction.
    with destination.open('xb') as stream:
        np.save(stream, template, allow_pickle=False)
    manifest = dict(schema_version='recorded-template-1', kind='recorded_eog_waveform_with_fixed_engineering_coupling',
        unit='V', sfreq=250., channels=list(CHANNELS), sha256=file_hash(destination),
        source_file_sha256=expected_source_sha256, source_file_name=source.name,
        source_url=source_evidence['source_url'], unit_and_channel_evidence=source_evidence['unit_and_channel_evidence'],
        sample_selection=dict(run_index_zero_based=2, source_column_zero_based=22, source_channel='EOG1',
            starts_zero_based=starts, length_samples=1500, selection='fixed before reading amplitudes or outcomes'),
        source_scale_to_V=1e-6, spatial_coupling=coupling.tolist(),
        coupling_provenance='fixed engineering frontal-weighted projection, centered once across channels; not a measured ocular leadfield',
        labels_used=False, source_unchanged=True,
        limitations=['Recorded EOG can contain neural and other non-ocular activity; it is a waveform template, not pure artifact truth.',
            'No confirmed individual blink annotations; windows are not selected by amplitude or physiological classification.',
            'Injection strengths are explicitly normalized later; they do not estimate actual scalp contamination amplitude.'])
    write(destination.with_suffix('.json'), manifest)
    return manifest
