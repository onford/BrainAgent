import { apiRequest } from './client'
import type { ToolIntegration, ValidationResult } from '../types/integration'

export interface IntegrationUpdate {
  enabled: boolean
  credentials: Record<string, string | number | boolean>
  remove_credentials: string[]
}

export function fetchIntegrations(): Promise<ToolIntegration[]> {
  return apiRequest('/api/integrations/tools')
}

export function saveIntegration(
  toolId: string,
  payload: IntegrationUpdate,
): Promise<ToolIntegration> {
  return apiRequest(`/api/integrations/tools/${toolId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function validateIntegration(toolId: string): Promise<ValidationResult> {
  return apiRequest(`/api/integrations/tools/${toolId}/validate`, { method: 'POST' })
}

export async function deleteIntegration(toolId: string): Promise<void> {
  await apiRequest<void>(`/api/integrations/tools/${toolId}`, { method: 'DELETE' })
}
