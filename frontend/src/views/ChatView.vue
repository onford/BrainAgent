<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useChatStore } from '../stores/chat'
import type { ChatMessage, Session, StreamActivity } from '../types/session'
import { renderMarkdown } from '../utils/markdown'
import PreprocessingCard from '../components/PreprocessingCard.vue'

function preprocessingOutputs(message: ChatMessage) {
  return (message.activities ?? []).flatMap((activity) => {
    const result = activity.data?.result as { agent_name?: string; output?: Record<string, unknown> } | undefined
    return activity.event_type === 'observation' && result?.agent_name === 'data_preprocessing' && result.output ? [result.output] : []
  })
}

const store = useChatStore()
const draft = ref('')
const sidebarOpen = ref(false)
const conversation = ref<HTMLElement | null>(null)
const textarea = ref<HTMLTextAreaElement | null>(null)
const copiedMessageId = ref<string | null>(null)
let copyResetTimer: ReturnType<typeof setTimeout> | undefined

const currentTitle = computed(() =>
  store.activeSession ? sessionTitle(store.activeSession) : '新对话',
)

function sessionTitle(session: Session): string {
  const firstUser = session.messages.find((message) => message.role === 'user')?.content.trim()
  return firstUser?.replace(/\s+/g, ' ') || '新对话'
}

function sessionPreview(session: Session): string {
  const last = [...session.messages].reverse().find((message) => message.content.trim())
  return last?.content.replace(/\s+/g, ' ') || '等待输入…'
}

function timeLabel(value: string): string {
  const date = new Date(value)
  const now = new Date()
  if (date.toDateString() === now.toDateString()) {
    return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(date)
  }
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(date)
}

function activityLabel(activity: StreamActivity): string {
  const labels: Record<string, string> = {
    run_started: '开始分析',
    thought: '规划下一步',
    agent_started: '调用 Agent',
    observation: '收到结果',
    run_completed: '完成回答',
    run_failed: '运行失败',
  }
  return activity.agent_name
    ? `${activity.agent_name} · ${labels[activity.event_type] ?? activity.event_type}`
    : labels[activity.event_type] ?? activity.event_type
}

function hasActivity(message: ChatMessage): boolean {
  return Boolean(message.activities?.length)
}

function submit(): void {
  const value = draft.value.trim()
  if (!value || store.isStreaming) return
  draft.value = ''
  resizeTextarea()
  void store.submit(value)
}

function handleComposerKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    submit()
  }
}

function handleGlobalShortcut(event: KeyboardEvent): void {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    void createConversation()
  }
}

function resizeTextarea(): void {
  void nextTick(() => {
    if (!textarea.value) return
    textarea.value.style.height = '0px'
    textarea.value.style.height = `${Math.min(textarea.value.scrollHeight, 180)}px`
  })
}

function chooseSession(sessionId: string): void {
  store.selectSession(sessionId)
  sidebarOpen.value = false
}

async function createConversation(): Promise<void> {
  await store.newSession()
  sidebarOpen.value = false
  await nextTick()
  textarea.value?.focus()
}

async function removeConversation(session: Session): Promise<void> {
  if (store.runningSessionIds.includes(session.id)) return
  const title = sessionTitle(session)
  if (!window.confirm(`确定删除“${title}”吗？此操作无法撤销。`)) return
  await store.deleteSession(session.id).catch(() => undefined)
}

async function copyMessage(message: ChatMessage): Promise<void> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(message.content)
    } else {
      const input = document.createElement('textarea')
      input.value = message.content
      input.style.position = 'fixed'
      input.style.opacity = '0'
      document.body.appendChild(input)
      input.select()
      document.execCommand('copy')
      input.remove()
    }
    copiedMessageId.value = message.id
    if (copyResetTimer) clearTimeout(copyResetTimer)
    copyResetTimer = setTimeout(() => {
      copiedMessageId.value = null
    }, 1600)
  } catch {
    store.error = '复制失败，请手动选择文本复制'
  }
}

async function scrollToBottom(): Promise<void> {
  await nextTick()
  if (conversation.value) conversation.value.scrollTop = conversation.value.scrollHeight
}

watch(draft, resizeTextarea)
watch(
  () => store.activeMessages.map((message) => `${message.content}:${message.activities?.length ?? 0}`),
  scrollToBottom,
)
watch(() => store.activeSessionId, scrollToBottom)

