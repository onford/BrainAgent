<script setup lang="ts">
import { t } from '../i18n'
import { computed } from 'vue'
import { searchArtifactUrl } from '../api/searches'
import type { OperatorUsage } from '../types/search'

const props = defineProps<{ searchId: string; candidateId: string; usage?: OperatorUsage | null }>()
const names: Record<string, string> = { get resample() { return t('Resampling') }, get filter() { return t('Filtering') }, get notch() { return t('Line-noise notch filtering') }, get reference() { return t('Re-referencing') }, get epoch() { return t('Task epoching') }, get detrend() { return t('Detrending') }, get detect_bad_channels() { return t('Bad-channel diagnosis') }, get mark_channels() { return t('Bad-channel marking') }, get interpolate_bad_channels() { return t('Bad-channel interpolation') }, get asr_clean() { return t('ASR reconstruction') } }
const asr = computed(() => Object.values(props.usage?.summary.operators ?? {}).find(row => row.op === 'asr_clean'))
const href = computed(() => props.usage ? searchArtifactUrl(props.searchId, { name: `candidates/${props.candidateId}/${props.usage.artifact.path}` }) : '')
</script>

<template>
  <section v-if="usage" class="operator-usage" :aria-label="t('Actual operator execution')">
    <p v-if="asr?.counts.not_applicable" class="notice">{{ t('ASR was not applied to {0} records. The conditional strategy retained the step input and continued processing. These records remain in the evaluation denominator.', { 0: asr.counts.not_applicable }) }}</p>
    <details>
      <summary>{{ t('Operator execution · {0} records', { 0: usage.summary.record_count }) }}<span>{{ t('View applied, inapplicable, and failed steps') }}</span></summary>
      <p>{{ t('Applied means execution completed; it does not imply the signal changed or improved. Record completion and operator application are counted separately.') }}</p>
      <div class="scroll"><table><thead><tr><th>{{ t('Operator') }}</th><th>{{ t('Applied') }}</th><th>{{ t('Not applicable') }}</th><th>{{ t('Failed') }}</th><th>{{ t('Not executed') }}</th><th>{{ t('Record denominator') }}</th></tr></thead><tbody><tr v-for="(row, id) in usage.summary.operators" :key="id"><td>{{ names[row.op] ?? row.op }}<details v-if="row.counts.failed || row.counts.not_applicable || row.counts.not_reached"><summary>{{ t('Reason counts') }}</summary><pre>{{ JSON.stringify(row.reason_counts, null, 2) }}</pre></details></td><td>{{ row.counts.applied }}</td><td>{{ row.counts.not_applicable }}</td><td>{{ row.counts.failed }}</td><td>{{ row.counts.not_reached }}</td><td>{{ row.denominator }}</td></tr></tbody></table></div>
      <a :href="href" target="_blank" rel="noopener">{{ t('Per-record operators, calibration duration, and evidence files ↗') }}</a>
    </details>
  </section>
</template>

<style scoped>
.operator-usage{margin:12px 0 22px;border:1px solid #dce9e4;border-radius:10px;padding:14px 16px;color:#25453e;font-size:13px}summary{cursor:pointer;line-height:1.7}summary span,p{color:#667e78}summary span{margin-left:12px;font-size:12px}.notice{background:#fff7e7;border-radius:6px;padding:10px;color:#835b20;margin:0 0 12px}.scroll{max-height:320px;overflow:auto;margin:14px 0}table{border-collapse:collapse;width:100%;white-space:nowrap}th,td{text-align:left;padding:10px;border-bottom:1px solid #e8efeb}th{position:sticky;top:0;background:#f5f9f6}pre{max-width:330px;white-space:pre-wrap;font-size:11px}a{color:#247465}
</style>
