import { apiRequest } from './client'
import type { AgentInfo } from '../types/agent'

export function fetchAgents(): Promise<AgentInfo[]> {
  return apiRequest('/api/agents')
}
