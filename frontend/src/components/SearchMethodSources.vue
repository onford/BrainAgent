<script setup lang="ts">
import { computed } from 'vue'
import type { SearchState } from '../types/search'

const props = defineProps<{ state: SearchState }>()
const intake = computed(() => props.state.protocol?.method_intake as {
  absence_reasons?: string[];
  methods?: { title: string; status: string; reasons: string[]; lineage: { source_url?: string; branch_id?: string }; method_ref: { id: string } }[]
} | undefined)
const blocked = computed(() => intake.value?.methods?.filter(m => m.status === 'blocked') ?? [])
const terminal = computed(() => ['completed', 'stopped', 'failed', 'cancelled'].includes(props.state.status))
const label = (origin: string) => ({ basic: '基础方法', literature: '本轮文献', literature_adaptation: '文献适配', derived: '派生方法' }[origin] ?? origin)
const outcome = (id: string) => props.state.candidates?.find(c => c.id === id)
const deferredReason = (id: string) => {
  const finished = [...(props.state.actions ?? [])].reverse().find(a => a.action === 'finish' && a.status === 'completed')
  const reasons = finished?.request?.untried_candidate_reasons as Record<string, string> | undefined
  return reasons?.[id] ?? props.state.stop_reason
}
const status = (id: string) => {
  const value = outcome(id)?.status
  return value ? ({ evaluated: '已评价', running: '执行中', reserved: '待执行', candidate_invalid: '候选无效', execution_failure: '执行失败', interrupted: '已中断' }[value] ?? value) : terminal.value ? '已推迟' : '待执行'
}
const link = (path: string) => `/api/searches/${props.state.id}/artifacts/${path}?download=true`
</script>

<template>
  <section class="method-sources" aria-label="方法来源与执行状态">
    <h3>方法来源与执行状态</h3>
    <p v-if="state.literature_participation" class="reason">{{ state.literature_participation.statement }}</p>
    <p v-for="reason in intake?.absence_reasons" :key="reason" class="reason">{{ reason }}</p>
    <details v-for="entry in state.registry ?? []" :key="entry.id">
      <summary>{{ entry.title }} · {{ label(entry.origin) }} · {{ status(entry.id) }}</summary>
      <p v-if="entry.parent_ids?.length">父方法：{{ entry.parent_ids.join('、') }}</p>
      <p v-if="!outcome(entry.id) && terminal">推迟原因：{{ deferredReason(entry.id) }}</p>
      <p v-if="outcome(entry.id)?.error">{{ outcome(entry.id)?.error }}</p>
      <ul>
        <li v-for="(source, i) in entry.lineage ?? []" :key="i">
          <a v-if="source.source_url" :href="source.source_url" target="_blank" rel="noopener noreferrer">{{ source.source_id }}</a>
          <span v-else>{{ source.method_id }}</span>
          <span v-if="source.branch_id"> · 分支 {{ source.branch_id }} · {{ source.analysis }}</span>
          <span v-if="source.version"> · v{{ source.version }}</span>
          <a v-if="source.method_ref" :href="link(`source-methods/${source.method_ref.id.slice(0, 24)}.json`)">原始方法与定位证据</a>
          <a v-if="typeof source.extraction_path === 'string'" :href="link(source.extraction_path.replace(/^preprocessing\//, '').replace(/[^/]+$/, 'extraction.json'))">模型原始提取</a>
          <a v-if="typeof source.extraction_path === 'string' && source.extraction_path.endsWith('resolved-extraction.json')" :href="link(source.extraction_path.replace(/^preprocessing\//, ''))">修订后草案</a>
        </li>
        <li v-for="note in entry.deviations" :key="note">{{ note }}</li>
        <li v-for="(issue, i) in entry.issues ?? []" :key="`issue-${i}`">{{ issue.severity }}：{{ issue.message }}</li>
      </ul>
      <p>{{ entry.recipe.nodes.map(n => n.operator).join(' → ') }}</p>
      <details v-if="state.candidate_contrasts_to_reference?.[entry.id]">
        <summary>相对基础对照的实际配置差异</summary>
        <p>移除：{{ state.candidate_contrasts_to_reference[entry.id]!.removed_operations.join('、') || '无' }}；增加：{{ state.candidate_contrasts_to_reference[entry.id]!.added_operations.join('、') || '无' }}</p>
        <p v-for="change in state.candidate_contrasts_to_reference[entry.id]!.parameter_changes" :key="`${change.operation}:${change.parameter}`">{{ change.operation }} · {{ change.parameter }}：{{ JSON.stringify(change.before) }} → {{ JSON.stringify(change.after) }}</p>
        <p v-if="state.candidate_contrasts_to_reference[entry.id]!.shared_operation_order_changed">共同操作的执行顺序也发生变化。</p>
        <p v-if="state.candidate_contrasts_to_reference[entry.id]!.scope_changes?.length">拟合范围或端口变化：{{ state.candidate_contrasts_to_reference[entry.id]!.scope_changes.join('、') }}；完整连线见配方。</p>
        <p>{{ state.candidate_contrasts_to_reference[entry.id]!.interpretation }}</p>
      </details>
      <details v-if="entry.edits.length"><summary>修改与组合记录</summary><pre>{{ JSON.stringify(entry.edits, null, 2) }}</pre></details>
      <p v-if="outcome(entry.id)">
        <a :href="link(`candidates/${entry.id}/method.json`)">编译方法</a> ·
        <a :href="link(`candidates/${entry.id}/plan.json`)">实际参数与执行计划</a> ·
        <a v-if="outcome(entry.id)?.receipt" :href="link(`candidates/${entry.id}/receipt.json`)">评价结果</a>
      </p>
    </details>
    <details v-for="item in blocked" :key="item.method_ref.id">
      <summary>{{ item.title }} · 本轮文献 · 阻塞</summary>
      <p>分支：{{ item.lineage.branch_id }}</p>
      <ul><li v-for="reason in item.reasons" :key="reason">{{ reason }}</li></ul>
      <a :href="link(`source-methods/${item.method_ref.id.slice(0, 24)}.json`)">原始草案、缺口与证据</a>
    </details>
    <p><a :href="link('method-status.json')">完整方法状态</a> · <a :href="link('method-extraction.json')">本轮拆解清单</a></p>
  </section>
</template>

<style scoped>
.method-sources { margin-block: 1.5rem; }
details { padding-block: .65rem; border-bottom: 1px solid var(--border-color, #d8e1e5); }
summary { cursor: pointer; line-height: 1.6; }
p, li { line-height: 1.65; overflow-wrap: anywhere; }
pre { overflow: auto; white-space: pre-wrap; }
a { color: var(--accent-color, #127e79); margin-inline-end: .4rem; }
.reason { color: var(--text-secondary, #52636b); }
</style>
