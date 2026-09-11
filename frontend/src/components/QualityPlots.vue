<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { apiRequest } from '../api/client'
import { searchArtifactUrl } from '../api/searches'
import { db, finite, mean, numeric, metricCurves, perSubject, curve, type Series } from '../utils/assessmentPlots'
import AssessmentPlot from './AssessmentPlot.vue'
import AssessmentHeatmap from './AssessmentHeatmap.vue'

const props = defineProps<{ searchId: string; candidateId: string; basePath: string; receiptPath: string }>()
const receipt = ref<any>(null), detail = ref<any>(null), error = ref(''), loading = ref(false)
const stage = ref('processed_task'), metric = ref('psd'), recordId = ref(''), channel = ref(0)
const stages: Record<string, string> = { processed_task: '处理后任务', source_task: '源任务', source_raw: '源连续记录', processed_continuous: '处理后连续记录', source_precue: '源基线', processed_precue: '同处理基线' }
const names: Record<string, string> = { psd: '功率谱 PSD', psd_window_quantiles: '窗级 PSD Q10/Q50/Q90', oha: 'OHA 超幅曲线', thv: 'THV 跨通道波动', chv: 'CHV 通道时间波动', peak_to_peak: '峰峰值', robust_dispersion: '稳健离散度', channel_correlation: '通道相关性', low_correlation_fraction: '低相关比例', flat_fraction: '平坦比例', numerical_rank: '数值秩', participation_rank: '参与率秩', covariance_condition: '协方差条件数', covariance_trace: '总方差', mu_mean_psd: 'μ 频带 PSD', beta_mean_psd: 'β 频带 PSD', emg_hf_proxy: '高频代理', line_ratio_50hz: '50 Hz 比值', line_ratio_60hz: '60 Hz 比值', drift_slope: '漂移斜率', drift_power_ratio: '低频比', electrical_distance: '电气距离', reference_nrmse: '相对参考改变', erds_mu: 'μ ERDS', erds_beta: 'β ERDS' }
let serial = 0
const folder = computed(() => `candidates/${props.candidateId}/${props.basePath}/${props.receiptPath.split('/').slice(0,-1).join('/')}`.replace(/\/$/, ''))
const url = (path: string) => `/api/searches/${encodeURIComponent(props.searchId)}/artifacts/${path.split('/').map(encodeURIComponent).join('/')}?download=false`
async function load() {
  const current = ++serial
  loading.value = true; error.value = ''; detail.value = null
  try {
    if (!receipt.value) {
      const result = await apiRequest<any>(url(`candidates/${props.candidateId}/${props.basePath}/${props.receiptPath}`))
      if (current !== serial) return
      receipt.value = result
    }
    if (recordId.value) {
      const artifact = receipt.value.detail_artifacts?.find((a: any) => a.record_id === recordId.value)
      if (!artifact) throw new Error('该记录缺少明细索引')
      const result = await apiRequest<any>(url(`${folder.value}/${artifact.path}`))
      if (current === serial) detail.value = result
    }
  } catch (e) { if (current === serial) error.value = String(e) }
  finally { if (current === serial) loading.value = false }
}
watch(() => [props.searchId, props.candidateId, props.basePath, props.receiptPath], () => { serial++; receipt.value = null; detail.value = null; recordId.value = ''; void load() }, { immediate: true })
watch(recordId, () => { channel.value = 0; void load() })
const report = computed(() => detail.value?.stages?.[stage.value])
const row = computed(() => recordId.value ? report.value?.metrics?.find((m: any) => m.metricID === metric.value) : receipt.value?.stages?.[stage.value]?.[metric.value])
const chart = computed(() => metricCurves(row.value, !!recordId.value))
const subjectSeries = computed(() => [perSubject(receipt.value, stage.value, metric.value)])
const preview = computed(() => report.value?.metadata?.diagnostic_views)
const waveform = computed(() => preview.value?.waveform && preview.value.channels[channel.value] ? [curve(preview.value.channels[channel.value], preview.value.waveform.times_seconds, preview.value.waveform.values_uv[channel.value])] : [])
const overview = computed(() => {
  const p = preview.value, o = p?.overview
  return o && p.channels[channel.value] ? [curve('窗口最小值', o.start_seconds, o.minimum_uv[channel.value]), curve('窗口最大值', o.start_seconds, o.maximum_uv[channel.value])] : []
})
const provenance = computed(() => ({ search_id: props.searchId, candidate_id: props.candidateId, assessment_path: props.basePath, record_id: recordId.value || null, stage: stage.value, metric: metric.value, artifact: recordId.value ? receipt.value?.detail_artifacts?.find((a: any) => a.record_id === recordId.value) : props.receiptPath }))
const caption = computed(() => `${stages[stage.value]} · ${recordId.value ? '记录 '+recordId.value : '先记录均值，再被试等权'} · 原生视图；未经共同参考/带宽校验，不直接比较阶段差值。`)
const heatmap = computed(() => {
  const m = row.value, r = report.value
  if (!recordId.value || !m || !r) return null
  if (metric.value === 'psd_window_quantiles' && Array.isArray(m.details?.window_channel_median_psd)) {
    return { rows: m.details.windows.map((w: any) => `E${w.epoch_index} ${w.start_seconds_in_epoch}–${w.stop_seconds_in_epoch}s`), columns: m.details.frequencies_hz.map((f: number) => f+' Hz'), values: m.details.window_channel_median_psd.map((v: number[]) => v.map(db)), unit: `dB(${m.unit})`, caption: '每个完整 4 s 窗的通道中位 PSD；未拼接试次、未去掉坏窗。时间相对各输入片段起点。' }
  }
  if (!Array.isArray(m.value) || !m.value.every((v: unknown) => Array.isArray(v)) || metric.value === 'psd' || metric.value === 'psd_window_quantiles') return null
  const columns = metric.value === 'electrical_distance' ? m.details?.channel_pairs?.map((p: string[]) => p.join('–')) : r.channel_names
  if (!Array.isArray(columns) || !m.value.every((v: unknown[]) => v.length === columns.length)) return null
  const windows = m.details?.windows
  const indices = m.denominator?.valid_epoch_indices
  const rows = m.value.map((_: unknown, i: number) => windows?.[i] ? `E${windows[i].epoch_index} ${windows[i].start_seconds_in_epoch}–${windows[i].stop_seconds_in_epoch}s` : `E${metric.value.startsWith('erds_') ? i : indices?.[i] ?? i}`)
  return { rows, columns, values: m.value.map((a: unknown[]) => a.map(numeric)), unit: m.unit, caption: '保留明细原有通道和窗口/片段轴；E 为输入片段索引。每种指标独立色标，不进行跨指标标准化。' }
})
const channelSeries = computed<Series[]>(() => {
  const h = heatmap.value
  if (!h || metric.value === 'psd_window_quantiles') return []
  return [{ name: '通道/通道对均值', connect: false, points: h.columns.map((name: string, c: number) => ({ x: c+1, y: mean(h.values.map((v: unknown[]) => v[c])), label: name })) }]
})
const sensorSeries = computed<Series[]>(() => {
  const layout = preview.value?.sensor_layout
  if (!layout) return []
  return [{ name: '电极位置', connect: false, points: layout.positions_m.map((p: number[], i: number) => ({ x: p[0], y: p[1], label: layout.channels[i] })) }]
})
const detailLink = computed(() => {
  const artifact = receipt.value?.detail_artifacts?.find((a: any) => a.record_id === recordId.value)
  return artifact ? searchArtifactUrl(props.searchId, { name: `${folder.value}/${artifact.path}` }) : null
})
</script>
<template>
  <div class="quality-plots">
    <div class="controls"><label>图表阶段 <select v-model="stage"><option v-for="(name, key) in stages" :key="key" :value="key">{{ name }}</option></select></label><label>图表指标 <select v-model="metric"><option v-for="(name, key) in names" :key="key" :value="key">{{ name }}</option></select></label><label>范围 <select v-model="recordId"><option value="">被试等权汇总</option><option v-for="a in receipt?.detail_artifacts ?? []" :key="a.record_id" :value="a.record_id">{{ a.subject }} / {{ a.record_id }}</option></select></label><a v-if="detailLink" :href="detailLink" target="_blank" rel="noopener">本记录数值与来源</a></div>
    <p v-if="loading" role="status">读取图表数据…</p><p v-if="error" role="alert">{{ error }} <button @click="load">重试图表读取</button></p>
    <template v-if="!loading && !error">
      <p class="note">{{ caption }}</p>
      <p v-if="row" class="note">状态：{{ row.status }} · {{ row.reason || '无缺失原因' }} · 单位 {{ row.unit }}。{{ metric === 'psd_window_quantiles' ? '这些是窗口分位曲线；汇总时为记录分位曲线均值，不是置信区间或合并窗分位数。' : '' }}</p>
      <p v-else>此阶段没有该指标记录，不能用其他阶段填补。</p>
      <AssessmentPlot v-if="chart.series.length" :title="names[metric] || metric" v-bind="chart" :caption="caption" :provenance="provenance" />
      <AssessmentPlot v-else-if="!recordId && row && (finite(row.value) || row.value === null)" :title="(names[metric] || metric) + ' · 逐被试'" :series="subjectSeries" x-label="被试编号（按 ID 排序，完整 ID 见点标签）" :y-label="row.unit" :caption="caption + '每点为该被试内记录等权均值；不连接不同被试。'" :provenance="provenance" />
      <AssessmentHeatmap v-if="heatmap" :title="(names[metric] || metric) + ' · 记录明细'" v-bind="heatmap" :diverging="metric.startsWith('erds_') || metric === 'drift_slope'" :provenance="provenance" />
      <AssessmentPlot v-if="channelSeries.length" title="通道／通道对分布" :series="channelSeries" x-label="通道／通道对序号（见点标签）" :y-label="row.unit" :caption="caption + '各列有限窗口/片段等权平均，仅用于明细定位；完整缺失见热图。'" :provenance="provenance" />
      <details v-if="row"><summary>本图实际公式、参数和分母</summary><pre>{{ JSON.stringify({ formula: row.formula, axes: row.axes, denominator: row.denominator, details: row.details }, null, 2) }}</pre></details>
      <details v-if="recordId"><summary>波形预览与电极布局</summary>
        <template v-if="preview?.status === 'ok'">
          <p class="note">确定性预览：首个有限片段 E{{ preview.epoch_index }} · {{ preview.trial_id || '连续记录或未保存 trial ID' }}。显示 C3/Cz/C4 中已有通道，否则取前三通道。仅用于定位，不代表全部试次。位置来自文件，可能是标准模板。</p>
          <label>预览通道 <select v-model="channel"><option v-for="(c, i) in preview.channels" :key="c" :value="i">{{ c }}</option></select></label>
          <AssessmentPlot title="片段前 4 秒波形（不足时显示实际长度）" :series="waveform" x-label="相对输入片段起点 (s)" y-label="µV" caption="原采样点，无显示滤波和平滑。不是事件锁定平均。" :provenance="provenance" />
          <AssessmentPlot title="片段全长最小／最大包络" :series="overview" x-label="窗口起点，相对输入片段 (s)" y-label="µV" caption="最多 256 个连续桶保留极值；连线仅连接桶的极值，不能解释为原波形或频谱。" :provenance="provenance" />
          <AssessmentPlot v-if="sensorSeries.length" title="电极布局点图（无插值）" :equal-aspect="true" :series="sensorSeries" x-label="头坐标 x (m)" y-label="头坐标 y (m)" caption="保存的电极位置投影，横纵轴等比例。此图不估计头皮场或脑源；不能用位置图替代任务侧化证据。" :provenance="provenance" />
        </template><p v-else>此记录未保存波形／位置预览。旧运行保持只读，不从汇总指标重建信号。</p>
      </details>
    </template>
  </div>
</template>
<style scoped>
.quality-plots{margin-top:18px;padding-top:16px;border-top:1px solid #d9e4dd}.controls{display:flex;gap:12px;flex-wrap:wrap;align-items:center}label{font-size:12px}select,button{font:inherit;padding:6px 9px;background:white;border:1px solid #cfded4;border-radius:6px;color:#345541}a,summary{color:#287557;font-size:12px}summary{cursor:pointer;margin:14px 0}.note{font-size:12px;color:#62786a;line-height:1.8}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:280px;overflow:auto;font-size:11px}
</style>
