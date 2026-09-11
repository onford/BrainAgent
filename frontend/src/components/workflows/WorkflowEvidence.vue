<script setup lang="ts">
import { t, formatLocale } from '../../i18n'
import { RouterLink } from 'vue-router'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { apiRequest } from '../../api/client'
import type { SavedWorkflowEvaluation, SearchSummary } from '../../types/search'
const props = defineProps<{ workflowId: string; searchId?: string | null; evaluation?: SavedWorkflowEvaluation; reportCount: number; offline?: boolean }>()
const related = ref<SearchSummary[]>([]), inspectedSearch = ref(''), retrievalError = ref(false), loading = ref(false)
const evidenceSearchId = computed(() => props.searchId || inspectedSearch.value)
let serial = 0
async function loadRelated() {
  const token = ++serial
  retrievalError.value = false
  if (props.searchId || props.offline) { loading.value = false; return }
  loading.value = true
  try {
    const rows = await apiRequest<SearchSummary[]>('/api/searches')
    if (!Array.isArray(rows)) throw new Error('Invalid search list')
    if (token === serial) related.value = rows.filter(row => row.workflow_id === props.workflowId)
  } catch { if (token === serial) retrievalError.value = true }
  finally { if (token === serial) loading.value = false }
}
watch(() => [props.workflowId, props.searchId, props.offline], () => {
  related.value = []; inspectedSearch.value = ''
  void loadRelated()
}, { immediate: true })
onBeforeUnmount(() => { serial++ })
const searchLabel = (item: SearchSummary) => `${new Date(item.created_at).toLocaleString(formatLocale.value, {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})} · ${item.id.slice(0,8)} · ${{get completed() { return t('Completed') },get failed() { return t('Failed') },get stopped() { return t('Stopped') },get cancelled() { return t('Cancelled') },get running() { return t('Running') },get interrupted() { return t('Interrupted') },get preparing() { return t('Preparing') }}[item.status] || item.status}`
const emit = defineEmits<{ reports: []; files: [] }>()
const destinations = [
  { get title() { return t('Decision overview') }, view: 'overview', axis: '', get summary() { return t('Selected method, scoring rules, and candidate comparison.') } },
  { get title() { return t('Signal plots') }, view: 'assessment', axis: 'quality', get summary() { return t('Power spectra, amplitude, and channel relationships at each stage.') } },
  { get title() { return t('Evaluation metrics') }, view: 'assessment', axis: 'utility', get summary() { return t('Model performance, subject variability, signal quality, and reconstruction.') } },
  { get title() { return t('Preprocessing methods') }, view: 'assessment', axis: 'parameters', get summary() { return t('Processing steps, parameters, and per-record execution.') } },
  { get title() { return t('Agent decision history') }, view: 'rounds', axis: '', get summary() { return t('Proposal rationale, competing explanations, and measurement checks.') } },
]
</script>
<template>
  <section class="workflow-evidence" :aria-label="t('Workflow and evidence')">
    <header><h2>{{ t('Analysis results') }}</h2><p>{{ t('Plots, metrics, processing methods, and reports.') }}</p></header>
    <div v-if="!searchId" class="availability">
      <p v-if="loading" role="status">{{ t('Loading search records…') }}</p>
      <p v-else-if="retrievalError" role="alert">{{ t('Search records could not be loaded.') }}<button @click="loadRelated">{{ t('Retry') }}</button></p>
      <template v-else-if="related.length">
        <label>{{ t('Search records') }}<select v-model="inspectedSearch"><option value="">{{ t('Choose a search to inspect') }}</option><option v-for="item in related" :key="item.id" :value="item.id">{{ searchLabel(item) }}</option></select></label>
        <small>{{ t('These searches use this workflow\'s data. Their results are recorded separately from the original delivery.') }}</small>
      </template>
      <p v-else>{{ offline ? t('This offline edition contains workflow reports only.') : t('No search records yet. Existing reports and files remain available.') }}</p>
      <p v-if="evaluation?.selection_policy === 'random'" class="selection-note">{{ t('The original delivery used random selection, not metric-based selection.') }}</p>
    </div>
    <p v-else-if="offline" class="availability">{{ t('Included reports are available offline. Search plots and decision details require an online connection.') }}</p>
    <div class="evidence-grid"><article v-for="item in destinations" :key="item.view + item.axis"><h3>{{ item.title }}</h3><p>{{ item.summary }}</p><RouterLink v-if="evidenceSearchId && !offline" :to="{path:'/searches', query:{id:evidenceSearchId, view:item.view, ...(item.axis ? {axis:item.axis} : {})}}">{{ t('Open {0} →', { 0: item.title }) }}</RouterLink><span v-else class="unavailable">{{ offline ? t('Online only') : t('Not yet available') }}</span></article><article><h3>{{ t('Reports and original records') }}</h3><p>{{ t('{0} reports, plus measurements, models, and delivery files.', { 0: reportCount }) }}</p><div><button @click="emit('reports')">{{ t('Read reports →') }}</button><button @click="emit('files')">{{ t('View files →') }}</button></div></article></div>
  </section>
</template>
<style scoped>
.workflow-evidence{height:100%;box-sizing:border-box;overflow:auto;padding:28px 32px;color:#2a453c;line-height:1.8}header h2{font-size:25px;margin:5px 0 10px;font-weight:600}header>p:last-child{color:#5d766b;font-size:14px;max-width:780px}.availability select{display:block;max-width:100%;padding:8px;border:1px solid #d6c9af;border-radius:6px;font:inherit;background:white;color:#5e523e}.availability{background:#f4f7f5;color:#516b5e;border:1px solid #dce6df;padding:12px 16px;border-radius:9px;font-size:13px}.availability p{margin:4px 0}.availability small{display:block;margin:8px 0 0}.availability button{margin-left:8px}.selection-note{font-size:12px;color:#76613f}.evidence-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-top:24px}article{display:flex;flex-direction:column;align-items:start;padding:22px;border:1px solid #dae5df;border-radius:12px;background:#fafcfb}h3{font-size:17px;margin:4px 0}article p{font-size:13px;color:#587164;flex:1;margin:8px 0 15px}small{font-size:11px;color:#607b6e;margin-bottom:18px}.unavailable{font-size:12px;color:#7c8379}a,button{font:inherit;font-size:12px;color:#236b4e;background:white;border:1px solid #cddfd4;border-radius:6px;padding:7px 10px;text-decoration:none;cursor:pointer}article>div{display:flex;flex-wrap:wrap;gap:8px}a:hover,button:hover{background:#eaf3ee} @media(max-width:1100px){.evidence-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:650px){.workflow-evidence{padding:20px 16px}.evidence-grid{grid-template-columns:1fr}header h2{font-size:21px}}
</style>
