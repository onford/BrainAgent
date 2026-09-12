<script setup lang="ts">
import { t, formatLocale } from '../i18n'
import { computed, provide, ref, watch } from 'vue'
import { comparisonScope } from '../utils/figureComparison'
import FigureComparisonPanel from './FigureComparisonPanel.vue'
import { searchArtifactUrl } from '../api/searches'
import type { SearchUtilityReceipt } from '../types/search'
import { apiRequest } from '../api/client'
import AssessmentPlot from './AssessmentPlot.vue'
import QualityPlots from './QualityPlots.vue'
import SearchInterpretation from './SearchInterpretation.vue'
import MetricReading from './MetricReading.vue'
import { numeric, type Series } from '../utils/assessmentPlots'

const props = defineProps<{ searchId: string; candidateId: string; basePath?: string | null; assessment?: Record<string, any> | null; guideFrozen?: boolean; initialAxis?: string; hideAxisNavigation?: boolean }>()
provide(comparisonScope, computed(() => props.searchId))
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
const legacyModels: Record<string, string> = { csp_lda: 'CSP + LDA', fbcsp: 'FBCSP', get ts_lr() { return t('Tangent space + logistic regression') }, fgmdm: 'FgMDM', get ea_fbcsp() { return t('Per-band EA + FBCSP') }, get logvar_lr() { return t('Log-variance + logistic regression') } }
const models = computed(() => isV2.value ? { eegnet: 'EEGNet', csp_lda: 'CSP + LDA' } : legacyModels)
const statistics: Record<string, string> = { get ba() { return t('Balanced accuracy (BA)') }, get accuracy() { return t('Accuracy') }, get f1() { return t('F1 (right hand positive)') }, kappa: 'Cohen κ', auc: 'ROC-AUC', get brier() { return t('Brier score') }, get logloss() { return t('Log loss') } }
const stages: Record<string, string> = { get processed_task() { return t('Processed task epochs') }, get source_task() { return t('Source task epochs') }, get source_raw() { return t('Source continuous data') }, get processed_continuous() { return t('Processed continuous data') }, get source_precue() { return t('Source pre-cue baseline') }, get processed_precue() { return t('Matched processed pre-cue baseline') } }
const labels: Record<string, string> = { get peak_to_peak() { return t('Peak-to-peak amplitude') }, get robust_dispersion() { return t('Robust signal dispersion') }, get channel_correlation() { return t('Channel correlation') }, get low_correlation_fraction() { return t('Low-correlation window fraction') }, get covariance_condition() { return t('Covariance condition number') }, get covariance_trace() { return t('Total variance') }, get participation_rank() { return t('Participation-ratio effective rank') }, get mu_mean_psd() { return t('Mean mu-band power') }, get beta_mean_psd() { return t('Mean beta-band power') }, get emg_hf_proxy() { return t('High-frequency EMG proxy') }, get line_ratio_50hz() { return t('50 Hz line-noise residual') }, get line_ratio_60hz() { return t('60 Hz line-noise residual') }, get drift_slope() { return t('Slow-drift slope') }, get drift_power_ratio() { return t('Drift power ratio') }, get electrical_distance() { return t('Electrical distance') }, get reference_nrmse() { return t('Normalized error relative to reference') }, get erds_mu() { return t('Mu-band ERD/ERS') }, get erds_beta() { return t('Beta-band ERD/ERS') }, get psd() { return t('Power spectrum') }, get psd_window_quantiles() { return t('Window PSD quantiles') }, get oha() { return t('Amplitude exceedance fraction') }, get thv() { return t('Across-channel variability exceedance fraction') }, get chv() { return t('Within-channel variability exceedance fraction') }, get effective_rank() { return t('Effective rank') }, get numerical_rank() { return t('Numerical rank') }, get flat_fraction() { return t('Flat-signal fraction') }, get line_noise_ratio() { return t('Line-noise residual ratio') }, get drift_ratio() { return t('Slow-drift ratio') }, get high_frequency_ratio() { return t('High-frequency power ratio') }, get paired_nrmse() { return t('Residual contamination NRMSE') }, get reconstruction_nrmse() { return t('Reconstruction error relative to original signal') }, get clean_retention_nrmse() { return t('Cleaning-induced change to original signal') }, get clean_retention_rms_ratio() { return t('Original-signal amplitude retention ratio') }, get clean_retention_correlation() { return t('Original-signal retention correlation') }, get paired_ser_improvement_db() { return t('Contamination suppression improvement (dB)') }, get reconstruction_ser_improvement_db() { return t('Reconstruction error improvement (dB)') } }
const allQualityRows = computed(() => Object.entries(fullQuality.value?.stages?.[stage.value] ?? (stage.value === 'processed_task' ? quality.value?.metrics : undefined) ?? {}))
const qualityRows = computed(() => allQualityRows.value.filter(([key]) => `${key} ${labels[key] ?? ''}`.toLowerCase().includes(query.value.toLowerCase())))
const unavailableQualityCount = computed(() => allQualityRows.value.filter(([, row]) => !['ok', 'complete', 'evaluated'].includes(record(row).status)).length)
const caseRows = computed(() => Object.entries(reconstruction.value?.by_case ?? {}) as [string, any][])
const reconstructionMetric = ref('paired_nrmse')
const reconstructionMetrics = computed(() => Object.keys(caseRows.value[0]?.[1]?.metrics ?? {}))
function value(v: unknown) { return typeof v === 'number' && Number.isFinite(v) ? v.toLocaleString(formatLocale.value, { maximumSignificantDigits: 5 }) : v == null ? '—' : Array.isArray(v) ? t('Curve / array · {0} items', { 0: v.length }) : String(v) }
function percent(v: unknown) { return typeof v === 'number' ? `${(v * 100).toFixed(2)}%` : '—' }
function status(v: string) { return ({ get evaluated() { return t('Evaluated') }, get complete() { return t('Complete') }, get partial() { return t('Partially available') }, get incomplete() { return t('Incomplete') }, get failed() { return t('Failed') }, get not_applicable() { return t('Not applicable') }, get not_computable() { return t('Not computable') }, get not_assigned() { return t('Not assigned') }, get ok() { return t('Computed') } } as Record<string, string>)[v] ?? v }
function link(ref: any) { return ref?.path && props.basePath ? searchArtifactUrl(props.searchId, { name: `candidates/${props.candidateId}/${props.basePath}/${ref.path}` }) : undefined }

