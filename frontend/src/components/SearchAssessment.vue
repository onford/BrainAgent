<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { searchArtifactUrl } from '../api/searches'
import type { SearchUtilityReceipt } from '../types/search'
import { apiRequest } from '../api/client'
import AssessmentPlot from './AssessmentPlot.vue'
import QualityPlots from './QualityPlots.vue'
import SearchInterpretation from './SearchInterpretation.vue'
import { numeric, type Series } from '../utils/assessmentPlots'

const props = defineProps<{ searchId: string; candidateId: string; basePath?: string | null; assessment?: Record<string, any> | null; guideFrozen?: boolean; initialAxis?: string }>()
const showQualityPlots = ref(props.initialAxis === 'quality')
const axis = ref(['quality','reconstruction'].includes(props.initialAxis ?? '') ? props.initialAxis! : 'utility'), metric = ref('ba'), stage = ref('processed_task'), query = ref('')
watch(() => props.initialAxis, selected => { axis.value = ['quality','reconstruction'].includes(selected ?? '') ? selected! : 'utility'; showQualityPlots.value = selected === 'quality' })
const data = computed(() => props.assessment)
const utility = computed(() => data.value?.utility)
const isV2 = computed(() => data.value?.schema_version === 'assessment-v2' || utility.value?.utility_version === 2)
const seedSummary = computed(() => isV2.value ? utility.value?.seed_summary : null)
const fullUtility = ref<SearchUtilityReceipt | null>(null), utilityError = ref(''), utilityLoading = ref(false)
let utilityRequest = 0
watch(() => [props.searchId, props.candidateId, props.basePath, props.assessment], () => {
  utilityRequest++; fullUtility.value = null; utilityError.value = ''; utilityLoading.value = false
})
async function loadUtility() {
  const path = utility.value?.receipt_artifact?.path
  if (!path || !props.basePath || fullUtility.value || utilityLoading.value) return
  const serial = ++utilityRequest
  utilityLoading.value = true; utilityError.value = ''
  try {
    const name = `candidates/${props.candidateId}/${props.basePath}/${path}`
    const response = await apiRequest<SearchUtilityReceipt>(`/api/searches/${encodeURIComponent(props.searchId)}/artifacts/${name.split('/').map(encodeURIComponent).join('/')}?download=false`)
    if (serial === utilityRequest) fullUtility.value = response
  } catch (error) { if (serial === utilityRequest) utilityError.value = String(error) }
  finally { if (serial === utilityRequest) utilityLoading.value = false }
}
const quality = computed(() => data.value?.quality?.summary)
const fullQuality = ref<Record<string, any> | null>(null), qualityError = ref(''), qualityLoading = ref(false)
let requestNumber = 0
watch(() => [props.searchId, props.candidateId, props.basePath, props.assessment], () => { requestNumber++; fullQuality.value = null; qualityError.value = ''; qualityLoading.value = false; stage.value = 'processed_task'; showQualityPlots.value = props.initialAxis === 'quality' })
watch(stage, async selected => {
  if (selected === 'processed_task' || fullQuality.value) return
  const path = data.value?.quality?.receipt_artifact?.path
  if (!path || !props.basePath) return
  const serial = ++requestNumber
  qualityLoading.value = true; qualityError.value = ''
  try {
    const name = `candidates/${props.candidateId}/${props.basePath}/${path}`
    const response = await apiRequest<Record<string, any>>(`/api/searches/${encodeURIComponent(props.searchId)}/artifacts/${name.split('/').map(encodeURIComponent).join('/')}?download=false`)
    if (serial === requestNumber) fullQuality.value = response
  } catch (error) { if (serial === requestNumber) qualityError.value = String(error) }
  finally { if (serial === requestNumber) qualityLoading.value = false }
})
const reconstruction = computed(() => data.value?.reconstruction?.summary)
const legacyModels: Record<string, string> = { csp_lda: 'CSP + LDA', fbcsp: 'FBCSP', ts_lr: '切空间 + 逻辑回归', fgmdm: 'FgMDM', ea_fbcsp: '逐频带 EA + FBCSP', logvar_lr: '对数方差 + 逻辑回归' }
const models = computed(() => isV2.value ? { eegnet: 'EEGNet', csp_lda: 'CSP + LDA' } : legacyModels)
const statistics: Record<string, string> = { ba: '平衡准确率 BA', accuracy: '准确率', f1: 'F1（右手为正类）', kappa: 'Cohen κ', auc: 'ROC-AUC', brier: 'Brier 误差', logloss: '对数损失' }
const stages: Record<string, string> = { processed_task: '处理后任务片段', source_task: '源任务片段', source_raw: '源连续记录', processed_continuous: '处理后连续记录', source_precue: '源任务前基线', processed_precue: '同处理任务前基线' }
const labels: Record<string, string> = { peak_to_peak: '峰峰值', robust_dispersion: '稳健离散程度', channel_correlation: '通道相关性', low_correlation_fraction: '低相关窗口比例', covariance_condition: '协方差条件数', covariance_trace: '总方差', participation_rank: '参与率有效秩', mu_mean_psd: 'μ 频带平均功率', beta_mean_psd: 'β 频带平均功率', emg_hf_proxy: '肌电高频代理', line_ratio_50hz: '50 Hz 工频残余', line_ratio_60hz: '60 Hz 工频残余', drift_slope: '慢漂移斜率', drift_power_ratio: '漂移功率比', electrical_distance: '电气距离', reference_nrmse: '相对参考归一化误差', erds_mu: 'μ 频带 ERD/ERS', erds_beta: 'β 频带 ERD/ERS', psd: '功率谱', psd_window_quantiles: '窗口功率谱分位数', oha: '超幅比例', thv: '跨通道波动超阈比例', chv: '通道时间波动超阈比例', effective_rank: '有效秩', numerical_rank: '数值秩', flat_fraction: '平坦比例', line_noise_ratio: '工频残余比例', drift_ratio: '慢漂移比例', high_frequency_ratio: '高频功率比例', paired_nrmse: '残余污染归一化误差', reconstruction_nrmse: '相对原信号的重建误差', clean_retention_nrmse: '清理对原信号的改变', clean_retention_rms_ratio: '原信号幅度保留比', clean_retention_correlation: '原信号保留相关性', paired_ser_improvement_db: '污染抑制改善（dB）', reconstruction_ser_improvement_db: '重建误差改善（dB）' }
const qualityRows = computed(() => Object.entries(fullQuality.value?.stages?.[stage.value] ?? (stage.value === 'processed_task' ? quality.value?.metrics : undefined) ?? {}).filter(([key]) => `${key} ${labels[key] ?? ''}`.toLowerCase().includes(query.value.toLowerCase())))
const caseRows = computed(() => Object.entries(reconstruction.value?.by_case ?? {}) as [string, any][])
const reconstructionMetric = ref('paired_nrmse')
const reconstructionMetrics = computed(() => Object.keys(caseRows.value[0]?.[1]?.metrics ?? {}))
function value(v: unknown) { return typeof v === 'number' && Number.isFinite(v) ? v.toLocaleString('zh-CN', { maximumSignificantDigits: 5 }) : v == null ? '—' : Array.isArray(v) ? `曲线 / 数组 · ${v.length} 项` : String(v) }
function percent(v: unknown) { return typeof v === 'number' ? `${(v * 100).toFixed(2)}%` : '—' }
function status(v: string) { return ({ evaluated: '已评价', complete: '完整', partial: '部分可用', incomplete: '未完整', failed: '失败', not_applicable: '不适用', not_computable: '无法计算', not_assigned: '未分配', ok: '已计算' } as Record<string, string>)[v] ?? v }
function link(ref: any) { return ref?.path && props.basePath ? searchArtifactUrl(props.searchId, { name: `candidates/${props.candidateId}/${props.basePath}/${ref.path}` }) : undefined }
function direction(v: unknown) { return ({ non_monotonic: '没有统一的越高或越低越好', lower_is_better: '越低越好（在适用条件内）', higher_is_better: '越高越好（在适用条件内）' } as Record<string, string>)[String(v)] || '结合适用条件与测量定义解读' }
function record(v: unknown): any { return v && typeof v === 'object' ? v : {} }
const seedSeries = computed<Series[]>(() => [{ name: 'EEGNet 种子', connect: false, points: Object.entries(fullUtility.value?.learners?.eegnet?.seeds ?? {}).map(([seed, run], i) => ({ x: i+1, y: numeric(run.summary?.[metric.value]?.mean), label: `seed ${seed} · ${run.status}` })) }])
const learnerSeries = computed<Series[]>(() => {
  const learners = Object.entries(fullUtility.value?.learners ?? {})
  const ids = [...new Set(learners.flatMap(([, output]) => Object.keys(output.subjects ?? {})))].sort()
  return learners.map(([name, output]) => ({ name: models.value[name as keyof typeof models.value] || name, connect: false, points: ids.map((id, i) => ({ x: i+1, y: numeric(output.subjects?.[id]?.[metric.value]), label: id })) }))
})
const reconstructionSeries = computed<Series[]>(() => [{ name: '污染条件', connect: false, points: caseRows.value.map(([id, row]) => ({ x: numeric(row.metrics?.clean_retention_nrmse?.value) ?? NaN, y: numeric(row.metrics?.paired_nrmse?.value), label: `${id} · 残余 ${row.metrics?.paired_nrmse?.n_valid ?? 0}/${row.metrics?.paired_nrmse?.n_total ?? 0} · 保留 ${row.metrics?.clean_retention_nrmse?.n_valid ?? 0}/${row.metrics?.clean_retention_nrmse?.n_total ?? 0}` })) }])
const reconstructionProvenance = computed(() => ({ search_id: props.searchId, candidate_id: props.candidateId, path: props.basePath, cases: reconstruction.value?.by_case }))
</script>

