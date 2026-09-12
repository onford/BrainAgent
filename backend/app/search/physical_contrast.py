"""Shared linear measurement projection and signed signal differences, without fitting."""
from copy import deepcopy
import numpy as np

from app.preprocessing.storage import digest
from .reconstruction import align_fair_targets
from .quality_diagnostics import diagnostic_views


def check_sample_geometry(config, source_sfreq):
    from app.preprocessing.units.operations_v2 import DEFINITIONS
    from .quality_evaluation import _data_chain
    for step in _data_chain(config):
        if step.unit_id in {'EEG-CLASSIC-NATIVE','EEG-RELAX-NATIVE'}:
            raise ValueError('native_pipeline_requires_an_explicit_interior_sample_map_and_band_contract')
        if step.implementation_version=='2':
            effect=DEFINITIONS[(step.unit_id,step.op)]['effect']
            if effect in {'crop','crop_join','decimate','native_pipeline','csd'}:
                raise ValueError('changed_sample_or_physical_geometry_requires_explicit_comparison_adapter')
        if step.op.startswith('resample') and step.params.get('sfreq')!=source_sfreq:
            raise ValueError('resampling_requires_explicit_same_source_sample_comparison_adapter')


def contrast_epochs(source, processed, *, sfreq, channels, source_trial_ids, processed_trial_ids,
                    source_history, processed_history, time_window):
    if not source_trial_ids or source_trial_ids!=processed_trial_ids or len(set(source_trial_ids))!=len(source_trial_ids):
        raise ValueError('common_view_requires_identical_original_trial_order')
    if len(np.shape(source))!=3 or np.shape(source)!=np.shape(processed) or np.shape(source)[0]!=len(source_trial_ids):
        raise ValueError('common_view_requires_identical_original_sample_grid')
    if any(h is None or not h.get('nominal_band_hz') for h in (source_history,processed_history)):
        raise ValueError('common_view_requires_declared_frequency_history')
    # Fixed engineering envelope, intersected with declared inherited bands.
    # No signal-based optimization, inferred bandwidth or fitted scaling.
    lo=max(0.5,source_history['nominal_band_hz'][0],processed_history['nominal_band_hz'][0])
    hi=min(45.,source_history['nominal_band_hz'][1],processed_history['nominal_band_hz'][1])
    if not 0<lo<hi<sfreq/2:
        raise ValueError('no_valid_common_analysis_band')
    if len(channels)<2:
        raise ValueError('common_average_reference_requires_at_least_two_channels')
    referenced={key:np.asarray(value,dtype=float)-np.asarray(value,dtype=float).mean(axis=1,keepdims=True)
                for key,value in {'source':source,'processed':processed}.items()}
    projected,space=align_fair_targets(referenced,sfreq,channels=channels,
        input_unit='V',output_unit='V',source_reference='average',reference='unchanged',band_hz=(lo,hi))
    space['alignment']['reference']='separate_common_average_over_identical_channels_before_shared_filter'
    projected['difference']=projected['source']-projected['processed']
    contract=dict(schema_version='physical-contrast-1',space=space,original_trial_ids=list(source_trial_ids),
        time_window=list(time_window),difference='common_source_minus_common_processed',
        projection_selection='fixed_0.5_to_45Hz_envelope_intersect_declared_inherited_bands',
        source_history=deepcopy(source_history),processed_history=deepcopy(processed_history),
        geometry='same_original_cues_samples_channels; no_resampling_or_time_warp',
        fit_scope='not_fitted',selection_role='descriptive_only',neural_preservation='not_established')
    report=dict(status='evaluated',contract=contract,contract_sha256=digest(contract),
        expected_trials=len(source_trial_ids),paired_trials=len(source_trial_ids),unit='V',
        views={key:dict(rms_V=float(np.sqrt(np.mean(value*value))),
                       preview=diagnostic_views(value,sfreq,list(channels),trial_ids=source_trial_ids))
               for key,value in projected.items()},
        limitations=['Signed signal difference includes filtering, reference, interpolation and cleaning effects; it is not isolated artifact or neural ground truth.',
            'Shared analysis filter and CAR do not undo inherited attenuation, interpolate missing bandwidth or make different transfer functions identical.',
            'Zero-phase epoch filtering has edge effects; full supplied windows and their denominator are retained without padding across trials.',
            'Unknown acquisition filters remain unknown; nominal bands are not calibrated usable bandwidth.'])
    return projected,report
