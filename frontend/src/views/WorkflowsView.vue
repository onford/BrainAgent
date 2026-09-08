<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { apiRequest, apiUrl } from '../api/client'
import { groupArtifactFiles } from '../utils/artifacts'

type Stage = { name: string; label: string; status: string; error?: string }
type Workflow = { id: string; status: string; created_at: string; updated_at: string; error: string | null; stages: Stage[]; request: { source_root: string }; outputs: Record<string, any>; events: {time:string;agent:string;message:string}[]; artifacts: {name:string;bytes:number;sha256:string | null}[] }
const route = useRoute(), router = useRouter()
const jobs = ref<Workflow[]>([]), current = ref<Workflow | null>(null)
const roots = ref<string[]>([]), source = ref(''), count = ref(3), busy = ref(false), error = ref('')
const labels: Record<string,string> = {queued:'等待开始',pending:'等待执行',running:'正在执行',completed:'已完成',failed:'需要处理',interrupted:'等待恢复'}
const selectedId = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
const active = computed(() => current.value && ['queued','running','interrupted'].includes(current.value.status))
const delivered = computed(() => current.value?.outputs.data_delivery)
const sourceSummary = computed(() => current.value?.outputs.data_survey)
const completedCount = computed(() => current.value?.stages.filter(s => s.status==='completed').length ?? 0)
const artifactGroups = computed(() => {
  const names: Record<string, string> = {
    process: '流程索引与结构定义', survey: '数据调研', collection: '数据接入与标准副本',
    preprocessing: '预处理 · 全部候选', evaluation: '结果选择', report: '数据报告', delivery: '训练数据与溯源',
  }
  const groups = new Map<string, Workflow['artifacts']>()
  for (const artifact of current.value?.artifacts ?? []) {
    const key = artifact.name.includes('/') ? artifact.name.split('/')[0]! : 'workflow'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(artifact)
  }
  const order = [...Object.keys(names), 'workflow']
  return [...groups].sort(([a], [b]) => order.indexOf(a) - order.indexOf(b))
    .map(([key, files]) => ({key, label: names[key] ?? '运行记录与数据包', files, families: groupArtifactFiles(files)}))
})
function fileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}
function fileUrl(name: string, download = true) {
  return apiUrl(`/api/workflows/${current.value!.id}/artifacts/${name.split('/').map(encodeURIComponent).join('/')}?download=${download}`)
}
async function refresh(id: string) {
  try {
    const state = await apiRequest<Workflow>(`/api/workflows/${id}`)
    if (disposed || selectedId.value !== id) return
    current.value = state
    jobs.value = [state,...jobs.value.filter(j=>j.id!==id)]
    error.value = ''
    if (active.value) timer = setTimeout(()=>void refresh(id),2000)
  } catch (reason) { if (!disposed && selectedId.value===id) error.value = String(reason) }
}
async function select(id:string) {
  if (timer) clearTimeout(timer)
  selectedId.value=id
  await router.replace({path:'/workflows',query:{id}})
  await refresh(id)
}
async function start() {
  if (busy.value) return
  busy.value=true; error.value=''
  try {
    const job=await apiRequest<Workflow>('/api/workflows',{method:'POST',body:JSON.stringify({source_root:source.value,max_subjects:count.value,adapter:'eegmmidb',runs:[4,8],seed:42,tmin:0,tmax:2})})
    await select(job.id)
  } catch(reason) { error.value=String(reason) }
  finally {busy.value=false}
}
async function retry() {
  if(!current.value || busy.value) return
  busy.value=true
  try { await apiRequest(`/api/workflows/${current.value.id}/retry`,{method:'POST'}); await select(current.value.id) }
  catch(reason) {error.value=String(reason)} finally {busy.value=false}
}
onMounted(async()=>{
  try {
    const [settings,items]=await Promise.all([apiRequest<{allowed_roots:string[]}>('/api/workflows/sources'),apiRequest<Workflow[]>('/api/workflows')])
    if(disposed) return
    roots.value=settings.allowed_roots; source.value=roots.value[0] ?? ''; jobs.value=items
    const id=typeof route.query.id==='string' ? route.query.id : items[0]?.id
    if(id) await select(id)
  } catch(reason) {if(!disposed) error.value=String(reason)}
})
onBeforeUnmount(()=>{disposed=true;if(timer) clearTimeout(timer)})
</script>