<template>
  <div v-if="data" class="assessment">
    <div class="summary"><div><span>策略选择分数</span><strong>{{ percent(data.selection_score) }}</strong><small>{{ isV2 ? 'EEGNet · 三种子 × 被试等权 · 开发结果' : '历史 v1 · 三个模型 × 被试等权 · 开发结果' }}</small></div><div><span>评价范围</span><strong>{{ data.coverage?.subjects_expected }} <small>被试</small></strong><small>{{ data.coverage?.records_expected }} 条记录 · {{ data.coverage?.eligible_trials }} 个合格试次</small></div><div><span>评价状态</span><strong class="state">{{ status(data.status) }}</strong><small>覆盖与缺失见各项指标</small></div></div>
    <div v-if="initialAxis === 'parameters'" class="parameter-entry"><h3>配方参数与实际执行</h3><p class="note">各步骤的执行情况、处理参数与训练配置。</p><slot name="parameters" /></div>
    <nav aria-label="评价维度"><button v-for="(name, key) in { utility: '训练效用', quality: '信号质量', reconstruction: '重建实验' }" :key="key" :aria-pressed="axis === key" @click="axis = key">{{ name }}</button></nav>
    <section v-if="axis === 'utility'">
      <div class="tools"><label>查看指标 <select v-model="metric"><option v-for="(name, key) in statistics" :key="key" :value="key">{{ name }}</option></select></label><a v-if="link(utility?.receipt_artifact)" :href="link(utility.receipt_artifact)" target="_blank" rel="noopener">完整模型、逐被试与预测记录 ↗</a></div>
      <p class="note">{{ isV2 ? 'EEGNet 三个种子（17、42、2026）全部完成才产生选择分数；CSP-LDA 仅为基准对照。被试指标为三种子均值，n_trials 仍为 N；预测分母为 3×N。' : '历史 v1：三个主模型全部完成才产生选择分数。' }}下四分位与离散程度描述被试差异；Brier 和对数损失越低越好。开发得分经过反复选择，尚未经独立确认。</p>
      <div v-if="isV2">
        <p>主模型完整数 {{ utility?.primary_models_available ?? '—' }} / {{ utility?.primary_models_expected ?? '—' }} · 三种子预测覆盖 {{ utility?.primary_trial_predictions_available ?? '—' }} / {{ utility?.primary_trial_predictions_expected ?? '—' }}</p>
        <p>种子 BA 均值 {{ percent(seedSummary?.mean_ba) }} · 种子 SD {{ value(seedSummary?.seed_sd) }} · 最低 / 最高 BA {{ percent(seedSummary?.minimum_ba) }} / {{ percent(seedSummary?.maximum_ba) }} · 种子 {{ seedSummary?.seeds?.join('、') ?? '—' }}</p>
        <button :disabled="utilityLoading || !utility?.receipt_artifact || !basePath" @click="loadUtility">{{ utilityLoading ? '正在读取种子明细…' : '读取逐种子指标与来源' }}</button>
        <p v-if="utilityError" role="alert">{{ utilityError }} · 可重试读取</p>
        <div v-for="(output, seed) in fullUtility?.learners?.eegnet?.seeds" :key="seed">
          <p>种子 {{ seed }} · {{ status(output.status) }} · {{ statistics[metric] }} 被试均值 {{ value(output.summary?.[metric]?.mean) }} · 被试 Q25 {{ value(output.summary?.[metric]?.lower_quartile) }} · 被试 SD {{ value(output.summary?.[metric]?.subject_sd) }}</p>
          <details><summary>种子 {{ seed }} 的模型、预测与来源</summary><pre>{{ JSON.stringify(output, null, 2) }}</pre></details>
        </div>
      </div>
      <div class="scroll"><table><thead><tr><th>模型</th><th>用途 / 状态</th><th>被试均值</th><th>下四分位</th><th>被试标准差</th><th>覆盖被试</th></tr></thead><tbody><tr v-for="(name, key) in models" :key="key"><td>{{ name }}</td><td>{{ utility?.primary_suite?.includes(key) ? '主模型' : '对照' }} · {{ status(utility?.learner_statuses?.[key]) }}</td><td>{{ value(utility?.learner_statistics?.[key]?.[metric]?.mean) }}</td><td>{{ value(utility?.learner_statistics?.[key]?.[metric]?.lower_quartile) }}</td><td>{{ value(utility?.learner_statistics?.[key]?.[metric]?.subject_sd) }}</td><td>{{ utility?.learner_coverage?.[key]?.subjects_available }} / {{ utility?.learner_coverage?.[key]?.subjects_expected }}</td></tr></tbody></table></div>
      <button v-if="!isV2 && !fullUtility && utility?.receipt_artifact" :disabled="utilityLoading" @click="loadUtility">读取模型与被试图表</button>
      <AssessmentPlot v-if="isV2 && fullUtility" title="逐种子表现" :series="seedSeries" x-label="种子序号（17、42、2026，非连续自变量）" :y-label="statistics[metric] || metric" caption="每点为一个种子的被试宏平均；种子离散度不是被试差异或置信区间。缺失种子不产生完整主分数。" :y-domain="['ba','accuracy','f1','auc','brier'].includes(metric) ? [0,1] : undefined" :reference="metric === 'ba' ? .5 : undefined" />
      <AssessmentPlot v-if="fullUtility" title="逐被试模型表现" :provenance="{ searchId, candidateId, basePath, artifact: utility?.receipt_artifact, metric }" :series="learnerSeries" x-label="被试序号（完整 ID 见点标签）" :y-label="statistics[metric] || metric" :caption="(isV2 ? '每点为一个被试的结果；EEGNet 为三个种子的均值。' : '每点为一个被试的结果，模型按该运行的评价协议显示。') + (metric === 'ba' ? '虚线表示 BA=0.5，仅供参考。' : '') + '此图展示个体差异，不含置信区间。'" :y-domain="['ba','accuracy','f1','auc','brier'].includes(metric) ? [0,1] : undefined" :reference="metric === 'ba' ? .5 : undefined" />
      <p v-for="reason in utility?.failure_reasons" :key="reason" class="reason">{{ reason }}</p>
    </section>
    <section v-else-if="axis === 'quality'">
      <div class="tools"><label v-if="!showQualityPlots">信号阶段 <select v-model="stage"><option v-for="(name, key) in stages" :key="key" :value="key">{{ name }}</option></select></label><input v-model="query" aria-label="搜索质量指标" placeholder="查找指标" /><a v-if="link(data.quality?.receipt_artifact)" :href="link(data.quality.receipt_artifact)" target="_blank" rel="noopener">逐记录与完整曲线 ↗</a></div>
      <p class="note">幅度或高频功率降低不一定意味着质量提高。比较阶段前，请核对参考、通带与单位；EA 后的无量纲数据不能按电压解读。</p>
      <p v-if="!quality" class="reason">{{ data.quality?.reason }}</p>
      <p v-if="qualityLoading" class="note">正在读取该阶段的完整记录…</p><p v-if="qualityError" class="reason">{{ qualityError }}</p>
      <button v-if="basePath && data.quality?.receipt_artifact?.path" :aria-pressed="showQualityPlots" @click="showQualityPlots = !showQualityPlots">{{ showQualityPlots ? '收起信号图表' : '打开信号图表与实际参数' }}</button>
      <QualityPlots v-model:stage="stage" v-if="showQualityPlots && basePath" :search-id="searchId" :candidate-id="candidateId" :base-path="basePath" :receipt-path="data.quality.receipt_artifact.path" />
      <div v-if="quality" class="scroll"><table><thead><tr><th>指标</th><th>观测值</th><th>单位</th><th>状态 / 明细</th></tr></thead><tbody><tr v-for="[key, row] in qualityRows" :key="key"><td>{{ labels[key] ?? key }}<small v-if="labels[key]">{{ key }}</small></td><td>{{ value(record(row).value) }}</td><td>{{ record(row).unit }}</td><td>{{ status(record(row).status) }}<details class="metric-reading"><summary>覆盖与解读</summary><p><strong>覆盖被试：</strong>{{ record(row).denominator?.available_subjects ?? '未记录' }} / {{ record(row).denominator?.expected_subjects ?? '未记录' }}</p><p><strong>如何比较：</strong>{{ direction(record(row).direction) }}</p><p v-if="record(row).formula"><strong>计算定义：</strong>{{ record(row).formula }}</p><p v-if="record(row).aggregation === 'equal_subjects_mean'"><strong>汇总方式：</strong>被试等权平均</p><p v-if="record(row).reason"><strong>状态原因：</strong>{{ record(row).reason }}</p><p>本项用于信号诊断，不参与主评分加权。解释时结合信号阶段、单位、参考方式与通带。</p><details><summary>原始测量记录</summary><pre>{{ JSON.stringify(row, null, 2) }}</pre></details></details></td></tr></tbody></table></div>
    </section>
    <section v-else>
      <div class="tools"><label>查看指标 <select v-model="reconstructionMetric"><option v-for="key in reconstructionMetrics" :key="key" :value="key">{{ labels[key] ?? key }}</option></select></label><a v-if="link(data.reconstruction?.receipt_artifact)" :href="link(data.reconstruction.receipt_artifact)" target="_blank" rel="noopener">污染配置、对照与逐被试结果 ↗</a></div>
      <p class="note">实际 EEG 作为参考代理，加入已知污染后重跑同一处理。同时看污染残余与原信号保留，防止把零输出或过度衰减评为成功。默认均衡分配十种条件，每名被试参加一种；分类评价仍使用全部记录。</p>
      <p v-if="!reconstruction" class="reason">{{ data.reconstruction?.reason }}</p>
      <AssessmentPlot v-if="reconstruction" title="污染残余与原信号改变" :series="reconstructionSeries" x-label="clean retention NRMSE（改变程度）" y-label="paired NRMSE（污染残余）" caption="每点对应一种污染条件的组均值。两轴的有效被试可能不同，人数见点标签；用于观察残余污染与信号改变，不用于配对推断或综合排名。" :provenance="reconstructionProvenance" />
      <template v-if="reconstruction"><p class="note">设计：{{ reconstruction.design === 'balanced' ? '全部被试均衡分配' : '全部条件交叉' }} · {{ reconstruction.subjects_expected }} 名被试 · {{ reconstruction.cases_expected }} 个预定个案</p><div class="scroll"><table><thead><tr><th>污染条件</th><th>观测值</th><th>有效 / 分配被试</th><th>状态</th></tr></thead><tbody><tr v-for="[key, row] in caseRows" :key="key"><td>{{ key }}</td><td>{{ value(row.metrics?.[reconstructionMetric]?.value) }}</td><td>{{ row.metrics?.[reconstructionMetric]?.n_valid }} / {{ row.metrics?.[reconstructionMetric]?.n_total }}</td><td>{{ status(row.metrics?.[reconstructionMetric]?.status) }}</td></tr></tbody></table></div></template>
    </section>
    <slot v-if="initialAxis !== 'parameters'" name="parameters" />
    <SearchInterpretation :search-id="searchId" :frozen="guideFrozen" />
  </div>
  <div v-else><p class="empty">该候选暂无多维评价结果。运行参数与已有记录仍可查看。</p><slot name="parameters" /><SearchInterpretation :search-id="searchId" :frozen="guideFrozen" /></div>
