<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { t } from '../i18n'
import type { ChatMessage } from '../types/session'
import { renderMarkdown } from '../utils/markdown'
import { agentLabel, activityLabel } from '../utils/chatLabels'
import PreprocessingCard from './PreprocessingCard.vue'

const props = defineProps<{ message: ChatMessage; copied: boolean; currentAgent: string | null }>()
const emit = defineEmits<{ copy: [message: ChatMessage] }>()
const html = computed(() => props.message.role === 'assistant' ? renderMarkdown(props.message.content) : '')
const outputs = computed(() => preprocessingOutputs(props.message))
const activityOpen = ref(false)
watch(() => props.message.pending, pending => { activityOpen.value = Boolean(pending) }, { immediate: true })
function hasActivity(message: ChatMessage) { return Boolean(message.activities?.length) }

function preprocessingOutputs(message: ChatMessage) {
  return (message.activities ?? []).flatMap((activity) => {
    const result = activity.data?.result as { agent_name?: string; output?: Record<string, unknown> } | undefined
    return activity.event_type === 'observation' && result?.agent_name === 'data_preprocessing' && result.output ? [result.output] : []
  })
}

</script>

<template>
  <article
    class="message-row"
    :class="[`role-${message.role}`, { failed: message.error }]"
  >
    <div v-if="message.role === 'assistant'" class="assistant-avatar" aria-hidden="true">
      <span></span><span></span><span></span>
    </div>
    <div class="message-body">
      <div v-if="message.role === 'assistant'" class="message-author">
        <strong>Brain Agent</strong>
        <span v-if="message.pending" class="live-label"><i />{{ t('Working') }}</span>
      </div>

      <details v-if="hasActivity(message)" class="agent-activity" :open="activityOpen" @toggle="activityOpen = ($event.target as HTMLDetailsElement).open">
        <summary>
          <span v-if="message.pending" class="activity-spinner" />
          <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="m7 12 3 3 7-7" /></svg>
          {{ message.pending ? t('{0} is processing', { 0: agentLabel(currentAgent) }) : t('View {0} execution records', { 0: message.activities?.length }) }}
          <svg class="chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 7 5 5-5 5" /></svg>
        </summary>
        <div v-if="activityOpen" class="activity-list">
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

      <PreprocessingCard v-for="(output, index) in outputs" :key="index" :output="output" />

      <div
        v-if="message.content && message.role === 'assistant'"
        class="message-content markdown-content"
        v-html="html"
      />
      <div v-else-if="message.content" class="message-content">{{ message.content }}</div>
      <div v-else-if="message.pending && !hasActivity(message)" class="thinking-line">
        <span></span><span></span><span></span>
      </div>
      <button
        v-if="message.content"
        type="button"
        class="message-copy-button"
        :class="{ copied }"
        :aria-label="copied ? t('Copied') : t('Copy message')"
        @click="emit('copy', message)"
      >
        <svg v-if="!copied" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 8h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2Z" /><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h2" /></svg>
        <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6" /></svg>
        <span>{{ copied ? t('Copied') : t('Copy') }}</span>
      </button>
    </div>
  </article>
</template>
