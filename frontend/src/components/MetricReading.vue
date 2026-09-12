<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { apiRequest } from '../api/client'
import { locale, t } from '../i18n'

const props = defineProps<{ searchId: string; candidateId: string; stage: string; metricId: string; row: Record<string, any> }>()
type Source = { id: string; title: string; url: string; locator: string; evidence: string }
type Result = {
  created_at: string; input_hash: string; model: { name: string }
  reading: { assessment: string; claims: { text: string; source_ids: string[] }[]; next_check?: string | null }
  context: { sources: Source[]; cards: { id: string; title: string; reading: string }[] }
}
const result = ref<Result | null>(null), loading = ref(false), error = ref(''), expanded = ref(false)
let serial = 0
const coverage = computed(() => {
  const d = props.row.denominator
  return [d?.available_subjects, d?.expected_subjects].map(n => typeof n === 'number' && Number.isFinite(n) ? n : '—')
})
const sources = computed(() => result.value?.context.sources.filter(s => result.value?.reading.claims.some(c => c.source_ids.includes(s.id))) ?? [])
function source(id: string) { return sources.value.find(s => s.id === id) }
async function load() {
  if (loading.value || result.value) return
  const request = ++serial
  loading.value = true; error.value = ''
  try {
    const response = await apiRequest<Result>(`/api/searches/${encodeURIComponent(props.searchId)}/metric-reading`, {
      method: 'POST', body: JSON.stringify({ candidate_id: props.candidateId, stage: props.stage, metric_id: props.metricId, language: locale.value }),
    })
    if (request === serial) result.value = response
  } catch (e) { if (request === serial) error.value = String(e) }
  finally { if (request === serial) loading.value = false }
}
function toggle(event: Event) {
  if (event.target !== event.currentTarget) return
  expanded.value = (event.target as HTMLDetailsElement).open
  if (expanded.value && !error.value) void load()
}
watch(() => [props.searchId, props.candidateId, props.stage, props.metricId, props.row, locale.value], () => {
  serial++; result.value = null; error.value = ''; loading.value = false
  if (expanded.value) void load()
})
onBeforeUnmount(() => { serial++ })
</script>

<template>
  <details class="metric-reading" @toggle="toggle">
    <summary>{{ t('Coverage and interpretation') }}<span class="coverage"> · {{ t('Subject coverage:') }} {{ coverage[0] }} / {{ coverage[1] }}</span></summary>
    <p v-if="row.aggregation === 'equal_subjects_mean'" class="coverage">{{ t('Equal-subject mean') }}</p>
    <p v-if="loading" class="muted" role="status">{{ t('Checking evidence and reading the knowledge base…') }}</p>
    <div v-if="error" role="alert"><p>{{ t('The interpretation is unavailable. No conclusion has been substituted.') }}</p><small>{{ error }}</small><button type="button" @click="load">{{ t('Retry interpretation') }}</button></div>
    <template v-if="result">
      <p v-for="(claim, i) in result.reading.claims" :key="i" class="claim">{{ claim.text }} <template v-for="id in claim.source_ids" :key="id"><a v-if="source(id)" :href="source(id)!.url" :title="source(id)!.title" target="_blank" rel="noopener noreferrer" class="citation">[{{ sources.findIndex(s => s.id === id) + 1 }}]</a></template></p>
      <p v-if="result.reading.next_check" class="next-check">{{ t('To resolve this:') }} {{ result.reading.next_check }}</p>
      <small class="muted">{{ t('Model interpretation · {0} · Saved with this evidence', { 0: result.model.name }) }}</small>
      <details class="evidence"><summary>{{ t('Theory, sources and audit record') }}</summary>
        <p v-for="card in result.context.cards" :key="card.id"><strong>{{ card.title }}</strong><br />{{ card.reading }}</p>
        <ol><li v-for="s in sources" :key="s.id"><a :href="s.url" target="_blank" rel="noopener noreferrer">{{ s.title }}</a><small>{{ s.locator }} · {{ s.evidence }}</small></li></ol>
        <details><summary>{{ t('Interpretation audit record') }}</summary><pre>{{ JSON.stringify(result, null, 2) }}</pre></details>
      </details>
    </template>
    <details><summary>{{ t('Original measurement record') }}</summary><pre>{{ JSON.stringify(row, null, 2) }}</pre></details>
  </details>
</template>

<style scoped>
.metric-reading{min-width:250px;max-width:650px;white-space:normal;line-height:1.7}summary{cursor:pointer;color:#286c60;margin-top:5px}.coverage{color:#637575;font-size:12px;margin:10px 0}.claim{margin:10px 0;color:#253b40}.citation{font-size:11px;vertical-align:super;margin-right:4px}.muted,small{color:#667878;font-size:11px}.next-check{padding-left:10px;border-left:2px solid #b9d0c9;font-size:12px}.evidence{margin-top:10px;font-size:12px}.evidence small{display:block}a{color:#246e61}ol{padding-left:20px}pre{max-width:580px;max-height:240px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px}button{display:block;margin-top:8px;background:white;border:1px solid #bfd1cc;border-radius:6px;color:#286c60;padding:5px 10px;cursor:pointer}[role=alert]{color:#875e32;font-size:12px;overflow-wrap:anywhere}
</style>
