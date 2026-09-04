export type MessageRole = 'user' | 'assistant'

export interface StreamActivity {
  id: string
  event_type: string
  agent_name: string | null
  message: string
  detail?: string
  data?: Record<string, unknown>
  timestamp: string
}

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  created_at: string
  pending?: boolean
  error?: boolean
  activities?: StreamActivity[]
}

export interface Session {
  id: string
  created_at: string
  updated_at: string
  messages: ChatMessage[]
}
