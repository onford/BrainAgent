import { apiRequest } from './client'
import type { ChatResponse } from '../types/agent'

export function sendChat(sessionId: string, message: string): Promise<ChatResponse> {
  return apiRequest('/api/chat', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, message }),
  })
}

export async function streamChat(
  sessionId: string,
  message: string,
  onEvent: (event: import('../types/agent').ExecutionEvent) => void,
): Promise<void> {
  const apiBase = import.meta.env.VITE_API_BASE_URL ?? ''
  const response = await fetch(`${apiBase}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ session_id: sessionId, message }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(body.detail ?? '流式请求失败')
  }
  if (!response.body) throw new Error('浏览器未提供可读响应流')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const emitFrame = (frame: string): void => {
    const payload = frame
      .split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n')
    if (payload && payload !== '[DONE]') onEvent(JSON.parse(payload))
  }
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const frames = buffer.split(/\r?\n\r?\n/)
    buffer = frames.pop() ?? ''
    frames.forEach(emitFrame)
    if (done) {
      if (buffer.trim()) emitFrame(buffer)
      break
    }
  }
}
