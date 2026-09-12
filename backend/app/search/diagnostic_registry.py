"""Versioned, trusted diagnostic kernels; requests cannot supply executable code."""
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Literal

from pydantic import Field, model_validator
from app.preprocessing.schemas import Contract
from app.preprocessing.storage import digest

NextAction = Literal['propose_candidate', 'request_evidence', 'request_diagnostic', 'finish']


class DiagnosticBranch(Contract):
    next_action: NextAction
    reason: str = Field(min_length=1, max_length=2000)


class DiagnosticExperiment(Contract):
    hypothesis: str = Field(min_length=1, max_length=2000)
    competing_explanation: str = Field(min_length=1, max_length=2000)
    metric: str = Field(min_length=1, max_length=160)
    comparison: Literal['gt', 'ge', 'lt', 'le']
    threshold: float = Field(allow_inf_nan=False)
    threshold_rationale: str = Field(min_length=1, max_length=2000)
    branches: dict[Literal['condition_met', 'condition_not_met', 'unavailable'], DiagnosticBranch]

    @model_validator(mode='after')
    def complete(self):
        if set(self.branches) != {'condition_met', 'condition_not_met', 'unavailable'}:
            raise ValueError('诊断必须预登记成立、不成立和不可用三个分支')
        return self


class DiagnosticResponse(Contract):
    diagnostic_id: str
    disposition: Literal['follow', 'revise']
    reason: str = Field(min_length=1, max_length=2000)


@dataclass(frozen=True)
class DiagnosticDefinition:
    kind: str
    version: str
    input_domain: str
    numeric_contract: str
    scalar_paths: tuple[str, ...]
    handler: object
    reference_required: bool = False


_REGISTRY = {}


def register(definition):
    if definition.kind in _REGISTRY or not callable(definition.handler):
        raise ValueError('诊断注册重复或缺少受信任实现')
    _REGISTRY[definition.kind] = definition


def _profile(quality, reference, baseline, stage):
    return {}


def _paired(quality, reference, baseline, stage):
    from .neural_diagnostics import comparison
    return comparison(baseline, quality, {}, {}, stage)


def _spectrum(quality, reference, baseline, stage):
    from .metric_claims import spectral_facts
    row = quality.get('stages', {}).get(stage, {}).get('psd', {})
    facts = spectral_facts(row)
    return {'spectral_distribution': facts or {'status': 'unavailable',
                'reason': row.get('reason') or 'complete_positive_psd_with_frequency_axis_required'},
            'status': 'evaluated' if facts else 'unavailable',
            'spectral_reference': {**reference, 'json_pointer': f'/stages/{stage}/psd'}}


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


def catalog():
    return {'schema_version': 'diagnostic-registry-1', 'label_permission': 'none',
        'implementation_policy': 'trusted_versioned_code_only; no request-supplied code or subject-specific recipe',
        'cost_contract': {'max_input_bytes_per_call': 64 * 1024**2, 'max_input_files_per_call': 4096,
            'max_output_bytes_per_call': 4 * 1024**2, 'max_seconds_per_call': 60,
            'timeout_enforcement': 'cooperative between bounded reads and kernels; not a hard OS deadline'},
        'definitions': [{'kind': d.kind, 'version': d.version, 'input_domain': d.input_domain,
            'stages': ['source_raw', 'source_task', 'processed_task', 'processed_continuous'],
            'reference_required': d.reference_required, 'label_permission': 'none',
            'numeric_contract': d.numeric_contract, 'scalar_paths': list(d.scalar_paths),
            'artifacts': ['hashed_diagnostic_json', 'hashed_input_references', 'branch_observation_and_next_action']}
            for d in _REGISTRY.values()]}


def validate_request(protocol, request):
    definition = _REGISTRY.get(request['kind'])
    frozen = (protocol or {}).get('diagnostic_registry')
    if definition is None:
        raise ValueError('诊断未注册，不能执行模型提供的代码')
    if request.get('stage') not in {'source_raw', 'source_task', 'processed_task', 'processed_continuous'}:
        raise ValueError('诊断输入阶段不在注册合同内')
    if frozen is None:
        if protocol is not None and request['kind'] not in {'signal_profile', 'paired_comparison'}:
            raise ValueError('历史运行未冻结此诊断，不能回填新协议')
    elif digest(frozen) != protocol.get('diagnostic_registry_hash') or frozen != catalog():
        raise ValueError('冻结诊断注册合同与当前实现不一致')
    if definition.reference_required != bool(request.get('reference_candidate_id')):
        raise ValueError('诊断参考候选要求不满足')
    experiment = request.get('experiment')
    if frozen and not experiment:
        raise ValueError('诊断需先登记竞争假设、数值条件及后续分支')
    if experiment:
        parsed = DiagnosticExperiment.model_validate(experiment)
        if parsed.metric not in definition.scalar_paths:
            raise ValueError('诊断预测指标不在已注册数值合同内')
    return definition


def branch_result(result, experiment):
    parsed = DiagnosticExperiment.model_validate(experiment)
    value = result
    valid = True
    for part in parsed.metric.split('.'):
        if not isinstance(value, dict):
            valid = False
            break
        if value.get('status') not in (None, 'ok', 'evaluated', 'computed'):
            valid = False
        value = value.get(part)
    valid = valid and type(value) in (int, float) and math.isfinite(value)
    if valid:
        met = {'gt': value > parsed.threshold, 'ge': value >= parsed.threshold,
               'lt': value < parsed.threshold, 'le': value <= parsed.threshold}[parsed.comparison]
        outcome = 'condition_met' if met else 'condition_not_met'
    else:
        outcome = 'unavailable'
    return {'experiment': parsed.model_dump(mode='json'), 'value': value if valid else None,
        'outcome': outcome, 'selected_branch': parsed.branches[outcome].model_dump(),
        'interpretation': 'A numeric condition tests a prediction; it does not establish its proposed mechanism.'}


def pending_response(state):
    acknowledged = {((a.get('result') or {}).get('diagnostic_response') or {}).get('diagnostic_id')
                    for a in state.get('actions', []) if a['action'] == 'model_decision' and a['status'] == 'completed'}
    return next((d for d in state.get('diagnostics', [])
                 if d.get('decision_effect') and d['id'] not in acknowledged), None)


def validate_response(state, result):
    pending = pending_response(state)
    reply = result.get('diagnostic_response')
    if pending is None:
        if reply:
            raise ValueError('没有待响应的诊断，不能伪造诊断影响')
        return
    if not reply or reply['diagnostic_id'] != pending['id']:
        raise ValueError('下一步必须响应待处理诊断的实际结果')
    parsed = DiagnosticResponse.model_validate(reply)
    if parsed.disposition == 'follow' and result['decision']['action'] != pending['decision_effect']['selected_branch']['next_action']:
        raise ValueError('下一动作不符合预登记分支；改变计划须显式说明修订理由')


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

    def read(self, path, expected_hash):
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
        return json.loads(data.decode('utf-8'))
