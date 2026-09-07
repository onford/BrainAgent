export type RunStatus = 'pending' | 'planning' | 'running' | 'completed' | 'failed' | 'cancelled'
export type StepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'submitted' | 'blocked'

export interface PlanStep {
  step: number
  agent: string
  task: string
  depends_on: number[]
  status: StepStatus
  attempts: number
}

export interface Plan {
  goal: string
  steps: PlanStep[]
}

export interface AgentResult {
  agent_name: string
  success: boolean
  output: unknown
  observations: string[]
  error: string | null
}

export interface ExecutionEvent {
  event_type: string
  agent_name: string | null
  step: number | null
  message: string
  timestamp: string
  data: Record<string, unknown>
}

export interface ChatResponse {
  run_id: string
  session_id: string
  status: RunStatus
  plan: Plan | null
  results: AgentResult[]
  events: ExecutionEvent[]
  final_answer: unknown
  error: string | null
}

export interface AgentInfo {
  name: string
  description: string
}