function record(v: unknown): any { return v && typeof v === 'object' ? v : {} }
const seedSeries = computed<Series[]>(() => [{ id: 'eegnet', get name() { return t('EEGNet seeds') }, connect: false, points: [17, 42, 2026].map((seed, i) => ({ x: i+1, y: numeric(fullUtility.value?.learners?.eegnet?.seeds?.[String(seed)]?.summary?.[metric.value]?.mean), label: `seed ${seed}` })) }])
const learnerSeries = computed<Series[]>(() => {
  const learners = Object.entries(fullUtility.value?.learners ?? {}).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
  const ids = [...new Set(learners.flatMap(([, output]) => Object.keys(output.subjects ?? {})))].sort()
  return learners.map(([name, output]) => ({ id: name, name: models.value[name as keyof typeof models.value] || name, connect: false, points: ids.map((id, i) => ({ x: i+1, y: numeric(output.subjects?.[id]?.[metric.value]), label: id })) }))
})
const multipleUtilitySubjects = computed(() => new Set(learnerSeries.value.flatMap(s => s.points.filter(p => numeric(p.y) !== null).map(p => p.label))).size > 1)
const reconstructionSeries = computed<Series[]>(() => [{ id: reconstructionMetric.value, name: labels[reconstructionMetric.value] || reconstructionMetric.value, connect: false, points: caseRows.value.map(([id, row], i) => ({ x: i + 1, y: numeric(row.metrics?.[reconstructionMetric.value]?.value), label: id })) }])
const reconstructionProvenance = computed(() => ({ search_id: props.searchId, candidate_id: props.candidateId, path: props.basePath, cases: reconstruction.value?.by_case }))
</script>