<template>
  <main class="workflow-page">
    <header><RouterLink to="/">← 返回对话</RouterLink><span>Brain Agent</span></header>
    <div class="intro"><p class="eyebrow">EEG DATA WORKFLOW</p><h1>从本地 EEG 到训练数据</h1><p>查看六个模块的处理进度，获取报告与带标签的数据包。</p></div>
    <div class="workspace-grid">
      <aside>
        <form class="panel" @submit.prevent="start">
          <h2>开始数据流程</h2>
          <label>本地数据目录<input v-model="source" list="source-roots" required placeholder="选择已配置的 EEGMMIDB 目录" aria-label="本地数据目录" /></label>
          <datalist id="source-roots"><option v-for="root in roots" :key="root" :value="root" /></datalist>
          <label>被试数量<input v-model.number="count" type="number" min="1" max="12" required aria-label="被试数量" /></label>
          <p class="hint">左右手运动想象 · Run 4 / 8<br>训练窗口 0–2 秒 · 两种频带候选</p>
          <button class="primary" :disabled="busy || !source">{{busy?'正在提交…':'开始完整流程'}}</button>
        </form>
        <section class="history"><h2>运行记录</h2><button v-for="job in jobs" :key="job.id" :class="{chosen:job.id===selectedId}" @click="select(job.id)"><strong>{{labels[job.status] ?? job.status}}</strong><span>{{new Date(job.created_at).toLocaleString('zh-CN')}}</span></button><p v-if="!jobs.length" class="hint">还没有运行记录</p></section>
      </aside>
      <section class="results">
        <p v-if="error" role="alert" class="error">{{error}} <button v-if="selectedId" @click="select(selectedId)">刷新</button></p>
        <template v-if="current">
          <section class="panel progress-panel"><div class="section-heading"><h2>{{sourceSummary?.profile.name ?? 'EEG 数据流程'}}</h2><span class="badge">{{labels[current.status]}}</span></div><p role="status">{{completedCount}} / 6 个模块已完成</p><progress :value="completedCount" max="6" aria-label="流程进度" />
            <ol class="stages"><li v-for="(stage,index) in current.stages" :key="stage.name" :class="stage.status"><span class="stage-number">{{stage.status==='completed'?'✓':index+1}}</span><div><strong>{{stage.label}}</strong><small>{{labels[stage.status]}}</small><p v-if="stage.error" class="error">{{stage.error}}</p></div></li></ol>
            <button v-if="current.status==='failed'" :disabled="busy" @click="retry">重试未完成步骤</button>
          </section>
          <section v-if="delivered" class="panel delivery-panel"><div class="section-heading"><h2>训练数据已就绪</h2><span class="badge">随机选择候选</span></div><div class="stats"><div><strong>{{delivered.shape[0]}}</strong><span>Epoch</span></div><div><strong>{{delivered.shape[1]}}</strong><span>EEG 通道</span></div><div><strong>{{delivered.shape[2]}}</strong><span>每段时间点</span></div></div><p>训练 / 验证 / 测试按被试分组。候选方法随机选择，本轮未进行质量排名。</p><div class="download-actions"><a class="primary" :href="fileUrl('training-data.zip')">下载训练数据包</a><a :href="fileUrl('report/report.html',false)" target="_blank" rel="noopener">打开报告</a><a :href="fileUrl('delivery/manifest.json')">下载数据清单</a></div><p class="hint">数据包包含 X、y、分组、通道信息、原始事件映射与复现记录。</p></section>
          <section v-if="current.status==='completed'" class="panel"><h2>报告预览</h2><iframe :src="fileUrl('report/report.html',false)" title="EEG 训练数据报告" sandbox="allow-same-origin" /></section>
          <section class="panel files-panel" aria-label="全部产出文件">
            <div class="section-heading"><h2>全部产出文件</h2><span class="badge">{{current.artifacts.length}} 个文件</span></div>
            <p class="hint">按模块整理，同类文件默认收起，展开后可逐个下载。流程执行时会逐步加入已生成的记录。</p>
            <a v-if="current.artifacts.some(a => a.name === 'process/index.json')" :href="fileUrl('process/index.json')">查看结构化流程索引</a>
            <p v-if="!current.artifacts.length" class="hint">尚无产出文件。</p>
            <details v-for="group in artifactGroups" :key="current.id+group.key" class="file-group" open>
              <summary>{{group.label}} <span>{{group.files.length}} 个文件</span></summary>
              <template v-for="family in group.families" :key="family.key">
                <ul v-if="family.files.length === 1" class="single-file"><li v-for="artifact in family.files" :key="artifact.name">
                  <a :href="fileUrl(artifact.name)">{{artifact.name}}</a><small>{{fileSize(artifact.bytes)}}</small>
                </li></ul>
                <details v-else class="file-family">
                  <summary :title="family.key">{{family.label}} <span>{{family.files.length}} 个文件 · {{fileSize(family.bytes)}}</span></summary>
                  <ul><li v-for="artifact in family.files" :key="artifact.name">
                    <a :href="fileUrl(artifact.name)">{{artifact.name}}</a><small>{{fileSize(artifact.bytes)}}</small>
                  </li></ul>
                </details>
              </template>
            </details>
          </section>
          <details class="panel records"><summary>执行日志</summary><ul><li v-for="event in current.events" :key="event.time+event.agent">{{new Date(event.time).toLocaleTimeString('zh-CN')}} · {{event.message}}</li></ul></details>
        </template>
        <section v-else class="panel empty"><h2>选择数据，开始处理</h2><p>流程会读取数据、创建标准副本、运行候选预处理、随机选择结果，并生成报告和训练数据包。</p></section>
      </section>
    </div>
  </main>