</template>

<style scoped>
.assessment{color:#243d43}.summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-bottom:22px}.summary>div{padding:20px;background:#f5f8f9;border:1px solid #e3eeeb;border-radius:14px}.summary span,.summary small,td small{display:block;color:#627b7d;font-size:12px}.summary strong{display:block;font-size:29px;margin:7px 0;font-weight:600}.summary strong small{display:inline;font-size:14px}.summary .state{font-size:24px}nav{display:flex;gap:4px;padding:5px;background:#eef3f4;border-radius:10px;width:fit-content;max-width:100%;overflow:auto}nav button{white-space:nowrap;border-color:transparent;background:transparent}nav button[aria-pressed=true]{background:white;border-color:#dce5e7;box-shadow:0 1px 3px #163c3a0d}button,select,input{font:inherit;border:1px solid #d9e5e1;border-radius:8px;padding:8px 12px;background:white;color:inherit}button{cursor:pointer}button[aria-pressed=true]{background:#e5f3ee;border-color:#7eb3a4;color:#145d4d}.tools{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:20px 0 10px}.tools a{margin-left:auto;color:#247465;font-size:13px}.note{color:#627b7d;line-height:1.7;font-size:13px;max-width:1000px}.scroll{max-height:460px;overflow:auto;border:1px solid #e5ecea;border-radius:10px}table{min-width:600px;width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:13px 15px;border-bottom:1px solid #e8efec;vertical-align:top}th{position:sticky;top:0;background:#f7faf8;font-weight:500;z-index:1}pre{max-width:450px;max-height:230px;overflow:auto;white-space:pre-wrap;font-size:11px}summary{cursor:pointer;color:#357c6e;margin-top:5px}.reason{padding:12px;background:#fff8ed;color:#885c25;border-radius:8px;font-size:13px;overflow-wrap:anywhere}.empty{padding:35px;color:#697e7e}@media(max-width:760px){.summary{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.summary>div:first-child{grid-column:1/-1}.tools a{margin-left:0}.summary>div{padding:12px}.summary strong{font-size:24px}}
</style>
