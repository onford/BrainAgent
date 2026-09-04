export type CredentialFieldType = 'text' | 'email' | 'secret' | 'number' | 'boolean' | 'select'
export type CredentialRequirement = 'none' | 'optional' | 'required'

export interface CredentialOption {
  label: string
  value: string
}

export interface CredentialField {
  key: string
  label: string
  type: CredentialFieldType
  required: boolean
  description?: string | null
  placeholder?: string | null
  options: CredentialOption[]
  configured: boolean
  value?: string | number | boolean | null
  masked_value?: string | null
}

export interface ToolIntegration {
  id: string
  name: string
  description: string
  category: string
  credential_requirement: CredentialRequirement
  credential_schema: CredentialField[]
  cost_policy: {
    tier: string
    summary: string
    requires_user_approval: boolean
  }
  configured: boolean
  enabled: boolean
  status: 'unvalidated' | 'valid' | 'invalid'
  last_validated_at?: string | null
  last_validation_error?: string | null
}

export interface ValidationResult {
  tool_id: string
  valid: boolean
  status: string
  message: string
  validated_at: string
}
