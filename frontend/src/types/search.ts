export type SearchStrategy = 'adaptive' | 'random' | 'exhaustive' | 'one_shot'
export interface OperatorUsage {
  summary: {
    schema_version: string
    record_count: number
    evidence_issue_records: number
    record_execution_counts: Record<string, number>
    operators: Record<string, {
      unit_id: string; op: string; denominator: number; configured_records: number
      counts: { applied: number; not_applicable: number; failed: number; not_reached: number }
      reason_counts: Record<string, Record<string, number>>
    }>
  }
  artifact: { path: string; sha256: string; bytes: number }
}
export type SearchStatus = 'preparing' | 'running' | 'completed' | 'stopped' | 'failed' | 'cancelled' | 'interrupted'
export type SearchEvaluationMode = 'group_cross_validation' | 'subject_holdout'

export interface SearchFold {
  id: string
  train_subjects: string[]
  development_subjects: string[]
}

export interface SearchSignalDiagnostics {
  channel_variance: number[]
  channel_flat_fraction: number[]
  covariance_condition: number
  covariance_condition_before?: number
  covariance_condition_after?: number
  mean_channel_variance_before?: number
  mean_channel_variance_after?: number
  effective_rank_before?: number
  effective_rank_after?: number
}

export interface SearchDiagnosticsSummary {
  mean_condition_before: number
  mean_condition_after: number
  mean_variance_before: number
  mean_variance_after: number
  gate_fraction: number | null
  mean_effective_rank: number
  mean_anisotropy: number
}

export interface SearchRepresentation {
  version: '2'
  unit: 'V'
  channels: string[]
  records: Record<string, { subject: string; array_path: string; array_sha256: string; shape: number[]; unit: 'V' }>
}

export interface WorkflowEvaluation {
  selection_policy: 'development_score'
  quality_evaluated: true
  search_id: string
  score: number
  evaluation_scope: 'development'
  selected_candidate_id?: string
  selected_method_ref: { id: string; sha256: string }
  reason?: string
}

export interface SavedWorkflowEvaluation {
  selection_policy?: string
  quality_evaluated?: boolean
  search_id?: string
  score?: number | null
  evaluation_scope?: string
  selected_candidate_id?: string
  selected_method_ref?: { id: string; sha256?: string }
  reason?: string
}

export interface WorkflowSearchSummary {
  id: string
  status: SearchStatus
  message: string
  usage: SearchUsage
  budget: SearchBudget
  selected_candidate_id: string | null
}

export interface SearchBudget {
  max_candidates: number
  max_proposals: number
  max_evidence_reads: number
  max_seconds: number
  max_memory_mb: number | null
  max_disk_mb: number | null
}

export interface SearchRequest {
  workflow_id: string
  strategy: SearchStrategy
  budget: SearchBudget
  seed: number
  train_subjects?: string[]
  development_subjects?: string[]
}

export interface SearchUsage {
  candidates?: number
  proposals?: number
  evidence_reads?: number
  llm_calls?: number
  elapsed_seconds?: number
  retries?: number
}

export interface SearchSubjectMetrics {
  ba?: number | null
  delta?: number | null
  recall_left?: number | null
  recall_right?: number | null
  original_trials?: number
  eligible_trials?: number
  available_trials?: number
  predicted_trials?: number
  missing?: number
  [key: string]: unknown
}

export interface SearchSubject extends SearchSubjectMetrics {
  subject: string | number
}

export interface SearchCoverage {
  original?: number
  eligible?: number
  available?: number
  predicted?: number
  missing?: number
  common_invalid?: number
  common_invalid_reasons?: Record<string, number>
  train?: Omit<SearchCoverage, 'train' | 'development'>
  development?: Omit<SearchCoverage, 'train' | 'development'>
}

export interface SearchCandidate {
  id: string
  title?: string
  parameters?: { l_freq?: number; h_freq?: number; reference?: 'average' | 'original' }
  status: string
  job_id?: string | null
  receipt?: {
    assessment?: { selection_score: number | null; [key: string]: unknown } | null
    assessment_path?: string | null
    operator_usage?: OperatorUsage | null
    evaluator_version?: number
    evaluation_mode?: SearchEvaluationMode | null
    folds?: SearchFold[]
    primary_learner?: string
    secondary_learner?: string
    secondary_macro_ba?: number | null
    secondary_subjects?: Record<string, number>
    paired_subject_ci?: { low: number; high: number; n_subjects: number; confidence?: number; n_resamples?: number; seed?: number; method?: string; interpretation?: string } | null
    representation?: SearchRepresentation | null
    status?: string
    macro_ba?: number | null
    mean_delta?: number | null
    subjects?: Record<string, SearchSubjectMetrics>
    coverage?: SearchCoverage | null
    diagnostics?: { floor_fraction?: number | null; converged?: boolean | null; warnings?: string[]; subjects?: Record<string, SearchSignalDiagnostics>; summary?: SearchDiagnosticsSummary | null }
    [key: string]: unknown
  } | null
  error?: string | null
}

export interface SearchPrediction {
  kind: 'signal' | 'utility'
  metric: string
  direction: 'increase' | 'decrease' | 'unchanged'
  tolerance: number
  explanation: string
}

