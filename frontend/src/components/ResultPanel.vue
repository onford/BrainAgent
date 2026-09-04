<script setup lang="ts">
import type { AgentResult } from '../types/agent'
defineProps<{ results: AgentResult[] }>()
</script>

<template>
  <section class="panel">
    <div class="section-title"><span>Agent results</span><small>{{ results.length }} completed</small></div>
    <article v-for="result in results" :key="result.agent_name" class="result-card">
      <header><span class="pulse"></span><strong>{{ result.agent_name }}</strong><span>{{ result.success ? 'completed' : 'failed' }}</span></header>
      <pre>{{ JSON.stringify(result.output, null, 2) }}</pre>
    </article>
  </section>
</template>
