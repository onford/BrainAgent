<script setup lang="ts">
import LanguageSwitcher from '../components/LanguageSwitcher.vue'
import { t, formatLocale } from '../i18n'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import SearchDecisionOverview from '../components/SearchDecisionOverview.vue'
import SearchMethodExplorer from '../components/SearchMethodExplorer.vue'
import SearchAssessment from '../components/SearchAssessment.vue'
import SearchParameters from '../components/SearchParameters.vue'
import '../styles/search-assessment.css'
import SearchOperatorUsage from '../components/SearchOperatorUsage.vue'
import { cancelSearch, createSearch, fetchSearch, fetchSearches, retrySearch, searchArtifactUrl } from '../api/searches'
import type { SearchAdaptation, SearchBudget, SearchRequest, SearchState, SearchStrategy, SearchSubject, SearchSummary } from '../types/search'

const route = useRoute(), router = useRouter()
const searches = ref<SearchSummary[]>([]), current = ref<SearchState | null>(null)
const loading = ref(false), listLoading = ref(false), busy = ref(false)
const error = ref(''), listError = ref('')
const tab = ref('overview'), inspectedId = ref(''), reportName = ref('')
const artifactQuery = ref('')
const artifactOpened = ref<Record<string, boolean>>({}), artifactPages = ref<Record<string, number>>({})
const artifactPageSize = 30
const artifactsLoading = ref(false), artifactRetries = ref(0)
const maxArtifactRetries = 10
const workflowId = ref(''), strategy = ref<SearchStrategy>('adaptive'), seed = ref(42)
const trainSubjects = ref(''), developmentSubjects = ref('')
const formBudget = reactive({ max_candidates: 48, max_proposals: 128, max_evidence_reads: 32, max_seconds: 86400, max_memory_mb: '' as number | string, max_disk_mb: '' as number | string })
const statuses: Record<string, string> = { get preparing() { return t('Preparing') }, get running() { return t('Running') }, get completed() { return t('Completed') }, get stopped() { return t('Stopped') }, get failed() { return t('Failed') }, get cancelled() { return t('Cancelled') }, get interrupted() { return t('Awaiting recovery') }, get pending() { return t('Awaiting execution') }, get queued() { return t('In queue') }, get proposed() { return t('Proposed') }, get evaluating() { return t('Under evaluation') }, get evaluated() { return t('Evaluation complete') }, get reserved() { return t('Awaiting execution') }, get execution_failure() { return t('Execution failed') }, get resource_failure() { return t('Insufficient resources') }, get candidate_invalid() { return t('Invalid candidate') }, get data_unevaluable() { return t('Data cannot be evaluated') }, get rejected() { return t('Rejected') }, get skipped() { return t('Skipped') }, get succeeded() { return t('Succeeded') } }
const phases: Record<string, string> = { get freeze_panel() { return t('Freeze development panel') }, get candidate() { return t('Evaluate candidate') }, get decision() { return t('Choose next action') }, get finished() { return t('Search ended') } }
const actionLabels: Record<string, string> = { get initial_schedule() { return t('Create initial plan') }, get model_decision() { return t('Decide next step') }, get enumerate_remaining() { return t('Enumerate remaining candidates') }, get invalid_proposal() { return t('Invalid proposal') }, get finish() { return t('End search') }, get request_evidence() { return t('Additional evidence') }, get propose_candidate() { return t('Propose candidate') } }
const stopReasons: Record<string, string> = { get cancelled_by_user() { return t('Stopped by user') }, get service_interrupted() { return t('Service interrupted') }, get time_budget_exhausted() { return t('Time budget exhausted') }, get candidate_budget_exhausted() { return t('Candidate budget exhausted') }, get proposal_budget_exhausted() { return t('Proposal budget exhausted') }, get memory_budget_exhausted() { return t('Memory budget exhausted') }, get disk_budget_exhausted() { return t('Disk budget exhausted') }, get execution_conditions_unavailable() { return t('Execution requirements unavailable') }, get reference_failed() { return t('Baseline evaluation failed') }, get resource_unavailable() { return t('Execution resources unavailable') }, get catalog_exhausted() { return t('Candidate catalog exhausted') }, get schedule_exhausted() { return t('Plan completed') }, get model_finished() { return t('Model ended search') } }
const strategies: Record<SearchStrategy, string> = { get adaptive() { return t('Adaptive') }, get random() { return t('Random-order control') }, get exhaustive() { return t('Exhaustive') }, get one_shot() { return t('One-shot proposal control') } }
const assessmentAxis = ref('utility')
const resultsPanel = ref<HTMLElement>()
function navigateEvidence(view: string, candidateId?: string, axis = 'utility') {
  if (candidateId && candidates.value.some(c => c.id === candidateId)) inspectedId.value = candidateId
  assessmentAxis.value = axis
  tab.value = view
  void nextTick(() => resultsPanel.value?.scrollIntoView?.({ block: 'start' }))
}
const tabs = { get overview() { return t('Decision overview') }, get candidates() { return t('Candidate comparison') }, get methods() { return t('Search space') }, get assessment() { return t('Multidimensional evaluation') }, get rounds() { return t('Round timeline') }, get subjects() { return t('Development subjects') }, get artifacts() { return t('Reports / files') } }
const budgetFields = [
  { key: 'max_candidates', get label() { return t('Candidate count') }, min: 1, max: 256 },
  { key: 'max_proposals', get label() { return t('Proposal count') }, min: 0, max: 1024 },
  { key: 'max_evidence_reads', get label() { return t('Evidence reads') }, min: 0, max: 256 },
  { key: 'max_seconds', get label() { return t('Time limit (s)') }, min: 0, max: undefined },
] as const
const id = computed(() => typeof route.query.id === 'string' ? route.query.id : '')
const supportedSearch = computed(() => current.value?.schema_version === '1' && ['2', '3'].includes(current.value.protocol?.version ?? ''))
const active = computed(() => supportedSearch.value && current.value && ['preparing', 'running'].includes(current.value.status))
const terminalStatuses = new Set(['completed', 'stopped', 'failed', 'cancelled'])
const finishedCandidateStatuses = new Set(['evaluated', 'completed', 'candidate_invalid', 'data_unevaluable', 'execution_failure', 'resource_failure', 'failed', 'cancelled', 'skipped', 'rejected'])
const terminal = computed(() => !!current.value && terminalStatuses.has(current.value.status))
const canRetry = computed(() => supportedSearch.value && current.value && ['failed', 'interrupted', 'cancelled'].includes(current.value.status))
const candidates = computed(() => current.value?.candidates ?? [])
const actions = computed(() => (current.value?.actions ?? []).filter(action => action.action !== 'model_decision' || !['completed', 'succeeded'].includes(action.status)))
const panel = computed(() => typeof current.value?.panel === 'object' ? current.value?.panel : null)
const panelTrainCount = computed(() => Array.isArray(panel.value?.train_subjects) ? panel.value.train_subjects.length : undefined)
const panelDevelopmentCount = computed(() => Array.isArray(panel.value?.development_subjects) ? panel.value.development_subjects.length : undefined)
const inspected = computed(() => candidates.value.find(c => c.id === inspectedId.value) ?? candidates.value.find(c => c.id === current.value?.selected_candidate_id) ?? candidates.value[0])
const savedLearner = computed(() => inspected.value?.receipt?.primary_learner || (inspected.value?.receipt?.evaluator_version === 1 ? 'logvariance-scaler-logistic-v1' : current.value?.protocol?.evaluator))
const multiMetric = computed(() => String(current.value?.protocol?.version) === '3' || !!current.value?.protocol?.assessment)
const eegnetUtility = computed(() => current.value?.protocol?.assessment === 'assessment-v2' || (current.value?.protocol?.assessment as any)?.version === 2 || current.value?.protocol?.utility_version === 2 || current.value?.candidates?.some(c => c.receipt?.assessment?.schema_version === 'assessment-v2' || (c.receipt?.assessment?.utility as any)?.utility_version === 2))
const utilityLabel = computed(() => eegnetUtility.value ? t('Three-seed EEGNet training utility') : t('Legacy v1 three-model training utility'))
const cspEvaluation = computed(() => ['csp4_reg0.1_shrinkage_lda', 'csp-shrinkage-lda-v2'].includes(savedLearner.value ?? ''))
const evaluatorLabel = computed(() => cspEvaluation.value ? t('CSP + shrinkage LDA') : ['logvariance-scaler-logistic-v1', 'logvariance_standardizer_logistic_regression'].includes(savedLearner.value ?? '') ? t('Log-variance + scaling + logistic regression') : savedLearner.value || t('Recorded evaluator'))
const subjectRows = computed<SearchSubject[]>(() => {
  const rows = inspected.value?.receipt?.subjects
  if (!rows) return []
  return Array.isArray(rows) ? rows : Object.entries(rows).map(([subject, values]) => ({ ...values, subject }))
})
const signalRows = computed(() => Object.entries(inspected.value?.receipt?.diagnostics?.subjects ?? {}).map(([subject, values]) => ({ subject, ...values })))
const diagnosticSummary = computed(() => inspected.value?.receipt?.diagnostics?.summary)
const representation = computed(() => inspected.value?.receipt?.representation)
const adaptationRows = computed(() => Object.entries(representation.value?.subjects ?? {}).map(([subject, values]) => ({ subject, ...values })))
const diagnosticChannels = computed(() => representation.value?.channels ?? (Array.isArray(panel.value?.output_contract?.channels) ? panel.value.output_contract.channels as string[] : []))
const budget = computed(() => current.value?.budget ?? current.value?.request?.budget)
const displayedElapsed = computed(() => {
  const state = current.value, elapsed = state?.usage?.elapsed_seconds
  const deadline = state?.deadline, seconds = budget.value?.max_seconds
  if (!active.value || typeof deadline !== 'number' || !Number.isFinite(deadline) || typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds <= 0) return elapsed
  // A fresh lightweight state response invalidates this computation every two seconds.
  const reported = typeof elapsed === 'number' && Number.isFinite(elapsed) ? elapsed : 0
  return Math.max(reported, Date.now() / 1000 - (deadline - seconds), 0)
})
const displayedPhase = computed(() => {
  if (active.value && current.value?.request.strategy === 'one_shot' && current.value.actions?.some(action => action.action === 'initial_schedule' && action.status === 'running')) return t('Create initial plan')
  const state = current.value
  return state?.phase ? (phases[state.phase] ?? state.phase) : state ? label(state.status) : ''
})
const meters = computed(() => [
  { get label() { return t('Candidate') }, used: current.value?.usage?.candidates, limit: budget.value?.max_candidates },
  { get label() { return t('Proposal') }, used: current.value?.usage?.proposals, limit: budget.value?.max_proposals },
  { get label() { return t('Evidence read') }, used: current.value?.usage?.evidence_reads, limit: budget.value?.max_evidence_reads },
  { get label() { return t('Elapsed time (s)') }, used: displayedElapsed.value, limit: budget.value?.max_seconds },
])
const artifacts = computed(() => current.value?.artifacts ?? [])
const finalArtifactsReady = computed(() => {
  const names = new Set(artifacts.value.map(file => file.name))
  return names.has('report.html') && names.has('files.json')
})
type Artifact = NonNullable<SearchState['artifacts']>[number]
type ArtifactGroup = { key: string; title: string; path: string; files: Artifact[] }
const matchedArtifacts = computed(() => {
  const query = artifactQuery.value.trim().toLowerCase()
  return artifacts.value.filter(file => `${file.name} ${file.description ?? ''}`.toLowerCase().includes(query))
})
function artifactGroup(file: Artifact): Omit<ArtifactGroup, 'files'> {
  const parts = file.name.split('/')
  if (parts[0] === 'candidates' && parts.length > 2) {
    const candidate = candidates.value.find(item => item.id === parts[1])
    return { key: `candidates/${parts[1]}`, path: `candidates/${parts[1]}`, title: t('Candidate process · {0}', { 0: candidate?.title || parts[1] }) }
  }
  if (parts[0] === 'engine') {
    if (parts[1] === 'runs' && parts.length > 3) {
      const candidate = candidates.value.find(item => item.job_id === parts[2])
      return { key: `engine/runs/${parts[2]}`, path: `engine/runs/${parts[2]}`, title: t('Numerical execution · {0}', { 0: candidate?.title || candidate?.id || parts[2] }) }
    }
    const directory = parts.length > 2 ? parts[1] : ''
    const names: Record<string, string> = { get objects() { return t('Object snapshot') }, get inputs() { return t('Input snapshot') }, get methods() { return t('Method snapshot') }, get plans() { return t('Run plan') }, get jobs() { return t('Task record') }, get reports() { return t('Numerical report') } }
    return { key: directory ? `engine/${directory}` : 'engine', path: directory ? `engine/${directory}` : 'engine', title: t('Numerical file · {0}', { 0: names[directory] || directory || t('Execution metadata') }) }
  }
  return { key: 'core', path: '', get title() { return t('Core reports and records') } }
}
const artifactGroups = computed(() => {
  const groups = new Map<string, ArtifactGroup>()
  for (const file of matchedArtifacts.value) {
    const group = artifactGroup(file)
    const existing = groups.get(group.key)
    if (existing) existing.files.push(file)
    else groups.set(group.key, { ...group, files: [file] })
  }
  return [...groups.values()].sort((a, b) => a.key === 'core' ? -1 : b.key === 'core' ? 1 : a.key.localeCompare(b.key, 'en'))
})
function artifactGroupOpen(key: string) { return artifactOpened.value[key] ?? key === 'core' }
function artifactPageCount(group: ArtifactGroup) { return Math.max(1, Math.ceil(group.files.length / artifactPageSize)) }
function artifactPage(group: ArtifactGroup) { return Math.min(artifactPages.value[group.key] ?? 1, artifactPageCount(group)) }
function artifactPageFiles(group: ArtifactGroup) {
  const start = (artifactPage(group) - 1) * artifactPageSize
  return group.files.slice(start, start + artifactPageSize)
}
watch(artifactQuery, () => { artifactPages.value = {} })
const reports = computed(() => artifacts.value.filter(a => /\.(html?|pdf)$/i.test(a.name)))
const report = computed(() => reports.value.find(a => a.name === reportName.value) ?? reports.value[0])
let timer: ReturnType<typeof setTimeout> | undefined
let generation = 0, refreshSerial = 0, disposed = false
let pendingState: SearchState | null = null

