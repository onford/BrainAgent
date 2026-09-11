<script setup lang="ts">
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
const statuses: Record<string, string> = { preparing: '准备中', running: '执行中', completed: '已完成', stopped: '已停止', failed: '失败', cancelled: '已取消', interrupted: '等待恢复', pending: '待执行', queued: '排队中', proposed: '已提议', evaluating: '评估中', evaluated: '已评估', reserved: '待执行', execution_failure: '执行失败', resource_failure: '资源不足', candidate_invalid: '候选无效', data_unevaluable: '数据不可评价', rejected: '已拒绝', skipped: '已跳过', succeeded: '成功' }
const phases: Record<string, string> = { freeze_panel: '冻结开发面板', candidate: '评估候选', decision: '选择下一步', finished: '搜索结束' }
const actionLabels: Record<string, string> = { initial_schedule: '制定初始计划', model_decision: '决定下一步', enumerate_remaining: '穷举剩余候选', invalid_proposal: '无效提议', finish: '结束搜索', request_evidence: '补充证据', propose_candidate: '提出候选' }
const stopReasons: Record<string, string> = { cancelled_by_user: '用户停止', service_interrupted: '服务中断', time_budget_exhausted: '时间预算耗尽', candidate_budget_exhausted: '候选预算耗尽', proposal_budget_exhausted: '提议预算耗尽', memory_budget_exhausted: '内存预算耗尽', disk_budget_exhausted: '磁盘预算耗尽', execution_conditions_unavailable: '执行条件不可用', reference_failed: '基线评估失败', resource_unavailable: '执行资源不可用', catalog_exhausted: '候选目录已遍历', schedule_exhausted: '计划已执行完毕', model_finished: '模型决定结束搜索' }
const strategies: Record<SearchStrategy, string> = { adaptive: '自适应', random: '随机顺序对照', exhaustive: '穷举', one_shot: '一次性提案对照' }
const assessmentAxis = ref('utility')
const resultsPanel = ref<HTMLElement>()
function navigateEvidence(view: string, candidateId?: string, axis = 'utility') {
  if (candidateId && candidates.value.some(c => c.id === candidateId)) inspectedId.value = candidateId
  assessmentAxis.value = axis
  tab.value = view
  void nextTick(() => resultsPanel.value?.scrollIntoView?.({ block: 'start' }))
}
const tabs = { overview: '决策概览', candidates: '候选比较', methods: '探索空间', assessment: '多维评价', rounds: '轮次时间线', subjects: '开发被试', artifacts: '报告 / 文件' }
const budgetFields = [
  { key: 'max_candidates', label: '候选数', min: 1, max: 256 },
  { key: 'max_proposals', label: '提议数', min: 0, max: 1024 },
  { key: 'max_evidence_reads', label: '证据读取数', min: 0, max: 256 },
  { key: 'max_seconds', label: '时限（秒）', min: 0, max: undefined },
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
const utilityLabel = computed(() => eegnetUtility.value ? 'EEGNet 三种子训练效用' : '历史 v1 三模型训练效用')
const cspEvaluation = computed(() => ['csp4_reg0.1_shrinkage_lda', 'csp-shrinkage-lda-v2'].includes(savedLearner.value ?? ''))
const evaluatorLabel = computed(() => cspEvaluation.value ? 'CSP + 收缩 LDA' : ['logvariance-scaler-logistic-v1', 'logvariance_standardizer_logistic_regression'].includes(savedLearner.value ?? '') ? '对数方差 + 标准化 + 逻辑回归' : savedLearner.value || '保存的评价器')
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
  if (active.value && current.value?.request.strategy === 'one_shot' && current.value.actions?.some(action => action.action === 'initial_schedule' && action.status === 'running')) return '制定初始计划'
  const state = current.value
  return state?.phase ? (phases[state.phase] ?? state.phase) : state ? label(state.status) : ''
})
const meters = computed(() => [
  { label: '候选', used: current.value?.usage?.candidates, limit: budget.value?.max_candidates },
  { label: '提议', used: current.value?.usage?.proposals, limit: budget.value?.max_proposals },
  { label: '证据读取', used: current.value?.usage?.evidence_reads, limit: budget.value?.max_evidence_reads },
  { label: '耗时（秒）', used: displayedElapsed.value, limit: budget.value?.max_seconds },
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
    return { key: `candidates/${parts[1]}`, path: `candidates/${parts[1]}`, title: `候选过程 · ${candidate?.title || parts[1]}` }
  }
  if (parts[0] === 'engine') {
    if (parts[1] === 'runs' && parts.length > 3) {
      const candidate = candidates.value.find(item => item.job_id === parts[2])
      return { key: `engine/runs/${parts[2]}`, path: `engine/runs/${parts[2]}`, title: `数值执行 · ${candidate?.title || candidate?.id || parts[2]}` }
    }
    const directory = parts.length > 2 ? parts[1] : ''
    const names: Record<string, string> = { objects: '对象快照', inputs: '输入快照', methods: '方法快照', plans: '执行计划', jobs: '任务记录', reports: '数值报告' }
    return { key: directory ? `engine/${directory}` : 'engine', path: directory ? `engine/${directory}` : 'engine', title: `数值文件 · ${names[directory] || directory || '执行元数据'}` }
  }
  return { key: 'core', path: '', title: '核心报告与记录' }
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
function count(value: unknown) { return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('zh-CN', { maximumFractionDigits: 1 }) : '—' }
function percent(value: unknown) { return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '—' }
function scientific(value: unknown) { return typeof value === 'number' && Number.isFinite(value) ? value.toExponential(2) : '—' }
function measurement(value: unknown) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  return value !== 0 && (Math.abs(value) < .001 || Math.abs(value) >= 1e6) ? value.toExponential(3) : value.toLocaleString('zh-CN', { maximumSignificantDigits: 6 })
}
function metricLabel(path: string): string {
  const labels: Record<string, string> = { 'assessment.selection_score': utilityLabel.value, macro_ba: 'CSP 锚点 BA', mean_delta: '相对基线平均差', secondary_macro_ba: '次要对照 BA', 'diagnostics.floor_fraction': '方差下限比例', covariance_condition: '协方差条件数', covariance_condition_before: '适配前协方差条件数', covariance_condition_after: '适配后协方差条件数', mean_channel_variance_before: '适配前平均通道方差', mean_channel_variance_after: '适配后平均通道方差', covariance_anisotropy: '协方差条件数', gate_metric_value: '门控值 Q90/Q10', gate_fraction: '条件触发比例', gate_subject_count: '门控被试数', gate_passed_subject_count: '触发被试数', effective_rank_before: '适配前有效秩', effective_rank_after: '适配后有效秩', mean_condition_before: '平均适配前条件数', mean_condition_after: '平均适配后条件数', mean_variance_before: '平均适配前方差', mean_variance_after: '平均适配后方差', mean_effective_rank: '平均适配前有效秩', mean_anisotropy: '平均谱 Q90/Q10', channel_variance: '通道方差', channel_flat_fraction: '通道平坦比例', ba: '主评分 BA', delta: '相对基线差', recall_left: '左手召回率', recall_right: '右手召回率', predicted_trials: '预测 trial 数', eligible_trials: '合格 trial 数', fit_trials: '拟合 trial 数' }
  if (labels[path]) return labels[path]
  const parts = path.split('.'), subjectIndex = parts.indexOf('subjects')
  const field = parts.at(-1) ?? path
  return subjectIndex >= 0 && parts[subjectIndex + 1] ? `${parts[subjectIndex + 1]} · ${labels[field] ?? field}` : path.startsWith('diagnostics.summary.') ? `总体 · ${labels[field] ?? field}` : labels[field] ?? path
}
function directionLabel(value: string) { return ({ increase: '增加', decrease: '减少', unchanged: '不变' } as Record<string, string>)[value] ?? value }
function checkLabel(value: string) { return ({ matched: '符合预测', contradicted: '与预测不符', unavailable: '无法核验' } as Record<string, string>)[value] ?? value }
function branchLabel(key: string) { return ({ improvement: '改善时', improved: '改善时', no_improvement: '未改善时', otherwise: '其他情况' } as Record<string, string>)[key] ?? key }
function adaptationLabel(value: SearchAdaptation | 'scale_only') { return ({ subject_scale: '逐被试统一尺度', scale_only: '保持空间结构，仅统一尺度', none: 'none · 不对齐', euclidean_alignment: 'uniformEA · 逐被试欧氏对齐', conditional_alignment: 'conditionalEA · 诊断条件对齐' })[value] }
function delta(value: unknown) { return typeof value === 'number' && Number.isFinite(value) ? `${value > 0 ? '+' : ''}${(value * 100).toFixed(1)} pp` : '—' }
function date(value: string) { return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }
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
  if (!workflowId.value.trim()) throw new Error('请填写来源流程 ID。')
  for (const field of budgetFields) {
    const value = Number(formBudget[field.key])
    if (field.key === 'max_seconds') {
      if (!Number.isFinite(value) || value <= 0) throw new Error('时限（秒）需为大于 0 的数值。')
    } else if (String(formBudget[field.key]).trim() === '' || !Number.isInteger(value) || value < field.min) {
      throw new Error(`${field.label}需为不小于 ${field.min} 的整数。`)
    }
    if (field.max != null && value > field.max) throw new Error(`${field.label}不能超过 ${field.max}。`)
  }
  if (!Number.isSafeInteger(Number(seed.value)) || String(seed.value).trim() === '' || Number(seed.value) < 0 || Number(seed.value) > 4294967295) throw new Error('随机种子需为 0–4294967295 的整数。')
  const optionalLimit = (value: string | number) => {
    if (String(value).trim() === '') return null
    if (!Number.isInteger(Number(value)) || Number(value) < 64) throw new Error('内存和磁盘预算需为至少 64 MB 的整数，或留空自动设置。')
    return Number(value)
  }
  const train = subjects(trainSubjects.value), development = subjects(developmentSubjects.value)
  if (!!train.length !== !!development.length) throw new Error('训练被试与开发被试须同时指定，或同时留空。')
  if (train.some(subject => development.includes(subject))) throw new Error('训练被试与开发被试不能重叠。')
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
    <header class="topbar"><RouterLink to="/workflows">← 数据工作区</RouterLink><strong>Brain Agent <span> / 预处理研究</span></strong><RouterLink :to="{ path: '/searches', query: current ? { workflow: current.workflow_id } : {} }">＋ 新建搜索</RouterLink></header>
    <div class="search-layout">
      <aside class="sidebar" aria-label="搜索列表">
        <div class="section-heading"><h2>搜索记录 <small>{{ searches.length }}</small></h2><button :disabled="listLoading" aria-label="刷新搜索列表" @click="loadList">↻</button></div>
        <p v-if="listError" class="error" role="alert">{{ listError }}</p>
        <p v-if="!searches.length" class="empty">{{ listLoading ? '正在载入记录…' : '暂无搜索，从已接入的数据开始。' }}</p>
        <nav aria-label="选择搜索"><RouterLink v-for="item in searches" :key="item.id" :to="{ path: '/searches', query: { id: item.id } }" class="search-item" :class="{ chosen: id === item.id }" :aria-current="id === item.id ? 'page' : undefined"><span><strong>{{ item.id }}</strong><span class="badge" :class="item.status">{{ label(item.status) }}</span></span><small class="source-id" :title="item.workflow_id">来源 {{ item.workflow_id }}</small><small>{{ date(item.created_at) }} · 候选 {{ count(item.usage?.candidates) }} / {{ count(item.budget?.max_candidates) }}</small></RouterLink></nav>
      </aside>
      <section class="main-content" :aria-busy="loading">
        <p v-if="error" class="error" role="alert">{{ error }} <button v-if="id" :disabled="busy || loading" @click="refresh()">重新连接</button></p>
        <template v-if="!id">
          <header class="page-heading"><p class="eyebrow">OFFLINE SEARCH</p><h1>预处理策略搜索</h1><p class="muted">设定有限预算，根据信号诊断比较预处理策略，保留假设、预测核验与评估记录。</p></header>
          <p class="notice">开发评估用于策略选择，不是独立测试结果，也不直接衡量神经信号质量。</p>
          <form class="card create-form" aria-label="创建预算搜索" @submit.prevent="start">
            <label class="wide">来源流程 ID<input v-model="workflowId" required aria-label="来源流程 ID" placeholder="已完成数据接入的流程 ID" /><small>使用该流程已接入的数据。</small></label>
            <p class="wide muted" aria-label="默认评估方式">默认按被试分组交叉验证，最多 5 折；全部被试各作为开发被试一次。主评分为 EEGNet 固定种子 17、42、2026 的被试平均 BA 等权均值，三个种子须全部完成；CSP-LDA 仅为基准对照，25 项信号质量与 14 项重建指标分别展示。</p><fieldset class="wide"><legend>搜索策略</legend><div class="strategy-options"><label v-for="(name, key) in strategies" :key="key" :class="{ chosen: strategy === key }"><input v-model="strategy" type="radio" name="strategy" :value="key" />{{ name }}</label></div><p v-if="strategy === 'random'" class="strategy-hint muted">随机安排候选执行顺序，最终仍按开发主评分选择。</p><p v-if="strategy === 'one_shot'" class="strategy-hint muted">LLM 在开始时一次性提出候选顺序，后续按冻结顺序执行，不根据中途评价调整提案。</p></fieldset>
            <label v-for="field in budgetFields" :key="field.key">{{ field.label }}<input v-model.number="formBudget[field.key]" type="number" :min="field.min" :max="field.max" :step="field.key === 'max_seconds' ? 'any' : 1" required :aria-label="field.label" /></label>
            <label>内存上限（MB）<input v-model="formBudget.max_memory_mb" type="number" min="64" step="1" placeholder="自动" aria-label="内存上限（MB）" /></label>
            <label>磁盘上限（MB）<input v-model="formBudget.max_disk_mb" type="number" min="64" step="1" placeholder="自动" aria-label="磁盘上限（MB）" /></label>
            <label>随机种子<input v-model.number="seed" type="number" min="0" max="4294967295" step="1" required aria-label="随机种子" /></label>
            <details class="wide optional-subjects"><summary>高级：指定训练 / 开发被试</summary><p class="muted">默认按被试分组交叉验证，最多 5 折；全部被试各作为开发被试一次。高级覆盖：同时填写两组后使用被试留出评估，须覆盖全部接入被试且互不重叠。ID 用空格或逗号分隔。</p><div class="subject-fields"><label>训练被试<input v-model="trainSubjects" aria-label="训练被试" placeholder="如 S001, S002" /></label><label>开发被试<input v-model="developmentSubjects" aria-label="开发被试" placeholder="如 S003, S004" /></label></div></details>
            <div class="form-footer wide"><span class="muted">内存、磁盘留空时自动设置。</span><button class="primary" :disabled="busy">{{ busy ? '正在创建…' : '开始预算搜索 →' }}</button></div>
          </form>
        </template>
        <template v-else-if="current">
          <header class="page-heading run-heading"><div><p class="eyebrow">OFFLINE SEARCH · {{ current.id }}</p><h1>{{ supportedSearch ? '预处理策略搜索' : '预算搜索记录' }} <span class="badge" :class="current.status">{{ label(current.status) }}</span></h1><p class="muted"><RouterLink :to="{path:'/workflows',query:{id:current.workflow_id}}">来源流程 {{ current.workflow_id }} ↗</RouterLink> · {{ strategies[current.request?.strategy] ?? current.request?.strategy ?? '—' }} · 种子 {{ current.request?.seed ?? '—' }} · 更新于 {{ date(current.updated_at) }}</p></div><div class="run-controls"><span v-if="!supportedSearch" class="muted">只读记录</span><button v-if="active" :disabled="busy" @click="control('cancel')">{{ busy ? '正在处理…' : '停止搜索' }}</button><button v-if="canRetry" class="primary" :disabled="busy" @click="control('retry')">{{ busy ? '正在处理…' : '重试搜索' }}</button></div></header>
          <p class="notice">开发评估用于策略选择，不是独立测试结果，也不直接衡量神经信号质量。</p>
          <details class="card budget-panel" :open="!terminal" aria-label="进度与预算"><summary class="budget-toggle">进度与预算 <span role="status">{{ displayedPhase }}</span></summary>
            <div class="section-heading"><h2>用量明细</h2><span>{{ current.message }}</span></div>
            <div class="budget-grid"><div v-for="meter in meters" :key="meter.label" class="meter"><div><span>{{ meter.label }}</span><strong>{{ count(meter.used) }} <small>/ {{ count(meter.limit) }}</small></strong></div><div class="meter-track" role="progressbar" :aria-label="meter.label" :aria-valuenow="meter.used == null || meter.limit == null ? undefined : ratio(meter.used, meter.limit)" aria-valuemin="0" aria-valuemax="100" :aria-valuetext="`${count(meter.used)} / ${count(meter.limit)}`"><i :style="{ width: `${ratio(meter.used, meter.limit)}%` }" /></div></div></div>
            <div class="budget-meta"><span>LLM 调用 {{ count(current.usage?.llm_calls) }}</span><span>重试 {{ count(current.usage?.retries) }}</span><span>内存 {{ !budget ? '—' : budget.max_memory_mb == null ? '自动' : `${count(budget.max_memory_mb)} MB` }}</span><span>磁盘 {{ !budget ? '—' : budget.max_disk_mb == null ? '自动' : `${count(budget.max_disk_mb)} MB` }}</span><span>开发评估选中 {{ current.selected_candidate_id || '尚未选择' }}</span></div>
            <p v-if="current.stop_reason" class="stop-reason">停止原因：{{ stopReasons[current.stop_reason] ?? current.stop_reason }}</p>
            <details v-if="current.error" class="error"><summary>搜索错误</summary><pre>{{ current.error }}</pre></details>
            <p v-if="typeof current.panel === 'string'" class="panel-summary">开发面板：{{ current.panel }}</p>
            <details v-else-if="panel" class="panel-summary" aria-label="评估面板">
              <summary>评估范围 · {{ count(panelDevelopmentCount) }} 名{{ panel.evaluation_mode === 'group_cross_validation' ? '被试' : '开发被试' }} · {{ count(panel.eligible_count) }} 个试次 <template v-if="panel.folds?.length">· {{ panel.folds.length }} 折</template><span class="muted"> · 查看划分</span></summary>
              <h3>{{ panel.evaluation_mode === 'group_cross_validation' ? '按被试分组交叉验证' : panel.evaluation_mode === 'subject_holdout' ? '被试留出评估' : '开发评估面板' }}</h3>
              <p v-if="panel.evaluation_mode === 'group_cross_validation'">{{ panel.folds?.length ?? '—' }} 折 · 每名被试作为开发被试一次。训练被试按折确定，各折训练与开发被试互不重叠。</p>
              <p v-else-if="panel.evaluation_mode === 'subject_holdout'">使用显式指定的训练与开发被试；学习器只在训练被试上拟合，开发被试用于策略选择。</p>
              <div class="budget-meta"><span v-if="panel.evaluation_mode !== 'group_cross_validation'">训练被试 {{ count(panelTrainCount) }}</span><span>{{ panel.evaluation_mode === 'group_cross_validation' ? '参与交叉验证的被试' : '开发被试' }} {{ count(panelDevelopmentCount) }}</span><span>原始 trial {{ count(panel.trial_count) }}</span><span>合格 trial {{ count(panel.eligible_count) }}</span></div>
              <div v-if="panel.folds?.length" class="table-scroll"><table class="fold-table" aria-label="评估折次"><thead><tr><th>折次</th><th>训练被试</th><th>开发被试</th></tr></thead><tbody><tr v-for="fold in panel.folds" :key="fold.id"><td>{{ fold.id }}</td>
                <td v-for="group in [{ role: '训练', subjects: fold.train_subjects }, { role: '开发', subjects: fold.development_subjects }]" :key="group.role">
                  <details class="fold-subjects"><summary :aria-label="`${fold.id} ${group.role}被试：${group.subjects.length} 人，查看完整名单`">{{ group.subjects.length }} 人</summary><ul class="fold-subject-list" tabindex="0" :aria-label="`${fold.id} ${group.role}被试完整名单`"><li v-for="subject in group.subjects" :key="subject">{{ subject }}</li></ul></details>
                </td>
              </tr></tbody></table></div>
              <details><summary>开发面板详情</summary><pre>{{ detail(panel) }}</pre></details>
            </details>
            <details v-if="current.request?.train_subjects?.length || current.request?.development_subjects?.length" class="panel-summary"><summary>被试划分</summary><p>训练：{{ current.request.train_subjects?.join('、') || '自动分配' }}</p><p>开发：{{ current.request.development_subjects?.join('、') || '自动分配' }}</p></details>
          </details>
          <details class="card evaluator-summary" aria-label="评分与适配含义">
            <summary>评分与适配 <span class="muted">· {{ multiMetric ? `${utilityLabel}、信号质量、重建实验` : evaluatorLabel }}</span></summary><p v-if="!cspEvaluation">评价器：{{ evaluatorLabel }}。分数与选择结果按保存的记录展示。</p>
            <p v-if="eegnetUtility">主评分取 EEGNet 种子 17、42、2026 的被试宏平均 BA 等权均值，三个种子须全部完成。CSP-LDA 仅为基准对照；25 项质量与 14 项重建指标独立呈现。</p><p v-else-if="multiMetric">历史 v1：主评分取 CSP-LDA、FBCSP、TS-LR 三个被试宏平均 BA 的等权均值，三种模型须完整。质量和重建实验独立呈现；CSP 明细作为共同锚点保留。</p><p v-else-if="cspEvaluation">主评分为 CSP + 收缩 LDA 的被试平均 BA：先计算每名开发被试的左右手平衡准确率，再对被试等权平均。CSP 与分类器在每折训练被试上拟合。</p>
            <p v-if="cspEvaluation && !eegnetUtility">次要对照使用 log-variance（对数方差）+ Logistic Regression（逻辑回归），用于检查表示与预测行为。</p>
            <p v-if="cspEvaluation">策略比较：公共处理、逐被试统一尺度、统一规则逐被试对齐、按信号诊断条件对齐。个体参数由各被试自己的整批无标签数据离线拟合；条件策略未触发对齐时保持空间结构，仅统一尺度，确保各被试均为无量纲表示。整批数据适配与在线逐试次预测的条件不同。</p>
          </details>
          <section ref="resultsPanel" class="card results">
            <nav class="tabs" aria-label="搜索结果视图"><button v-for="(name, key) in tabs" :key="key" :aria-pressed="tab === key" @click="tab = key">{{ name }}<small v-if="key === 'candidates'">{{ candidates.length }}</small><small v-if="key === 'rounds'">{{ actions.length }}</small><small v-if="key === 'artifacts'">{{ artifacts.length }}</small></button></nav>
            <section v-if="tab === 'overview'" class="tab-content"><SearchDecisionOverview :state="current" @navigate="navigateEvidence" /></section>
            <section v-else-if="tab === 'methods'" class="tab-content"><SearchMethodExplorer :entries="current.registry ?? []" :space="current.protocol?.space" /></section>
            <section v-else-if="tab === 'assessment'" class="tab-content"><div class="section-heading"><h2>候选的多维评价</h2><label>候选 <select :value="inspected?.id" @change="inspectedId = ($event.target as HTMLSelectElement).value"><option v-for="candidate in candidates" :key="candidate.id" :value="candidate.id">{{ candidate.title || candidate.id }}</option></select></label></div><SearchOperatorUsage v-if="inspected" :search-id="current.id" :candidate-id="inspected.id" :usage="inspected.receipt?.operator_usage" /><SearchAssessment v-if="inspected" :initial-axis="assessmentAxis" :guide-frozen="!!current.protocol?.interpretation_guide_hash" :search-id="current.id" :candidate-id="inspected.id" :base-path="inspected.receipt?.assessment_path" :assessment="inspected.receipt?.assessment"><template #parameters><SearchParameters :expanded="assessmentAxis === 'parameters'" :protocol="current.protocol" :panel="panel" :recipe="current.registry?.find(r => r.id === inspected?.id)?.recipe" /></template></SearchAssessment></section>
            <section v-else-if="tab === 'candidates'" class="tab-content" aria-label="候选比较">
              <div class="section-heading"><h2>策略开发 BA 比较</h2><span class="muted">{{ multiMetric ? `主指标：${utilityLabel} · Δ 为 CSP 锚点相对基线的百分点` : `评价器：${evaluatorLabel} · 被试平均 BA · Δ 为相对基线的百分点` }}</span></div>
              <div v-if="candidates.length" class="table-scroll"><table><thead><tr><th>候选 / 参数</th><th>状态</th><th>主评分 BA</th><th>次要对照 BA</th><th>平均 Δ</th><th>覆盖（预测 / 合格）</th><th>选择</th><th>详情</th></tr></thead><tbody><tr v-for="candidate in candidates" :key="candidate.id" :class="{ selected: candidate.id === current.selected_candidate_id }"><td><strong>{{ candidate.title || candidate.id }}</strong><small v-if="multiMetric">{{ recipeSummary(candidate.id) || candidate.id }}</small><small v-else>{{ candidate.id }} · {{ candidate.parameters?.l_freq ?? '—' }}–{{ candidate.parameters?.h_freq ?? '—' }} Hz · {{ candidate.parameters?.reference === 'average' ? '平均参考' : candidate.parameters?.reference === 'original' ? '原始参考' : '参考未知' }}</small><small v-if="candidate.parameters?.adaptation">{{ adaptationLabel(candidate.parameters.adaptation) }}<template v-if="candidate.parameters.adaptation === 'conditional_alignment' && candidate.parameters.alignment_threshold != null"> · 条件阈值 {{ count(candidate.parameters.alignment_threshold) }}</template></small></td><td>{{ label(candidate.status) }}<small v-if="candidate.receipt?.status">回执：{{ label(candidate.receipt.status) }}</small><details v-if="candidate.error" class="candidate-error"><summary>错误</summary><pre>{{ candidate.error }}</pre></details></td><td class="score">{{ percent(multiMetric ? candidate.receipt?.assessment?.selection_score : candidate.receipt?.macro_ba) }}<small v-if="multiMetric">CSP 锚点 {{ percent(candidate.receipt?.macro_ba) }}</small></td><td>{{ percent(candidate.receipt?.secondary_macro_ba) }}</td><td>{{ delta(candidate.receipt?.mean_delta) }}<small v-if="candidate.receipt?.paired_subject_ci">描述性区间 {{ delta(candidate.receipt.paired_subject_ci.low) }} ～ {{ delta(candidate.receipt.paired_subject_ci.high) }}<br />{{ candidate.receipt.paired_subject_ci.n_subjects }} 名配对被试 · 开发比较</small></td><td>{{ count(candidate.receipt?.coverage?.predicted) }} / {{ count(candidate.receipt?.coverage?.eligible) }}</td><td><span v-if="candidate.id === current.selected_candidate_id" class="selection-mark">✓ 开发评估选中</span><span v-else class="muted">—</span></td><td><button :aria-label="`查看候选 ${candidate.id} 的开发被试`" @click="inspectedId = candidate.id; tab = 'subjects'">查看被试 →</button></td></tr></tbody></table></div>
              <p v-else class="empty">尚无候选。搜索开始后将在此展示参数与开发面板评估。</p>
            </section>
            <section v-else-if="tab === 'rounds'" class="tab-content" aria-label="轮次时间线"><div class="section-heading"><h2>每轮决策与结果</h2><span class="muted">按执行记录顺序</span></div><ol v-if="actions.length" class="timeline"><li v-for="action in actions" :key="action.index"><span class="round-number">{{ action.index }}</span><div class="round-body"><div class="section-heading"><h3>{{ actionLabels[action.action] ?? action.action }}</h3><span>{{ label(action.status) }} · {{ count(action.cost_seconds) }} 秒</span></div><p>{{ action.reason || '暂无决策说明' }}</p><p v-if="action.base_candidate_id || action.candidate_id" class="muted">{{ action.base_candidate_id || '起始' }} → {{ action.candidate_id || '—' }}</p><section v-if="action.request?.hypothesis" class="hypothesis" aria-label="机制假设">
                <h4>机制假设</h4><p>{{ action.request.hypothesis.explanation }}</p>
                <h4>竞争解释</h4><p>{{ action.request.hypothesis.competing_explanation }}</p>
                <h4>观测依据</h4><ul class="observations"><li v-for="(observation, index) in action.request.hypothesis.observations" :key="index"><span>{{ candidates.find(candidate => candidate.id === observation.candidate_id)?.title || observation.candidate_id }}</span> · <span :title="observation.metric">{{ metricLabel(observation.metric) }}</span></li></ul>
                <h4>预先登记的预测</h4><ul class="predictions"><li v-for="(prediction, index) in action.request.hypothesis.predictions" :key="index"><strong>{{ prediction.kind === 'signal' ? '信号预测' : '效用预测' }} · {{ metricLabel(prediction.metric) }} {{ directionLabel(prediction.direction) }}</strong><span class="muted"> · 容差 {{ measurement(prediction.tolerance) }}</span><p>{{ prediction.explanation }}</p></li></ul>
                <h4>削弱该解释的结果</h4><p>{{ action.request.hypothesis.weakened_by }}</p>
              </section>
              <section v-if="action.result?.prediction_checks" class="prediction-checks" aria-label="实测预测核验">
                <h4>实测预测核验</h4>
                <div v-if="action.result.prediction_checks.checks.length" class="table-scroll"><table><thead><tr><th>预测</th><th>核验状态</th><th>之前</th><th>之后</th><th>实测差值</th><th>容差</th></tr></thead><tbody><tr v-for="(check, index) in action.result.prediction_checks.checks" :key="index"><td class="readable-cell"><strong>{{ check.kind === 'signal' ? '信号' : '效用' }} · {{ metricLabel(check.metric) }}</strong><small>预期{{ directionLabel(check.direction) }} · {{ check.explanation }}</small></td><td><span class="check-status" :class="check.status">{{ checkLabel(check.status) }}</span></td><td>{{ measurement(check.before) }}</td><td>{{ measurement(check.after) }}</td><td>{{ measurement(check.difference) }}</td><td>{{ measurement(check.tolerance) }}</td></tr></tbody></table></div>
                <p v-else class="muted">暂无可核验的预测。</p><p class="muted">{{ action.result.prediction_checks.interpretation }}</p>
              </section>
