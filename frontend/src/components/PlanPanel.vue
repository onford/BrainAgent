<script setup lang="ts">
import type { Plan } from '../types/agent'
defineProps<{ plan: Plan }>()
</script>

<template>
  <section class="panel">
    <div class="section-title"><span>Execution plan</span><small>{{ plan.steps.length }} steps</small></div>
    <ol class="plan-list">
      <li v-for="step in plan.steps" :key="step.step" :class="step.status">
        <span class="step-index">{{ step.step }}</span>
        <div><strong>{{ step.agent }}</strong><p>{{ step.task }}</p></div>
        <span class="status">{{ step.status }}</span>
      </li>
    </ol>
  </section>
</template>
