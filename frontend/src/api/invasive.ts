import { apiUrl } from './client'

export type InvasiveRef = { id: string; sha256: string }
export type InvasiveArtifact = { name: string; bytes: number; sha256: string | null }
export type InvasiveCollection = {
  id: string
  path: string
  modality: string
  representation: string
  entity_axis: string
  shape: number[]
  dtype: string
  physical_units?: string | null
  upstream_processed: boolean
  metadata: Record<string, unknown>
}
export type InvasiveSnapshot = {
  dataset_id: string
  session_id: string
  subject_id?: string | null
  standard: string
  standard_version?: string | null
  modality: string
  source: { path: string; size_bytes: number; modified_ns: number; sha256?: string | null }
  collections: InvasiveCollection[]
  timebases: Array<{ id: string; kind: string; count: number; rate_hz?: number | null; observed_start?: number | null; observed_stop?: number | null }>
  processing_history: string[]
  warnings: string[]
  inspected_values: number
}
export type InvasivePlanStep = {
  id: string
  stage: string
  operation: string
  status: 'run' | 'skip' | 'blocked' | 'optional'
  reason: string
  parameters: Record<string, unknown>
  evidence_needed: string[]
}
export type InvasivePlan = {
  task: string
  modality: string
  input_representation: string
  strategy: string
  executable: boolean
  method_profile?: string | null
  qc: Record<string, unknown>
  transform: { bin_size_s: number; smoothing_sigma_s?: number | null; representation: string; run_baseline: boolean; [key: string]: unknown }
  steps: InvasivePlanStep[]
  warnings: string[]
  literature_evidence_refs: InvasiveRef[]
  code_evidence_refs: InvasiveRef[]
}
export type InvasiveBaseline = {
  status: string
  model?: string
  alpha?: number
  split?: string
  train_rows?: number
  test_rows?: number
  r2?: Array<number | null>
  reason?: string
  interpretation?: string
}
export type InvasiveResult = {
  status: string
  created_at?: string | null
  report: string
  final_shapes: Record<string, number[] | null>
  unit_retention_ratio: number
  warnings: string[]
  alignment: Record<string, any>
  validation: {
    unit_count_input: number
    unit_count_retained: number
    unit_retention_ratio: number
    signal_distribution?: Record<string, number> | null
    baseline: InvasiveBaseline
    [key: string]: unknown
  }
}
export type InvasiveRunDetail = {
  result_ref: InvasiveRef
  result: InvasiveResult
  plan_ref: InvasiveRef
  plan: InvasivePlan
  snapshot_ref: InvasiveRef
  snapshot: InvasiveSnapshot
  artifacts: InvasiveArtifact[]
}
export type InvasiveRunSummary = {
  result_ref: InvasiveRef
  status: string
  created_at?: string | null
  dataset_id: string
  session_id: string
  subject_id?: string | null
  modality: string
  task: string
  strategy: string
  final_shapes: Record<string, number[] | null>
  unit_retention_ratio: number
}

export function invasiveArtifactUrl(resultId: string, name: string): string {
  return apiUrl(`/api/preprocessing/invasive/results/${encodeURIComponent(resultId)}/artifacts/${name.split('/').map(encodeURIComponent).join('/')}`)
}
