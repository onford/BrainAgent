<script setup lang="ts">
import LanguageSwitcher from '../components/LanguageSwitcher.vue'
import { t, formatLocale } from '../i18n'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useChatStore } from '../stores/chat'
import type { ChatMessage, Session } from '../types/session'
import { agentLabel } from '../utils/chatLabels'
import ChatMessageRow from '../components/ChatMessageRow.vue'

const store = useChatStore()
const draft = ref('')
const sidebarOpen = ref(false)
const conversation = ref<HTMLElement | null>(null)
const textarea = ref<HTMLTextAreaElement | null>(null)
const copiedMessageId = ref<string | null>(null)
let copyResetTimer: ReturnType<typeof setTimeout> | undefined
let disposed = false

const currentTitle = computed(() =>
  store.activeSession ? sessionTitle(store.activeSession) : t('New conversation'),
)

function sessionTitle(session: Session): string {
  const firstUser = session.messages.find((message) => message.role === 'user')?.content.trim()
  return firstUser?.replace(/\s+/g, ' ') || t('New conversation')
}

function sessionPreview(session: Session): string {
  const last = [...session.messages].reverse().find((message) => message.content.trim())
  return last?.content.replace(/\s+/g, ' ') || t('Waiting for input…')
}

function timeLabel(value: string): string {
  const date = new Date(value)
  const now = new Date()
  if (date.toDateString() === now.toDateString()) {
    return new Intl.DateTimeFormat(formatLocale.value, { hour: '2-digit', minute: '2-digit' }).format(date)
  }
  return new Intl.DateTimeFormat(formatLocale.value, { month: 'numeric', day: 'numeric' }).format(date)
}

const sessionRows = computed(() => store.sessions.map(session => ({
  session,
  title: sessionTitle(session),
  preview: sessionPreview(session),
  time: timeLabel(session.updated_at),
})))

function submit(): void {
  const value = draft.value.trim()
  if (!value || store.isStreaming) return
  draft.value = ''
  resizeTextarea()
  void store.submit(value)
  scrollToBottom(true)
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
  if (!window.confirm(t('Delete “{0}”? This cannot be undone.', { 0: title }))) return
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
    store.error = t('Copy failed. Select and copy the text manually.')
  }
}

let scrollFrame: number | undefined
let followLatest = true
function trackScroll(): void {
  const element = conversation.value
  if (element) followLatest = element.scrollHeight - element.scrollTop - element.clientHeight < 80
}
function scrollToBottom(force = false): void {
  if (force) followLatest = true
  if (!followLatest || scrollFrame !== undefined) return
  scrollFrame = requestAnimationFrame(() => {
    scrollFrame = undefined
    if (followLatest && conversation.value) conversation.value.scrollTop = conversation.value.scrollHeight
  })
}

watch(draft, resizeTextarea)
watch(
  () => {
    const last = store.activeMessages.at(-1)
    return [store.activeMessages.length, last?.content, last?.activities?.length, last?.pending]
  },
  () => scrollToBottom(),
  { flush: 'post' },
)
watch(() => store.activeSessionId, () => scrollToBottom(true), { flush: 'post' })

onMounted(async () => {
  window.addEventListener('keydown', handleGlobalShortcut)
  await store.initialize()
  if (!disposed) scrollToBottom(true)
})
onBeforeUnmount(() => {
  disposed = true
  window.removeEventListener('keydown', handleGlobalShortcut)
  if (copyResetTimer) clearTimeout(copyResetTimer)
  if (scrollFrame !== undefined) cancelAnimationFrame(scrollFrame)
})
</script>