<template>
  <div v-if="data" class="assessment">
    <div class="summary"><div><span>{{ t('Selection score') }}</span><strong>{{ percent(data.selection_score) }}</strong><small>{{ isV2 ? t('EEGNet · Three seeds, equal subject weights · Development') : t('Legacy v1 · Three models, equal subject weights · Development') }}</small></div><div><span>{{ t('Evaluation scope') }}</span><strong>{{ data.coverage?.subjects_expected }} <small>{{ t('Subjects') }}</small></strong><small>{{ t('{0} records · {1} eligible trials', { 0: data.coverage?.records_expected, 1: data.coverage?.eligible_trials }) }}</small></div><div><span>{{ t('Evaluation completeness') }}</span><strong class="state">{{ status(data.status) }}</strong><small>{{ t('Complete means evaluated, not that all metrics passed.') }}</small></div></div>
    <div v-if="initialAxis === 'parameters'" class="parameter-entry"><h3>{{ t('Recipe parameters and execution') }}</h3><p class="note">{{ t('Step execution, preprocessing parameters, and training configuration.') }}</p><slot name="parameters" /></div>
    <FigureComparisonPanel />
    <nav v-if="!hideAxisNavigation" :aria-label="t('Evaluation dimensions')"><button v-for="(name, key) in { utility: t('Training utility'), quality: t('Signal quality'), reconstruction: t('Reconstruction experiments') }" :key="key" :aria-pressed="axis === key" @click="axis = key">{{ name }}</button></nav>
    <section v-if="axis === 'utility'">
      <div class="tools"><label>{{ t('Metric') }}<select v-model="metric"><option v-for="(name, key) in statistics" :key="key" :value="key">{{ name }}</option></select></label><a v-if="link(utility?.receipt_artifact)" :href="link(utility.receipt_artifact)" target="_blank" rel="noopener">{{ t('Full model, subject, and prediction records ↗') }}</a></div>
      <p class="note essential">{{ t('Development scores need independent confirmation. Read performance together with coverage.') }}</p>
      <details class="reading-note"><summary>{{ t('How scoring and variability are calculated') }}</summary><p class="note">{{ t('{0} The lower quartile and dispersion describe subject variability. Lower Brier score and log loss are better. Repeatedly selected development scores require independent confirmation.', { 0: isV2 ? t('All three EEGNet seeds (17, 42, 2026) must complete before a selection score is available. CSP-LDA is a benchmark only. Subject metrics average the three seeds; n_trials remains N and the prediction denominator is 3×N.') : t('Legacy v1: all three primary models must complete before a selection score is available.') }) }}</p></details>
      <div v-if="isV2">
        <p>{{ t('Complete primary models: {0} / {1} · Three-seed prediction coverage: {2} / {3}', { 0: utility?.primary_models_available ?? '—', 1: utility?.primary_models_expected ?? '—', 2: utility?.primary_trial_predictions_available ?? '—', 3: utility?.primary_trial_predictions_expected ?? '—' }) }}</p>
        <details class="reading-note"><summary>{{ t('Seed summary · Mean, spread and range') }}</summary><p>{{ t('Seed BA mean: {0} · Seed SD: {1} · Min / max BA: {2} / {3} · Seeds: {4}', { 0: percent(seedSummary?.mean_ba), 1: value(seedSummary?.seed_sd), 2: percent(seedSummary?.minimum_ba), 3: percent(seedSummary?.maximum_ba), 4: seedSummary?.seeds?.join('、') ?? '—' }) }}</p></details>
        <button :disabled="utilityLoading || !utility?.receipt_artifact || !basePath" @click="loadUtility">{{ utilityLoading ? t('Loading seed details…') : t('Load per-seed metrics and provenance') }}</button>
        <p v-if="utilityError" role="alert">{{ t('{0} · Loading can be retried', { 0: utilityError }) }}</p>
        <details v-if="fullUtility" class="reading-note"><summary>{{ t('Per-seed statistics and source files') }}</summary>
        <div v-for="(output, seed) in fullUtility?.learners?.eegnet?.seeds" :key="seed">
          <p>{{ t('Seed {0} · {1} · {2} subject mean: {3} · Subject Q25: {4} · Subject SD: {5}', { 0: seed, 1: status(output.status), 2: statistics[metric], 3: value(output.summary?.[metric]?.mean), 4: value(output.summary?.[metric]?.lower_quartile), 5: value(output.summary?.[metric]?.subject_sd) }) }}</p>
          <details><summary>{{ t('Seed {0}: model, predictions, and provenance', { 0: seed }) }}</summary><pre>{{ JSON.stringify(output, null, 2) }}</pre></details>
        </div>
        </details>
      </div>
      <div class="scroll"><table><thead><tr><th>{{ t('Model') }}</th><th>{{ t('Role / status') }}</th><th>{{ t('Subject mean') }}</th><th>{{ t('Lower quartile') }}</th><th>{{ t('Subject standard deviation') }}</th><th>{{ t('Subject coverage') }}</th></tr></thead><tbody><tr v-for="(name, key) in models" :key="key"><td>{{ name }}</td><td>{{ utility?.primary_suite?.includes(key) ? t('Primary model') : t('Benchmark') }} · {{ status(utility?.learner_statuses?.[key]) }}</td><td>{{ value(utility?.learner_statistics?.[key]?.[metric]?.mean) }}</td><td>{{ value(utility?.learner_statistics?.[key]?.[metric]?.lower_quartile) }}</td><td>{{ value(utility?.learner_statistics?.[key]?.[metric]?.subject_sd) }}</td><td>{{ utility?.learner_coverage?.[key]?.subjects_available }} / {{ utility?.learner_coverage?.[key]?.subjects_expected }}</td></tr></tbody></table></div>
      <button v-if="!isV2 && !fullUtility && utility?.receipt_artifact" :disabled="utilityLoading" @click="loadUtility">{{ t('Load model and subject plots') }}</button>
      <AssessmentPlot :comparison-key="`utility:${metric}:seeds`" :comparison-label="t('Performance by seed') + ' · ' + (statistics[metric] || metric)" :provenance="{ search_id: searchId, candidate_id: candidateId, assessment_path: basePath, artifact: utility?.receipt_artifact, metric }" v-if="isV2 && fullUtility" :title="t('Performance by seed')" categorical :series="seedSeries" :x-label="t('Seed index (17, 42, 2026; categorical)')" :y-label="statistics[metric] || metric" :caption="t('Each point is one seed\'s subject-macro average. Seed dispersion is neither subject variability nor a confidence interval. Missing seeds prevent a complete primary score.')" :y-domain="['ba','accuracy','f1','auc','brier'].includes(metric) ? [0,1] : undefined" :reference="metric === 'ba' ? .5 : undefined" />
      <AssessmentPlot :comparison-key="`utility:${metric}:subjects`" :comparison-label="t('Model performance by subject') + ' · ' + (statistics[metric] || metric)" v-if="fullUtility && multipleUtilitySubjects" :title="t('Model performance by subject')" :provenance="{ searchId, candidateId, basePath, artifact: utility?.receipt_artifact, metric }" categorical :series="learnerSeries" :x-label="t('Subject index (full IDs in point labels)')" :y-label="statistics[metric] || metric" :caption="(isV2 ? t('Each point is a subject result. EEGNet averages the three seeds.') : t('Each point is a subject result. Models follow this run\'s evaluation protocol.')) + (metric === 'ba' ? t('The dashed BA=0.5 line is a reference only.') : '') + t('This plot shows subject variability, without confidence intervals.')" :y-domain="['ba','accuracy','f1','auc','brier'].includes(metric) ? [0,1] : undefined" :reference="metric === 'ba' ? .5 : undefined" />
      <p v-for="reason in utility?.failure_reasons" :key="reason" class="reason">{{ reason }}</p>
    </section>
    <section v-else-if="axis === 'quality'">
      <div class="tools quality-actions"><p class="note essential">{{ t('Lower amplitude alone does not mean better signal quality. Match reference, passband and units when comparing.') }}</p><label v-if="!showQualityPlots">{{ t('Signal stage') }}<select v-model="stage"><option v-for="(name, key) in stages" :key="key" :value="key">{{ name }}</option></select></label><button v-if="basePath && data.quality?.receipt_artifact?.path" :aria-pressed="showQualityPlots" @click="showQualityPlots = !showQualityPlots">{{ showQualityPlots ? t('Hide signal plots') : t('Open signal plots and parameters') }}</button></div>
      <details class="reading-note"><summary>{{ t('Stage comparison and EA units') }}</summary><p class="note">{{ t('Lower amplitude or high-frequency power does not necessarily mean higher quality. Check reference, passband, and units before comparing stages. Dimensionless data after EA cannot be interpreted as voltage.') }}</p></details>
      <p v-if="!quality" class="reason">{{ data.quality?.reason }}</p>
      <p v-if="qualityLoading" class="note">{{ t('Loading complete records for this stage…') }}</p><p v-if="qualityError" class="reason">{{ qualityError }}</p>
      <QualityPlots v-model:stage="stage" v-if="showQualityPlots && basePath" :search-id="searchId" :candidate-id="candidateId" :base-path="basePath" :receipt-path="data.quality.receipt_artifact.path" />
      <details v-if="quality" class="metric-directory" :open="!showQualityPlots">
        <summary>{{ t('All metrics and interpretations') }} <span>{{ t('{0} metrics · {1} with limited or unavailable results', { 0: allQualityRows.length, 1: unavailableQualityCount }) }}</span></summary>
        <div class="tools"><input v-model="query" type="search" :aria-label="t('Search quality metrics')" :placeholder="t('Find a metric')" /><a v-if="link(data.quality?.receipt_artifact)" :href="link(data.quality.receipt_artifact)" target="_blank" rel="noopener">{{ t('Per-record data and full curves ↗') }}</a></div>
        <p class="note">{{ t('Table values summarize subjects at the selected stage; selecting a record above only changes the plots.') }}</p>
        <p v-if="!qualityRows.length && !qualityLoading" role="status">{{ t('No matching metrics.') }}</p>
      <div class="scroll"><table><thead><tr><th>{{ t('Metric name') }}</th><th>{{ t('Observed value') }}</th><th>{{ t('Unit') }}</th><th>{{ t('Status / detail') }}</th></tr></thead><tbody><tr v-for="[key, row] in qualityRows" :key="key"><td>{{ labels[key] ?? key }}<small v-if="labels[key]">{{ key }}</small></td><td>{{ value(record(row).value) }}</td><td>{{ record(row).unit }}</td><td>{{ status(record(row).status) }}<small v-if="record(row).reason" class="measurement-reason">{{ record(row).reason }}</small><MetricReading :search-id="searchId" :candidate-id="candidateId" :stage="stage" :metric-id="key" :row="record(row)" /></td></tr></tbody></table></div>
      </details>
    </section>
    <section v-else>
      <div class="tools"><label>{{ t('Metric') }}<select v-model="reconstructionMetric"><option v-for="key in reconstructionMetrics" :key="key" :value="key">{{ labels[key] ?? key }}</option></select></label><a v-if="link(data.reconstruction?.receipt_artifact)" :href="link(data.reconstruction.receipt_artifact)" target="_blank" rel="noopener">{{ t('Contamination settings, controls, and subject results ↗') }}</a></div>
      <p class="note essential">{{ t('Check contamination removal and original-signal retention together. Conditions may use different subjects.') }}</p>
      <details class="reading-note"><summary>{{ t('How the reconstruction experiment is designed') }}</summary><p class="note">{{ t('Real EEG serves as a reference proxy. The same pipeline is rerun after adding known contamination. Residual contamination and original-signal retention are evaluated together to avoid rewarding zero output or excessive attenuation. By default, ten conditions are allocated evenly, one per subject; classification still uses all records.') }}</p></details>
      <p v-if="!reconstruction" class="reason">{{ data.reconstruction?.reason }}</p>
      <AssessmentPlot :comparison-key="`reconstruction:${reconstructionMetric}:conditions`" :comparison-label="t('Reconstruction metric by condition') + ' · ' + (labels[reconstructionMetric] || reconstructionMetric)" v-if="reconstruction" :title="t('Reconstruction metric by condition')" categorical :series="reconstructionSeries" :x-label="t('Contamination conditions')" :y-label="labels[reconstructionMetric] || reconstructionMetric" :caption="t('One point per assigned condition. Missing conditions keep their position. Conditions can use different subjects; this is a descriptive comparison, not paired inference.')" :provenance="{ ...reconstructionProvenance, metric: reconstructionMetric }" />
      <template v-if="reconstruction"><p class="note">{{ t('Design: {0} · {1} subjects · {2} planned cases', { 0: reconstruction.design === 'balanced' ? t('Balanced allocation across all subjects') : t('Full crossing of conditions'), 1: reconstruction.subjects_expected, 2: reconstruction.cases_expected }) }}</p><div class="scroll"><table><thead><tr><th>{{ t('Contamination conditions') }}</th><th>{{ t('Observed value') }}</th><th>{{ t('Valid / assigned subjects') }}</th><th>{{ t('Status') }}</th></tr></thead><tbody><tr v-for="[key, row] in caseRows" :key="key"><td>{{ key }}</td><td>{{ value(row.metrics?.[reconstructionMetric]?.value) }}</td><td>{{ row.metrics?.[reconstructionMetric]?.n_valid }} / {{ row.metrics?.[reconstructionMetric]?.n_total }}</td><td>{{ status(row.metrics?.[reconstructionMetric]?.status) }}</td></tr></tbody></table></div></template>
    </section>
    <slot v-if="initialAxis !== 'parameters'" name="parameters" />
    <SearchInterpretation :search-id="searchId" :frozen="guideFrozen" />
  </div>
  <div v-else><p class="empty">{{ t('No multidimensional evaluation is available for this candidate. Parameters and existing records remain accessible.') }}</p><slot name="parameters" /><SearchInterpretation :search-id="searchId" :frozen="guideFrozen" /></div>
