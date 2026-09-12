"""Explicit measurement frames; unknown provenance never authorizes subtraction."""
from copy import deepcopy
import re
from app.preprocessing.storage import digest


def measurement_frame(report, *, source_files, record_id, stage, sample_identity, verified):
    history=report.get('metadata',{}).get('history')
    if not verified or not history or 'sfreq' not in report:
        return dict(status='unavailable',reason='verified_measurement_provenance_unavailable')
    # Use actual unit/operation/parameters from the checked execution plan.
    # Full operation matching is conservative: a changed cleaning operation
    # requires an explicit common-view comparison rather than a native delta.
    operations=[{k:o.get(k) for k in ('unit_id','op','implementation_version','profile','frozen_parameters')}
                for o in history.get('operations',[])]
    contract=dict(schema_version='physical-frame-1',record_id=record_id,stage=stage,
        source_files_sha256=digest(source_files),unit=report['unit'],channels=report['channel_names'],
        sfreq=report['sfreq'],epoch_count=report['n_epochs'],samples_per_epoch=report['n_samples_per_epoch'],
        sample_identity=sample_identity,reference=history.get('reference'),
        runtime_reference=history.get('runtime_reference'),runtime_custom_ref_applied=history.get('runtime_custom_ref_applied'),
        reference_bindings=history.get('reference_bindings',[]),
        nominal_band_hz=history.get('nominal_band_hz'),notch_centers_hz=history.get('notch_centers_hz'),
        acquisition_filters={k:history.get(k) for k in ('source_software_filters','source_hardware_filters','source_filter_metadata_incomplete')},
        executed_signal_operations=operations)
    return dict(status='verified',contract=deepcopy(contract),sha256=digest(contract))


def paired_frames(left_records,right_records,stage):
    left={r['record_id']:r for r in left_records}
    right={r['record_id']:r for r in right_records}
    reasons={}
    if len(left)!=len(left_records) or len(right)!=len(right_records):
        return False,{'records':'duplicate_record_identity'}
    for rid in sorted(left.keys()|right.keys()):
        a=left.get(rid,{}).get('measurement_frames',{}).get(stage,{})
        b=right.get(rid,{}).get('measurement_frames',{}).get(stage,{})
        if any(f.get('status')!='verified' or not re.fullmatch(r'[a-f0-9]{64}',f.get('sha256','')) for f in (a,b)):
            reasons[rid]='physical_frame_unavailable'
        elif any('contract' in f and f.get('sha256')!=digest(f['contract']) for f in (a,b)):
            reasons[rid]='physical_frame_checksum_mismatch'
        elif a['sha256']!=b['sha256']:
            reasons[rid]='physical_frame_differs'
    return bool(left) and not reasons,reasons
