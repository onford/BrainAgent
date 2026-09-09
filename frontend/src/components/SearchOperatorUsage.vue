<script setup lang="ts">
import { computed } from 'vue'
import { searchArtifactUrl } from '../api/searches'
import type { OperatorUsage } from '../types/search'

const props = defineProps<{ searchId: string; candidateId: string; usage?: OperatorUsage | null }>()
const names: Record<string, string> = { resample: '重采样', filter: '滤波', notch: '工频陷波', reference: '重参考', epoch: '任务切窗', detrend: '去趋势', detect_bad_channels: '坏道诊断', mark_channels: '坏道标记', interpolate_bad_channels: '坏道插值', asr_clean: 'ASR 重建' }
const asr = computed(() => Object.values(props.usage?.summary.operators ?? {}).find(row => row.op === 'asr_clean'))
const href = computed(() => props.usage ? searchArtifactUrl(props.searchId, { name: `candidates/${props.candidateId}/${props.usage.artifact.path}` }) : '')
</script>

<template>
  <section v-if="usage" class="operator-usage" aria-label="算子实际执行情况">
    <p v-if="asr?.counts.not_applicable" class="notice">{{ asr.counts.not_applicable }} 条记录未应用 ASR；条件策略保留该步骤输入，并继续其余处理。它们仍在评价分母中。</p>
    <details>
      <summary>算子实际执行 · {{ usage.summary.record_count }} 条记录 <span>查看应用、未适用及失败情况</span></summary>
      <p>“已应用”表示执行完成，不等于信号发生变化或效果更好。记录完成与每个算子实际应用分别统计。</p>
      <div class="scroll"><table><thead><tr><th>算子</th><th>已应用</th><th>不适用</th><th>失败</th><th>未执行</th><th>记录分母</th></tr></thead><tbody><tr v-for="(row, id) in usage.summary.operators" :key="id"><td>{{ names[row.op] ?? row.op }}<details v-if="row.counts.failed || row.counts.not_applicable || row.counts.not_reached"><summary>原因计数</summary><pre>{{ JSON.stringify(row.reason_counts, null, 2) }}</pre></details></td><td>{{ row.counts.applied }}</td><td>{{ row.counts.not_applicable }}</td><td>{{ row.counts.failed }}</td><td>{{ row.counts.not_reached }}</td><td>{{ row.denominator }}</td></tr></tbody></table></div>
      <a :href="href" target="_blank" rel="noopener">逐记录算子、校准时长与证据文件 ↗</a>
    </details>
  </section>
</template>

<style scoped>
.operator-usage{margin:12px 0 22px;border:1px solid #dce9e4;border-radius:10px;padding:14px 16px;color:#25453e;font-size:13px}summary{cursor:pointer;line-height:1.7}summary span,p{color:#667e78}summary span{margin-left:12px;font-size:12px}.notice{background:#fff7e7;border-radius:6px;padding:10px;color:#835b20;margin:0 0 12px}.scroll{max-height:320px;overflow:auto;margin:14px 0}table{border-collapse:collapse;width:100%;white-space:nowrap}th,td{text-align:left;padding:10px;border-bottom:1px solid #e8efeb}th{position:sticky;top:0;background:#f5f9f6}pre{max-width:330px;white-space:pre-wrap;font-size:11px}a{color:#247465}
</style>
