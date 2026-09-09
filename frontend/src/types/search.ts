export type SearchStrategy = 'adaptive' | 'random' | 'exhaustive' | 'one_shot'
export type SearchStatus = 'preparing' | 'running' | 'completed' | 'stopped' | 'failed' | 'cancelled' | 'interrupted'

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
  predicted?: number
  missing?: number
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
    status?: string
    macro_ba?: number | null
    mean_delta?: number | null
    subjects?: Record<string, SearchSubjectMetrics>
    coverage?: SearchCoverage
    diagnostics?: { floor_fraction?: number | null; converged?: boolean | null }
    [key: string]: unknown
  } | null
  error?: string | null
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
  request?: unknown
  result?: unknown
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
  schema_version: '1'
  request: SearchRequest
  phase?: string | null
  message?: string | null
  error?: string | null
  panel?: string | SearchPanel | null
  candidates?: SearchCandidate[]
  actions?: SearchAction[]
  artifacts?: { name: string; description?: string; url?: string }[]
}