onMounted(async () => {
  window.addEventListener('keydown', handleGlobalShortcut)
  await store.initialize()
  await scrollToBottom()
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleGlobalShortcut)
  if (copyResetTimer) clearTimeout(copyResetTimer)
})
</script>

<template>
  <div class="app-layout">
    <button
      v-if="sidebarOpen"
      class="sidebar-scrim"
      aria-label="关闭会话侧栏"
      @click="sidebarOpen = false"
    />

    <aside class="session-sidebar" :class="{ open: sidebarOpen }">
      <div class="sidebar-brand">
        <div class="brand-glyph" aria-hidden="true">
          <span></span><span></span><span></span>
        </div>
        <div><strong>Brain Agent</strong><small>Neural workspace</small></div>
      </div>

      <button class="new-chat-button" type="button" @click="createConversation">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
        新建对话
        <kbd>⌘ K</kbd>
      </button>

      <div class="session-section-heading">
        <span>最近对话</span>
        <span v-if="store.loadingSessions" class="mini-spinner" />
      </div>

      <nav class="session-list" aria-label="会话列表">
        <div
          v-for="session in store.sessions"
          :key="session.id"
          class="session-item-shell"
          :class="{ active: store.activeSessionId === session.id }"
        >
          <button type="button" class="session-item" @click="chooseSession(session.id)">
            <span class="session-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24"><path d="M7 8h10M7 12h7m-7 8 3.2-3H18a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h1v3Z" /></svg>
            </span>
            <span class="session-copy">
              <strong>{{ sessionTitle(session) }}</strong>
              <small>{{ sessionPreview(session) }}</small>
            </span>
            <span
              v-if="store.runningSessionIds.includes(session.id)"
              class="session-running"
              aria-label="运行中"
            />
            <span
              v-else-if="store.deletingSessionIds.includes(session.id)"
              class="mini-spinner"
              aria-label="正在删除"
            />
            <time v-else>{{ timeLabel(session.updated_at) }}</time>
          </button>
          <button
            type="button"
            class="session-delete"
            :disabled="store.runningSessionIds.includes(session.id) || store.deletingSessionIds.includes(session.id)"
            :aria-label="`删除会话：${sessionTitle(session)}`"
            title="删除会话"
            @click="removeConversation(session)"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7m4 4v5m4-5v5" /></svg>
          </button>
        </div>
        <p v-if="!store.loadingSessions && store.sessions.length === 0" class="empty-sessions">
          还没有对话。创建一个 session 开始研究。
        </p>
      </nav>

      <div class="sidebar-footer">
        <RouterLink to="/settings/integrations" class="sidebar-link">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21h-4v-.09A1.7 1.7 0 0 0 8.5 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3v-4h.09A1.7 1.7 0 0 0 4.6 8.5a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3h4v.09A1.7 1.7 0 0 0 15.5 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.18.37.4.7.6 1 .3.3.7.5 1.1.5h.1v4h-.1c-.4 0-.8.2-1.1.5-.2.3-.42.63-.6 1Z" /></svg>
          Tool integrations
        </RouterLink>
        <RouterLink to="/agents" class="sidebar-link">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm8 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM2.5 20v-2.2A4.8 4.8 0 0 1 7.3 13h1.4a4.8 4.8 0 0 1 4.8 4.8V20m0-6.6a4.8 4.8 0 0 1 8 3.6v3" /></svg>
          Agent registry
        </RouterLink>
        <div class="runtime-state"><span></span>Orchestrator online</div>
      </div>
    </aside>

    <main class="conversation-pane">
      <header class="conversation-header">
        <button class="mobile-menu" type="button" aria-label="打开会话侧栏" @click="sidebarOpen = true">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
        </button>
        <div class="conversation-heading">
          <strong>{{ currentTitle }}</strong>
          <small v-if="store.isStreaming"><span class="header-pulse" />{{ store.currentAgent ?? 'orchestrator' }} 正在工作</small>
          <small v-else>Orchestrated agent session</small>
        </div>
        <button class="header-new-chat" type="button" aria-label="新建对话" @click="createConversation">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
        </button>
      </header>

      <section ref="conversation" class="conversation-scroll" aria-live="polite">
        <div v-if="store.activeMessages.length === 0" class="welcome-state">
          <div class="welcome-mark" aria-hidden="true">
            <span></span><span></span><span></span>
          </div>
          <h1>今天想研究什么？</h1>
          <p>描述你的神经科学问题。Orchestrator 会规划步骤，并在这里实时汇报各 Agent 的进展。</p>
          <div class="prompt-suggestions">
            <button type="button" @click="draft = '帮我调研一个公开神经数据集，并判断是否适合表征学习'">
              <strong>调研公开数据</strong><span>比较数据规模、格式和研究价值</span>
            </button>
            <button type="button" @click="draft = '分析我的神经数据预处理流程，并给出可复现的改进方案'">
              <strong>审查数据流程</strong><span>检查预处理、质量控制与评估</span>
            </button>
          </div>
        </div>

        <div v-else class="message-thread">
          <article
            v-for="message in store.activeMessages"
            :key="message.id"
            class="message-row"
            :class="[`role-${message.role}`, { failed: message.error }]"
          >
            <div v-if="message.role === 'assistant'" class="assistant-avatar" aria-hidden="true">
              <span></span><span></span><span></span>
            </div>
            <div class="message-body">
              <div v-if="message.role === 'assistant'" class="message-author">
                <strong>Brain Agent</strong>
                <span v-if="message.pending" class="live-label"><i />LIVE</span>
              </div>

              <details v-if="hasActivity(message)" class="agent-activity" :open="message.pending">
                <summary>
                  <span v-if="message.pending" class="activity-spinner" />
                  <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="m7 12 3 3 7-7" /></svg>
                  {{ message.pending ? `${store.currentAgent ?? 'orchestrator'} 正在处理` : `查看 ${message.activities?.length} 条执行记录` }}
                  <svg class="chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 7 5 5-5 5" /></svg>
                </summary>
                <div class="activity-list">
                  <div v-for="activity in message.activities" :key="activity.id" class="activity-item">
                    <span class="activity-dot" />
                    <div>
                      <strong>{{ activityLabel(activity) }}</strong>
                      <p>{{ activity.message }}</p>
                      <pre v-if="activity.detail">{{ activity.detail }}</pre>
                    </div>
                  </div>
                </div>
              </details>

              <PreprocessingCard v-for="(output, index) in preprocessingOutputs(message)" :key="index" :output="output" />

              <div
                v-if="message.content && message.role === 'assistant'"
                class="message-content markdown-content"
                v-html="renderMarkdown(message.content)"
              />
              <div v-else-if="message.content" class="message-content">{{ message.content }}</div>
              <div v-else-if="message.pending && !hasActivity(message)" class="thinking-line">
                <span></span><span></span><span></span>
              </div>
              <button
                v-if="message.content"
                type="button"
                class="message-copy-button"
                :class="{ copied: copiedMessageId === message.id }"
                :aria-label="copiedMessageId === message.id ? '已复制' : '复制消息'"
                @click="copyMessage(message)"
              >
                <svg v-if="copiedMessageId !== message.id" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 8h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2Z" /><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h2" /></svg>
                <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6" /></svg>
                <span>{{ copiedMessageId === message.id ? '已复制' : '复制' }}</span>
              </button>
            </div>
          </article>
        </div>
      </section>

      <div class="composer-region" :class="{ welcome: store.activeMessages.length === 0 }">
        <p v-if="store.error" class="composer-error">{{ store.error }}</p>
        <form class="chat-composer" @submit.prevent="submit">
          <textarea
            ref="textarea"
            v-model="draft"
            rows="1"
            aria-label="发送消息"
            placeholder="向 Brain Agent 提问…"
            @keydown="handleComposerKeydown"
          />
          <div class="composer-actions">
            <button class="attach-button" type="button" aria-label="附件功能尚未启用" title="附件功能尚未启用" disabled>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
            </button>
            <span>Enter 发送 · Shift Enter 换行</span>
            <button class="send-button" type="submit" :disabled="!draft.trim() || store.isStreaming" aria-label="发送">
              <span v-if="store.isStreaming" class="send-spinner" />
              <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 7-7 7 7M12 5v14" /></svg>
            </button>
          </div>
        </form>
        <small class="composer-note">Agent 可能会出错，请检查重要的研究结论和数据处理结果。</small>
      </div>
    </main>
  </div>
</template>
