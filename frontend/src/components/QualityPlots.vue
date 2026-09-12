<script setup lang="ts">
import { t } from '../i18n'
import { computed, ref, watch } from 'vue'
import { apiRequest } from '../api/client'
import { searchArtifactUrl } from '../api/searches'
import { db, finite, mean, numeric, metricCurves, perSubject, curve, type Series } from '../utils/assessmentPlots'
import { axisDomain, colorDomain, type Domain } from '../utils/figureStyle'
import { electricalMatrix, epochSeries, fractionDomain } from '../utils/qualityFigureData'
import AssessmentPlot from './AssessmentPlot.vue'
import AssessmentHeatmap from './AssessmentHeatmap.vue'
import MetricReading from './MetricReading.vue'

const props = defineProps<{ searchId: string; candidateId: string; basePath: string; receiptPath: string }>()
const receipt = ref<any>(null), detail = ref<any>(null), error = ref(''), loading = ref(false)
const stage = defineModel<string>('stage', { default: 'processed_task' })
const metric = ref('psd'), recordId = ref(''), channel = ref(0)
const statuses: Record<string, string> = { get ok() { return t('Computed') }, get partial() { return t('Partially available') }, get not_applicable() { return t('Not applicable') }, get not_computable() { return t('Not computable') }, get failed() { return t('Computation failed') } }
const stages: Record<string, string> = { get processed_task() { return t('Processed task') }, get source_task() { return t('Source task') }, get source_raw() { return t('Source continuous data') }, get processed_continuous() { return t('Processed continuous data') }, get source_precue() { return t('Source baseline') }, get processed_precue() { return t('Matched processed baseline') } }
const names: Record<string, string> = { get psd() { return t('Power spectral density (PSD)') }, get psd_window_quantiles() { return t('Window PSD Q10/Q50/Q90') }, get oha() { return t('OHA amplitude exceedance') }, get thv() { return t('THV across-channel variability') }, get chv() { return t('CHV within-channel temporal variability') }, get peak_to_peak() { return t('Peak-to-peak amplitude') }, get robust_dispersion() { return t('Robust dispersion') }, get channel_correlation() { return t('Channel correlation') }, get low_correlation_fraction() { return t('Low-correlation fraction') }, get flat_fraction() { return t('Flat-signal fraction') }, get numerical_rank() { return t('Numerical rank') }, get participation_rank() { return t('Participation-ratio rank') }, get covariance_condition() { return t('Covariance condition number') }, get covariance_trace() { return t('Total variance') }, get mu_mean_psd() { return t('Mu-band PSD') }, get beta_mean_psd() { return t('Beta-band PSD') }, get emg_hf_proxy() { return t('High-frequency proxy') }, get line_ratio_50hz() { return t('50 Hz ratio') }, get line_ratio_60hz() { return t('60 Hz ratio') }, get drift_slope() { return t('Drift slope') }, get drift_power_ratio() { return t('Low-frequency ratio') }, get electrical_distance() { return t('Electrical distance') }, get reference_nrmse() { return t('Change from reference') }, erds_mu: 'μ ERDS', erds_beta: 'β ERDS' }
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
      if (!artifact) throw new Error(t('No detail index is available for this record'))
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
const neural = computed(() => report.value?.metadata?.neural_tfr)
// Freeze the comparison scope to all ROI channels and the complete saved time axis.
const neuralLimits = computed(() => colorDomain(neural.value?.erds_percent?.flat(2) ?? [], true))
const waveformLimits = computed(() => axisDomain(preview.value?.waveform?.values_uv?.flat() ?? [], undefined, .04))
const boundedMetrics = ['oha', 'thv', 'chv', 'channel_correlation', 'low_correlation_fraction', 'flat_fraction']
const metricLimits = computed<Domain | undefined>(() => boundedMetrics.includes(metric.value) ? (metric.value === 'channel_correlation' ? [0, 1] : fractionDomain([...(Array.isArray(row.value?.value) ? row.value.value.flat(3) : [row.value?.value]), ...subjectSeries.value.flatMap(s => s.points.map(p => p.y))])) : undefined)
const epochs = computed(() => recordId.value ? epochSeries(row.value) : [])
const singleValue = computed(() => uniform.value ? uniform.value.value : recordId.value ? (finite(row.value?.value) ? row.value.value : epochs.value[0]?.points.length === 1 ? epochs.value[0].points[0]!.y : null) : null)
const pairs = computed(() => electricalMatrix(row.value, report.value?.channel_names ?? []))
const showChannelMeans = ref(false)
watch([metric, recordId, stage], () => { showChannelMeans.value = false })
const hasSubjects = computed(() => subjectSeries.value.some(s => s.points.some(p => finite(p.y))))
const longPreview = computed(() => preview.value?.sample_count > (preview.value?.waveform?.times_seconds?.length ?? Infinity))
const waveform = computed(() => preview.value?.waveform && preview.value.channels[channel.value] ? [curve(preview.value.channels[channel.value], preview.value.waveform.times_seconds, preview.value.waveform.values_uv[channel.value])] : [])
const overview = computed(() => {
  const p = preview.value, o = p?.overview
  return o && p.channels[channel.value] ? [{ ...curve(t('Window minimum'), o.start_seconds, o.minimum_uv[channel.value]), id: 'window-min' }, { ...curve(t('Window maximum'), o.start_seconds, o.maximum_uv[channel.value]), id: 'window-max' }] : []
})
const provenance = computed(() => ({ search_id: props.searchId, candidate_id: props.candidateId, assessment_path: props.basePath, record_id: recordId.value || null, stage: stage.value, metric: metric.value, artifact: recordId.value ? receipt.value?.detail_artifacts?.find((a: any) => a.record_id === recordId.value) : props.receiptPath }))
const caption = computed(() => t('{0} · {1}. Compare stages only with matching references and effective passbands.', { 0: stages[stage.value], 1: recordId.value ? t('Record ')+recordId.value : t('Average records, then weight subjects equally') }))
const heatmap = computed(() => {
  const m = row.value, r = report.value
  if (!recordId.value || !m || !r || metric.value === 'electrical_distance') return null
  if (metric.value === 'psd_window_quantiles' && Array.isArray(m.details?.window_channel_median_psd)) {
    return { rows: m.details.windows.map((w: any) => `E${w.epoch_index} ${w.start_seconds_in_epoch}–${w.stop_seconds_in_epoch}s`), columns: m.details.frequencies_hz.map((f: number) => Number(f.toPrecision(4))+' Hz'), values: m.details.window_channel_median_psd.map((v: number[]) => v.map(db)), unit: `dB(${m.unit})`, get caption() { return t('Channel-median PSD in each complete 4 s window. Trials are not concatenated and bad windows are not removed. Time is relative to each input segment.') } }
  }
  if (!Array.isArray(m.value) || !m.value.every((v: unknown) => Array.isArray(v)) || metric.value === 'psd' || metric.value === 'psd_window_quantiles') return null
  const columns = metric.value === 'electrical_distance' ? m.details?.channel_pairs?.map((p: string[]) => p.join('–')) : r.channel_names
  if (!Array.isArray(columns) || !m.value.every((v: unknown[]) => v.length === columns.length)) return null
  const windows = m.details?.windows
  const indices = m.denominator?.valid_epoch_indices
  const rows = m.value.map((_: unknown, i: number) => windows?.[i] ? `E${windows[i].epoch_index} ${Number(windows[i].start_seconds_in_epoch.toFixed(3))}–${Number(windows[i].stop_seconds_in_epoch.toFixed(3))}s` : `E${metric.value.startsWith('erds_') ? i : indices?.[i] ?? i}`)
  return { rows, columns, values: m.value.map((a: unknown[]) => a.map(numeric)), unit: m.unit, get caption() { return t('Original channel and window/segment axes are retained. E denotes the input segment index. Each metric has its own color scale; metrics are not standardized against each other.') } }
})
const channelSeries = computed<Series[]>(() => {
  const h = heatmap.value
  if (!h || metric.value === 'psd_window_quantiles') return []
  return [{ get name() { return t('Channel / channel-pair mean') }, connect: false, points: h.columns.map((name: string, c: number) => ({ x: c+1, y: mean(h.values.map((v: unknown[]) => v[c])), label: name })) }]
})
const uniform = computed(() => {
  const series = !recordId.value ? subjectSeries.value : epochs.value.length ? epochs.value : heatmap.value?.rows.length === 1 ? channelSeries.value : []
  const points = series.flatMap(s => s.points)
  if (points.length < 2 || !points.every(p => finite(p.y)) || new Set(points.map(p => p.y)).size !== 1) return null
  return { value: points[0]!.y!, count: points.length }
})
const sensorSeries = computed<Series[]>(() => {
  const layout = preview.value?.sensor_layout
  if (!layout) return []
  return [{ get name() { return t('Electrode positions') }, connect: false, points: layout.positions_m.map((p: number[], i: number) => ({ x: p[0], y: p[1], label: layout.channels[i], annotation: ['C3', 'Cz', 'C4'].includes(layout.channels[i]) ? layout.channels[i] : undefined })) }]
})
const detailLink = computed(() => {
  const artifact = receipt.value?.detail_artifacts?.find((a: any) => a.record_id === recordId.value)
  return artifact ? searchArtifactUrl(props.searchId, { name: `${folder.value}/${artifact.path}` }) : null
})
</script>
<template>
  <div class="quality-plots">
    <div class="controls"><label>{{ t('Plot stage') }}<select v-model="stage"><option v-for="(name, key) in stages" :key="key" :value="key">{{ name }}</option></select></label><label>{{ t('Plot metric') }}<select v-model="metric"><option v-for="(name, key) in names" :key="key" :value="key">{{ name }}</option></select></label><label>{{ t('Scope') }}<select v-model="recordId"><option value="">{{ t('Equal-subject aggregate') }}</option><option v-for="a in receipt?.detail_artifacts ?? []" :key="a.record_id" :value="a.record_id">{{ a.subject }} / {{ a.record_id }}</option></select></label><a v-if="detailLink" :href="detailLink" target="_blank" rel="noopener">{{ t('Record values and provenance') }}</a></div>
    <p v-if="loading" role="status">{{ t('Loading plot data…') }}</p><p v-if="error" role="alert">{{ error }} <button @click="load">{{ t('Retry loading plots') }}</button></p>
    <template v-if="!loading && !error">
      <p v-if="row" class="note">{{ statuses[row.status] || row.status }} · {{ row.unit }}<span v-if="row.reason"> · {{ row.reason }}</span>{{ metric === 'psd_window_quantiles' ? t('These are window quantile curves. Aggregation averages record-level quantile curves; they are neither confidence intervals nor pooled-window quantiles.') : '' }}</p>
      <p v-else>{{ t('This metric was not recorded at this stage. Values from other stages cannot fill the gap.') }}</p>
      <AssessmentPlot :comparison-key="`quality:${metric}:curve`" v-if="chart.series.length" :title="names[metric] || metric" v-bind="chart" :y-domain="metricLimits" :caption="caption" :provenance="provenance" />
      <AssessmentPlot :comparison-key="`quality:${metric}:subjects`" v-else-if="!recordId && row && hasSubjects && !uniform" :title="(names[metric] || metric) + t(' · By subject')" categorical :series="subjectSeries" :y-domain="metricLimits" :x-label="t('Subject index (sorted by ID; full IDs in point labels)')" :y-label="row.unit" :caption="caption + t('Each point is an equal-record mean within a subject. Different subjects are not connected.')" :provenance="provenance" />
      <p v-if="finite(singleValue)" class="single-value">{{ names[metric] || metric }}<span v-if="uniform"> · {{ t('{0} available observations have the same value', { 0: uniform.count }) }}</span>: <strong>{{ singleValue.toLocaleString(undefined, { maximumSignificantDigits: 6 }) }} {{ row.unit }}</strong></p>
      <AssessmentPlot :comparison-key="`quality:${metric}:epochs`" v-if="epochs[0] && epochs[0].points.length > 1 && !uniform" :title="(names[metric] || metric) + t(' · By epoch')" categorical :series="epochs" :x-label="t('Original epoch index')" :y-label="row.unit" :caption="caption" :provenance="provenance" />
      <AssessmentHeatmap comparison-key="quality:electrical_distance:pairs" v-if="pairs" :title="t('Electrical distance by electrode pair')" v-bind="pairs" full-matrix :caption="t('Mean of finite epochs for each recorded pair. Symmetric cells repeat the same pair; the diagonal is unmeasured. This is not a spatial map or a bridge diagnosis.')" :provenance="provenance" />
      <AssessmentHeatmap :comparison-key="`quality:${metric}:matrix`" v-if="heatmap && heatmap.rows.length > 1" :title="(names[metric] || metric) + t(' · Record detail')" v-bind="heatmap" :full-matrix="metric === 'psd_window_quantiles'" :color-limits="metricLimits" :diverging="metric.startsWith('erds_') || metric === 'drift_slope'" :provenance="provenance" />
      <button v-if="channelSeries.length && (heatmap?.rows.length ?? 0) > 1" :aria-pressed="showChannelMeans" @click="showChannelMeans = !showChannelMeans">{{ t('Channel means') }}</button>
      <AssessmentPlot :comparison-key="`quality:${metric}:channels`" v-if="channelSeries.length && !uniform && (showChannelMeans || heatmap?.rows.length === 1)" :title="(names[metric] || metric) + t(' · Channel means')" categorical :series="channelSeries" :y-domain="metricLimits" :x-label="t('Channel / channel-pair index (see point labels)')" :y-label="row.unit" :caption="caption + t('Equal-weight mean over finite windows/segments in each column, for locating details. The heatmap shows all missing values.')" :provenance="provenance" />
      <MetricReading v-if="row && !recordId" :search-id="searchId" :candidate-id="candidateId" :stage="stage" :metric-id="metric" :row="row" />
      <details v-if="row"><summary>{{ t('Formula, parameters, and denominators') }}</summary><pre>{{ JSON.stringify({ formula: row.formula, axes: row.axes, denominator: row.denominator, details: row.details }, null, 2) }}</pre></details>
      <details v-if="recordId"><summary>{{ t('Waveform preview and electrode layout') }}</summary>
        <details><summary>{{ '感觉运动 ROI 时频与基线支持' }}</summary>
          <p v-if="!neural">{{ '此记录未保存时频诊断。' }}</p>
          <template v-else>
            <p>{{ neural.status }} · {{ neural.reason || '已保存任务诊断' }} · 有效配对 {{ neural.paired_trials }} / {{ neural.expected_trials }} 试次</p>
            <p>时间相对片段起点；相对真实基线的变化不证明来源或神经保留。本记录全部 ROI 通道、频率和时间共用对称色标；负值蓝、正值红，灰色表示缺失或边缘支持不足。不同记录与阶段的色限见各自色条。</p>
            <AssessmentHeatmap comparison-key="diagnostic:neural-tfr" comparison-label="任务时频变化" v-for="(ch, i) in (neural.erds_percent ? neural.channels : [])" :key="ch" :title="ch + ' 任务时频变化'" :rows="neural.frequencies_hz.map((f: number) => `${f} Hz`)" :columns="neural.times_seconds.map((t: number) => `${t.toFixed(3)} s`)" :values="neural.erds_percent[i]" unit="%" full-matrix :caption="'逐试次相对同处理基线变化的等权平均；不使用计分类别、不设合格方向。'" diverging reverse-rows x-label="时间 (s)" y-label="频率 (Hz)" :color-limits="neuralLimits" :provenance="{ ...provenance, metric: 'neural_tfr', channel: ch, measurement: 'metadata.neural_tfr', paired_trials: neural.paired_trials, expected_trials: neural.expected_trials, parameters: neural.parameters, limitations: neural.limitations }" />
          </template>
        </details>
        <template v-if="preview?.status === 'ok'">
          <p class="note">{{ t('Preview: first complete segment E{0} · {1}. Available C3/Cz/C4 channels are shown, otherwise the first three channels. This preview does not represent all trials. Positions come from the file and may use a standard template.', { 0: preview.epoch_index, 1: preview.trial_id || t('Continuous data or trial ID not recorded') }) }}</p>
          <label>{{ t('Preview channel') }}<select v-model="channel"><option v-for="(c, i) in preview.channels" :key="c" :value="i">{{ c }}</option></select></label>
          <AssessmentPlot comparison-key="diagnostic:waveform" :title="t('First 4 s of the segment (or its available duration)')" :series="waveform" :y-domain="waveformLimits" :x-label="t('Time from segment onset (s)')" y-label="µV" :caption="t('Original samples, without display filtering or smoothing. This is not an event-locked average.')" :provenance="{ ...provenance, metric: 'waveform', channel: preview.channels[channel], scale_scope: 'all preview channels in this record and stage' }" />
          <AssessmentPlot comparison-key="diagnostic:envelope" :comparison-label="t('Full-segment minimum / maximum envelope')" v-if="longPreview" :title="preview.channels[channel] + ' · ' + t('Full-segment minimum / maximum envelope')" :series="overview" :x-label="t('Window onset relative to segment (s)')" y-label="µV" :caption="t('Up to 256 time bins retain their minimum and maximum values to locate transients. Connecting lines are not the original waveform.')" :provenance="{ ...provenance, metric: 'envelope', channel: preview.channels[channel] }" />
          <details v-if="sensorSeries.length"><summary>{{ t('Electrode layout (no interpolation)') }}</summary><AssessmentPlot comparison-key="diagnostic:electrodes" :title="t('Electrode layout (no interpolation)')" :equal-aspect="true" :series="sensorSeries" :x-label="t('Head-coordinate x (m)')" :y-label="t('Head-coordinate y (m)')" :caption="t('Projected electrode positions with equal axis scaling. This plot does not estimate scalp fields or brain sources and is not evidence of task lateralization.')" :provenance="{ ...provenance, metric: 'electrodes' }" /></details>
        </template><p v-else>{{ t('No waveform or electrode-position preview was saved for this record.') }}</p>
      </details>
    </template>
  </div>
</template>
<style scoped>
.quality-plots { margin-top: 14px; }
.controls { display: grid; grid-template-columns: minmax(120px, 1fr) minmax(140px, 1.4fr) minmax(150px, 1.4fr); gap: 12px; padding: 16px; background: #f5f8f9; border-radius: 8px; }
label { display: flex; flex-direction: column; gap: 6px; color: #586f75; font-size: 12px; min-width: 0; }
select, button { font: inherit; padding: 9px 10px; background: #fff; border: 1px solid #cbd9dd; border-radius: 6px; color: #253e43; min-width: 0; }
a, summary { color: #176e65; font-size: 12px; }
.controls a { grid-column: 1 / -1; }
summary { cursor: pointer; margin: 14px 0; }
.note { font-size: 12px; color: #586f75; line-height: 1.8; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 280px; overflow: auto; font-size: 11px; padding: 14px; background: #f5f8f9; border-radius: 6px; }
@media(max-width: 560px) { .controls { grid-template-columns: 1fr; padding: 12px; } }
</style>
