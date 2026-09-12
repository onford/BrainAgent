<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { apiRequest } from '../api/client'
import PreprocessingCard from '../components/PreprocessingCard.vue'

type Field = { type: string | string[]; default?: unknown; runtime_binding?: string; enum?: unknown[]; minimum?: number; maximum?: number }
type Capability = { identity: string; unit_id: string; op: string; profile: string; input_kind: string; effect: string; fit: boolean; model_kind: string | null; decision: boolean; profile_parameters: Record<string, unknown>; parameters: { required: string[]; properties: Record<string, Field> }; status: { collected: boolean; adapted: boolean; compiled: boolean; executed: boolean; numerically_verified: boolean; real_data_verified: boolean; current_input_applicable: boolean | null; dependency_missing: unknown[] }; unavailable_reasons: string[]; verification: unknown; source_fields: Record<string, string> }
const rows = ref<Capability[]>([])
const query = ref('')
const filter = ref('all')
const selected = ref<Capability | null>(null)
const error = ref('')
const busy = ref(false)
const inputId = ref('')
const recipe = ref<Record<string, any>[]>([])
const outputId = ref('')
const selectedJson = ref('{}')
const plan = ref<any>(null)
const gridJson = ref('{}')
const searchSpace = ref<any>(null)
const assetForm = ref({ path: '', sha256: '', kind: 'forward', provenance: '' })
const assetRef = ref<unknown>(null)
const selectedDomains = computed(() => searchSpace.value?.operators.filter((o: any) => recipe.value.some(s => s.unit_id === o.unit_id && s.op === o.op)))
const shown = computed(() => rows.value.filter(r => r.identity.toLowerCase().includes(query.value.toLowerCase()) && (filter.value === 'all' || (filter.value === 'verified' ? r.status.numerically_verified : filter.value === 'missing' ? r.status.dependency_missing.length : !r.status.numerically_verified))))
const count = computed(() => ({ units: new Set(rows.value.map(r => r.unit_id)).size, operations: new Set(rows.value.map(r => `${r.unit_id}/${r.op}`)).size, profiles: rows.value.length, verified: rows.value.filter(r => r.status.numerically_verified).length }))
const labels = (r: Capability) => [r.status.collected && '已收录', r.status.adapted && '已适配', r.status.compiled && '编译通过', r.status.executed && '运行通过', r.status.numerically_verified && '数值验证通过', r.status.real_data_verified && '真实数据通过', r.status.dependency_missing.length > 0 && '依赖缺失', r.status.current_input_applicable === false && '当前输入不适用', r.decision && '需要决定'].filter(Boolean)
onMounted(async () => { try { const [capabilities, space] = await Promise.all([apiRequest<{ rows: Capability[] }>('/api/preprocessing/capabilities'), apiRequest('/api/preprocessing/graph-search/space')]); rows.value = capabilities.rows; searchSpace.value = space } catch (e) { error.value = String(e) } })
function select(row: Capability) {
  selected.value = row
  const params: Record<string, unknown> = {}
  for (const [name, field] of Object.entries(row.parameters.properties)) {
    if (field.runtime_binding) params[name] = field.runtime_binding
    else if (Object.prototype.hasOwnProperty.call(field, 'default')) params[name] = field.default
    else if (['picks', 'donors', 'targets', 'ref_chs', 'reref_chs'].includes(name)) params[name] = '$eeg_channels'
    else if (name === 'picks_artifact') params[name] = '$eog_channels'
    else if (name === 'event_id') params[name] = '$event_id'
    else if (name === 'adaptation_scope') params[name] = 'record_unlabeled'
    else params[name] = null
  }
  Object.assign(params, row.profile_parameters)
  if (row.op === 'wica_apply' && params.variant === 'ordinary') for (const key of ['eye_weights', 'extra_eye', 'line_freq', 'muscle_slope']) delete params[key]
  if (row.op === 'ecg_assess' && params.method === 'ctps') delete params.measure
  if (row.op === 'autoreject_fit' && params.mode === 'global') for (const key of ['n_interpolate', 'consensus', 'thresh_method']) delete params[key]
  selectedJson.value = JSON.stringify({ id: `step${recipe.value.length + 1}`, unit_id: row.unit_id, op: row.op, profile: row.profile, implementation_version: '2', input: recipe.value.at(-1)?.id ?? 'raw', params, evidence_indices: [0], ...(row.fit ? { fit_scope: { role: 'calibration', ids: ['calibration'] }, adaptation_scope: 'calibration' } : {}), ...(row.model_kind && !['model', 'reference_model'].includes(row.effect) ? { model_from: '' } : {}), ...(row.decision ? { decision: { mode: 'manual', status: 'pending', reason: '等待核对当前数据与决定' } } : {}) }, null, 2)
  const draft = JSON.parse(selectedJson.value)
  if (params.adaptation_scope) draft.adaptation_scope = params.adaptation_scope
  if (row.input_kind === 'array') draft.input_representation = 'array'
  if (row.model_kind === 'prep_reference' || ['relax_budget', 'relax_muscle_trials'].includes(row.op)) draft.input_channels = '$eeg_channels'
  selectedJson.value = JSON.stringify(draft, null, 2)
}
function append() { try { const value = JSON.parse(selectedJson.value); const existing = recipe.value.findIndex(s => s.id === value.id); if (existing >= 0) recipe.value.splice(existing, 1, value); else recipe.value.push(value); plan.value = null; error.value = '' } catch (e) { error.value = String(e) } }
async function checkInput() {
  try { rows.value = (await apiRequest<{ rows: Capability[] }>('/api/preprocessing/capabilities/input', { method: 'POST', body: JSON.stringify({ id: inputId.value, sha256: inputId.value }) })).rows } catch (e) { error.value = String(e) }
}
async function registerAsset() {
  try { assetRef.value = await apiRequest('/api/preprocessing/assets', { method: 'POST', body: JSON.stringify(assetForm.value) }) } catch (e) { error.value = String(e) }
}
async function compile(sweep = false) {
  busy.value = true; error.value = ''; plan.value = null
  try {
    if (!/^[a-f0-9]{64}$/.test(inputId.value)) throw new Error('请填写已注册输入的 64 位 SHA-256 ID')
    const method = { id: 'composed-unit-method', version: '2', title: '基本单元组合流程', source: 'classic', mechanism: recipe.value.map(s => s.op).join(' → '), recipe: recipe.value, output: outputId.value || recipe.value.at(-1)?.id, evidence: [{ source_url: 'brainagent:user:recipe', locator: '交互配方', text: '用户根据显示的来源合同选择操作与参数；该组合属于工程配方，尚不声明论文复现。', source_version: '2' }], adaptations: ['用户工程配方；逐操作来源见冻结单元目录。'] }
    if (sweep) { plan.value = await apiRequest('/api/preprocessing/graph-search/plans', { method: 'POST', body: JSON.stringify({ input_ref: { id: inputId.value, sha256: inputId.value }, method, grid: JSON.parse(gridJson.value), max_candidates: 16 }) }); return }
    const reference = await apiRequest<{ id: string; sha256: string }>('/api/preprocessing/methods', { method: 'POST', body: JSON.stringify(method) })
    plan.value = await apiRequest('/api/preprocessing/plans', { method: 'POST', body: JSON.stringify({ input_ref: { id: inputId.value, sha256: inputId.value }, methods: [reference], mode: 'exploratory', selection: 'all', max_candidates: 1 }) })
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
</script>

<template>
  <main class="units-page">
    <nav><RouterLink to="/">对话</RouterLink><RouterLink to="/workflows">工作流</RouterLink><RouterLink to="/searches">策略搜索</RouterLink></nav>
    <h1>预处理基本单元与流程编排</h1>
    <p>{{ count.units }} 个单元 · {{ count.operations }} 个操作 · {{ count.profiles }} 个 profile · {{ count.verified }} 项数值验证通过</p>
    <p>已适配、实际运行、数值验证和真实数据验证分别显示。是否可执行还取决于当前数据、依赖、模型和决定。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <div class="tools"><input v-model="query" aria-label="搜索单元或操作" placeholder="搜索单元、操作、profile"><select v-model="filter" aria-label="能力状态"><option value="all">全部</option><option value="verified">数值验证通过</option><option value="unverified">尚未数值验证</option><option value="missing">依赖缺失</option></select></div>
    <div class="workspace">
      <section class="catalog" aria-label="全量单元清单"><button v-for="row in shown" :key="row.identity" @click="select(row)"><strong>{{ row.unit_id }} / {{ row.op }}</strong><span>{{ row.profile }}</span><small>{{ labels(row).join(' · ') }}</small></button></section>
      <section v-if="selected" class="editor" aria-label="操作与配方编辑">
        <h2>{{ selected.op }}</h2><p>{{ selected.input_kind }} → {{ selected.effect }}</p>
        <p v-if="selected.status.dependency_missing.length">依赖缺失：{{ selected.status.dependency_missing }}</p>
        <details><summary>来源合同与验证证据</summary><pre>{{ selected.source_fields }}</pre><pre>{{ selected.verification }}</pre></details>
        <details><summary>全部参数合同</summary><pre>{{ selected.parameters }}</pre></details>
        <p>补齐参数及数据、模型、诊断端口。缺失的科学参数保留为空，编译器会检查。</p>
        <textarea v-model="selectedJson" aria-label="步骤配置" spellcheck="false" rows="20"></textarea><button @click="append">加入或更新方法步骤</button>
      </section>
    </div>
    <section aria-label="当前方法配方"><h2>方法配方</h2><ol><li v-for="(item, index) in recipe" :key="index"><strong>{{ item.id }}</strong> {{ item.input }} → {{ item.op }}<span v-if="item.model_from"> · 模型：{{ item.model_from }}</span><span v-if="item.decision_from"> · 决定：{{ item.decision_from }}</span><button @click="selected = rows.find(r => r.unit_id === item.unit_id && r.op === item.op && r.profile === item.profile) ?? rows.find(r => r.unit_id === item.unit_id && r.op === item.op) ?? null; selectedJson = JSON.stringify(item, null, 2)">编辑</button><button @click="recipe.splice(index, 1); plan = null">移除</button><details><summary>完整步骤与端口</summary><pre>{{ item }}</pre></details></li></ol>
      <label>最终数据输出 <select v-model="outputId" aria-label="最终数据输出"><option value="">最后一个步骤的数据</option><option v-for="item in recipe" :key="item.id" :value="item.id">{{ item.id }}</option></select></label>
      <label>已注册输入 ID <input v-model="inputId" aria-label="已注册输入 ID" size="68"></label><button :disabled="busy || !recipe.length" @click="compile(false)">绑定数据并编译执行计划</button>
      <button :disabled="!/^[a-f0-9]{64}$/.test(inputId)" @click="checkInput">检查当前输入前置条件</button>
      <details><summary>注册前向模型、投影或注释资产</summary><p>从后端配置的数据根目录读取，校验文件哈希后保存快照。在步骤 asset_inputs 中使用返回的引用。</p><select v-model="assetForm.kind" aria-label="资产类型"><option value="forward">MNE 前向模型</option><option value="projections">MNE 投影</option><option value="annotations">MNE 注释</option></select><input v-model="assetForm.path" aria-label="资产文件路径" placeholder="后端资产绝对路径"><input v-model="assetForm.sha256" aria-label="资产 SHA-256" placeholder="SHA-256"><input v-model="assetForm.provenance" aria-label="资产来源" placeholder="来源、版本及生成条件"><button @click="registerAsset">校验并注册资产</button><pre v-if="assetRef">{{ assetRef }}</pre></details>
      <details><summary>有界参数搜索</summary><p>填写步骤参数及候选值，例如 {"step1.l_freq": [1.0, 2.0]}。候选必须属于下列有限域；每个候选仍执行逐记录合同检查。</p><textarea v-model="gridJson" aria-label="搜索参数网格" rows="4"></textarea><button :disabled="busy || !recipe.length" @click="compile(true)">生成候选并编译</button><pre>{{ selectedDomains }}</pre></details>
      <PreprocessingCard v-if="plan" :key="plan.plan_ref.id" :output="{ plan_ref: plan.plan_ref, record_count: plan.plan.records.length, screening: plan.plan.screening }" />
    </section>
  </main>
</template>

<style scoped>
.units-page{max-width:1440px;min-height:100vh;margin:auto;padding:28px;color:#243c35;background:#fff;font:15px/1.6 system-ui;box-sizing:border-box}nav,.tools{display:flex;gap:20px;margin-bottom:20px}.workspace{display:grid;grid-template-columns:1fr 1.1fr;gap:24px}.catalog{max-height:70vh;overflow:auto}.catalog button{display:flex;flex-direction:column;text-align:left;width:100%;margin:5px 0;padding:12px;background:#f5f8f6;border:1px solid #cad9d0;border-radius:6px;cursor:pointer}.editor{min-width:0}textarea{width:100%;font:13px/1.5 monospace}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}button,input,select{padding:8px}li button{margin-left:12px}small{color:#526859}[role=alert]{color:#942c25}@media(max-width:850px){.workspace{grid-template-columns:1fr}.catalog{max-height:40vh}input{max-width:95%}}
</style>
