<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AssessmentPlot from './AssessmentPlot.vue'
import { curve } from '../utils/assessmentPlots'
import { axisDomain } from '../utils/figureStyle'
import { searchArtifactUrl } from '../api/searches'
const props = defineProps<{ contrast?: any; searchId: string; folder: string; recordId: string }>()
const channel = ref(0)
watch(() => props.contrast, () => { channel.value = 0 })
const names: Record<string, string> = { source: '原始信号的共同视图', processed: '处理信号的共同视图', difference: '原始 − 处理的信号差值' }
const channels = computed<string[]>(() => props.contrast?.views?.source?.preview?.channels ?? [])
const keys = ['source', 'processed', 'difference']
const limits = computed(() => axisDomain(keys.flatMap(k => props.contrast?.views?.[k]?.preview?.waveform?.values_uv?.flat() ?? []), undefined, .04))
const series = (key: string) => {
  const p = props.contrast?.views?.[key]?.preview
  return p?.waveform && p.channels[channel.value] ? [curve(names[key]!, p.waveform.times_seconds.map((v: number) => v + (props.contrast?.contract?.time_window?.[0] ?? 0)), p.waveform.values_uv[channel.value])] : []
}
</script>
<template>
  <details class="physical-contrast">
    <summary>共同物理视图与信号差值</summary>
    <p v-if="!contrast">此记录没有保存共同视图。</p>
    <p v-else-if="contrast.status !== 'evaluated'">不可比：{{ contrast.reason }}。未生成信号差值。</p>
    <template v-else>
      <p>配对 {{ contrast.paired_trials }} / {{ contrast.expected_trials }} 个原始试次；统一平均参考，分析频带 {{ contrast.contract.space.band_hz.join('–') }} Hz。</p>
      <p>差值包含滤波、参考、插值和清理的共同影响，不等于纯伪迹，也不证明神经信号保留。共同滤波不能恢复已衰减的频率信息。</p>
      <label>预览通道<select v-model="channel"><option v-for="(name, i) in channels" :key="name" :value="i">{{ name }}</option></select></label>
      <AssessmentPlot v-for="key in keys" :key="key" comparison-key="physical-contrast:shared-voltage" :title="names[key]!" :series="series(key)" :y-domain="limits" x-label="相对事件时间 (s)" y-label="µV"
        caption="同一原始试次的前 4 秒（或可用时长）；共同分析滤波后的数据，三个视图和全部预览通道共用纵轴。完整数组包含全部配对试次，边缘效应保留。"
        :provenance="{ record_id: recordId, view: key, contract_sha256: contrast.contract_sha256, trial_id: contrast.views[key].preview.trial_id, channel: channels[channel] }" />
      <p v-for="a in contrast.artifacts" :key="a.view"><a :href="searchArtifactUrl(searchId, { name: `${folder}/${a.path}` })" target="_blank" rel="noopener">下载{{ names[a.view] }}完整数组（V）</a></p>
    </template>
  </details>
</template>
<style scoped>
.physical-contrast{margin:18px 0;padding:14px;border:1px solid #cbd9dd;border-radius:8px}p{line-height:1.6}label{display:flex;gap:12px;align-items:center}select{padding:6px}summary{cursor:pointer}
</style>
