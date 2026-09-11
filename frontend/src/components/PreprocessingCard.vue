<script setup lang="ts">
import { t } from '../i18n'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { apiRequest, apiUrl } from '../api/client'

type Reference = { id: string; sha256: string }
type Artifact = { name: string; kind: string }
type RecordResult = { key: string; record_id: string; method_id: string; status: string; attempt: number; error: string | null; result: { artifacts: Artifact[] } | null }
type Job = { job_id: string; status: string; completed: number; total: number; cancel_requested: boolean; records: RecordResult[] }
const props = defineProps<{ output: { job_id?: string; plan_ref?: Reference; execution_status?: string; record_count?: number; screening?: { status: string; reasons: string[] }[]; missing_fields?: string[]; blocking_reason?: string } }>()
const job = ref<Job | null>(null)
const error = ref('')
const busy = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
const labels: Record<string, string> = { get queued() { return t('Queued') }, get running() { return t('Processing') }, get completed() { return t('Processing complete') }, get partial() { return t('Partially complete') }, get failed() { return t('Processing failed') }, get interrupted() { return t('Awaiting recovery') }, get cancelled() { return t('Cancelled') }, get planned() { return t('Plan ready') }, get needs_input() { return t('Additional input needed') } }
const status = computed(() => job.value?.status ?? props.output.execution_status ?? 'planned')
const active = computed(() => ['queued', 'running', 'interrupted'].includes(status.value))
const planUrl = computed(() => props.output.plan_ref ? `/api/preprocessing/plans/${props.output.plan_ref.id}` : '')

async function refresh(id: string): Promise<void> {
  try {
    const result = await apiRequest<Job>(`/api/preprocessing/jobs/${encodeURIComponent(id)}`)
    if (disposed) return
    job.value = result
    error.value = ''
    if (active.value) timer = setTimeout(() => void refresh(id), 2000)
  } catch (reason) {
    if (!disposed) error.value = reason instanceof Error ? reason.message : t('Unable to update progress')
  }
}

async function act(action: 'submit' | 'cancel' | 'retry'): Promise<void> {
  if (busy.value) return
  busy.value = true
  error.value = ''
  if (timer) clearTimeout(timer)
  try {
    const result = action === 'submit'
      ? await apiRequest<Job>('/api/preprocessing/jobs', { method: 'POST', body: JSON.stringify({ plan_ref: props.output.plan_ref }) })
      : await apiRequest<Job>(`/api/preprocessing/jobs/${job.value!.job_id}/${action}`, { method: 'POST' })
    if (!disposed) {
      job.value = result
      if (active.value) timer = setTimeout(() => void refresh(result.job_id), 2000)
    }
  } catch (reason) {
    if (!disposed) error.value = reason instanceof Error ? reason.message : t('Action failed')
  } finally { busy.value = false }
}

function artifactUrl(record: RecordResult, artifact: Artifact): string {
  return apiUrl(`/api/preprocessing/jobs/${job.value!.job_id}/artifacts/${record.key}/${artifact.name.split('/').map(encodeURIComponent).join('/')}`)
}

onMounted(async () => {
  if (props.output.job_id) await refresh(props.output.job_id)
  else if (planUrl.value) {
    try {
      const existing = await apiRequest<Job | null>(`${planUrl.value}/job`)
      if (existing && !disposed) await refresh(existing.job_id)
    } catch { /* A plan can be viewed before it has been submitted. */ }
  }
})
onBeforeUnmount(() => { disposed = true; if (timer) clearTimeout(timer) })
</script>

<template>
  <section class="preprocessing-card" :aria-label="t('EEG preprocessing task')">
    <strong>{{ t('EEG preprocessing · {0}', { 0: labels[status] ?? status }) }}</strong>
    <p v-if="job" role="status">{{ t('Completed {0} / {1} method–record combinations', { 0: job.completed, 1: job.total }) }}<span v-if="job.cancel_requested">{{ t('· Cancelling') }}</span></p>
    <p v-else-if="output.record_count !== undefined">{{ t('The plan contains {0} method–record combinations.', { 0: output.record_count }) }}</p>
    <p v-if="output.missing_fields?.length">{{ t('Required: {0}', { 0: output.missing_fields.join('、') }) }}</p>
    <p v-if="output.blocking_reason">{{ output.blocking_reason }}</p>
    <details v-if="output.screening?.length"><summary>{{ t('Method screening') }}</summary><ul><li v-for="(item, index) in output.screening" :key="index">{{ item.status }}：{{ item.reasons.join('；') }}</li></ul></details>
    <div class="preprocessing-actions">
      <a v-if="planUrl" :href="apiUrl(planUrl)" target="_blank" rel="noopener">{{ t('View full plan') }}</a>
      <button v-if="!job && output.plan_ref && output.record_count" :disabled="busy" @click="act('submit')">{{ t('Run plan') }}</button>
      <button v-if="job && active" :disabled="busy || job.cancel_requested" @click="act('cancel')">{{ t('Cancel processing') }}</button>
      <button v-if="job && ['partial', 'failed', 'cancelled'].includes(status)" :disabled="busy" @click="act('retry')">{{ t('Retry incomplete records') }}</button>
      <button v-if="error && (job?.job_id || output.job_id)" @click="refresh(job?.job_id || output.job_id!)">{{ t('Refresh progress') }}</button>
    </div>
    <details v-if="job?.records.length"><summary>{{ t('Records and artifacts') }}</summary>
      <ul><li v-for="record in job.records" :key="record.key">
        <span>{{ t('{0} · Method {1} · {2} · Attempt {3}', { 0: record.record_id, 1: record.method_id.slice(0, 8), 2: labels[record.status] ?? record.status, 3: record.attempt }) }}</span>
        <p v-if="record.error">{{ record.error }}</p>
        <details v-if="record.status === 'completed' && record.result"><summary>{{ t('Download artifacts') }}</summary><ul><li v-for="artifact in record.result.artifacts" :key="artifact.name"><a :href="artifactUrl(record, artifact)" download>{{ artifact.name }}</a></li></ul></details>
      </li></ul>
    </details>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.preprocessing-card { padding: 14px 16px; margin: 12px 0; border: 1px solid #d7dedb; border-radius: 10px; background: #f6f9f7; color: #294437; font-size: 13px; overflow-wrap: anywhere; }
.preprocessing-card a { color: #236b4e; }
.preprocessing-card p { margin: 8px 0; }
.preprocessing-actions { display: flex; align-items: center; gap: 12px; margin: 8px 0; flex-wrap: wrap; }
.preprocessing-actions button { border: 1px solid #becfc5; border-radius: 5px; padding: 5px 9px; background: white; cursor: pointer; }
.preprocessing-card summary { cursor: pointer; margin: 6px 0; }
.preprocessing-card li { margin: 8px 0; }
</style>