export interface SearchHypothesis {
  explanation: string
  competing_explanation: string
  observations: { candidate_id: string; metric: string }[]
  predictions: SearchPrediction[]
  weakened_by: string
}

export interface SearchPredictionCheck extends SearchPrediction {
  status: 'matched' | 'contradicted' | 'unavailable'
  before: number | null
  after: number | null
  difference: number | null
}

export interface SearchAction {
  index: number
  action: string
  status: string
  reason?: string | null
  expected_result?: unknown
  decision_branches?: unknown
  base_candidate_id?: string | null
  candidate_id?: string | null
  cost_seconds?: number | null
  error?: string | null
  request?: { hypothesis?: SearchHypothesis; [key: string]: unknown } | null
  result?: { prediction_checks?: { checks: SearchPredictionCheck[]; interpretation: string }; [key: string]: unknown } | null
}

export interface SearchSummary {
  id: string
  workflow_id: string
  status: SearchStatus
  created_at: string
  updated_at: string
  selected_candidate_id?: string | null
  stop_reason?: string | null
  usage?: SearchUsage
  budget?: SearchBudget
}

export interface SearchPanel {
  evaluation_mode?: SearchEvaluationMode
  folds?: SearchFold[]
  trial_count?: number
  eligible_count?: number
  train_subjects?: string[]
  development_subjects?: string[]
  records?: Record<string, Record<string, unknown>>
  output_contract?: Record<string, unknown>
  panel_hash?: string
  [key: string]: unknown
}

export interface SearchState extends SearchSummary {
  candidate_contrasts_to_reference?: Record<string, { removed_operations: string[]; added_operations: string[]; parameter_changes: { operation: string; parameter: string; before: unknown; after: unknown }[]; shared_operation_order_changed: boolean; scope_changes: string[]; interpretation: string }>
  literature_participation?: { status: string; statement: string; evaluated_candidate_ids: string[]; distinct_from_controls_evaluated_ids: string[] }
  diagnostics?: Record<string, any>[]
  schema_version?: string
  protocol?: { version?: string; evaluator?: string; space?: SearchOperatorSpace; [key: string]: unknown }
  registry?: SearchRecipeEntry[]
  request: SearchRequest
  deadline?: number
  phase?: string | null
  message?: string | null
  error?: string | null
  panel?: string | SearchPanel | null
  candidates?: SearchCandidate[]
  actions?: SearchAction[]
  artifacts?: { name: string; description?: string; url?: string }[]
}

export interface SearchRecipeEntry {
  id: string
  title: string
  origin: 'basic' | 'literature' | 'literature_adaptation' | 'derived'
  lineage?: { kind?: string; source_url?: string; source_id?: string; branch_id?: string; analysis?: string; method_id?: string; version?: string; method_ref?: { id: string }; [key: string]: unknown }[]
  parent_ids?: string[]
  issues?: { severity: string; code: string; message: string }[]
  seed_id: string
  parent_id: string | null
  recipe: { nodes: { id: string; operator: string; parameters: Record<string, unknown> }[] }
  edits: { action: string; [key: string]: unknown }[]
  deviations: string[]
  evidence_ids: string[]
  prior_challenges: Record<string, string>
}

export interface SearchOperatorSpace {
  operators: { id: string; title: string; input_stage: string; output_stage: string; required: boolean; domains: Record<string, { kind: string; minimum?: number; maximum?: number; choices?: unknown[]; unit: string; rationale: string; origin: string }>; requires: string[]; input_highpass?: { minimum_hz: number; window_parameter: string; minimum_cycles: number; rationale: string } | null; separations?: { upper_parameter: string; lower_parameter: string; minimum: number; rationale: string }[] }[]
  methods: { id: string; title: string; origin: string }[]
  priors: { id: string; strength: 'hard' | 'soft'; condition: string; rationale: string; evidence_ids: string[] }[]
  evidence: Record<string, { source_url: string; locator: string; text: string }>
}

export interface SearchSeedSummary {
  seeds: number[]
  mean_ba: number | null
  seed_sd: number | null
  minimum_ba: number | null
  maximum_ba: number | null
}
export interface SearchUtilityArtifact { path: string; sha256?: string }
export interface SearchMetricDistribution {
  mean: number; lower_quartile: number; subject_sd: number; n_subjects: number
}
export interface SearchSeedOutput {
  status: string
  seed: number
  folds: { fold_id: string; train_subjects: string[]; development_subjects: string[]; model: SearchUtilityArtifact; metadata: SearchUtilityArtifact; predictions: SearchUtilityArtifact }[]
  predictions: SearchUtilityArtifact | null
  metadata: SearchUtilityArtifact | null
  subjects: Record<string, SearchSubjectMetrics & { n_trials: number }>
  summary: Record<string, SearchMetricDistribution | null>
  error?: string | null
}
export interface SearchUtilityReceipt {
  utility_version: 1 | 2
  primary_suite: string[]
  learner_scores: Record<string, number | null>
  seed_summary?: SearchSeedSummary | null
  learners: Record<string, Omit<SearchSeedOutput, 'seed'> & { seeds?: Record<string, SearchSeedOutput>; seed_summary?: SearchSeedSummary | null }>
}
