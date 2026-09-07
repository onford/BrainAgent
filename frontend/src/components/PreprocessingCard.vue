<script setup lang="ts">
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
const labels: Record<string, string> = { queued: '等待处理', running: '正在处理', completed: '处理完成', partial: '部分完成', failed: '处理失败', interrupted: '等待恢复', cancelled: '已取消', planned: '计划已就绪', needs_input: '需要补充输入' }
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
    if (!disposed) error.value = reason instanceof Error ? reason.message : '无法更新处理进度'
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
    if (!disposed) error.value = reason instanceof Error ? reason.message : '操作失败'
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
  <section class="preprocessing-card" aria-label="EEG 预处理任务">
    <strong>EEG 预处理 · {{ labels[status] ?? status }}</strong>
    <p v-if="job" role="status">已完成 {{ job.completed }} / {{ job.total }} 项方法与记录组合<span v-if="job.cancel_requested"> · 正在取消</span></p>
    <p v-else-if="output.record_count !== undefined">计划包含 {{ output.record_count }} 项方法与记录组合。</p>
    <p v-if="output.missing_fields?.length">需要：{{ output.missing_fields.join('、') }}</p>
    <p v-if="output.blocking_reason">{{ output.blocking_reason }}</p>
    <details v-if="output.screening?.length"><summary>查看方法初筛</summary><ul><li v-for="(item, index) in output.screening" :key="index">{{ item.status }}：{{ item.reasons.join('；') }}</li></ul></details>
    <div class="preprocessing-actions">
      <a v-if="planUrl" :href="apiUrl(planUrl)" target="_blank" rel="noopener">查看完整计划</a>
      <button v-if="!job && output.plan_ref && output.record_count" :disabled="busy" @click="act('submit')">执行计划</button>
      <button v-if="job && active" :disabled="busy || job.cancel_requested" @click="act('cancel')">取消处理</button>
      <button v-if="job && ['partial', 'failed', 'cancelled'].includes(status)" :disabled="busy" @click="act('retry')">重跑未完成记录</button>
      <button v-if="error && (job?.job_id || output.job_id)" @click="refresh(job?.job_id || output.job_id!)">刷新进度</button>
    </div>
    <details v-if="job?.records.length"><summary>记录与产物</summary>
      <ul><li v-for="record in job.records" :key="record.key">
        <span>{{ record.record_id }} · 方法 {{ record.method_id.slice(0, 8) }} · {{ labels[record.status] ?? record.status }} · 第 {{ record.attempt }} 次尝试</span>
        <p v-if="record.error">{{ record.error }}</p>
        <details v-if="record.status === 'completed' && record.result"><summary>下载产物</summary><ul><li v-for="artifact in record.result.artifacts" :key="artifact.name"><a :href="artifactUrl(record, artifact)" download>{{ artifact.name }}</a></li></ul></details>
      </li></ul>
    </details>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.preprocessing-card { padding: 14px 16px; margin: 12px 0; border: 1px solid #d7dedb; border-radius: 10px; background: #f6f9f7; font-size: 13px; overflow-wrap: anywhere; }
.preprocessing-card p { margin: 8px 0; }
.preprocessing-actions { display: flex; align-items: center; gap: 12px; margin: 8px 0; flex-wrap: wrap; }
.preprocessing-actions button { border: 1px solid #becfc5; border-radius: 5px; padding: 5px 9px; background: white; cursor: pointer; }
.preprocessing-card summary { cursor: pointer; margin: 6px 0; }
.preprocessing-card li { margin: 8px 0; }
</style>