</template>

<style scoped>
.assessment{color:#243d43}.summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-bottom:22px}.summary>div{padding:14px 16px;background:#f5f8f9;border:1px solid #e3eeeb;border-radius:14px}.summary span,.summary small,td small{display:block;color:#627b7d;font-size:12px}.summary strong{display:block;font-size:25px;margin:7px 0;font-weight:600}.summary strong small{display:inline;font-size:14px}.summary .state{font-size:24px}nav{display:flex;gap:4px;padding:5px;background:#eef3f4;border-radius:10px;width:fit-content;max-width:100%;overflow:auto}nav button{white-space:nowrap;border-color:transparent;background:transparent}nav button[aria-pressed=true]{background:white;border-color:#dce5e7;box-shadow:0 1px 3px #163c3a0d}button,select,input{font:inherit;border:1px solid #d9e5e1;border-radius:8px;padding:8px 12px;background:white;color:inherit}button{cursor:pointer}button[aria-pressed=true]{background:#e5f3ee;border-color:#7eb3a4;color:#145d4d}.tools{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:20px 0 10px}.tools a{margin-left:auto;color:#247465;font-size:13px}.note{color:#627b7d;line-height:1.7;font-size:13px;max-width:1000px}.scroll{max-height:460px;overflow:auto;border:1px solid #e5ecea;border-radius:10px}table{min-width:600px;width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:13px 15px;border-bottom:1px solid #e8efec;vertical-align:top}th{position:sticky;top:0;background:#f7faf8;font-weight:500;z-index:1}pre{max-width:450px;max-height:230px;overflow:auto;white-space:pre-wrap;font-size:11px}summary{cursor:pointer;color:#357c6e;margin-top:5px}.reason{padding:12px;background:#fff8ed;color:#885c25;border-radius:8px;font-size:13px;overflow-wrap:anywhere}.empty{padding:35px;color:#697e7e}@media(max-width:760px){.summary{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.summary>div:first-child{grid-column:1/-1}.tools a{margin-left:0}.summary>div{padding:12px}.summary strong{font-size:24px}}
.reading-note { margin: 8px 0 14px; font-size: 12px; line-height: 1.75; }
.reading-note > summary { color: #59756d; }
.essential { margin: 8px 0; color: #425e55; }
.metric-directory { margin: 20px 0; padding: 15px; border: 1px solid #dce5e7; border-radius: 10px; }
.metric-directory > summary { font-size: 14px; font-weight: 600; }
.metric-directory > summary span { display: inline-block; margin-left: 10px; font-size: 12px; font-weight: 400; color: #627b7d; }
.metric-directory input { width: min(300px, 100%); }
.measurement-reason { max-width: 440px; overflow-wrap: anywhere; margin-top: 5px; }
.quality-actions { margin: 14px 0 8px; justify-content: space-between; gap: 8px; }
.quality-actions .essential { flex: 1 1 440px; margin: 0; }
</style>
