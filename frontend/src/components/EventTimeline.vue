<script setup lang="ts">
import type { ExecutionEvent } from '../types/agent'
defineProps<{ events: ExecutionEvent[] }>()
</script>

<template>
  <section class="panel timeline">
    <div class="section-title"><span>Execution trace</span><small>runtime events</small></div>
    <ol>
      <li v-for="(event, index) in events" :key="`${event.timestamp}-${index}`">
        <span class="trace-dot" :class="event.event_type"></span>
        <div><strong>{{ event.agent_name ?? 'orchestrator' }}</strong><p>{{ event.message }}</p></div>
        <time>{{ event.event_type }}</time>
      </li>
    </ol>
  </section>
</template>
