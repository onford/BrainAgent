"""Deterministic claim eligibility after the caller verifies numerical receipts."""
from math import isfinite
from typing import Literal

from pydantic import Field
from app.preprocessing.schemas import Contract
from app.preprocessing.storage import digest
from .method_space import BASELINE_ID


class ClaimEligibility(Contract):
    id: str
    title: str
    status: Literal['supported_within_scope', 'not_established', 'unavailable']
    scope: str
    reason: str
    evidence: list[str]


class ConclusionEligibility(Contract):
    schema_version: Literal['conclusion-eligibility-1'] = 'conclusion-eligibility-1'
    selected_candidate_id: str | None
    panel_hash: str | None
    protocol_sha256: str
    selected_assessment_sha256: str | None
    reference_assessment_sha256: str | None
    primary_development_score: float | None = Field(default=None, ge=0, le=1)
    paired_development_score_difference: float | None = Field(default=None, ge=-1, le=1)
    claims: list[ClaimEligibility]


def _assessment(candidate):
    return ((candidate or {}).get('receipt') or {}).get('assessment') or {}


def _ready(candidate):
    assessment = _assessment(candidate)
    score = assessment.get('selection_score')
    from .assessment_contracts import AssessmentSummary
    from pydantic import ValidationError
    try:
        AssessmentSummary.model_validate(assessment)
    except ValidationError:
        return False
    return (candidate is not None and candidate.get('status') == 'evaluated'
        and (candidate.get('receipt') or {}).get('status') == 'evaluated'
        and assessment.get('schema_version') == 'assessment-v2'
        and assessment.get('selection_ready') is True
        and assessment.get('utility', {}).get('status') == 'evaluated'
        and type(score) in (float, int) and isfinite(score) and 0 <= score <= 1)


def qualify(state):
    """A complete evaluation is not automatically a successful scientific claim.

    Callers must verify the selected receipt and its artifact manifest first.
    No new experiments or inferential statistics are invented here.
    """
    selected = next((c for c in state['candidates'] if c['id'] == state.get('selected_candidate_id')), None)
    reference = next((c for c in state['candidates'] if c['id'] == BASELINE_ID), None)
    assessment, base = _assessment(selected), _assessment(reference)
    ready = _ready(selected)
    pair = (ready and _ready(reference) and selected['id'] != reference['id']
        and assessment.get('selection_policy') == base.get('selection_policy')
        and all(assessment.get('bindings', {}).get(k) is not None and
                assessment['bindings'][k] == base.get('bindings', {}).get(k) for k in ('input_hash', 'panel_hash')))
    rows = []
    def add(identity, title, supported, scope, reason, evidence=(), unavailable=False):
        rows.append(ClaimEligibility(id=identity, title=title,
            status='supported_within_scope' if supported else 'unavailable' if unavailable else 'not_established',
            scope=scope, reason=reason, evidence=list(evidence)))
    add('development_predictability', '开发面板预测表现', ready,
        ('固定 EEGNet 三种子、冻结开发被试与试次' if assessment.get('schema_version') == 'assessment-v2'
         else '保存的历史学习器协议；不转换为当前主指标'),
        '三个种子完整后可报告该面板的描述性主指标；反复选择带来的偏差仍存在。' if ready else '缺少当前协议完整主指标。',
        ['selected_receipt.assessment.utility'] if ready else [], unavailable=not ready)
    add('development_comparison', '同协议开发分数差值', pair,
        '选中候选与固定参考的描述性差值',
        '差值未作独立确认，也没有由此得到置信区间或因果效应。' if pair else '没有不同候选之间完整且绑定一致的参考比较。',
        ['selected_receipt.assessment', 'reference_candidate.assessment'] if pair else [], unavailable=not pair)
    current = bool(selected and selected.get('status') == 'evaluated'
                   and (selected.get('receipt') or {}).get('status') == 'evaluated')
    quality = assessment.get('quality', {}) if current else {}
    add('physical_proxy_measurements', '物理信号代理观测', quality.get('status') in {'evaluated', 'partial'},
        '已保存的单位、参考、通带、阶段和有效分母',
        '只能报告各可测指标及缺失原因；幅度或污染代理下降不证明神经信号保留。',
        ['selected_receipt.assessment.quality'] if quality.get('receipt_artifact') else [],
        unavailable=quality.get('status') not in {'evaluated', 'partial'})
    reconstruction = assessment.get('reconstruction', {}) if current else {}
    add('synthetic_reconstruction', '声明污染条件下的重建表现', reconstruction.get('status') in {'evaluated', 'partial'},
        '冻结半合成污染、cleanproxy 与有效配对窗口',
        '只能报告实际完成条件；真实 EEG cleanproxy 不是神经真值，不能外推到所有伪迹。',
        ['selected_receipt.assessment.reconstruction'] if reconstruction.get('receipt_artifact') else [],
        unavailable=reconstruction.get('status') not in {'evaluated', 'partial'})
    add('neural_preservation', '神经信号保留', False, '独立神经保护证据',
        '当前回执没有经验证的神经真值或完整保护验收；分类、质量代理与半合成重建不能代替该证据。')
    add('independent_generalization', '独立泛化改善', False, '事前隔离且未参与方法选择的数据',
        '当前流程使用开发反馈选择方法，没有绑定独立确认实验。')
    add('preprocessing_specific_benefit', '可归因于预处理的改善', False, '固定学习器、资源和数据划分的受控比较',
        '当前分数不足以区分预处理、学习器及搜索选择的贡献；需要事前声明的消融与独立验证。')
    return ConclusionEligibility(selected_candidate_id=state.get('selected_candidate_id'),
        panel_hash=(state.get('panel') or {}).get('panel_hash'), protocol_sha256=digest(state['protocol']),
        selected_assessment_sha256=digest(assessment) if assessment else None,
        reference_assessment_sha256=digest(base) if pair else None,
        primary_development_score=assessment['selection_score'] if ready else None,
        paired_development_score_difference=assessment['selection_score']-base['selection_score'] if pair else None,
        claims=rows).model_dump(mode='json')