<div v-if="action.expected_result != null || action.decision_branches != null" class="hypothesis"><h4>假设与预期结果</h4><p v-if="action.expected_result != null">{{ detail(action.expected_result) }}</p><dl v-if="action.decision_branches && typeof action.decision_branches === 'object'"><template v-for="(branch, key) in action.decision_branches" :key="key"><dt>{{ branchLabel(String(key)) }}</dt><dd>{{ detail(branch) }}</dd></template></dl><p v-else-if="action.decision_branches != null">{{ detail(action.decision_branches) }}</p></div><p v-if="action.result?.status" class="muted">执行结果：{{ label(String(action.result.status)) }}</p><div v-if="Array.isArray(action.result?.excerpts)" class="evidence-excerpts"><p v-for="(excerpt, index) in action.result.excerpts" :key="index">{{ excerpt }}</p></div><details v-if="action.error" class="error"><summary>本轮错误</summary><pre>{{ action.error }}</pre></details></div></li></ol><p v-else class="empty">尚无轮次记录。</p></section>
            <section v-else-if="tab === 'subjects'" class="tab-content" aria-label="开发被试明细"><h2>开发被试明细</h2><nav v-if="candidates.length" class="candidate-tabs" aria-label="查看候选"><button v-for="candidate in candidates" :key="candidate.id" :aria-pressed="inspected?.id === candidate.id" @click="inspectedId = candidate.id">{{ candidate.title || candidate.id }}<span v-if="candidate.id === current.selected_candidate_id"> · 开发评估选中</span></button></nav><template v-if="inspected"><div class="section-heading"><h3>{{ inspected.title || inspected.id }}</h3><span class="muted">任务 {{ inspected.job_id || '—' }}</span></div><div class="diagnostics"><span>原始（开发） {{ count(inspected.receipt?.coverage?.original) }}</span><span>合格（开发） {{ count(inspected.receipt?.coverage?.eligible) }}</span><span>预测（开发） {{ count(inspected.receipt?.coverage?.predicted) }}</span><span>缺失 {{ count(inspected.receipt?.coverage?.missing) }}</span><span>下限比例 {{ percent(inspected.receipt?.diagnostics?.floor_fraction) }}</span><span>收敛 {{ inspected.receipt?.diagnostics?.converged === true ? '是' : inspected.receipt?.diagnostics?.converged === false ? '否' : '—' }}</span></div><details v-if="inspected.receipt?.diagnostics?.warnings?.length" class="panel-summary"><summary>诊断警告（{{ inspected.receipt.diagnostics.warnings.length }}）</summary><ul><li v-for="(warning, index) in inspected.receipt.diagnostics.warnings" :key="index">{{ warning }}</li></ul></details><details v-if="inspected.receipt?.coverage?.train || inspected.receipt?.coverage?.development" class="panel-summary"><summary>训练 / 开发覆盖明细</summary><pre>{{ detail(inspected.receipt.coverage) }}</pre></details><section v-if="signalRows.length" class="diagnostic-section" aria-label="信号诊断">
                <h3>信号诊断</h3><p class="muted">逐被试展示适配前的通道方差和平坦比例，以及适配前后的协方差条件数、平均方差与有效秩。</p>
                <div v-if="diagnosticSummary" class="diagnostics" aria-label="诊断总体均值"><span>平均条件数 {{ measurement(diagnosticSummary.mean_condition_before) }} → {{ measurement(diagnosticSummary.mean_condition_after) }}</span><span>平均通道方差 {{ scientific(diagnosticSummary.mean_variance_before) }} → {{ scientific(diagnosticSummary.mean_variance_after) }}</span><span>平均有效秩（适配前） {{ measurement(diagnosticSummary.mean_effective_rank) }}</span><span>平均谱 Q90/Q10 {{ measurement(diagnosticSummary.mean_anisotropy) }}</span><span>条件触发比例 {{ diagnosticSummary.gate_fraction === null ? '不适用' : percent(diagnosticSummary.gate_fraction) }}</span></div>
                <div class="table-scroll"><table><thead><tr><th>被试</th><th>协方差条件数（前 → 后）</th><th>平均通道方差（前 → 后）</th><th>有效秩（前 → 后）</th><th>适配前通道诊断</th></tr></thead><tbody><tr v-for="row in signalRows" :key="row.subject"><td>{{ row.subject }}</td><td>{{ measurement(row.covariance_condition_before ?? row.covariance_condition) }} → {{ measurement(row.covariance_condition_after) }}</td><td>{{ scientific(row.mean_channel_variance_before) }} → {{ scientific(row.mean_channel_variance_after) }}</td><td>{{ count(row.effective_rank_before) }} → {{ count(row.effective_rank_after) }}</td><td><details><summary>查看 {{ row.channel_variance.length }} 个通道</summary><ul class="channel-diagnostics"><li v-for="(variance, index) in row.channel_variance" :key="index">{{ diagnosticChannels[index] ?? `通道 ${index + 1}` }} · 方差 {{ scientific(variance) }} · 平坦比例 {{ percent(row.channel_flat_fraction[index]) }}</li></ul></details></td></tr></tbody></table></div>
              </section>
              <section v-if="representation && adaptationRows.length" class="diagnostic-section" aria-label="逐被试适配">
                <h3>逐被试适配 · {{ adaptationLabel(representation.policy.adaptation) }}</h3><p class="muted">{{ representation.transductive ? '使用每名被试整批无标签数据拟合。' : '按保存的策略保留输入表示。' }}<template v-if="representation.policy.adaptation === 'conditional_alignment'">门控值为归一化收缩协方差谱的 Q90/Q10，达到阈值 {{ measurement(representation.policy.alignment_threshold) }} 时触发；协方差条件数单独展示。阈值为预先声明的工程参数。</template></p>
                <p class="muted" aria-label="条件触发比例">条件触发比例：<template v-if="representation.policy.adaptation === 'conditional_alignment'">{{ percent(representation.gate_fraction) }} · {{ count(representation.gate_passed_subject_count) }} / {{ count(representation.gate_subject_count) }} 名被试（全部所选被试）</template><template v-else>不适用</template></p>
                <div class="table-scroll"><table><thead><tr><th>被试</th><th>实际适配</th><th>协方差条件数</th><th>门控值 Q90/Q10</th><th>条件满足</th><th>拟合 trial</th><th>输出单位</th><th>回退说明</th></tr></thead><tbody><tr v-for="row in adaptationRows" :key="row.subject"><td>{{ row.subject }}</td><td>{{ representation.policy.adaptation === 'conditional_alignment' && !row.gate_passed ? '保持空间结构，仅统一尺度' : adaptationLabel(row.applied_adaptation) }}</td><td>{{ measurement(row.covariance_anisotropy) }}</td><td>{{ measurement(row.gate_metric_value) }}</td><td>{{ representation.policy.adaptation === 'conditional_alignment' ? (row.gate_passed ? '是' : '否') : '不适用' }}</td><td>{{ count(row.fit_trials) }}</td><td>{{ row.unit === 'V' ? 'V' : '无量纲' }}</td><td class="readable-cell">{{ row.fallback_reason || '—' }}</td></tr></tbody></table></div>
              </section><p v-if="inspected.error" class="error">{{ inspected.error }}</p><div v-if="subjectRows.length" class="table-scroll"><table><thead><tr><th>开发被试</th><th>{{ multiMetric ? 'CSP 锚点 BA' : '主评分 BA' }}</th><th>次要对照 BA</th><th>Δ（百分点）</th><th>预测 / 合格</th><th>完整记录</th></tr></thead><tbody><tr v-for="subject in subjectRows" :key="subject.subject"><td>{{ subject.subject }}</td><td class="score">{{ percent(subject.ba) }}</td><td>{{ percent(inspected.receipt?.secondary_subjects?.[subject.subject]) }}</td><td>{{ delta(subject.delta) }}</td><td>{{ count(subject.predicted_trials) }} / {{ count(subject.eligible_trials) }}</td><td><details><summary>查看记录</summary><pre>{{ detail(subject) }}</pre></details></td></tr></tbody></table></div><p v-else class="empty">该候选暂无开发被试回执。</p></template><p v-else class="empty">候选生成后可查看开发被试。</p></section>
            <section v-else class="tab-content" aria-label="报告与文件"><div class="section-heading"><h2>报告与文件</h2><button :disabled="artifactsLoading || busy" @click="refreshFiles">{{ artifactsLoading ? '正在刷新文件…' : '刷新文件' }}</button></div><p v-if="supportedSearch && terminal && !finalArtifactsReady" class="notice" role="status"><template v-if="artifactRetries < maxArtifactRetries || artifactsLoading">正在整理产物，等待报告与文件索引。自动检查 {{ artifactRetries }} / {{ maxArtifactRetries }} 次。</template><template v-else>自动检查已达 {{ maxArtifactRetries }} 次，部分产物仍未就绪。请稍后点击“刷新文件”。</template></p><div v-if="reports.length" class="report-reader"><nav class="candidate-tabs" aria-label="选择搜索报告"><button v-for="item in reports" :key="item.name" :aria-pressed="report?.name === item.name" @click="reportName = item.name">{{ item.description || item.name }}</button></nav><iframe v-if="report && searchArtifactUrl(current.id, report, false)" :key="`${current.id}/${report.name}`" :src="searchArtifactUrl(current.id, report, false)" :title="report.description || report.name" sandbox="allow-same-origin" /></div><div v-if="artifacts.length" class="artifact-browser">
                <div class="artifact-toolbar"><label>查找文件<input v-model="artifactQuery" type="search" aria-label="查找搜索文件" placeholder="文件名、候选 ID 或说明…" /></label><span class="muted">{{ matchedArtifacts.length }} / {{ artifacts.length }} 个文件</span></div>
                <p class="muted">核心文件直接展示；候选过程和数值文件按组展开，每页最多 30 个。</p>
                <details v-for="group in artifactGroups" :key="`${current.id}/${group.key}`" class="artifact-group" :data-group="group.key" :open="artifactGroupOpen(group.key)">
                  <summary @click.prevent="artifactOpened[group.key] = !artifactGroupOpen(group.key)"><strong>{{ group.title }}</strong><span v-if="group.path" class="muted group-path">{{ group.path }}</span><small>{{ group.files.length }} 个文件</small></summary>
                  <template v-if="artifactGroupOpen(group.key)">
                    <ul class="artifact-list"><li v-for="artifact in artifactPageFiles(group)" :key="artifact.name"><div><a v-if="searchArtifactUrl(current.id, artifact)" :href="searchArtifactUrl(current.id, artifact)" target="_blank" rel="noopener noreferrer">{{ artifact.name }}</a><strong v-else>{{ artifact.name }}</strong><span class="artifact-description">{{ artifact.description || '搜索产物' }}</span></div><span v-if="!searchArtifactUrl(current.id, artifact)" class="muted">链接不可用</span></li></ul>
                    <nav v-if="group.files.length > artifactPageSize" class="artifact-pagination" :aria-label="`${group.title} 文件分页`"><button :disabled="artifactPage(group) === 1" @click="artifactPages[group.key] = artifactPage(group) - 1">上一页</button><span>第 {{ artifactPage(group) }} / {{ artifactPageCount(group) }} 页 · 共 {{ group.files.length }} 个</span><button :disabled="artifactPage(group) === artifactPageCount(group)" @click="artifactPages[group.key] = artifactPage(group) + 1">下一页</button></nav>
                  </template>
                </details>
                <p v-if="!matchedArtifacts.length" class="empty">没有匹配的文件，请尝试其他文件名或说明。</p>
              </div><p v-else class="empty">尚无报告或文件，生成后会自动显示。</p></section>
          </section>
        </template>
        <p v-else class="empty">{{ loading ? '正在载入搜索…' : '未能载入搜索，请重新连接。' }}</p>
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
</style>
