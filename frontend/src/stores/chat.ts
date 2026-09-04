import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { streamChat } from '../api/chat'
import {
  createSession as createSessionRequest,
  deleteSession as deleteSessionRequest,
  fetchSessions,
} from '../api/sessions'
import type { ChatResponse, ExecutionEvent } from '../types/agent'
import type { ChatMessage, Session, StreamActivity } from '../types/session'
import { activityDetail, stringifyValue } from '../utils/activity'

function localId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`
}

export const useChatStore = defineStore('chat', () => {
  const sessions = ref<Session[]>([])
  const activeSessionId = ref<string | null>(null)
  const loadingSessions = ref(false)
  const runningSessionIds = ref<string[]>([])
  const deletingSessionIds = ref<string[]>([])
  const error = ref<string | null>(null)

  const activeSession = computed(
    () => sessions.value.find((session) => session.id === activeSessionId.value) ?? null,
  )
  const activeMessages = computed(() => activeSession.value?.messages ?? [])
  const isStreaming = computed(
    () => activeSessionId.value !== null && runningSessionIds.value.includes(activeSessionId.value),
  )
  const currentAgent = computed(() => {
    const pending = [...activeMessages.value].reverse().find((message) => message.pending)
    return [...(pending?.activities ?? [])].reverse().find((activity) => activity.agent_name)
      ?.agent_name ?? null
  })

  async function initialize(): Promise<void> {
    loadingSessions.value = true
    error.value = null
    try {
      sessions.value = await fetchSessions()
      if (!activeSessionId.value && sessions.value.length) {
        activeSessionId.value = sessions.value[0].id
      }
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : '无法加载会话'
    } finally {
      loadingSessions.value = false
    }
  }

  async function newSession(): Promise<Session> {
    const existingEmpty = sessions.value.find(
      (session) => session.messages.length === 0 && !runningSessionIds.value.includes(session.id),
    )
    if (existingEmpty) {
      activeSessionId.value = existingEmpty.id
      return existingEmpty
    }
    error.value = null
    const session = await createSessionRequest()
    sessions.value.unshift(session)
    activeSessionId.value = session.id
    return session
  }

  function selectSession(sessionId: string): void {
    activeSessionId.value = sessionId
    error.value = null
  }

  function promoteSession(sessionId: string): void {
    const index = sessions.value.findIndex((session) => session.id === sessionId)
    if (index > 0) {
      const [session] = sessions.value.splice(index, 1)
      sessions.value.unshift(session)
    }
  }

  async function deleteSession(sessionId: string): Promise<void> {
    if (
      runningSessionIds.value.includes(sessionId)
      || deletingSessionIds.value.includes(sessionId)
    ) return
    const index = sessions.value.findIndex((session) => session.id === sessionId)
    if (index < 0) return

    error.value = null
    deletingSessionIds.value.push(sessionId)
    try {
      await deleteSessionRequest(sessionId)
      sessions.value.splice(index, 1)
      if (activeSessionId.value === sessionId) {
        activeSessionId.value = sessions.value[index]?.id ?? sessions.value[index - 1]?.id ?? null
      }
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : '无法删除会话'
      throw reason
    } finally {
      deletingSessionIds.value = deletingSessionIds.value.filter((id) => id !== sessionId)
    }
  }

  function applyEvent(sessionId: string, assistantId: string, event: ExecutionEvent): void {
    const session = sessions.value.find((item) => item.id === sessionId)
    const assistant = session?.messages.find((message) => message.id === assistantId)
    if (!session || !assistant) return

    if (event.event_type === 'stream_completed') {
      const response = event.data.response as ChatResponse | undefined
      if (response) assistant.content = stringifyValue(response.final_answer)
      assistant.pending = false
      return
    }
    if (event.event_type === 'run_completed') {
      assistant.content = stringifyValue(event.data.final_answer)
    } else if (event.event_type === 'run_failed') {
      assistant.content = event.message || 'Agent 运行失败'
      assistant.error = true
      assistant.pending = false
    }

    const activity: StreamActivity = {
      id: localId('event'),
      event_type: event.event_type,
      agent_name: event.agent_name,
      message: event.message,
      detail: activityDetail(event),
      data: event.data,
      timestamp: event.timestamp,
    }
    assistant.activities ??= []
    assistant.activities.push(activity)
  }

  async function submit(rawMessage: string): Promise<void> {
    const content = rawMessage.trim()
    if (!content) return
    let session = activeSession.value
    if (!session) session = await newSession()
    if (runningSessionIds.value.includes(session.id)) return

    error.value = null
    const timestamp = new Date().toISOString()
    const userMessage: ChatMessage = {
      id: localId('user'),
      role: 'user',
      content,
      created_at: timestamp,
    }
    const assistantMessage: ChatMessage = {
      id: localId('assistant'),
      role: 'assistant',
      content: '',
      created_at: timestamp,
      pending: true,
      activities: [],
    }
    session.messages.push(userMessage, assistantMessage)
    session.updated_at = timestamp
    promoteSession(session.id)
    runningSessionIds.value.push(session.id)

    try {
      await streamChat(session.id, content, (event) =>
        applyEvent(session!.id, assistantMessage.id, event),
      )
    } catch (reason) {
      assistantMessage.pending = false
      assistantMessage.error = true
      assistantMessage.content = reason instanceof Error ? reason.message : '流式请求失败'
      error.value = assistantMessage.content
    } finally {
      assistantMessage.pending = false
      runningSessionIds.value = runningSessionIds.value.filter((id) => id !== session!.id)
    }
  }

  return {
    sessions,
    activeSessionId,
    activeSession,
    activeMessages,
    loadingSessions,
    runningSessionIds,
    deletingSessionIds,
    isStreaming,
    currentAgent,
    error,
    initialize,
    newSession,
    selectSession,
    deleteSession,
    submit,
  }
})