<template>
  <div class="app-layout">
    <button
      v-if="sidebarOpen"
      class="sidebar-scrim"
      :aria-label="t('Close conversation sidebar')"
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
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>{{ t('New chat') }}<kbd>⌘ K</kbd>
      </button>

      <div class="session-section-heading">
        <span>{{ t('Recent conversations') }}</span>
        <span v-if="store.loadingSessions" class="mini-spinner" />
      </div>

      <nav class="session-list" :aria-label="t('Conversation list')">
        <div
          v-for="{ session, title, preview, time } in sessionRows"
          :key="session.id"
          class="session-item-shell"
          :class="{ active: store.activeSessionId === session.id }"
        >
          <button type="button" class="session-item" @click="chooseSession(session.id)">
            <span class="session-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24"><path d="M7 8h10M7 12h7m-7 8 3.2-3H18a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h1v3Z" /></svg>
            </span>
            <span class="session-copy">
              <strong>{{ title }}</strong>
              <small>{{ preview }}</small>
            </span>
            <span
              v-if="store.runningSessionIds.includes(session.id)"
              class="session-running"
              :aria-label="t('In progress')"
            />
            <span
              v-else-if="store.deletingSessionIds.includes(session.id)"
              class="mini-spinner"
              :aria-label="t('Deleting')"
            />
            <time v-else>{{ time }}</time>
          </button>
          <button
            type="button"
            class="session-delete"
            :disabled="store.runningSessionIds.includes(session.id) || store.deletingSessionIds.includes(session.id)"
            :aria-label="t('Delete conversation: {0}', { 0: title })"
            :title="t('Delete conversation')"
            @click="removeConversation(session)"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7m4 4v5m4-5v5" /></svg>
          </button>
        </div>
        <p v-if="!store.loadingSessions && store.sessions.length === 0" class="empty-sessions">{{ t('No conversations yet. Start a new chat to begin.') }}</p>
      </nav>

      <div class="sidebar-footer">
        <RouterLink to="/settings/integrations" class="sidebar-link">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21h-4v-.09A1.7 1.7 0 0 0 8.5 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3v-4h.09A1.7 1.7 0 0 0 4.6 8.5a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3h4v.09A1.7 1.7 0 0 0 15.5 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.18.37.4.7.6 1 .3.3.7.5 1.1.5h.1v4h-.1c-.4 0-.8.2-1.1.5-.2.3-.42.63-.6 1Z" /></svg>
          {{ t('Tool integrations') }}
        </RouterLink>
        <RouterLink to="/workflows" class="sidebar-link">{{ t('Data workflows') }}</RouterLink>
        <RouterLink to="/invasive" class="sidebar-link">侵入式数据处理</RouterLink>
        <RouterLink to="/preprocessing/units" class="sidebar-link">预处理单元与编排</RouterLink>
        <RouterLink to="/agents" class="sidebar-link">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm8 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM2.5 20v-2.2A4.8 4.8 0 0 1 7.3 13h1.4a4.8 4.8 0 0 1 4.8 4.8V20m0-6.6a4.8 4.8 0 0 1 8 3.6v3" /></svg>
          {{ t('Agent registry') }}
        </RouterLink>
        <div class="runtime-state"><span></span>{{ t('Research workspace') }}</div>
      </div>
    </aside>

    <main class="conversation-pane">
      <header class="conversation-header">
        <button class="mobile-menu" type="button" :aria-label="t('Open conversation sidebar')" @click="sidebarOpen = true">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
        </button>
        <div class="conversation-heading">
          <strong>{{ currentTitle }}</strong>
          <small v-if="store.isStreaming"><span class="header-pulse" />{{ t('{0} is working', { 0: agentLabel(store.currentAgent) }) }}</small>
          <small v-else>{{ t('Research chat') }}</small>
        </div>
        <LanguageSwitcher dark /><button class="header-new-chat" type="button" :aria-label="t('New chat')" @click="createConversation">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
        </button>
      </header>

      <section ref="conversation" class="conversation-scroll" aria-live="polite" @scroll.passive="trackScroll">
        <div v-if="store.activeMessages.length === 0" class="welcome-state">
          <div class="welcome-mark" aria-hidden="true">
            <span></span><span></span><span></span>
          </div>
          <h1>{{ t('What would you like to explore?') }}</h1>
          <p>{{ t('Start with a dataset, a preprocessing method, or a research question.') }}</p>
          <div class="prompt-suggestions">
            <button type="button" @click="draft = t('Research a public neural dataset and assess its suitability for representation learning')">
              <strong>{{ t('Explore public data') }}</strong><span>{{ t('Compare dataset size, formats, and research uses') }}</span>
            </button>
            <button type="button" @click="draft = t('Review my neural data preprocessing pipeline and suggest reproducible improvements')">
              <strong>{{ t('Review a data pipeline') }}</strong><span>{{ t('Inspect preprocessing, quality control, and evaluation') }}</span>
            </button>
          </div>
        </div>

        <div v-else class="message-thread">
          <ChatMessageRow
            v-for="message in store.activeMessages"
            :key="message.id"
            :message="message"
            :copied="copiedMessageId === message.id"
            :current-agent="message.pending ? store.currentAgent : null"
            @copy="copyMessage"
          />
        </div>
      </section>

      <div class="composer-region" :class="{ welcome: store.activeMessages.length === 0 }">
        <p v-if="store.error" class="composer-error">{{ store.error }}</p>
        <form class="chat-composer" @submit.prevent="submit">
          <textarea
            ref="textarea"
            v-model="draft"
            rows="1"
            :aria-label="t('Send a message')"
            :placeholder="t('Ask Brain Agent…')"
            @keydown="handleComposerKeydown"
          />
          <div class="composer-actions">
            <span>{{ t('Enter to send · Shift+Enter for a new line') }}</span>
            <button class="send-button" type="submit" :disabled="!draft.trim() || store.isStreaming" :aria-label="t('Send')">
              <span v-if="store.isStreaming" class="send-spinner" />
              <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 7-7 7 7M12 5v14" /></svg>
            </button>
          </div>
        </form>
        <small class="composer-note">{{ t('Check important research findings and processing results for errors.') }}</small>
      </div>
    </main>
  </div>
</template>
