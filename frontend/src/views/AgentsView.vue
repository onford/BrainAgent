<script setup lang="ts">
import LanguageSwitcher from '../components/LanguageSwitcher.vue'
import { t } from '../i18n'
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { fetchAgents } from '../api/agents'
import type { AgentInfo } from '../types/agent'

const agents = ref<AgentInfo[]>([])
const error = ref<string | null>(null)
onMounted(async () => {
  try {
    agents.value = await fetchAgents()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : t('Loading failed')
  }
})
</script>

<template>
  <main class="registry-page">
    <header class="registry-header">
      <RouterLink to="/" class="back-link">{{ t('← Back to chat') }}</RouterLink>
      <LanguageSwitcher />
    </header>
    <section class="registry-content">
      <span class="page-kicker">{{ t('Agent registry') }}</span>
      <h1>{{ t('Research agents') }}</h1>
      <p>{{ t('Specialist agents handle data research and processing, with results returned to your conversation.') }}</p>
      <p v-if="error" class="composer-error">{{ error }}</p>
      <div class="agent-grid">
        <article v-for="(agent, index) in agents" :key="agent.name" class="agent-card">
          <span>0{{ index + 1 }}</span>
          <h2>{{ agent.name.replaceAll('_', ' ') }}</h2>
          <p>{{ agent.description }}</p>
        </article>
      </div>
    </section>
  </main>
</template>
