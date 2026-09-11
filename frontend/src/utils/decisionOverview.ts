import type { SearchCandidate, SearchState } from '../types/search'

export function assessmentProtocol(state: SearchState, candidate?: SearchCandidate) {
  const assessment = candidate?.receipt?.assessment
  const utility = assessment?.utility as { utility_version?: number } | undefined
  if (assessment?.schema_version === 'assessment-v2' || utility?.utility_version === 2) return 'eegnet'
  if (assessment?.schema_version === 'assessment-v1' || utility?.utility_version === 1) return 'legacy-suite'
  if (state.protocol?.utility_version === 2 || state.protocol?.assessment === 'assessment-v2' || (state.protocol?.assessment as { version?: number } | undefined)?.version === 2) return 'eegnet'
  if (state.protocol?.version === '3' || state.protocol?.assessment) return 'legacy-suite'
  return 'single'
}

// A missing primary score must never be replaced by the CSP anchor or a partial seed result.
export function decisionScore(state: SearchState, candidate: SearchCandidate): number | null {
  const value = assessmentProtocol(state, candidate) === 'single' ? candidate.receipt?.macro_ba : candidate.receipt?.assessment?.selection_score
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1 ? value : null
}

export function protocolLabel(state: SearchState, candidate?: SearchCandidate) {
  const kind = assessmentProtocol(state, candidate)
  if (kind === 'eegnet') return 'EEGNet 三种子被试宏平均 BA'
  if (kind === 'legacy-suite') return '历史协议 · 三主模型平均 BA'
  const learner = candidate?.receipt?.primary_learner ?? (candidate?.receipt?.evaluator_version === 1 ? 'logvariance-scaler-logistic-v1' : state.protocol?.evaluator)
  return ['csp4_reg0.1_shrinkage_lda', 'csp-shrinkage-lda-v2'].includes(learner ?? '') ? 'CSP + 收缩 LDA · 被试平均 BA' : `保存的评价器${learner ? `（${learner}）` : ''} · BA`
}
