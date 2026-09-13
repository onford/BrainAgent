"""Versioned, trusted diagnostic kernels; requests cannot supply executable code."""
from dataclasses import dataclass
import hashlib
import io
import json
import math
from pathlib import Path
import time
from typing import Literal

from app.preprocessing.storage import digest


@dataclass(frozen=True)
class DiagnosticDefinition:
    kind: str
    version: str
    input_domain: str
    numeric_contract: str
    scalar_paths: tuple[str, ...]
    handler: object
    reference_required: bool = False
    stages: tuple[str, ...] = ('source_raw', 'source_task', 'processed_task', 'processed_continuous')


_REGISTRY = {}


def register(definition):
    if definition.kind in _REGISTRY or not callable(definition.handler):
        raise ValueError('诊断注册重复或缺少受信任实现')
    _REGISTRY[definition.kind] = definition


def _profile(quality, reference, baseline, stage, context):
    return {}


def _paired(quality, reference, baseline, stage, context):
    from .neural_diagnostics import comparison
    return comparison(baseline, quality, {}, {}, stage)


def _spectrum(quality, reference, baseline, stage, context):
    from .metric_claims import spectral_facts
    row = quality.get('stages', {}).get(stage, {}).get('psd', {})
    facts = spectral_facts(row)
    return {'spectral_distribution': facts or {'status': 'unavailable',
                'reason': row.get('reason') or 'complete_positive_psd_with_frequency_axis_required'},
            'status': 'evaluated' if facts else 'unavailable',
            'spectral_reference': {**reference, 'json_pointer': f'/stages/{stage}/psd'}}


def _common_change(quality, reference, baseline, stage, context):
    from .temporal_preservation import common_view_diagnostic
    return common_view_diagnostic(quality, context)


def _components(quality, reference, baseline, stage, context):
    from .neural_spectra import spectral_components_diagnostic
    return spectral_components_diagnostic(quality, stage, context)


def _lateralization(quality, reference, baseline, stage, context):
    from .sensor_lateralization import lateralization_diagnostic
    return lateralization_diagnostic(quality, stage, context)


METRICS = ('line_ratio_50hz', 'line_ratio_60hz', 'low_correlation_fraction', 'flat_fraction',
            'numerical_rank', 'mu_mean_psd', 'beta_mean_psd', 'erds_mu', 'erds_beta',
            'emg_hf_proxy', 'covariance_trace')
register(DiagnosticDefinition('signal_profile', '2', 'verified_saved_quality_scalars',
    'Complete finite saved scalar measurements; missing and partial values stay unavailable.',
    tuple('observations.' + mid + '.value' for mid in METRICS), _profile))
register(DiagnosticDefinition('paired_comparison', '2', 'two_verified_saved_quality_receipts',
    'Candidate minus reference; all grouped records, coverage, denominators and native physical frames must match.',
    tuple('metrics.' + mid + '.mean_subject_difference' for mid in METRICS), _paired, True))
register(DiagnosticDefinition('spectral_distribution', '1', 'verified_saved_psd_and_frequency_axis',
    'Finite nonnegative complete PSD; mean over saved nonfrequency axes; first maximum bin and trapezoid integral on strictly increasing saved frequencies. No peak interpolation or neural-origin inference.',
    ('spectral_distribution.maximum_bin_hz', 'spectral_distribution.maximum_bin_psd',
     'spectral_distribution.integral_on_saved_grid'), _spectrum))
register(DiagnosticDefinition('common_view_change', '1', 'verified_paired_common_physical_voltage_arrays',
    'Unshifted normalized error/gain/correlation, bounded delay with ties and boundary maxima unavailable, and energy-centroid change. Full original trial/channel denominator. No alignment or neural-truth claim.',
    tuple('common_view_change.summary.' + name + '.value' for name in
          ('normalized_change', 'gain', 'zero_lag_correlation', 'lag_ms', 'energy_centroid_shift_ms')),
    _common_change, stages=('processed_task',)))