</template>

<style scoped>
.workflow-page{min-height:100vh;background:#f4f7f5;color:#213b2d;padding:28px 5vw;font:15px/1.6 system-ui,sans-serif}header{display:flex;justify-content:space-between}a{color:#246b4c}h1{font-size:34px;line-height:1.25;margin:8px 0}h2{font-size:19px;margin:0 0 14px}.intro{margin:32px 0}.intro p{color:#607267}.eyebrow{font-size:12px;letter-spacing:.12em}.workspace-grid{display:grid;grid-template-columns:280px minmax(0,1fr);gap:26px;max-width:1320px}.panel{background:white;border:1px solid #dce6df;border-radius:14px;padding:24px;margin-bottom:22px}label{display:block;margin:16px 0}input{box-sizing:border-box;display:block;width:100%;margin-top:6px;padding:10px;border:1px solid #bdccbf;border-radius:7px;font:inherit}button{cursor:pointer;border:1px solid #bdccbf;background:white;padding:8px 12px;border-radius:7px;font:inherit}button:disabled{opacity:.5;cursor:wait}.primary{display:inline-block;background:#256648;color:white;border:0;border-radius:8px;padding:10px 15px;text-decoration:none}.hint{font-size:13px;color:#62766a}.section-heading{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}.badge{font-size:12px;border-radius:20px;background:#eaf2ec;padding:4px 10px;align-self:start}.history{padding:0 8px}.history button{display:block;width:100%;text-align:left;margin-bottom:10px}.history span{display:block;color:#66756c;font-size:12px}.history .chosen{background:#e5eee7;border-color:#58906b}progress{width:100%;height:7px;accent-color:#36875c}.stages{list-style:none;padding:0;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:22px;margin:24px 0}.stages li{display:flex;gap:10px;align-items:start}.stage-number{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:#edf1ee;flex-shrink:0}.completed .stage-number{background:#d9efdf;color:#23653a}.running .stage-number{background:#246b4c;color:white}.stages small{display:block;color:#748278}.stats{display:flex;gap:46px;margin:18px 0}.stats strong{font-size:32px;display:block}.stats span{font-size:13px;color:#607568}.download-actions{display:flex;gap:20px;align-items:center;flex-wrap:wrap}.error{color:#9a3627;overflow-wrap:anywhere}iframe{border:0;width:100%;height:650px}.records summary{cursor:pointer}.records ul{font-size:13px;overflow-wrap:anywhere}.empty{min-height:220px;display:flex;flex-direction:column;justify-content:center}@media(max-width:950px){.workspace-grid{grid-template-columns:1fr}.stages{grid-template-columns:repeat(2,minmax(0,1fr))}.history{display:none}h1{font-size:28px}.workflow-page{padding:20px}.stats{gap:20px}}
.files-panel { min-width: 0; }
.file-group { margin-top: 18px; border-top: 1px solid #e4ece6; padding-top: 12px; }
.file-group summary { cursor: pointer; font-weight: 600; }
.file-group summary span { font-size: 12px; font-weight: 400; color: #62766a; margin-left: 8px; }
.file-group ul { padding: 0; list-style: none; margin: 10px 0 0; }
.file-group li { display: flex; align-items: baseline; gap: 14px; padding: 6px 0; font-size: 13px; }
.file-group a { overflow-wrap: anywhere; text-decoration: underline; text-underline-offset: 3px; }
.file-group small { flex-shrink: 0; margin-left: auto; color: #62766a; white-space: nowrap; }
.file-group .single-file { margin: 4px 0 0; }
.file-family { margin-top: 8px; padding: 8px 12px; border: 1px solid #e4ece6; border-radius: 8px; background: #f8faf8; }
.file-family summary { font-size: 13px; overflow-wrap: anywhere; }
.file-family[open] > summary { padding-bottom: 8px; border-bottom: 1px solid #e4ece6; }
</style>
