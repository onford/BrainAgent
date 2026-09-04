<script setup lang="ts">
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
    error.value = reason instanceof Error ? reason.message : '加载失败'
  }
})
</script>

<template>
  <main class="registry-page">
    <header class="registry-header">
      <RouterLink to="/" class="back-link">← 返回对话</RouterLink>
      <span class="runtime-state"><i></i>Registry online</span>
    </header>
    <section class="registry-content">
      <span class="page-kicker">AGENT REGISTRY</span>
      <h1>专业数据 Agent</h1>
      <p>Orchestrator 根据对话目标选择这些 Agent，并将每一步的结果实时送回当前 session。</p>
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