register(DiagnosticDefinition('spectral_components', '1', 'verified_fixed_continuous_voltage_windows',
    'IRASA-style reciprocal resampling with fixed Welch parameters and passband guard; signed periodic/aperiodic descriptions on first up to 16 seconds per record. Complete 2–30 Hz support required for aggregate. No peak/slope fitting or neural-origin inference.',
    ('spectral_components.signed_periodic_fraction.value',), _components,
    stages=('source_raw', 'processed_continuous')))
register(DiagnosticDefinition('sensor_lateralization', '1', 'verified_paired_C3_C4_task_precue_ERDS',
    'C3 minus C4 ERDS percentage-point contrast for fixed mu/beta bands; complete original trials, positive paired baseline power and verified physical frame required. Equal trials/records/subjects; delete-one sensitivity is not a confidence interval or a contralateral/source inference.',
    ('sensor_lateralization.summary.mu.value', 'sensor_lateralization.summary.beta.value'), _lateralization,
    stages=('source_task', 'processed_task')))


def catalog():
    return {'schema_version': 'diagnostic-registry-1', 'label_permission': 'none',
        'implementation_policy': 'trusted_versioned_code_only; no request-supplied code or subject-specific recipe',
        'cost_contract': {'max_input_bytes_per_call': 64 * 1024**2, 'max_input_files_per_call': 4096,
            'max_output_bytes_per_call': 4 * 1024**2, 'max_seconds_per_call': 60,
            'timeout_enforcement': 'cooperative between bounded reads and kernels; not a hard OS deadline'},
        'definitions': [{'kind': d.kind, 'version': d.version, 'input_domain': d.input_domain,
            'stages': list(d.stages),
            'reference_required': d.reference_required, 'label_permission': 'none',
            'numeric_contract': d.numeric_contract, 'scalar_paths': list(d.scalar_paths),
            'artifacts': ['hashed_diagnostic_json', 'hashed_input_references']}
            for d in _REGISTRY.values()]}


def validate_request(protocol, request):
    definition = _REGISTRY.get(request['kind'])
    frozen = (protocol or {}).get('diagnostic_registry')
    if definition is None:
        raise ValueError('诊断未注册，不能执行模型提供的代码')
    if request.get('stage') not in definition.stages:
        raise ValueError('诊断输入阶段不在注册合同内')
    if frozen is None:
        if protocol is not None and request['kind'] not in {'signal_profile', 'paired_comparison'}:
            raise ValueError('历史运行未冻结此诊断，不能回填新协议')
    elif digest(frozen) != protocol.get('diagnostic_registry_hash') or frozen != catalog():
        raise ValueError('冻结诊断注册合同与当前实现不一致')
    if definition.reference_required != bool(request.get('reference_candidate_id')):
        raise ValueError('诊断参考候选要求不满足')
    if request.get('experiment') is not None:
        raise ValueError('诊断仅返回测量，不接受调整预处理的后续动作分支')
    return definition


class DiagnosticInputBudget:
    """Bound reads before parsing; hash precisely the bytes supplied to the kernel."""
    def __init__(self, max_bytes, max_seconds=60):
        self.max_bytes = max_bytes
        self.bytes = 0
        self.files = 0
        self.deadline = time.monotonic() + max_seconds

    def check(self):
        if time.monotonic() >= self.deadline:
            raise ValueError('诊断时间预算已用尽')

    def _payload(self, path, expected_hash):
        self.check()
        path = Path(path)
        size = path.stat().st_size
        self.files += 1
        if self.files > 4096 or size > self.max_bytes - self.bytes:
            raise ValueError('诊断输入预算已用尽')
        with path.open('rb') as stream:
            data = stream.read(size + 1)
        self.bytes += len(data)
        self.check()
        if len(data) != size or hashlib.sha256(data).hexdigest() != expected_hash:
            raise ValueError('诊断输入哈希不一致')
        return data

    def read(self, path, expected_hash):
        return json.loads(self._payload(path, expected_hash).decode('utf-8'))

    def read_array(self, path, expected_hash):
        import numpy as np
        result = np.load(io.BytesIO(self._payload(path, expected_hash)), allow_pickle=False)
        if not isinstance(result, np.ndarray) or result.dtype.kind != 'f':
            raise ValueError('诊断数组必须是浮点电压，不能包含pickle或归档')
        self.check()
        return result
