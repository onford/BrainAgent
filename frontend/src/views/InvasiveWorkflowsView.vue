<script setup lang="ts">
import { computed, nextTick, onMounted, ref, shallowRef, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { apiRequest } from '../api/client'
import {
  invasiveArtifactUrl,
  type InvasivePlan,
  type InvasiveRef,
  type InvasiveRunDetail,
  type InvasiveRunSummary,
  type InvasiveSnapshot,
} from '../api/invasive'
import { renderMarkdown } from '../utils/markdown'

type View = 'overview' | 'survey' | 'plan' | 'qc' | 'alignment' | 'results' | 'report' | 'files'
type LiveStage = 'survey' | 'plan' | 'qc' | 'alignment' | 'transform' | 'validate' | 'report' | ''
type QcRow = { unit_id: string | number; retained: boolean; reasons: string[]; metrics?: Record<string, number> }

const route = useRoute()
const router = useRouter()
const runs = ref<InvasiveRunSummary[]>([])
const current = shallowRef<InvasiveRunDetail | null>(null)
const draftSnapshot = shallowRef<InvasiveSnapshot | null>(null)
const draftPlan = shallowRef<InvasivePlan | null>(null)
const selectedId = ref('')
const roots = ref<string[]>([])
const source = ref('')
const task = ref('生成用于行为解码的 T×N 神经活动矩阵')
const binMs = ref(20)
const smoothingMs = ref<number | null>(null)
const runBaseline = ref(true)
const hashSource = ref(false)
const busy = ref(false)
const error = ref('')
const liveStage = ref<LiveStage>('')
const view = ref<View>('overview')
const dialog = ref<HTMLDialogElement>()
const qcRows = shallowRef<QcRow[] | null>(null)
const qcQuery = ref('')
const qcLimit = ref(200)
const reportText = ref('')
const artifactLoading = ref(false)

const snapshot = computed(() => current.value?.snapshot ?? draftSnapshot.value)
const plan = computed(() => current.value?.plan ?? draftPlan.value)
const result = computed(() => current.value?.result)
const baseline = computed(() => result.value?.validation?.baseline)
const matrixShape = computed(() => result.value?.final_shapes?.neural_matrix)
const targetShape = computed(() => result.value?.final_shapes?.aligned_target)
const r2 = computed(() => baseline.value?.r2 ?? [])
const positiveR2 = computed(() => r2.value.filter(value => typeof value === 'number' && value > 0).length)
const overlap = computed(() => result.value?.alignment?.target?.neural_coverage_overlap_ratio)
const maskCoverage = computed(() => result.value?.alignment?.evaluation_mask?.covered_fraction)
const filteredQcRows = computed(() => {
  const query = qcQuery.value.trim().toLowerCase()
  if (!query) return qcRows.value ?? []
  return (qcRows.value ?? []).filter(row =>
    `${row.unit_id} ${row.retained ? 'retained 保留' : 'removed 删除'} ${(row.reasons ?? []).join(' ')}`.toLowerCase().includes(query),
  )
})
const visibleQcRows = computed(() => filteredQcRows.value.slice(0, qcLimit.value))
const stages = computed(() => {
  const names: Array<{ id: LiveStage; label: string }> = [
    { id: 'survey', label: 'Survey' }, { id: 'plan', label: 'Plan' },
    { id: 'qc', label: 'QC' }, { id: 'alignment', label: 'Alignment' },
    { id: 'transform', label: 'Transform' }, { id: 'validate', label: 'Validate' },
    { id: 'report', label: 'Report' },
  ]
  const order = names.findIndex(item => item.id === liveStage.value)
  return names.map((item, index) => {
    let status = 'pending'
    if (current.value) status = 'completed'
    else if (busy.value && index < order) status = 'completed'
    else if (busy.value && index === order) status = 'running'
    else if (draftPlan.value && item.id !== 'survey' && item.id !== 'plan') {
      const step = draftPlan.value.steps.find(candidate => candidate.stage === item.id)
      status = step?.status === 'blocked' ? 'blocked' : 'pending'
    } else if (draftPlan.value || (draftSnapshot.value && item.id === 'survey')) status = 'completed'
    return { ...item, status }
  })
})
const tabs: Array<{ id: View; label: string }> = [
  { id: 'overview', label: '概览' }, { id: 'survey', label: '数据调研' },
  { id: 'plan', label: '处理计划' }, { id: 'qc', label: 'QC' },
  { id: 'alignment', label: '时间对齐' }, { id: 'results', label: '结果与可视化' },
  { id: 'report', label: '报告' }, { id: 'files', label: '文件' },
]

function fmt(value: unknown, digits = 3) {
  return typeof value === 'number' && Number.isFinite(value)
    ? value.toLocaleString('zh-CN', { maximumFractionDigits: digits }) : '—'
}
function bytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / 1024 ** 2).toFixed(1)} MiB`
}
function date(value?: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN') : '历史结果'
}
function shape(value?: number[] | null) { return value?.join(' × ') ?? '—' }
function percent(value: unknown) { return typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '—' }
function r2Style(value: number | null) {
  if (typeof value !== 'number') return {}
  const bounded = Math.max(-1, Math.min(1, value))
  return bounded >= 0
    ? { left: '50%', width: `${bounded * 50}%` }
    : { left: `${50 + bounded * 50}%`, width: `${-bounded * 50}%` }
}
function artifactUrl(name: string) {
  return current.value ? invasiveArtifactUrl(current.value.result_ref.id, name) : ''
}

async function refreshRuns() {
  runs.value = await apiRequest<InvasiveRunSummary[]>('/api/preprocessing/invasive/results')
}
async function select(id: string) {
  selectedId.value = id
  error.value = ''
  qcRows.value = null
  reportText.value = ''
  draftSnapshot.value = null
  draftPlan.value = null
  await router.replace({ path: '/invasive', query: { id } })
  current.value = await apiRequest<InvasiveRunDetail>(`/api/preprocessing/invasive/results/${encodeURIComponent(id)}/detail`)
}
async function loadArtifact(name: string) {
  if (!current.value || artifactLoading.value) return
  artifactLoading.value = true
  try {
    const response = await fetch(artifactUrl(name))
    if (!response.ok) throw new Error(`读取 ${name} 失败`)
    if (name === 'report.md') reportText.value = await response.text()
    else if (name === 'qc-decisions.json') qcRows.value = await response.json()
  } catch (reason) { error.value = String(reason) }
  finally { artifactLoading.value = false }
}
watch(view, value => {
  if (value === 'qc' && qcRows.value === null) void loadArtifact('qc-decisions.json')
  if (value === 'report' && !reportText.value) void loadArtifact('report.md')
})
watch(qcQuery, () => { qcLimit.value = 200 })

async function start() {
  if (busy.value || !source.value.trim() || !task.value.trim()) return
  busy.value = true
  error.value = ''
  current.value = null
  selectedId.value = ''
  draftSnapshot.value = null
  draftPlan.value = null
  qcRows.value = null
  reportText.value = ''
  view.value = 'overview'
  dialog.value?.close()
  try {
    liveStage.value = 'survey'
    const inspected = await apiRequest<{ snapshot_ref: InvasiveRef; snapshot: InvasiveSnapshot }>('/api/preprocessing/invasive/inspect', {
      method: 'POST', body: JSON.stringify({ path: source.value.trim(), hash_source: hashSource.value }),
    })
    draftSnapshot.value = inspected.snapshot
    liveStage.value = 'plan'
    const transform: Record<string, unknown> = { bin_size_s: Number(binMs.value) / 1000, run_baseline: runBaseline.value }
    if (typeof smoothingMs.value === 'number' && smoothingMs.value > 0) transform.smoothing_sigma_s = smoothingMs.value / 1000
    const planned = await apiRequest<{ plan_ref: InvasiveRef; plan: InvasivePlan }>('/api/preprocessing/invasive/plans', {
      method: 'POST', body: JSON.stringify({ snapshot_ref: inspected.snapshot_ref, task: task.value.trim(), transform }),
    })
    draftPlan.value = planned.plan
    if (!planned.plan.executable) {
      error.value = '当前计划需要补充实验或方法证据，已停止在 Plan 阶段；请查看阻塞步骤。'
      view.value = 'plan'
      return
    }
    liveStage.value = 'qc'
    await nextTick()
    liveStage.value = 'transform'
    const completed = await apiRequest<{ result_ref: InvasiveRef }>('/api/preprocessing/invasive/runs', {
      method: 'POST', body: JSON.stringify({ plan_ref: planned.plan_ref }),
    })
    liveStage.value = 'report'
    await refreshRuns()
    await select(completed.result_ref.id)
  } catch (reason) { error.value = String(reason) }
  finally { busy.value = false; liveStage.value = '' }
}

onMounted(async () => {
  try {
    const [settings] = await Promise.all([
      apiRequest<{ allowed_roots: string[] }>('/api/preprocessing/invasive/sources'),
      refreshRuns(),
    ])
    roots.value = settings.allowed_roots
    source.value = roots.value[0] ?? ''
    const id = typeof route.query.id === 'string' ? route.query.id : runs.value[0]?.result_ref.id
    if (id) await select(id)
  } catch (reason) { error.value = String(reason) }
})
</script>

<template>
  <main class="invasive-page">
    <header class="topbar">
      <div class="brand"><RouterLink to="/">←</RouterLink><span class="brand-mark">B</span><div><strong>Brain Agent</strong><small>INVASIVE DATA WORKSPACE</small></div></div>
      <div class="actions"><RouterLink to="/workflows">EEG workflows</RouterLink><label><span>当前运行</span><select :value="selectedId" aria-label="选择侵入式数据运行" @change="select(($event.target as HTMLSelectElement).value)"><option value="">暂无保存结果</option><option v-for="item in runs" :key="item.result_ref.id" :value="item.result_ref.id">{{item.dataset_id}} · {{date(item.created_at)}} · {{item.result_ref.id.slice(0,6)}}</option></select></label><button class="primary" @click="dialog?.showModal()">＋ 新建处理</button></div>
    </header>

    <p v-if="error" class="error" role="alert">{{error}}</p>

    <section v-if="snapshot || busy" class="progress-panel">
      <div class="run-heading"><div><p class="eyebrow">{{snapshot?.modality ?? 'INSPECTING NWB'}}</p><h1>{{snapshot?.dataset_id ?? '正在读取数据结构…'}}</h1><p>{{snapshot?.subject_id ?? '—'}} · {{snapshot?.session_id ?? '—'}} · {{plan?.task ?? task}}</p></div><span class="status" :class="{ running: busy }">{{busy ? '处理中' : current ? '已完成' : '需要处理'}}</span></div>
      <ol class="stages"><li v-for="(item,index) in stages" :key="item.id" :class="item.status"><span>{{item.status==='completed'?'✓':item.status==='blocked'?'!':index+1}}</span><strong>{{item.label}}</strong><small>{{item.status==='completed'?'完成':item.status==='running'?'执行中':item.status==='blocked'?'阻塞':'等待'}}</small></li></ol>
    </section>

    <section v-if="snapshot || busy" class="workspace">
      <nav class="tabs"><button v-for="tab in tabs" :key="tab.id" :aria-pressed="view===tab.id" :disabled="!snapshot" @click="view=tab.id">{{tab.label}}<span v-if="tab.id==='files'">{{current?.artifacts.length ?? 0}}</span></button></nav>
      <div class="content">
        <section v-if="view==='overview'" class="overview">
          <div class="metric-grid"><article><small>数据模态</small><strong>{{snapshot?.modality ?? '—'}}</strong><span>{{plan?.input_representation ?? '读取中'}}</span></article><article><small>神经矩阵 T × N</small><strong>{{shape(matrixShape)}}</strong><span>{{plan ? `${fmt(plan.transform.bin_size_s*1000,1)} ms bin` : '尚未生成'}}</span></article><article><small>Unit 保留</small><strong>{{percent(result?.unit_retention_ratio)}}</strong><span v-if="result">{{result.validation.unit_count_retained}} / {{result.validation.unit_count_input}}</span></article><article><small>Baseline</small><strong>{{baseline?.status ?? '—'}}</strong><span>{{baseline?.model ?? '等待验证'}}</span></article></div>
          <div class="overview-columns"><article class="panel"><header><div><p class="eyebrow">DATA READINESS</p><h2>处理摘要</h2></div></header><dl><div><dt>策略</dt><dd>{{plan?.strategy ?? '—'}}</dd></div><div><dt>目标 shape</dt><dd>{{shape(targetShape)}}</dd></div><div><dt>trial tensor</dt><dd>{{shape(result?.final_shapes?.trial_aligned)}}</dd></div><div><dt>时间覆盖</dt><dd>{{percent(overlap)}}</dd></div></dl><div v-if="result?.warnings.length" class="warnings"><strong>Warnings</strong><p v-for="warning in result.warnings" :key="warning">{{warning}}</p></div></article><article class="panel"><header><div><p class="eyebrow">BASELINE CHECK</p><h2>行为信息验证</h2></div><span v-if="r2.length">{{positiveR2}} / {{r2.length}} R² &gt; 0</span></header><div v-if="r2.length" class="mini-bars"><div v-for="(value,index) in r2" :key="index"><small>{{index+1}}</small><span class="r2-track"><i class="zero"/><i class="r2-bar" :class="{negative:typeof value==='number'&&value<0}" :style="r2Style(value)"/></span><b>{{fmt(value)}}</b></div></div><p v-else class="empty">完成运行后显示逐目标 ridge R²。</p></article></div>
        </section>

        <section v-else-if="view==='survey'" class="scroll-panel"><header class="section-heading"><div><p class="eyebrow">BOUNDED NWB SURVEY</p><h2>数据结构与 metadata</h2></div><span>仅读取 {{snapshot?.inspected_values}} 个标量样本</span></header><div class="facts"><div><small>Subject</small><strong>{{snapshot?.subject_id ?? '未提供'}}</strong></div><div><small>Session</small><strong>{{snapshot?.session_id}}</strong></div><div><small>标准</small><strong>{{snapshot?.standard}} {{snapshot?.standard_version}}</strong></div><div><small>文件大小</small><strong>{{snapshot ? bytes(snapshot.source.size_bytes) : '—'}}</strong></div></div><p class="source-path">{{snapshot?.source.path}}</p><h3>发现的对象</h3><div class="table-wrap"><table><thead><tr><th>Path</th><th>表示</th><th>Shape</th><th>Dtype / units</th><th>状态</th></tr></thead><tbody><tr v-for="item in snapshot?.collections" :key="item.path"><td><code>{{item.path}}</code></td><td>{{item.representation}}<small>{{item.entity_axis}}</small></td><td>{{shape(item.shape)}}</td><td>{{item.dtype}}<small>{{item.physical_units || 'units 未声明'}}</small></td><td><span class="pill">{{item.upstream_processed?'已有处理':'source'}}</span></td></tr></tbody></table></div><div v-if="snapshot?.processing_history.length" class="note"><strong>已有 processing modules</strong><p>{{snapshot.processing_history.join(' · ')}}</p></div></section>

        <section v-else-if="view==='plan'" class="scroll-panel"><header class="section-heading"><div><p class="eyebrow">CONDITIONAL PLAN</p><h2>{{plan?.task ?? '尚未生成计划'}}</h2></div><span class="pill">{{plan?.executable?'可执行':'需要证据'}}</span></header><div class="plan-summary"><span>策略：{{plan?.strategy}}</span><span>输入：{{plan?.input_representation}}</span><span>输出：{{plan?.transform.representation}}</span><span>Bin：{{plan ? fmt(plan.transform.bin_size_s*1000,1) : '—'}} ms</span></div><ol class="plan-list"><li v-for="step in plan?.steps" :key="step.id" :class="step.status"><span class="step-icon">{{step.status==='skip'?'↷':step.status==='blocked'?'!':'✓'}}</span><div><div><strong>{{step.stage}} · {{step.operation}}</strong><span class="pill">{{step.status}}</span></div><p>{{step.reason}}</p><details v-if="Object.keys(step.parameters).length || step.evidence_needed.length"><summary>参数与所需证据</summary><pre>{{JSON.stringify({parameters:step.parameters,evidence_needed:step.evidence_needed},null,2)}}</pre></details></div></li></ol></section>

        <section v-else-if="view==='qc'" class="scroll-panel"><header class="section-heading"><div><p class="eyebrow">UNIT QUALITY CONTROL</p><h2>Unit 保留与排除理由</h2></div><label class="qc-search"><input v-model="qcQuery" type="search" placeholder="Unit ID、结论或理由" aria-label="检索 unit QC" /><span>{{visibleQcRows.length}} / {{filteredQcRows.length}}</span></label></header><div class="retention"><div><strong>{{percent(result?.unit_retention_ratio)}}</strong><span>保留率</span></div><div class="retention-track"><i :style="{width:percent(result?.unit_retention_ratio)}"/></div><p>{{result?.validation.unit_count_retained ?? '—'}} retained / {{result?.validation.unit_count_input ?? '—'}} input</p></div><p v-if="artifactLoading" class="empty">正在读取 QC decisions…</p><template v-else><div class="table-wrap"><table><thead><tr><th>Unit</th><th>结论</th><th>理由</th><th>指标</th></tr></thead><tbody><tr v-for="row in visibleQcRows" :key="row.unit_id"><td>{{row.unit_id}}</td><td><span class="pill" :class="{removed:!row.retained}">{{row.retained?'保留':'删除'}}</span></td><td>{{row.reasons?.join('；') || '通过配置的 QC'}}</td><td><details v-if="row.metrics"><summary>查看</summary><pre>{{JSON.stringify(row.metrics,null,2)}}</pre></details></td></tr></tbody></table></div><button v-if="visibleQcRows.length<filteredQcRows.length" class="show-more" @click="qcLimit+=200">再显示 {{Math.min(200,filteredQcRows.length-visibleQcRows.length)}} 个 units</button></template></section>

        <section v-else-if="view==='alignment'" class="scroll-panel"><header class="section-heading"><div><p class="eyebrow">SHARED TIME AXIS</p><h2>Neural、behavior、trial 时间对齐</h2></div></header><div class="alignment-grid"><article v-for="(item,key) in result?.alignment" :key="key"><strong>{{key}}</strong><span v-if="item">{{item.name ?? `${item.count ?? item.unit_count ?? '—'} items`}}</span><span v-else>未发现</span><dl v-if="item"><div v-for="(value,name) in item" :key="name"><dt>{{name}}</dt><dd>{{Array.isArray(value)?value.join(' – '):typeof value==='number'?fmt(value,5):String(value)}}</dd></div></dl></article></div><div class="coverage"><label>Target / neural overlap <strong>{{percent(overlap)}}</strong></label><span><i :style="{width:percent(overlap)}"/></span><label>Evaluation mask coverage <strong>{{percent(maskCoverage)}}</strong></label><span><i :style="{width:percent(maskCoverage)}"/></span></div></section>

        <section v-else-if="view==='results'" class="scroll-panel"><header class="section-heading"><div><p class="eyebrow">MODEL-READY OUTPUT</p><h2>处理结果与 baseline</h2></div></header><div class="shape-grid"><article v-for="(value,name) in result?.final_shapes" :key="name"><small>{{name}}</small><strong>{{shape(value)}}</strong></article></div><article class="panel baseline-panel"><header><div><h2>Ridge decoder</h2><p>{{baseline?.split}} · α={{baseline?.alpha}} · train {{baseline?.train_rows}} / test {{baseline?.test_rows}}</p></div><span class="pill">{{baseline?.status}}</span></header><div class="r2-chart"><div v-for="(value,index) in r2" :key="index"><small>Target {{index+1}}</small><span class="r2-track"><i class="zero"/><i class="r2-bar" :class="{negative:typeof value==='number'&&value<0}" :style="r2Style(value)"/></span><b>{{fmt(value)}}</b></div></div><p class="note">{{baseline?.interpretation ?? baseline?.reason}}</p></article><article class="panel"><h2>信号分布</h2><dl><div v-for="(value,key) in result?.validation.signal_distribution" :key="key"><dt>{{key}}</dt><dd>{{fmt(value,6)}}</dd></div></dl></article></section>

        <section v-else-if="view==='report'" class="report-panel"><header class="section-heading"><div><p class="eyebrow">REPRODUCIBLE REPORT</p><h2>侵入式数据预处理报告</h2></div><div><a v-if="current" :href="artifactUrl('report.md')" target="_blank" rel="noopener">新窗口 ↗</a><a v-if="current" :href="artifactUrl('report.md')" download>下载</a></div></header><p v-if="artifactLoading" class="empty">正在读取报告…</p><article v-else-if="reportText" class="markdown" v-html="renderMarkdown(reportText)"/><p v-else class="empty">运行完成后生成报告。</p></section>

        <section v-else class="scroll-panel"><header class="section-heading"><div><p class="eyebrow">ARTIFACTS</p><h2>可复现文件与模型输入</h2></div><span>{{current?.artifacts.length ?? 0}} files</span></header><div class="file-list"><div v-for="file in current?.artifacts" :key="file.name"><div><strong>{{file.name}}</strong><small>{{file.name.endsWith('.npy')||file.name.endsWith('.npz')?'模型输入数组':file.name.endsWith('.json')?'结构化记录':'可读报告'}}</small></div><span>{{bytes(file.bytes)}}</span><a :href="artifactUrl(file.name)" download>下载</a></div></div></section>
      </div>
    </section>

    <section v-else class="initial"><span>⌁</span><h1>从 NWB 到 model-ready neural data</h1><p>按 metadata 决定跳过或执行哪些步骤，并保存 QC、对齐、baseline 和完整 provenance。</p><button class="primary" @click="dialog?.showModal()">处理一个 NWB 文件</button></section>

    <dialog ref="dialog"><header><div><p class="eyebrow">NEW INVASIVE RUN</p><h2>新建侵入式数据处理</h2></div><button class="close" @click="dialog?.close()">×</button></header><form @submit.prevent="start"><label>NWB 文件路径<input v-model="source" list="invasive-roots" required placeholder="/absolute/path/session.nwb" /></label><datalist id="invasive-roots"><option v-for="root in roots" :key="root" :value="root" /></datalist><label>处理任务<textarea v-model="task" required rows="3" /></label><div class="form-grid"><label>Bin size (ms)<input v-model.number="binMs" type="number" min="0.1" max="60000" step="0.1" required /></label><label>Smoothing σ (ms，可选)<input v-model.number="smoothingMs" type="number" min="0" step="0.1" placeholder="不平滑" /></label></div><label class="check"><input v-model="runBaseline" type="checkbox" />运行 ridge baseline</label><label class="check"><input v-model="hashSource" type="checkbox" />计算源文件 SHA-256（大型文件会较慢）</label><p v-if="roots.length" class="hint">允许读取：{{roots.join('；')}}</p><button class="primary submit" :disabled="busy">{{busy?'处理中…':'开始 Survey → Plan → Run'}}</button></form></dialog>
  </main>
</template>

<style scoped>
.invasive-page{height:100dvh;min-height:560px;box-sizing:border-box;display:flex;flex-direction:column;gap:15px;padding:0 28px 20px;background:#f2f5f3;color:#263e31;font:14px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif;overflow:hidden}.invasive-page *{box-sizing:border-box}h1,h2,h3,p{margin:0}button,input,textarea,select{font:inherit}button{cursor:pointer}a{color:#32684b;text-decoration:none}a:hover{text-decoration:underline}.topbar{height:72px;flex:none;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #dfe7e1;gap:20px}.brand,.actions,.actions label{display:flex;align-items:center}.brand{gap:12px}.brand>a{font-size:18px;color:#829187}.brand-mark{display:grid;place-items:center;width:30px;height:34px;border-radius:8px;background:#285e43;color:white;font:20px Georgia,serif}.brand strong{display:block;font-size:14px}.brand small{display:block;font-size:9px;letter-spacing:.11em;color:#89978e}.actions{gap:17px;font-size:12px}.actions label{gap:8px;color:#7e8d83}.actions select{max-width:285px;border:0;background:transparent;color:#3e604a}.primary{border:1px solid #285e43;background:#285e43;color:white;border-radius:7px;padding:9px 15px}.primary:hover{background:#204f38}.error{padding:8px 13px;border-radius:7px;background:#fff0e9;color:#9e5034;font-size:12px;flex:none}.progress-panel{flex:none}.run-heading{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:13px}.run-heading h1{font-size:19px}.run-heading>div>p:last-child{font-size:11px;color:#75877b;margin-top:3px;max-width:75vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.eyebrow{font-size:9px;letter-spacing:.13em;color:#72927e;text-transform:uppercase;margin-bottom:3px}.status,.pill{display:inline-flex;padding:3px 9px;border-radius:20px;background:#deeee2;color:#2d7045;font-size:10px;white-space:nowrap}.status.running{background:#e5eee9;color:#245f40}.stages{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:7px;list-style:none;margin:0;padding:0}.stages li{display:grid;grid-template-columns:25px minmax(0,1fr);align-items:center;gap:8px;padding:9px 11px;border:1px solid #dfe7e1;background:white;border-radius:8px;color:#75867b}.stages li>span{grid-row:1/3;display:grid;place-items:center;width:24px;height:24px;border-radius:50%;background:#f0f3f1;color:#91a195;font-size:10px}.stages strong{font-size:11px;line-height:1.1}.stages small{font-size:9px;color:#91a195}.stages .completed>span{background:#e3f0e7;color:#34734b}.stages .running{border-color:#69a27e;background:#f6fbf7}.stages .running>span{background:#2e704b;color:white}.stages .blocked{border-color:#e2ad8c;background:#fff8f4}.stages .blocked>span{background:#f7dfd1;color:#a65434}.workspace{flex:1;min-height:0;display:flex;flex-direction:column;background:white;border:1px solid #dce6df;border-radius:12px;overflow:hidden;box-shadow:0 3px 14px #1f4c2e04}.tabs{display:flex;align-items:center;height:49px;flex:none;padding:0 20px;gap:22px;border-bottom:1px solid #e4eae6;overflow-x:auto}.tabs button{height:100%;flex:none;border:0;border-bottom:2px solid transparent;background:none;color:#7b8b81;font-size:12px}.tabs button[aria-pressed=true]{color:#285f42;border-bottom-color:#2e7550;font-weight:650}.tabs button span{font-size:9px;padding:2px 5px;margin-left:5px;border-radius:5px;background:#eef3ef}.content{flex:1;min-height:0}.content>section{height:100%}.overview,.scroll-panel,.report-panel{padding:24px 28px;overflow:auto}.metric-grid,.shape-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.metric-grid article,.shape-grid article{padding:16px 18px;border:1px solid #e0e8e2;border-radius:9px;background:#fbfcfb}.metric-grid small,.shape-grid small{display:block;color:#87958c;font-size:10px;text-transform:uppercase}.metric-grid strong,.shape-grid strong{display:block;margin:5px 0 2px;font-size:22px;font-weight:550;color:#315e40;overflow-wrap:anywhere}.metric-grid article:first-child strong{font-size:16px}.metric-grid span{font-size:10px;color:#829087}.overview-columns{display:grid;grid-template-columns:.8fr 1.2fr;gap:14px;margin-top:14px}.panel{padding:20px;border:1px solid #e0e8e2;border-radius:9px;background:white}.panel>header,.section-heading{display:flex;align-items:start;justify-content:space-between;gap:16px}.panel h2,.section-heading h2{font-size:16px}.panel>header>span,.section-heading>span{font-size:11px;color:#788a7e}.panel dl{margin:14px 0 0}.panel dl div,.alignment-grid dl div{display:flex;justify-content:space-between;gap:20px;padding:7px 0;border-bottom:1px solid #edf1ee}.panel dt,.alignment-grid dt{color:#7a8c80}.panel dd,.alignment-grid dd{margin:0;text-align:right;overflow-wrap:anywhere}.warnings{margin-top:18px;padding:12px;border-radius:7px;background:#fff8ee;color:#8b643f;font-size:11px}.warnings p{margin-top:5px}.mini-bars,.r2-chart{margin-top:14px}.mini-bars>div,.r2-chart>div{display:grid;grid-template-columns:48px minmax(100px,1fr) 55px;align-items:center;gap:9px;margin:6px 0}.mini-bars small,.r2-chart small{font-size:10px;color:#7e8d83}.mini-bars b,.r2-chart b{text-align:right;font-size:10px;font-variant-numeric:tabular-nums}.r2-track{position:relative;display:block;height:7px;border-radius:5px;background:#edf1ee;overflow:hidden}.r2-track .zero{position:absolute;left:50%;top:0;height:100%;width:1px;background:#9eaca2;z-index:2}.r2-bar{position:absolute;top:0;height:100%;background:#4e9870}.r2-bar.negative{background:#c77b5d}.empty{display:grid;place-items:center;min-height:100px;color:#85938a}.section-heading{padding-bottom:18px;border-bottom:1px solid #e8ede9;margin-bottom:18px}.facts{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.facts div{padding:12px;background:#f6f9f7;border-radius:7px}.facts small{display:block;color:#809086}.facts strong{font-size:13px}.source-path{margin:14px 0;padding:10px 12px;background:#f5f7f6;border-radius:6px;font:11px/1.6 ui-monospace,monospace;overflow-wrap:anywhere}.scroll-panel h3{font-size:13px;margin:18px 0 8px}.table-wrap{overflow:auto;border:1px solid #e2e9e4;border-radius:8px}table{width:100%;border-collapse:collapse;font-size:12px}th{text-align:left;background:#f6f8f7;color:#66796c;font-size:10px;text-transform:uppercase}th,td{padding:10px 12px;border-bottom:1px solid #e8ede9;vertical-align:top}td code{font-size:10px;overflow-wrap:anywhere}td small{display:block;color:#89978e;margin-top:2px}.note{margin-top:16px;padding:12px 14px;border-left:3px solid #78a58a;background:#f4f8f5;font-size:12px}.note p{margin-top:4px}.plan-summary{display:flex;gap:8px;flex-wrap:wrap}.plan-summary span{padding:5px 9px;background:#f1f5f2;border-radius:5px;color:#607568;font-size:11px}.plan-list{list-style:none;padding:0;margin:18px 0}.plan-list li{display:grid;grid-template-columns:28px minmax(0,1fr);gap:12px;padding:14px 4px;border-bottom:1px solid #e8ede9}.step-icon{display:grid;place-items:center;width:25px;height:25px;border-radius:50%;background:#e5f0e8;color:#31724a}.plan-list .skip .step-icon{background:#edf0ee;color:#819087}.plan-list .blocked .step-icon{background:#f8e2d7;color:#a85231}.plan-list li>div>div{display:flex;justify-content:space-between;gap:12px}.plan-list p{font-size:12px;color:#708277;margin-top:5px}.plan-list details{margin-top:8px;font-size:11px;color:#58705f}.plan-list pre,td pre{white-space:pre-wrap;overflow-wrap:anywhere;font:10px/1.5 ui-monospace,monospace}.retention{display:grid;grid-template-columns:90px minmax(100px,1fr) auto;align-items:center;gap:20px;padding:18px;background:#f6f9f7;border-radius:8px;margin-bottom:16px}.retention strong{display:block;font-size:24px;color:#316443}.retention span{font-size:10px;color:#76877c}.retention-track{height:10px;background:#e5ebe7;border-radius:6px;overflow:hidden}.retention-track i,.coverage span i{display:block;height:100%;background:#4d966e}.retention p{font-size:11px;color:#718177}.pill.removed{background:#f7e5dd;color:#a34e31}.alignment-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.alignment-grid article{border:1px solid #e0e8e2;border-radius:8px;padding:15px}.alignment-grid article>strong{display:block;text-transform:capitalize}.alignment-grid article>span{font-size:11px;color:#7e8e84}.alignment-grid dl{font-size:11px}.coverage{margin-top:18px}.coverage label{display:flex;justify-content:space-between;margin:11px 0 5px;font-size:11px;color:#617669}.coverage>span{display:block;height:9px;background:#e5ebe7;border-radius:6px;overflow:hidden}.shape-grid{margin-bottom:14px}.shape-grid article strong{font-size:17px}.baseline-panel{margin-bottom:14px}.baseline-panel header p{font-size:11px;color:#7c8e82}.r2-chart>div{grid-template-columns:80px minmax(180px,1fr) 65px}.report-panel{display:flex;flex-direction:column}.report-panel .section-heading>div+div{display:flex;gap:14px;font-size:12px}.markdown{max-width:920px;width:100%;margin:0 auto;font-size:13px;line-height:1.75}.markdown :deep(h1){font-size:25px}.markdown :deep(h2){font-size:18px;margin-top:26px;border-bottom:1px solid #e2e8e4;padding-bottom:6px}.markdown :deep(code){background:#f1f4f2;padding:2px 4px;border-radius:3px}.file-list>div{display:grid;grid-template-columns:minmax(0,1fr) auto 70px;align-items:center;gap:20px;padding:13px 4px;border-bottom:1px solid #e8ede9}.file-list strong{font-size:12px}.file-list small{display:block;color:#84938a}.file-list>div>span{font-size:11px;color:#79887f}.initial{flex:1;display:flex;align-items:center;justify-content:center;flex-direction:column;text-align:center;gap:14px;color:#718679}.initial>span{font-size:45px;color:#9db7a5}.initial h1{font-size:25px;color:#345b40}.initial p{max-width:600px}.initial .primary{margin-top:5px}dialog{border:1px solid #d9e4dc;border-radius:15px;box-shadow:0 24px 100px #16352630;padding:26px;width:min(600px,calc(100vw - 30px));max-height:90dvh;overflow:auto;color:#314d3b}dialog::backdrop{background:#19342455;backdrop-filter:blur(3px)}dialog header{display:flex;justify-content:space-between}dialog h2{font-size:21px}.close{border:0;background:#f0f4f1;border-radius:50%;width:31px;height:31px;color:#789081;font-size:20px}form>label{display:block;margin-top:18px;font-size:12px;color:#5c7564}form input:not([type=checkbox]),form textarea{display:block;width:100%;margin-top:6px;padding:10px 11px;border:1px solid #d3dfd6;border-radius:7px;color:#294634}form textarea{resize:vertical}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.check{display:flex;align-items:center;gap:8px}.hint{font-size:10px;color:#829187;margin-top:15px;overflow-wrap:anywhere}.submit{width:100%;margin-top:22px}
.qc-search{display:flex;align-items:center;gap:9px}.qc-search input{width:220px;padding:7px 9px;border:1px solid #d5e0d8;border-radius:6px;font-size:11px}.qc-search span{font-size:10px;color:#7c8d82}.show-more{display:block;margin:14px auto 0;padding:7px 13px;border:1px solid #d4e0d7;border-radius:6px;background:#f5f8f6;color:#38654b}
@media(max-width:1000px){.invasive-page{padding:0 15px 14px}.stages{grid-template-columns:repeat(7,1fr)}.stages li{display:flex;flex-direction:column;text-align:center;padding:7px 2px;gap:4px}.stages li>span{grid-row:auto}.stages small{display:none}.metric-grid,.shape-grid{grid-template-columns:repeat(2,1fr)}.overview-columns{grid-template-columns:1fr}.actions>a,.actions label>span{display:none}}
@media(max-width:650px){.invasive-page{padding:0 9px 9px}.topbar{height:auto;min-height:68px}.brand small,.brand-mark{display:none}.actions{gap:8px}.actions select{max-width:135px;font-size:10px}.actions .primary{font-size:10px;padding:7px}.run-heading h1{font-size:15px}.run-heading>div>p:last-child{max-width:70vw}.stages strong{font-size:9px}.tabs{padding:0 12px;gap:17px}.overview,.scroll-panel,.report-panel{padding:17px 14px}.metric-grid,.facts,.alignment-grid{grid-template-columns:1fr 1fr}.metric-grid strong{font-size:18px}.retention{grid-template-columns:1fr}.form-grid{grid-template-columns:1fr}.file-list>div{grid-template-columns:minmax(0,1fr) auto}.file-list>div>span{display:none}}
</style>