function recipeSummary(id: string) {
  const entry = current.value?.registry?.find(e => e.id === id)
  return entry?.recipe.nodes.map(n => { const title = current.value?.protocol?.space?.operators.find(o => o.id === n.operator)?.title ?? n.operator; return n.operator === 'bandpass' ? `${title} ${n.parameters.l_freq}–${n.parameters.h_freq} Hz` : title }).join(' → ')
}
function label(status: string) { return statuses[status] ?? status }
function count(value: unknown) { return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString(formatLocale.value, { maximumFractionDigits: 1 }) : '—' }
function percent(value: unknown) { return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '—' }
function scientific(value: unknown) { return typeof value === 'number' && Number.isFinite(value) ? value.toExponential(2) : '—' }
function measurement(value: unknown) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  return value !== 0 && (Math.abs(value) < .001 || Math.abs(value) >= 1e6) ? value.toExponential(3) : value.toLocaleString(formatLocale.value, { maximumSignificantDigits: 6 })
}
function metricLabel(path: string): string {
  const labels: Record<string, string> = { 'assessment.selection_score': utilityLabel.value, get macro_ba() { return t('CSP anchor BA') }, get mean_delta() { return t('Mean difference from baseline') }, get secondary_macro_ba() { return t('Secondary benchmark BA') }, get 'diagnostics.floor_fraction'() { return t('Variance floor fraction') }, get covariance_condition() { return t('Covariance condition number') }, get covariance_condition_before() { return t('Pre-adaptation covariance condition number') }, get covariance_condition_after() { return t('Post-adaptation covariance condition number') }, get mean_channel_variance_before() { return t('Pre-adaptation mean channel variance') }, get mean_channel_variance_after() { return t('Post-adaptation mean channel variance') }, get covariance_anisotropy() { return t('Covariance condition number') }, get gate_metric_value() { return t('Gating ratio Q90/Q10') }, get gate_fraction() { return t('Trigger fraction') }, get gate_subject_count() { return t('Subjects evaluated by gate') }, get gate_passed_subject_count() { return t('Subjects triggering adaptation') }, get effective_rank_before() { return t('Pre-adaptation effective rank') }, get effective_rank_after() { return t('Post-adaptation effective rank') }, get mean_condition_before() { return t('Mean pre-adaptation condition number') }, get mean_condition_after() { return t('Mean post-adaptation condition number') }, get mean_variance_before() { return t('Mean pre-adaptation variance') }, get mean_variance_after() { return t('Mean post-adaptation variance') }, get mean_effective_rank() { return t('Mean pre-adaptation effective rank') }, get mean_anisotropy() { return t('Mean spectral Q90/Q10') }, get channel_variance() { return t('Channel variance') }, get channel_flat_fraction() { return t('Channel flat-signal fraction') }, get ba() { return t('Primary BA score') }, get delta() { return t('Difference from baseline') }, get recall_left() { return t('Left-hand recall') }, get recall_right() { return t('Right-hand recall') }, get predicted_trials() { return t('Predicted trials') }, get eligible_trials() { return t('Eligible trials') }, get fit_trials() { return t('Fitting trials') } }
  if (labels[path]) return labels[path]
  const parts = path.split('.'), subjectIndex = parts.indexOf('subjects')
  const field = parts.at(-1) ?? path
  return subjectIndex >= 0 && parts[subjectIndex + 1] ? `${parts[subjectIndex + 1]} · ${labels[field] ?? field}` : path.startsWith('diagnostics.summary.') ? t('Overall · {0}', { 0: labels[field] ?? field }) : labels[field] ?? path
}
function directionLabel(value: string) { return ({ get increase() { return t('Increase') }, get decrease() { return t('Decrease') }, get unchanged() { return t('Unchanged') } } as Record<string, string>)[value] ?? value }
function checkLabel(value: string) { return ({ get matched() { return t('Matches prediction') }, get contradicted() { return t('Contradicts prediction') }, get unavailable() { return t('Cannot verify') } } as Record<string, string>)[value] ?? value }
function branchLabel(key: string) { return ({ get improvement() { return t('If improved') }, get improved() { return t('If improved') }, get no_improvement() { return t('If not improved') }, get otherwise() { return t('Otherwise') } } as Record<string, string>)[key] ?? key }
function adaptationLabel(value: SearchAdaptation | 'scale_only') { return ({ get subject_scale() { return t('Uniform per-subject scaling') }, get scale_only() { return t('Rescale while preserving spatial structure') }, get none() { return t('none · No alignment') }, get euclidean_alignment() { return t('uniformEA · Per-subject Euclidean alignment') }, get conditional_alignment() { return t('conditionalEA · Diagnosis-conditioned alignment') } })[value] }
function delta(value: unknown) { return typeof value === 'number' && Number.isFinite(value) ? `${value > 0 ? '+' : ''}${(value * 100).toFixed(1)} pp` : '—' }
function date(value: string) { return new Date(value).toLocaleString(formatLocale.value, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }
function detail(value: unknown): string { return typeof value === 'string' ? value : JSON.stringify(value, null, 2) ?? '—' }
function message(reason: unknown) { return reason instanceof Error ? reason.message : String(reason) }
function ratio(used?: number, limit?: number) { return used == null || !limit ? 0 : Math.max(0, Math.min(100, used / limit * 100)) }
function upsert(state: SearchSummary) { searches.value = [state, ...searches.value.filter(s => s.id !== state.id)] }
function clearPoll() { if (timer) clearTimeout(timer); timer = undefined }
function schedule(searchId: string, version: number) {
  clearPoll()
  if (disposed || version !== generation || artifactsLoading.value || !supportedSearch.value) return
  if (active.value) {
    timer = setTimeout(() => void refresh(searchId, version, false), 2000)
  } else if (tab.value === 'artifacts' && terminal.value && !finalArtifactsReady.value && artifactRetries.value < maxArtifactRetries) {
    timer = setTimeout(() => {
      artifactRetries.value++
      void refresh(searchId, version, true)
    }, 2000)
  }
}
function completionChanged(previous: SearchState, next: SearchState) {
  const searchFinished = previous.status !== next.status && terminalStatuses.has(next.status)
  const previousCandidates = new Map((previous.candidates ?? []).map(candidate => [candidate.id, candidate.status]))
  const candidateFinished = (next.candidates ?? []).some(candidate => finishedCandidateStatuses.has(candidate.status) && previousCandidates.get(candidate.id) !== candidate.status)
  return searchFinished || candidateFinished
}
async function refresh(searchId = id.value, version = generation, includeArtifacts = !current.value) {
  if (!searchId) return
  const serial = ++refreshSerial
  clearPoll()
  artifactsLoading.value = includeArtifacts
  try {
    const state = await fetchSearch(searchId, includeArtifacts)
    if (disposed || version !== generation || serial !== refreshSerial || id.value !== searchId) return
    const previous = current.value?.id === searchId ? current.value : null
    const refreshFiles = !includeArtifacts && tab.value === 'artifacts' && previous && completionChanged(previous, state)
    if (previous?.status !== state.status) artifactRetries.value = 0
    const displayedState = !includeArtifacts && previous ? { ...state, artifacts: previous.artifacts } : state
    current.value = displayedState; upsert(displayedState); error.value = ''
    if (refreshFiles) await refresh(searchId, version, true)
  } catch (reason) {
    if (!disposed && version === generation && serial === refreshSerial) error.value = message(reason)
  } finally {
    if (!disposed && version === generation && serial === refreshSerial) {
      loading.value = false; artifactsLoading.value = false; schedule(searchId, version)
    }
  }
}
function refreshFiles() {
  if (current.value && !busy.value && !artifactsLoading.value) void refresh(id.value, generation, true)
}
watch(tab, value => {
  clearPoll()
  if (value === 'artifacts') refreshFiles()
  else schedule(id.value, generation)
})
async function loadList() {
  listLoading.value = true
  try {
    const items = await fetchSearches()
    if (disposed) return
    searches.value = current.value ? [current.value, ...items.filter(s => s.id !== current.value!.id)] : items
    listError.value = ''
  } catch (reason) { if (!disposed) listError.value = message(reason) }
  finally { if (!disposed) listLoading.value = false }
}
function subjects(value: string) { return [...new Set(value.split(/[\s,，;；]+/).filter(Boolean))] }
function request(): SearchRequest {
  if (!workflowId.value.trim()) throw new Error(t('Enter the source workflow ID.'))
  for (const field of budgetFields) {
    const value = Number(formBudget[field.key])
    if (field.key === 'max_seconds') {
      if (!Number.isFinite(value) || value <= 0) throw new Error(t('Time limit must be a number greater than 0.'))
    } else if (String(formBudget[field.key]).trim() === '' || !Number.isInteger(value) || value < field.min) {
      throw new Error(t('{0} must be an integer of at least {1}.', { 0: field.label, 1: field.min }))
    }
    if (field.max != null && value > field.max) throw new Error(t('{0} must not exceed {1}.', { 0: field.label, 1: field.max }))
  }
  if (!Number.isSafeInteger(Number(seed.value)) || String(seed.value).trim() === '' || Number(seed.value) < 0 || Number(seed.value) > 4294967295) throw new Error(t('The random seed must be an integer from 0 to 4294967295.'))
  const optionalLimit = (value: string | number) => {
    if (String(value).trim() === '') return null
    if (!Number.isInteger(Number(value)) || Number(value) < 64) throw new Error(t('Memory and disk budgets must be integers of at least 64 MB, or left blank for automatic settings.'))
    return Number(value)
  }
  const train = subjects(trainSubjects.value), development = subjects(developmentSubjects.value)
  if (!!train.length !== !!development.length) throw new Error(t('Specify both training and development subjects, or leave both blank.'))
  if (train.some(subject => development.includes(subject))) throw new Error(t('Training and development subjects must not overlap.'))
  const selectedBudget: SearchBudget = {
    max_candidates: Number(formBudget.max_candidates), max_proposals: Number(formBudget.max_proposals),
    max_evidence_reads: Number(formBudget.max_evidence_reads), max_seconds: Number(formBudget.max_seconds),
    max_memory_mb: optionalLimit(formBudget.max_memory_mb), max_disk_mb: optionalLimit(formBudget.max_disk_mb),
  }
  return { workflow_id: workflowId.value.trim(), strategy: strategy.value, budget: selectedBudget, seed: Number(seed.value),
    ...(train.length ? { train_subjects: train } : {}), ...(development.length ? { development_subjects: development } : {}) }
}
async function start() {
  if (busy.value) return
  let body: SearchRequest
  try { body = request() } catch (reason) { error.value = message(reason); return }
  const version = generation
  busy.value = true; error.value = ''
  try {
    const state = await createSearch(body)
    if (disposed) return
    upsert(state)
    if (version !== generation) return
    pendingState = state
    await router.push({ path: '/searches', query: { id: state.id } })
  } catch (reason) { if (!disposed && version === generation) error.value = message(reason) }
  finally { busy.value = false }
}
async function control(action: 'cancel' | 'retry') {
  if (!current.value || busy.value || (action === 'retry' ? !canRetry.value : !active.value)) return
  const searchId = current.value.id, version = ++generation
  clearPoll(); artifactsLoading.value = false; busy.value = true; error.value = ''
  try {
    const state = await (action === 'cancel' ? cancelSearch(searchId) : retrySearch(searchId))
    if (disposed || version !== generation || id.value !== searchId) return
    if (current.value.status !== state.status) artifactRetries.value = 0
    current.value = state; upsert(state)
  } catch (reason) { if (!disposed && version === generation) error.value = message(reason) }
  finally {
    busy.value = false
    if (!disposed && version === generation) schedule(searchId, version)
  }
}
watch(() => [route.query.view, route.query.axis], () => {
  tab.value = typeof route.query.view === 'string' && route.query.view in tabs ? route.query.view : 'overview'
  assessmentAxis.value = typeof route.query.axis === 'string' ? route.query.axis : 'utility'
})
watch(() => [route.query.id, route.query.workflow], () => {
  const version = ++generation
  clearPoll(); error.value = ''; current.value = null; inspectedId.value = ''; reportName.value = ''; tab.value = typeof route.query.view === 'string' && route.query.view in tabs ? route.query.view : 'overview'; assessmentAxis.value = typeof route.query.axis === 'string' ? route.query.axis : 'utility'
  artifactQuery.value = ''; artifactOpened.value = {}; artifactPages.value = {}
  artifactsLoading.value = false; artifactRetries.value = 0
  loading.value = !!id.value
  if (id.value) {
    if (pendingState?.id === id.value) {
      current.value = pendingState; pendingState = null; loading.value = false; schedule(id.value, version)
    } else void refresh(id.value, version)
  } else {
    workflowId.value = typeof route.query.workflow === 'string' ? route.query.workflow : ''
  }
}, { immediate: true })
onMounted(() => void loadList())
onBeforeUnmount(() => { disposed = true; generation++; clearPoll() })
</script>

<template>
  <main class="search-page">
    <header class="topbar"><RouterLink to="/workflows">{{ t('← Data workspace') }}</RouterLink><strong>Brain Agent <span>{{ t('/ Preprocessing research') }}</span></strong><LanguageSwitcher /><RouterLink :to="{ path: '/searches', query: current ? { workflow: current.workflow_id } : {} }">{{ t('＋ New search') }}</RouterLink></header>
    <div class="search-layout">
      <aside class="sidebar" :aria-label="t('Search list')">
        <div class="section-heading"><h2>{{ t('Search records') }}<small>{{ searches.length }}</small></h2><button :disabled="listLoading" :aria-label="t('Refresh searches')" @click="loadList">↻</button></div>
        <p v-if="listError" class="error" role="alert">{{ listError }}</p>
        <p v-if="!searches.length" class="empty">{{ listLoading ? t('Loading records…') : t('No searches yet. Start with ingested data.') }}</p>
        <nav :aria-label="t('Choose a search')"><RouterLink v-for="item in searches" :key="item.id" :to="{ path: '/searches', query: { id: item.id } }" class="search-item" :class="{ chosen: id === item.id }" :aria-current="id === item.id ? 'page' : undefined"><span><strong>{{ item.id }}</strong><span class="badge" :class="item.status">{{ label(item.status) }}</span></span><small class="source-id" :title="item.workflow_id">{{ t('Source {0}', { 0: item.workflow_id }) }}</small><small>{{ t('{0} · Candidates {1} / {2}', { 0: date(item.created_at), 1: count(item.usage?.candidates), 2: count(item.budget?.max_candidates) }) }}</small></RouterLink></nav>
      </aside>
      <section class="main-content" :aria-busy="loading">
        <p v-if="error" class="error" role="alert">{{ error }} <button v-if="id" :disabled="busy || loading" @click="refresh()">{{ t('Reconnect') }}</button></p>
        <template v-if="!id">
          <header class="page-heading"><p class="eyebrow">OFFLINE SEARCH</p><h1>{{ t('Preprocessing strategy search') }}</h1><p class="muted">{{ t('Compare preprocessing strategies within a budget using signal diagnostics. Hypotheses, prediction checks, and evaluations are recorded.') }}</p></header>
          <p class="notice">{{ t('Development evaluation guides selection. It is not an independent test or a direct measure of neural signal quality.') }}</p>
          <form class="card create-form" :aria-label="t('Create a budgeted search')" @submit.prevent="start">
            <label class="wide">{{ t('Source workflow ID') }}<input v-model="workflowId" required :aria-label="t('Source workflow ID')" :placeholder="t('ID of a workflow with completed data ingestion')" /><small>{{ t('Uses data already ingested by this workflow.') }}</small></label>
            <p class="wide muted" :aria-label="t('Default evaluation')">{{ t('Subject-grouped cross-validation uses up to five folds, with each subject held out once. The primary score averages subject-mean BA over EEGNet seeds 17, 42, and 2026; all three must complete. CSP-LDA is a benchmark only. The 25 signal-quality and 14 reconstruction metrics are reported separately.') }}</p><fieldset class="wide"><legend>{{ t('Search strategy') }}</legend><div class="strategy-options"><label v-for="(name, key) in strategies" :key="key" :class="{ chosen: strategy === key }"><input v-model="strategy" type="radio" name="strategy" :value="key" />{{ name }}</label></div><p v-if="strategy === 'random'" class="strategy-hint muted">{{ t('Run candidates in random order; final selection still uses the development primary score.') }}</p><p v-if="strategy === 'one_shot'" class="strategy-hint muted">{{ t('The LLM proposes the candidate order once at the start. Execution follows that fixed order without adapting proposals to interim evaluations.') }}</p></fieldset>
            <label v-for="field in budgetFields" :key="field.key">{{ field.label }}<input v-model.number="formBudget[field.key]" type="number" :min="field.min" :max="field.max" :step="field.key === 'max_seconds' ? 'any' : 1" required :aria-label="field.label" /></label>
            <label>{{ t('Memory limit (MB)') }}<input v-model="formBudget.max_memory_mb" type="number" min="64" step="1" :placeholder="t('Automatic')" :aria-label="t('Memory limit (MB)')" /></label>
            <label>{{ t('Disk limit (MB)') }}<input v-model="formBudget.max_disk_mb" type="number" min="64" step="1" :placeholder="t('Automatic')" :aria-label="t('Disk limit (MB)')" /></label>
            <label>{{ t('Random seed') }}<input v-model.number="seed" type="number" min="0" max="4294967295" step="1" required :aria-label="t('Random seed')" /></label>
            <details class="wide optional-subjects"><summary>{{ t('Advanced: specify training / development subjects') }}</summary><p class="muted">{{ t('By default, subject-grouped cross-validation uses up to five folds, holding out each subject once. Specifying both groups instead uses a subject holdout evaluation. The groups must be disjoint and cover all ingested subjects. Separate IDs with spaces or commas.') }}</p><div class="subject-fields"><label>{{ t('Training subjects') }}<input v-model="trainSubjects" :aria-label="t('Training subjects')" :placeholder="t('For example: S001, S002')" /></label><label>{{ t('Development subjects') }}<input v-model="developmentSubjects" :aria-label="t('Development subjects')" :placeholder="t('For example: S003, S004')" /></label></div></details>
            <div class="form-footer wide"><span class="muted">{{ t('Leave memory and disk limits blank for automatic settings.') }}</span><button class="primary" :disabled="busy">{{ busy ? t('Creating…') : t('Start budgeted search →') }}</button></div>
          </form>
        </template>
        <template v-else-if="current">
          <header class="page-heading run-heading"><div><p class="eyebrow">OFFLINE SEARCH · {{ current.id }}</p><h1>{{ supportedSearch ? t('Preprocessing strategy search') : t('Budgeted search record') }} <span class="badge" :class="current.status">{{ label(current.status) }}</span></h1><p class="muted"><RouterLink :to="{path:'/workflows',query:{id:current.workflow_id}}">{{ t('Source workflow {0} ↗', { 0: current.workflow_id }) }}</RouterLink>{{ t('· {0} · Seed {1} · Updated {2}', { 0: strategies[current.request?.strategy] ?? current.request?.strategy ?? '—', 1: current.request?.seed ?? '—', 2: date(current.updated_at) }) }}</p></div><div class="run-controls"><span v-if="!supportedSearch" class="muted">{{ t('Read-only record') }}</span><button v-if="active" :disabled="busy" @click="control('cancel')">{{ busy ? t('Processing…') : t('Stop search') }}</button><button v-if="canRetry" class="primary" :disabled="busy" @click="control('retry')">{{ busy ? t('Processing…') : t('Retry search') }}</button></div></header>
          <p class="notice">{{ t('Development evaluation guides selection. It is not an independent test or a direct measure of neural signal quality.') }}</p>
          <details class="card budget-panel" :open="!terminal" :aria-label="t('Progress and budget')"><summary class="budget-toggle">{{ t('Progress and budget') }}<span role="status">{{ displayedPhase }}</span></summary>
            <div class="section-heading"><h2>{{ t('Usage details') }}</h2><span>{{ current.message }}</span></div>
            <div class="budget-grid"><div v-for="meter in meters" :key="meter.label" class="meter"><div><span>{{ meter.label }}</span><strong>{{ count(meter.used) }} <small>/ {{ count(meter.limit) }}</small></strong></div><div class="meter-track" role="progressbar" :aria-label="meter.label" :aria-valuenow="meter.used == null || meter.limit == null ? undefined : ratio(meter.used, meter.limit)" aria-valuemin="0" aria-valuemax="100" :aria-valuetext="`${count(meter.used)} / ${count(meter.limit)}`"><i :style="{ width: `${ratio(meter.used, meter.limit)}%` }" /></div></div></div>
            <div class="budget-meta"><span>{{ t('LLM calls: {0}', { 0: count(current.usage?.llm_calls) }) }}</span><span>{{ t('Retries: {0}', { 0: count(current.usage?.retries) }) }}</span><span>{{ t('Memory: {0}', { 0: !budget ? '—' : budget.max_memory_mb == null ? t('Automatic') : `${count(budget.max_memory_mb)} MB` }) }}</span><span>{{ t('Disk: {0}', { 0: !budget ? '—' : budget.max_disk_mb == null ? t('Automatic') : `${count(budget.max_disk_mb)} MB` }) }}</span><span>{{ t('Selected in development evaluation: {0}', { 0: current.selected_candidate_id || t('Not selected yet') }) }}</span></div>
            <p v-if="current.stop_reason" class="stop-reason">{{ t('Stop reason: {0}', { 0: stopReasons[current.stop_reason] ?? current.stop_reason }) }}</p>
            <details v-if="current.error" class="error"><summary>{{ t('Search error') }}</summary><pre>{{ current.error }}</pre></details>
            <p v-if="typeof current.panel === 'string'" class="panel-summary">{{ t('Development panel: {0}', { 0: current.panel }) }}</p>
            <details v-else-if="panel" class="panel-summary" :aria-label="t('Evaluation panel')">
              <summary>{{ t('Evaluation scope · {0} {1} · {2} trials', { 0: count(panelDevelopmentCount), 1: panel.evaluation_mode === 'group_cross_validation' ? t('Subjects') : t('Development subjects'), 2: count(panel.eligible_count) }) }}<template v-if="panel.folds?.length">{{ t('· {0} folds', { 0: panel.folds.length }) }}</template><span class="muted">{{ t('· View splits') }}</span></summary>
              <h3>{{ panel.evaluation_mode === 'group_cross_validation' ? t('Subject-grouped cross-validation') : panel.evaluation_mode === 'subject_holdout' ? t('Subject holdout evaluation') : t('Development evaluation panel') }}</h3>
              <p v-if="panel.evaluation_mode === 'group_cross_validation'">{{ t('{0} folds. Each subject is held out once. Training subjects are assigned per fold and do not overlap with that fold\'s development subjects.', { 0: panel.folds?.length ?? '—' }) }}</p>
              <p v-else-if="panel.evaluation_mode === 'subject_holdout'">{{ t('Uses explicitly specified training and development subjects. Learners fit only training subjects; development subjects guide method selection.') }}</p>
              <div class="budget-meta"><span v-if="panel.evaluation_mode !== 'group_cross_validation'">{{ t('Training subjects: {0}', { 0: count(panelTrainCount) }) }}</span><span>{{ panel.evaluation_mode === 'group_cross_validation' ? t('Cross-validation subjects') : t('Development subjects') }} {{ count(panelDevelopmentCount) }}</span><span>{{ t('Original trials: {0}', { 0: count(panel.trial_count) }) }}</span><span>{{ t('Eligible trials: {0}', { 0: count(panel.eligible_count) }) }}</span></div>
              <div v-if="panel.folds?.length" class="table-scroll"><table class="fold-table" :aria-label="t('Evaluation folds')"><thead><tr><th>{{ t('Fold') }}</th><th>{{ t('Training subjects') }}</th><th>{{ t('Development subjects') }}</th></tr></thead><tbody><tr v-for="fold in panel.folds" :key="fold.id"><td>{{ fold.id }}</td>
                <td v-for="group in [{ role: t('Training'), subjects: fold.train_subjects }, { role: t('Development'), subjects: fold.development_subjects }]" :key="group.role">
                  <details class="fold-subjects"><summary :aria-label="t('{0} {1} subjects: {2}. View full list', { 0: fold.id, 1: group.role, 2: group.subjects.length })">{{ t('{0} subjects', { 0: group.subjects.length }) }}</summary><ul class="fold-subject-list" tabindex="0" :aria-label="t('Full list of {0} {1} subjects', { 0: fold.id, 1: group.role })"><li v-for="subject in group.subjects" :key="subject">{{ subject }}</li></ul></details>
                </td>
              </tr></tbody></table></div>
              <details><summary>{{ t('Development panel details') }}</summary><pre>{{ detail(panel) }}</pre></details>
            </details>
            <details v-if="current.request?.train_subjects?.length || current.request?.development_subjects?.length" class="panel-summary"><summary>{{ t('Subject split') }}</summary><p>{{ t('Training: {0}', { 0: current.request.train_subjects?.join('、') || t('Assigned automatically') }) }}</p><p>{{ t('Development: {0}', { 0: current.request.development_subjects?.join('、') || t('Assigned automatically') }) }}</p></details>
          </details>
          <details class="card evaluator-summary" :aria-label="t('Scoring and adaptation definitions')">
            <summary>{{ t('Scoring and adaptation') }}<span class="muted">· {{ multiMetric ? t('{0}, signal quality, and reconstruction experiments', { 0: utilityLabel }) : evaluatorLabel }}</span></summary><p v-if="!cspEvaluation">{{ t('Evaluator: {0}. Scores and selections follow the saved records.', { 0: evaluatorLabel }) }}</p>
            <p v-if="eegnetUtility">{{ t('The primary score averages subject-macro BA equally across EEGNet seeds 17, 42, and 2026. All three must complete. CSP-LDA is a benchmark only; 25 quality and 14 reconstruction metrics are reported independently.') }}</p><p v-else-if="multiMetric">{{ t('Legacy v1: the primary score is the equal-weight mean of subject-macro BA for CSP-LDA, FBCSP, and TS-LR, all of which must complete. Quality and reconstruction are reported independently; CSP details provide a common anchor.') }}</p><p v-else-if="cspEvaluation">{{ t('The primary score is subject-mean BA for CSP + shrinkage LDA: compute left/right balanced accuracy for each development subject, then weight subjects equally. CSP and the classifier fit only training subjects in each fold.') }}</p>
            <p v-if="cspEvaluation && !eegnetUtility">{{ t('The secondary benchmark uses log-variance + logistic regression to inspect representation and prediction behavior.') }}</p>
            <p v-if="cspEvaluation">{{ t('Strategies include shared processing, per-subject scaling, uniform-rule alignment, and diagnosis-conditioned alignment. Individual parameters are fitted offline using each subject\'s entire unlabeled batch. When conditional alignment is not triggered, scaling alone preserves spatial structure and keeps all outputs dimensionless. Batch adaptation differs from online trial-by-trial prediction.') }}</p>
          </details>
          <section ref="resultsPanel" class="card results">
            <nav class="tabs" :aria-label="t('Search result views')"><button v-for="(name, key) in tabs" :key="key" :aria-pressed="tab === key" @click="tab = key">{{ name }}<small v-if="key === 'candidates'">{{ candidates.length }}</small><small v-if="key === 'rounds'">{{ actions.length }}</small><small v-if="key === 'artifacts'">{{ artifacts.length }}</small></button></nav>
            <section v-if="tab === 'overview'" class="tab-content"><SearchDecisionOverview :state="current" @navigate="navigateEvidence" /></section>
            <section v-else-if="tab === 'methods'" class="tab-content"><SearchMethodExplorer :entries="current.registry ?? []" :space="current.protocol?.space" /></section>
            <section v-else-if="tab === 'assessment'" class="tab-content"><div class="section-heading"><h2>{{ t('Candidate multidimensional evaluation') }}</h2><label>{{ t('Candidate') }}<select :value="inspected?.id" @change="inspectedId = ($event.target as HTMLSelectElement).value"><option v-for="candidate in candidates" :key="candidate.id" :value="candidate.id">{{ candidate.title || candidate.id }}</option></select></label></div><SearchOperatorUsage v-if="inspected" :search-id="current.id" :candidate-id="inspected.id" :usage="inspected.receipt?.operator_usage" /><SearchAssessment v-if="inspected" :initial-axis="assessmentAxis" :guide-frozen="!!current.protocol?.interpretation_guide_hash" :search-id="current.id" :candidate-id="inspected.id" :base-path="inspected.receipt?.assessment_path" :assessment="inspected.receipt?.assessment"><template #parameters><SearchParameters :expanded="assessmentAxis === 'parameters'" :protocol="current.protocol" :panel="panel" :recipe="current.registry?.find(r => r.id === inspected?.id)?.recipe" /></template></SearchAssessment></section>
            <section v-else-if="tab === 'candidates'" class="tab-content" :aria-label="t('Candidate comparison')">
              <div class="section-heading"><h2>{{ t('Development BA comparison') }}</h2><span class="muted">{{ multiMetric ? t('Primary metric: {0} · Δ is the CSP anchor difference from baseline in percentage points', { 0: utilityLabel }) : t('Evaluator: {0} · Subject-mean BA · Δ is the difference from baseline in percentage points', { 0: evaluatorLabel }) }}</span></div>
              <div v-if="candidates.length" class="table-scroll"><table><thead><tr><th>{{ t('Candidate / parameters') }}</th><th>{{ t('Status') }}</th><th>{{ t('Primary BA score') }}</th><th>{{ t('Secondary benchmark BA') }}</th><th>{{ t('Mean Δ') }}</th><th>{{ t('Coverage (predicted / eligible)') }}</th><th>{{ t('Selection') }}</th><th>{{ t('Details') }}</th></tr></thead><tbody><tr v-for="candidate in candidates" :key="candidate.id" :class="{ selected: candidate.id === current.selected_candidate_id }"><td><strong>{{ candidate.title || candidate.id }}</strong><small v-if="multiMetric">{{ recipeSummary(candidate.id) || candidate.id }}</small><small v-else>{{ candidate.id }} · {{ candidate.parameters?.l_freq ?? '—' }}–{{ candidate.parameters?.h_freq ?? '—' }} Hz · {{ candidate.parameters?.reference === 'average' ? t('Average reference') : candidate.parameters?.reference === 'original' ? t('Acquisition reference') : t('Reference unknown') }}</small><small v-if="candidate.parameters?.adaptation">{{ adaptationLabel(candidate.parameters.adaptation) }}<template v-if="candidate.parameters.adaptation === 'conditional_alignment' && candidate.parameters.alignment_threshold != null">{{ t('· Conditional threshold {0}', { 0: count(candidate.parameters.alignment_threshold) }) }}</template></small></td><td>{{ label(candidate.status) }}<small v-if="candidate.receipt?.status">{{ t('Evaluation record: {0}', { 0: label(candidate.receipt.status) }) }}</small><details v-if="candidate.error" class="candidate-error"><summary>{{ t('Error') }}</summary><pre>{{ candidate.error }}</pre></details></td><td class="score">{{ percent(multiMetric ? candidate.receipt?.assessment?.selection_score : candidate.receipt?.macro_ba) }}<small v-if="multiMetric">{{ t('CSP anchor {0}', { 0: percent(candidate.receipt?.macro_ba) }) }}</small></td><td>{{ percent(candidate.receipt?.secondary_macro_ba) }}</td><td>{{ delta(candidate.receipt?.mean_delta) }}<small v-if="candidate.receipt?.paired_subject_ci">{{ t('Descriptive interval: {0} to {1}', { 0: delta(candidate.receipt.paired_subject_ci.low), 1: delta(candidate.receipt.paired_subject_ci.high) }) }}<br />{{ t('{0} paired subjects · Development comparison', { 0: candidate.receipt.paired_subject_ci.n_subjects }) }}</small></td><td>{{ count(candidate.receipt?.coverage?.predicted) }} / {{ count(candidate.receipt?.coverage?.eligible) }}</td><td><span v-if="candidate.id === current.selected_candidate_id" class="selection-mark">{{ t('✓ Selected by development evaluation') }}</span><span v-else class="muted">—</span></td><td><button :aria-label="t('View development subjects for candidate {0}', { 0: candidate.id })" @click="inspectedId = candidate.id; tab = 'subjects'">{{ t('View subjects →') }}</button></td></tr></tbody></table></div>
              <p v-else class="empty">{{ t('No candidates yet. Parameters and development evaluations appear here once the search starts.') }}</p>
            </section>
            <section v-else-if="tab === 'rounds'" class="tab-content" :aria-label="t('Round timeline')"><div class="section-heading"><h2>{{ t('Decisions and results by round') }}</h2><span class="muted">{{ t('In execution record order') }}</span></div><ol v-if="actions.length" class="timeline"><li v-for="action in actions" :key="action.index"><span class="round-number">{{ action.index }}</span><div class="round-body"><div class="section-heading"><h3>{{ actionLabels[action.action] ?? action.action }}</h3><span>{{ t('{0} · {1} s', { 0: label(action.status), 1: count(action.cost_seconds) }) }}</span></div><p>{{ action.reason || t('No decision rationale') }}</p><p v-if="action.base_candidate_id || action.candidate_id" class="muted">{{ action.base_candidate_id || t('Initial') }} → {{ action.candidate_id || '—' }}</p><section v-if="action.request?.hypothesis" class="hypothesis" :aria-label="t('Mechanistic hypothesis')">
                <h4>{{ t('Mechanistic hypothesis') }}</h4><p>{{ action.request.hypothesis.explanation }}</p>
                <h4>{{ t('Competing explanations') }}</h4><p>{{ action.request.hypothesis.competing_explanation }}</p>
                <h4>{{ t('Observed evidence') }}</h4><ul class="observations"><li v-for="(observation, index) in action.request.hypothesis.observations" :key="index"><span>{{ candidates.find(candidate => candidate.id === observation.candidate_id)?.title || observation.candidate_id }}</span> · <span :title="observation.metric">{{ metricLabel(observation.metric) }}</span></li></ul>
                <h4>{{ t('Preregistered predictions') }}</h4><ul class="predictions"><li v-for="(prediction, index) in action.request.hypothesis.predictions" :key="index"><strong>{{ prediction.kind === 'signal' ? t('Signal prediction') : t('Utility prediction') }} · {{ metricLabel(prediction.metric) }} {{ directionLabel(prediction.direction) }}</strong><span class="muted">{{ t('· Tolerance {0}', { 0: measurement(prediction.tolerance) }) }}</span><p>{{ prediction.explanation }}</p></li></ul>
                <h4>{{ t('Results that would weaken the explanation') }}</h4><p>{{ action.request.hypothesis.weakened_by }}</p>
              </section>
              <section v-if="action.result?.prediction_checks" class="prediction-checks" :aria-label="t('Measured prediction checks')">
                <h4>{{ t('Measured prediction checks') }}</h4>
                <div v-if="action.result.prediction_checks.checks.length" class="table-scroll"><table><thead><tr><th>{{ t('Prediction') }}</th><th>{{ t('Check status') }}</th><th>{{ t('Before') }}</th><th>{{ t('After') }}</th><th>{{ t('Measured difference') }}</th><th>{{ t('Tolerance') }}</th></tr></thead><tbody><tr v-for="(check, index) in action.result.prediction_checks.checks" :key="index"><td class="readable-cell"><strong>{{ check.kind === 'signal' ? t('Signal') : t('Utility') }} · {{ metricLabel(check.metric) }}</strong><small>{{ t('Expected: {0} · {1}', { 0: directionLabel(check.direction), 1: check.explanation }) }}</small></td><td><span class="check-status" :class="check.status">{{ checkLabel(check.status) }}</span></td><td>{{ measurement(check.before) }}</td><td>{{ measurement(check.after) }}</td><td>{{ measurement(check.difference) }}</td><td>{{ measurement(check.tolerance) }}</td></tr></tbody></table></div>
                <p v-else class="muted">{{ t('No verifiable predictions yet.') }}</p><p class="muted">{{ action.result.prediction_checks.interpretation }}</p>
              </section>
<div v-if="action.expected_result != null || action.decision_branches != null" class="hypothesis"><h4>{{ t('Hypotheses and expected results') }}</h4><p v-if="action.expected_result != null">{{ detail(action.expected_result) }}</p><dl v-if="action.decision_branches && typeof action.decision_branches === 'object'"><template v-for="(branch, key) in action.decision_branches" :key="key"><dt>{{ branchLabel(String(key)) }}</dt><dd>{{ detail(branch) }}</dd></template></dl><p v-else-if="action.decision_branches != null">{{ detail(action.decision_branches) }}</p></div><p v-if="action.result?.status" class="muted">{{ t('Execution result: {0}', { 0: label(String(action.result.status)) }) }}</p><div v-if="Array.isArray(action.result?.excerpts)" class="evidence-excerpts"><p v-for="(excerpt, index) in action.result.excerpts" :key="index">{{ excerpt }}</p></div><details v-if="action.error" class="error"><summary>{{ t('Round error') }}</summary><pre>{{ action.error }}</pre></details></div></li></ol><p v-else class="empty">{{ t('No rounds recorded yet.') }}</p></section>
            <section v-else-if="tab === 'subjects'" class="tab-content" :aria-label="t('Development subject details')"><h2>{{ t('Development subject details') }}</h2><nav v-if="candidates.length" class="candidate-tabs" :aria-label="t('Inspect candidate')"><button v-for="candidate in candidates" :key="candidate.id" :aria-pressed="inspected?.id === candidate.id" @click="inspectedId = candidate.id">{{ candidate.title || candidate.id }}<span v-if="candidate.id === current.selected_candidate_id">{{ t('· Selected in development evaluation') }}</span></button></nav><template v-if="inspected"><div class="section-heading"><h3>{{ inspected.title || inspected.id }}</h3><span class="muted">{{ t('Task {0}', { 0: inspected.job_id || '—' }) }}</span></div><div class="diagnostics"><span>{{ t('Original (development): {0}', { 0: count(inspected.receipt?.coverage?.original) }) }}</span><span>{{ t('Eligible (development): {0}', { 0: count(inspected.receipt?.coverage?.eligible) }) }}</span><span>{{ t('Predicted (development): {0}', { 0: count(inspected.receipt?.coverage?.predicted) }) }}</span><span>{{ t('Missing: {0}', { 0: count(inspected.receipt?.coverage?.missing) }) }}</span><span>{{ t('Floor fraction: {0}', { 0: percent(inspected.receipt?.diagnostics?.floor_fraction) }) }}</span><span>{{ t('Converged: {0}', { 0: inspected.receipt?.diagnostics?.converged === true ? t('Yes') : inspected.receipt?.diagnostics?.converged === false ? t('No') : '—' }) }}</span></div><details v-if="inspected.receipt?.diagnostics?.warnings?.length" class="panel-summary"><summary>{{ t('Diagnostic warnings ({0})', { 0: inspected.receipt.diagnostics.warnings.length }) }}</summary><ul><li v-for="(warning, index) in inspected.receipt.diagnostics.warnings" :key="index">{{ warning }}</li></ul></details><details v-if="inspected.receipt?.coverage?.train || inspected.receipt?.coverage?.development" class="panel-summary"><summary>{{ t('Training / development coverage details') }}</summary><pre>{{ detail(inspected.receipt.coverage) }}</pre></details><section v-if="signalRows.length" class="diagnostic-section" :aria-label="t('Signal diagnostics')">
                <h3>{{ t('Signal diagnostics') }}</h3><p class="muted">{{ t('Per-subject channel variance and flat-signal fractions before adaptation, plus covariance condition number, mean variance, and effective rank before and after adaptation.') }}</p>
                <div v-if="diagnosticSummary" class="diagnostics" :aria-label="t('Overall diagnostic means')"><span>{{ t('Mean condition number: {0} → {1}', { 0: measurement(diagnosticSummary.mean_condition_before), 1: measurement(diagnosticSummary.mean_condition_after) }) }}</span><span>{{ t('Mean channel variance: {0} → {1}', { 0: scientific(diagnosticSummary.mean_variance_before), 1: scientific(diagnosticSummary.mean_variance_after) }) }}</span><span>{{ t('Mean effective rank (before adaptation): {0}', { 0: measurement(diagnosticSummary.mean_effective_rank) }) }}</span><span>{{ t('Mean spectral Q90/Q10: {0}', { 0: measurement(diagnosticSummary.mean_anisotropy) }) }}</span><span>{{ t('Conditional trigger fraction: {0}', { 0: diagnosticSummary.gate_fraction === null ? t('Not applicable') : percent(diagnosticSummary.gate_fraction) }) }}</span></div>
                <div class="table-scroll"><table><thead><tr><th>{{ t('Subjects') }}</th><th>{{ t('Covariance condition number (before → after)') }}</th><th>{{ t('Mean channel variance (before → after)') }}</th><th>{{ t('Effective rank (before → after)') }}</th><th>{{ t('Pre-adaptation channel diagnostics') }}</th></tr></thead><tbody><tr v-for="row in signalRows" :key="row.subject"><td>{{ row.subject }}</td><td>{{ measurement(row.covariance_condition_before ?? row.covariance_condition) }} → {{ measurement(row.covariance_condition_after) }}</td><td>{{ scientific(row.mean_channel_variance_before) }} → {{ scientific(row.mean_channel_variance_after) }}</td><td>{{ count(row.effective_rank_before) }} → {{ count(row.effective_rank_after) }}</td><td><details><summary>{{ t('View {0} channels', { 0: row.channel_variance.length }) }}</summary><ul class="channel-diagnostics"><li v-for="(variance, index) in row.channel_variance" :key="index">{{ t('{0} · Variance: {1} · Flat fraction: {2}', { 0: diagnosticChannels[index] ?? t('Channel {0}', { 0: index + 1 }), 1: scientific(variance), 2: percent(row.channel_flat_fraction[index]) }) }}</li></ul></details></td></tr></tbody></table></div>
              </section>
              <section v-if="representation && adaptationRows.length" class="diagnostic-section" :aria-label="t('Per-subject adaptation')">
                <h3>{{ t('Per-subject adaptation · {0}', { 0: adaptationLabel(representation.policy.adaptation) }) }}</h3><p class="muted">{{ representation.transductive ? t('Fitted using each subject\'s entire unlabeled batch.') : t('Input representation retained according to the saved strategy.') }}<template v-if="representation.policy.adaptation === 'conditional_alignment'">{{ t('The gate uses Q90/Q10 of the normalized shrinkage covariance spectrum and triggers at {0}. Covariance condition number is shown separately. The threshold is a predefined engineering parameter.', { 0: measurement(representation.policy.alignment_threshold) }) }}</template></p>
                <p class="muted" :aria-label="t('Trigger fraction')">{{ t('Conditional trigger fraction:') }}<template v-if="representation.policy.adaptation === 'conditional_alignment'">{{ t('{0} · {1} / {2} subjects (all selected subjects)', { 0: percent(representation.gate_fraction), 1: count(representation.gate_passed_subject_count), 2: count(representation.gate_subject_count) }) }}</template><template v-else>{{ t('Not applicable') }}</template></p>
                <div class="table-scroll"><table><thead><tr><th>{{ t('Subjects') }}</th><th>{{ t('Applied adaptation') }}</th><th>{{ t('Covariance condition number') }}</th><th>{{ t('Gating ratio Q90/Q10') }}</th><th>{{ t('Condition met') }}</th><th>{{ t('Fitting trial count') }}</th><th>{{ t('Output units') }}</th><th>{{ t('Fallback explanation') }}</th></tr></thead><tbody><tr v-for="row in adaptationRows" :key="row.subject"><td>{{ row.subject }}</td><td>{{ representation.policy.adaptation === 'conditional_alignment' && !row.gate_passed ? t('Rescale while preserving spatial structure') : adaptationLabel(row.applied_adaptation) }}</td><td>{{ measurement(row.covariance_anisotropy) }}</td><td>{{ measurement(row.gate_metric_value) }}</td><td>{{ representation.policy.adaptation === 'conditional_alignment' ? (row.gate_passed ? t('Yes') : t('No')) : t('Not applicable') }}</td><td>{{ count(row.fit_trials) }}</td><td>{{ row.unit === 'V' ? 'V' : t('Dimensionless') }}</td><td class="readable-cell">{{ row.fallback_reason || '—' }}</td></tr></tbody></table></div>
              </section><p v-if="inspected.error" class="error">{{ inspected.error }}</p><div v-if="subjectRows.length" class="table-scroll"><table><thead><tr><th>{{ t('Development subjects') }}</th><th>{{ multiMetric ? t('CSP anchor BA') : t('Primary BA score') }}</th><th>{{ t('Secondary benchmark BA') }}</th><th>{{ t('Δ (percentage points)') }}</th><th>{{ t('Predicted / eligible') }}</th><th>{{ t('Full record') }}</th></tr></thead><tbody><tr v-for="subject in subjectRows" :key="subject.subject"><td>{{ subject.subject }}</td><td class="score">{{ percent(subject.ba) }}</td><td>{{ percent(inspected.receipt?.secondary_subjects?.[subject.subject]) }}</td><td>{{ delta(subject.delta) }}</td><td>{{ count(subject.predicted_trials) }} / {{ count(subject.eligible_trials) }}</td><td><details><summary>{{ t('View record') }}</summary><pre>{{ detail(subject) }}</pre></details></td></tr></tbody></table></div><p v-else class="empty">{{ t('No development subject evaluation record for this candidate yet.') }}</p></template><p v-else class="empty">{{ t('Development subjects become available after candidates are generated.') }}</p></section>
            <section v-else class="tab-content" :aria-label="t('Reports and files')"><div class="section-heading"><h2>{{ t('Reports and files') }}</h2><button :disabled="artifactsLoading || busy" @click="refreshFiles">{{ artifactsLoading ? t('Refreshing files…') : t('Refresh files') }}</button></div><p v-if="supportedSearch && terminal && !finalArtifactsReady" class="notice" role="status"><template v-if="artifactRetries < maxArtifactRetries || artifactsLoading">{{ t('Preparing artifacts and waiting for report and file indexes. Automatic check {0} / {1}.', { 0: artifactRetries, 1: maxArtifactRetries }) }}</template><template v-else>{{ t('After {0} automatic checks, some artifacts are still unavailable. Refresh files again later.', { 0: maxArtifactRetries }) }}</template></p><div v-if="reports.length" class="report-reader"><nav class="candidate-tabs" :aria-label="t('Choose a search report')"><button v-for="item in reports" :key="item.name" :aria-pressed="report?.name === item.name" @click="reportName = item.name">{{ item.description || item.name }}</button></nav><iframe v-if="report && searchArtifactUrl(current.id, report, false)" :key="`${current.id}/${report.name}`" :src="searchArtifactUrl(current.id, report, false)" :title="report.description || report.name" sandbox="allow-same-origin" /></div><div v-if="artifacts.length" class="artifact-browser">
                <div class="artifact-toolbar"><label>{{ t('Find files') }}<input v-model="artifactQuery" type="search" :aria-label="t('Find search files')" :placeholder="t('File name, candidate ID, or description…')" /></label><span class="muted">{{ t('{0} / {1} files', { 0: matchedArtifacts.length, 1: artifacts.length }) }}</span></div>
                <p class="muted">{{ t('Core files appear directly. Candidate process and numerical files are grouped, with up to 30 files per page.') }}</p>
                <details v-for="group in artifactGroups" :key="`${current.id}/${group.key}`" class="artifact-group" :data-group="group.key" :open="artifactGroupOpen(group.key)">
                  <summary @click.prevent="artifactOpened[group.key] = !artifactGroupOpen(group.key)"><strong>{{ group.title }}</strong><span v-if="group.path" class="muted group-path">{{ group.path }}</span><small>{{ t('{0} files', { 0: group.files.length }) }}</small></summary>
                  <template v-if="artifactGroupOpen(group.key)">
                    <ul class="artifact-list"><li v-for="artifact in artifactPageFiles(group)" :key="artifact.name"><div><a v-if="searchArtifactUrl(current.id, artifact)" :href="searchArtifactUrl(current.id, artifact)" target="_blank" rel="noopener noreferrer">{{ artifact.name }}</a><strong v-else>{{ artifact.name }}</strong><span class="artifact-description">{{ artifact.description || t('Search artifacts') }}</span></div><span v-if="!searchArtifactUrl(current.id, artifact)" class="muted">{{ t('Link unavailable') }}</span></li></ul>
                    <nav v-if="group.files.length > artifactPageSize" class="artifact-pagination" :aria-label="t('{0} file pagination', { 0: group.title })"><button :disabled="artifactPage(group) === 1" @click="artifactPages[group.key] = artifactPage(group) - 1">{{ t('Previous page') }}</button><span>{{ t('Page {0} / {1} · {2} items', { 0: artifactPage(group), 1: artifactPageCount(group), 2: group.files.length }) }}</span><button :disabled="artifactPage(group) === artifactPageCount(group)" @click="artifactPages[group.key] = artifactPage(group) + 1">{{ t('Next page') }}</button></nav>
                  </template>
                </details>
                <p v-if="!matchedArtifacts.length" class="empty">{{ t('No matching files. Try another file name or description.') }}</p>
              </div><p v-else class="empty">{{ t('No reports or files yet. They appear automatically when generated.') }}</p></section>
          </section>
        </template>
        <p v-else class="empty">{{ loading ? t('Loading search…') : t('Unable to load search. Reconnect to try again.') }}</p>
      </section>
    </div>
  </main>
</template>

<style scoped>
.fold-table{table-layout:fixed;min-width:320px}.fold-table th:first-child,.fold-table td:first-child{width:90px;min-width:0}.fold-table td{white-space:normal}.fold-subject-list{display:flex;flex-wrap:wrap;gap:4px 12px;list-style:none;padding:0;margin:8px 0 0;max-height:140px;overflow:auto;overflow-wrap:anywhere}.fold-subject-list:focus-visible{outline:2px solid #39845b;outline-offset:3px}
.prediction-checks{margin:16px 0}.prediction-checks h4{font-size:12px;margin:0 0 8px}.prediction-checks>p{margin-top:10px}.observations,.predictions{padding-left:18px;margin:0 0 12px}.predictions li{display:list-item;padding:0 0 8px}.observations li{display:list-item;padding:0}.check-status{padding:3px 7px;border-radius:4px;background:#edf0ed;color:#647568}.check-status.matched{background:#e2f0e5;color:#286242}.check-status.contradicted{background:#fff0df;color:#945421}.check-status.unavailable{background:#edf0ed;color:#647568}.evidence-excerpts{border-left:2px solid #d6e1d9;padding-left:12px}.evaluator-summary p{font-size:12px;color:#637b6a;margin-top:10px}.diagnostic-section{margin:20px 0;border-top:1px solid #e5ede7;padding-top:18px}.diagnostic-section>p{margin:8px 0}.channel-diagnostics{padding-left:18px;max-height:240px;overflow:auto}.readable-cell{white-space:normal;min-width:180px;overflow-wrap:anywhere}.hypothesis{margin-top:12px;padding:12px;background:#f5f8f5;border-radius:7px}.hypothesis h4{margin:0 0 8px;font-size:12px}.hypothesis dl{margin:0;font-size:12px}.hypothesis dt{font-weight:600}.hypothesis dd{margin:2px 0 8px;white-space:pre-wrap;overflow-wrap:anywhere}.panel-summary .table-scroll{margin:12px 0}
.search-page{min-height:100dvh;background:#f3f6f7;color:#253e43;font:14px/1.6 system-ui,-apple-system,'Segoe UI',sans-serif}.search-page *{box-sizing:border-box}h1,h2,h3,p{margin:0}h1{font-size:25px;letter-spacing:-.03em}h2{font-size:15px}h3{font-size:14px}a{color:#285e43;text-decoration:none}a:hover{text-decoration:underline}button,input{font:inherit}button{cursor:pointer;border:1px solid #d6e1d9;background:white;border-radius:7px;padding:7px 12px;color:#365a43}button:hover{background:#edf4ef}button:disabled{opacity:.55;cursor:wait}button:focus-visible,a:focus-visible,input:focus-visible,summary:focus-visible{outline:2px solid #39845b;outline-offset:3px}.primary{background:#285e43;color:white;border-color:#285e43}.primary:hover{background:#1e4c34}.muted,small{color:#708477;font-size:12px}.topbar{min-height:68px;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 28px;border-bottom:1px solid #dce6df;background:#fbfcfc}.topbar strong span{font-weight:400;color:#708477}.search-layout{display:grid;grid-template-columns:250px minmax(0,1fr);max-width:1760px;margin:auto}.sidebar{padding:24px 16px;border-right:1px solid #dce6df;max-height:calc(100dvh - 68px);overflow:auto;position:sticky;top:0}.section-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:16px}.section-heading>span{font-size:12px;overflow-wrap:anywhere}.sidebar .section-heading button{padding:2px 9px}.sidebar h2 small{margin-left:8px}.search-item{display:block;padding:14px 12px;margin-bottom:9px;border:1px solid transparent;border-radius:9px;color:#466550}.search-item:hover{background:#eaf1ec;text-decoration:none}.search-item.chosen{background:#fff;border-color:#afc8b7;box-shadow:0 3px 12px #244c3410}.search-item>span{display:flex;justify-content:space-between;gap:8px;align-items:center}.search-item strong{font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:105px}.search-item>small{display:block;margin-top:6px;overflow-wrap:anywhere;font-size:11px}.badge{display:inline-block;border-radius:20px;padding:2px 9px;background:#eaf1ed;color:#52705d;font-size:11px;font-weight:500;white-space:nowrap;vertical-align:middle}.badge.running,.badge.preparing{background:#e4eef7;color:#3c698d}.badge.failed{background:#f9e9e4;color:#a14d38}.badge.completed{background:#dceee1;color:#286242}.main-content{padding:28px;min-width:0}.page-heading{margin-bottom:20px}.page-heading h1{margin:5px 0 8px}.eyebrow{font-size:10px;color:#789681;letter-spacing:.12em;overflow-wrap:anywhere}.notice{background:#e9efe5;border:1px solid #d9e3d2;padding:10px 14px;border-radius:7px;color:#64744f;font-size:12px;margin-bottom:20px}.card{background:white;border:1px solid #dce6df;border-radius:12px;padding:22px;margin-bottom:20px}.create-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px;max-width:900px}.create-form label{display:flex;flex-direction:column;gap:7px;font-size:12px;color:#526b5b}.create-form input:not([type=radio]){width:100%;border:1px solid #d1ddd4;border-radius:7px;padding:10px 12px;color:#284733;background:#fcfdfc}.wide{grid-column:1/-1}.create-form fieldset{padding:0;border:0;margin:0}.create-form legend{font-size:12px;color:#526b5b;margin-bottom:10px}.strategy-options{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}.strategy-hint{margin-top:10px}.strategy-options label{flex:1;flex-direction:row;align-items:center;justify-content:center;border:1px solid #d6e1d9;border-radius:8px;padding:12px;cursor:pointer}.strategy-options .chosen{background:#edf5ef;border-color:#7da98b;color:#285e43}.strategy-options input{accent-color:#285e43}.optional-subjects{border-top:1px solid #e5ece7;padding-top:14px}.optional-subjects p{margin:10px 0}.subject-fields{display:grid;grid-template-columns:1fr 1fr;gap:18px}.form-footer{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-top:5px}.run-heading{display:flex;justify-content:space-between;align-items:center;gap:18px}.run-heading h1 .badge{margin-left:8px}.run-controls{flex-shrink:0}.budget-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:24px}.meter>div:first-child{display:flex;justify-content:space-between;gap:8px;font-size:12px;margin-bottom:10px}.meter strong{font-size:15px;font-variant-numeric:tabular-nums}.meter small{font-weight:400}.meter-track{height:5px;border-radius:5px;background:#eaf0eb;overflow:hidden}.meter-track i{height:100%;display:block;background:#558d68;border-radius:5px;transition:width .25s}.budget-meta,.diagnostics{display:flex;flex-wrap:wrap;gap:8px 22px;color:#718678;font-size:12px;margin-top:18px}.stop-reason{margin-top:14px;border-top:1px solid #e7ede8;padding-top:12px;color:#806647;font-size:12px}.panel-summary{margin-top:12px;font-size:12px;color:#637b6a}.results{padding:0;overflow:hidden}.tabs{display:flex;gap:22px;padding:0 22px;border-bottom:1px solid #e1e9e3;overflow:auto}.tabs button{padding:16px 0;border:0;border-radius:0;border-bottom:2px solid transparent;white-space:nowrap;background:transparent;color:#788c7f}.tabs button[aria-pressed=true]{color:#285e43;border-bottom-color:#285e43;font-weight:600}.tabs small{margin-left:7px}.tab-content{padding:22px;min-height:260px}.table-scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;text-align:left;font-size:12px}th{font-size:11px;color:#7c8f81;font-weight:500;background:#f7f9f7}th,td{padding:14px 12px;border-bottom:1px solid #e8eee9;white-space:nowrap;vertical-align:top}td:first-child{min-width:200px}td strong{display:block;max-width:310px;white-space:normal}td small{display:block;font-size:10px;margin-top:5px}td button{font-size:11px;padding:4px 8px}.selected td{background:#f0f7f1}.score{font-size:16px;font-weight:600;color:#305e41;font-variant-numeric:tabular-nums}.selection-mark{font-size:11px;color:#347046}.empty{padding:40px 15px;text-align:center;color:#829487;font-size:13px}.error{margin:0 0 16px;padding:12px;border:1px solid #ecd8ca;border-radius:7px;color:#a05d3d;background:#fff8f4;font-size:12px;overflow-wrap:anywhere}.budget-panel .error{margin-top:14px;margin-bottom:0}.error button{margin-left:8px}summary{cursor:pointer;color:#577460;font-size:12px}.error summary,.candidate-error summary{color:#a05d3d}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.7 system-ui;max-height:260px;overflow:auto;min-width:180px;max-width:100%;margin:10px 0 0}.timeline{list-style:none;margin:0;padding:0}.timeline li{display:flex;gap:16px;position:relative;padding-bottom:24px}.round-number{border:1px solid #cfdfd3;border-radius:50%;width:28px;height:28px;display:grid;place-items:center;flex-shrink:0;background:#f1f6f2;font-size:12px}.round-body{flex:1;min-width:0;padding-bottom:20px;border-bottom:1px solid #e5ede7}.round-body .section-heading{margin-bottom:7px}.round-body p{font-size:13px;margin-bottom:8px;overflow-wrap:anywhere}.round-body details{margin-top:10px}.candidate-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0 20px}.candidate-tabs button{font-size:12px;max-width:100%;overflow-wrap:anywhere}.candidate-tabs button[aria-pressed=true]{background:#edf5ef;border-color:#80a38c;color:#285e43}.diagnostics{background:#f5f8f5;border-radius:7px;padding:12px;margin:12px 0 20px}.report-reader iframe{width:100%;height:65dvh;min-height:360px;border:1px solid #dce6df;border-radius:7px;background:#fff}.artifact-list{padding:0;list-style:none;margin:20px 0 0}.artifact-list li{display:flex;justify-content:space-between;gap:20px;padding:15px 0;border-bottom:1px solid #e5ede7}.artifact-list strong{font-size:12px;overflow-wrap:anywhere}.artifact-list a{flex-shrink:0;font-size:12px}.artifact-list li>div{min-width:0}
@media(min-width:1500px){.main-content{padding:32px 42px}.budget-panel{padding:24px 28px}}@media(max-width:1100px){.search-layout{grid-template-columns:205px minmax(0,1fr)}.main-content{padding:22px 18px}.budget-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.run-heading{align-items:flex-start}.run-heading h1{font-size:21px}.tabs{gap:16px}}@media(max-width:720px){.topbar{padding:12px 16px;font-size:12px;flex-wrap:wrap}.topbar strong{display:none}.search-layout{display:block}.sidebar{position:static;max-height:220px;border-right:0;border-bottom:1px solid #dce6df;padding:12px 16px}.sidebar .section-heading{margin-bottom:8px}.sidebar nav{display:flex;gap:8px;overflow-x:auto}.search-item{min-width:220px;max-width:220px;margin:0}.sidebar .empty{padding:12px}.main-content{padding:20px 12px}.card{padding:16px}.results{padding:0}.tab-content{padding:16px}.tabs{padding:0 16px;gap:20px}.tabs button{font-size:12px}.run-heading{flex-direction:column;gap:8px}.run-heading h1{font-size:22px}.create-form{gap:16px}.form-footer{align-items:flex-start;flex-direction:column}.form-footer button{width:100%}.subject-fields{grid-template-columns:1fr}.section-heading{align-items:flex-start;flex-wrap:wrap}.budget-grid{gap:16px}.strategy-options{grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.strategy-options label{padding:10px 5px}.budget-meta{gap:7px 16px}}
.artifact-toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;margin:20px 0 10px}.artifact-toolbar label{display:flex;align-items:center;gap:12px;font-size:12px;flex:1;min-width:220px}.artifact-toolbar input{border:1px solid #d1ddd4;border-radius:7px;padding:8px 10px;background:#fcfdfc;color:#284733;width:min(100%,350px);min-width:0}.artifact-group{margin-top:12px;border:1px solid #dce6df;border-radius:8px;overflow:hidden}.artifact-group>summary{padding:12px 14px;background:#f7faf7;overflow-wrap:anywhere}.artifact-group>summary strong{font-size:12px}.artifact-group>summary small{margin-left:12px;white-space:nowrap}.group-path{margin-left:12px;font-size:11px}.artifact-group .artifact-list{margin:0;padding:0 14px}.artifact-list li>div{display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 12px;width:100%}.artifact-list li>div>a{flex-shrink:1;overflow-wrap:anywhere;min-width:0}.artifact-description{color:#819087;font-size:12px;overflow-wrap:anywhere}.artifact-pagination{display:flex;align-items:center;justify-content:flex-end;flex-wrap:wrap;gap:12px;padding:12px 14px;color:#708477;font-size:12px}.artifact-pagination button{font-size:12px}.artifact-pagination button:disabled{cursor:default}
.budget-toggle { display: flex; justify-content: space-between; align-items: center; font-size: 14px; font-weight: 600; color: #253e43; list-style: none; }
.budget-toggle::before { content: '›'; color: #176e65; margin-right: 10px; }
.budget-panel[open] > .budget-toggle::before { transform: rotate(90deg); }
.budget-toggle span { margin-left: auto; font-size: 12px; color: #586f75; font-weight: 400; }
.budget-panel[open] > .section-heading { margin-top: 18px; }
.source-id { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@media(max-width:700px){.topbar{flex-wrap:wrap}.topbar>strong{order:-1;width:calc(100% - 100px)}.topbar>.language-switcher{order:-1}.topbar>a{font-size:12px}}
</style>
