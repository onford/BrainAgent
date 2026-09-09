<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { apiRequest, apiUrl } from '../api/client'
import { artifactDescription } from '../utils/artifacts'
import ReportReader from '../components/workflows/ReportReader.vue'
import ArtifactExplorer from '../components/workflows/ArtifactExplorer.vue'

type Stage = { name: string; label: string; status: string; error?: string }
type Workflow = { id: string; engine?: string; status: string; created_at: string; updated_at: string; error: string | null; stages: Stage[]; request: { source_root: string }; outputs: Record<string, any>; events: {time:string;agent:string;message:string}[]; artifacts: {name:string;bytes:number;sha256:string | null}[] }
type View = 'reports' | 'files' | 'logs' | 'delivery'
const route = useRoute(), router = useRouter()
const jobs = ref<Workflow[]>([]), current = ref<Workflow | null>(null)
const roots = ref<string[]>([]), source = ref(''), count = ref(3), busy = ref(false), error = ref('')
const selectedId = ref(''), view = ref<View>('reports'), focused = ref(false)
const files = ref<InstanceType<typeof ArtifactExplorer>>()
const createDialog = ref<HTMLDialogElement>(), stageDialog = ref<HTMLDialogElement>()
const stageName = ref(''), logQuery = ref('')
const labels: Record<string,string> = {queued:'等待开始',pending:'等待执行',running:'正在执行',completed:'已完成',failed:'需要处理',interrupted:'等待恢复'}
const viewLabels: Record<View,string> = {reports:'报告阅读',files:'记录文件',logs:'执行日志',delivery:'训练数据'}
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
const active = computed(() => current.value && ['queued','running','interrupted'].includes(current.value.status))
const delivered = computed(() => current.value?.outputs.data_delivery)
const sourceSummary = computed(() => current.value?.outputs.data_survey)
const completedCount = computed(() => current.value?.stages.filter(s => s.status==='completed').length ?? 0)
const stage = computed(() => current.value?.stages.find(s=>s.name===stageName.value))
const latest = computed(() => current.value?.events.at(-1))
const events = computed(() => (current.value?.events ?? []).map((event,index)=>({...event,id:index})).reverse().filter(e=>`${e.agent} ${e.message}`.toLowerCase().includes(logQuery.value.trim().toLowerCase())))
const reports = computed(() => {
  const titles: Record<string,string> = {
    'survey/reports/dataset-basic.html':'数据集基本信息', 'survey/reports/data-information.html':'数据信息与三方核对',
    'survey/reports/statistics.html':'数据集统计信息', 'survey/reports/literature-usage.html':'使用数据集的文献',
    'survey/reports/literature-discussion.html':'讨论数据集的文献', 'survey/reports/literature-preprocessing.html':'预处理方法文献',
    'report/report.html':'最终处理报告',
  }
  const available = new Set(current.value?.artifacts.map(a=>a.name))
  return Object.entries(titles).filter(([name])=>available.has(name)).map(([name,title])=>({name,title,description:artifactDescription(name)}))
})
const stageDescriptions: Record<string,string> = {
  data_survey:'核对本地文件、官网与论文，整理统计和后续操作需要的文献。',
  data_collection:'检查数据接入条件、核对任务标签，并生成标准数据副本。',
  data_preprocessing:'根据调研设计候选方案，执行信号处理并校验输出。',
  data_evaluation:'从可用候选中随机选择一版，本轮未进行质量排名。',
  data_report:'将已验证的过程数据组织为可阅读的处理报告。',
  data_delivery:'导出训练数组、标签、被试分组和复现记录。',
}
function fileUrl(name: string, download = true) {
  const hash = current.value?.artifacts.find(file => file.name === name)?.sha256
  return apiUrl(`/api/workflows/${current.value!.id}/artifacts/${name.split('/').map(encodeURIComponent).join('/')}?download=${download}${hash ? `&v=${encodeURIComponent(hash)}` : ''}`)
}
function date(value: string) { return new Date(value).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) }
async function showStage(item: Stage) { stageName.value=item.name; await nextTick(); stageDialog.value?.showModal() }
function showStageFiles() {
  const mapping: Record<string,string> = {data_survey:'survey',data_collection:'collection',data_preprocessing:'preprocessing',data_evaluation:'evaluation',data_report:'report',data_delivery:'delivery'}
  files.value?.selectGroup(mapping[stageName.value] ?? 'all'); view.value='files'; stageDialog.value?.close()
}
function escapeFocus(event: KeyboardEvent) { if(event.key==='Escape') focused.value=false }
async function refresh(id:string) {
  try {
    const state=await apiRequest<Workflow>(`/api/workflows/${id}`)
    if(disposed || selectedId.value!==id) return
    current.value=state; jobs.value=[state,...jobs.value.filter(j=>j.id!==id)]; error.value=''
    if(active.value) timer=setTimeout(()=>void refresh(id),2000)
  } catch(reason) { if(!disposed && selectedId.value===id) error.value=String(reason) }
}
async function select(id:string) {
  if(timer) clearTimeout(timer)
  if(selectedId.value!==id) { current.value=null; view.value='reports'; focused.value=false; logQuery.value='' }
  selectedId.value=id
  await router.replace({path:'/workflows',query:{id}})
  await refresh(id)
}
async function start() {
  if(busy.value) return
  busy.value=true; error.value=''
  try {
    const job=await apiRequest<Workflow>('/api/workflows',{method:'POST',body:JSON.stringify({source_root:source.value,max_subjects:count.value,adapter:'eegmmidb',runs:[4,8],seed:42,tmin:0,tmax:2})})
    createDialog.value?.close(); await select(job.id)
  } catch(reason) {error.value=String(reason)} finally {busy.value=false}
}
async function retry() {
  if(!current.value || busy.value) return
  busy.value=true
  try {await apiRequest(`/api/workflows/${current.value.id}/retry`,{method:'POST'});stageDialog.value?.close();await select(current.value.id)}
  catch(reason) {error.value=String(reason)} finally {busy.value=false}
}
onMounted(async()=>{
  document.addEventListener('keydown',escapeFocus)
  try {
    const [settings,items]=await Promise.all([apiRequest<{allowed_roots:string[]}>('/api/workflows/sources'),apiRequest<Workflow[]>('/api/workflows')])
    if(disposed) return
    roots.value=settings.allowed_roots;source.value=roots.value[0] ?? '';jobs.value=items
    const id=typeof route.query.id==='string' ? route.query.id : items[0]?.id
    if(id) await select(id)
    else {await nextTick();createDialog.value?.showModal()}
  } catch(reason) {if(!disposed) error.value=String(reason)}
})
onBeforeUnmount(()=>{disposed=true;if(timer) clearTimeout(timer);document.removeEventListener('keydown',escapeFocus)})
</script>

<template>
  <main class="workflow-page" :class="{focused}">
    <header v-show="!focused" class="topbar">
      <div class="brand"><RouterLink to="/" aria-label="返回对话">←</RouterLink><span class="brand-mark">B</span><div><strong>Brain Agent</strong><span class="brand-caption">数据工作区</span></div></div>
      <div class="top-actions"><label class="run-picker"><span>当前运行</span><select :value="selectedId" aria-label="选择运行记录" @change="select(($event.target as HTMLSelectElement).value)"><option v-if="!jobs.length" value="">暂无运行</option><option v-for="job in jobs" :key="job.id" :value="job.id">{{date(job.created_at)}} · {{labels[job.status] ?? job.status}} · {{job.id.slice(0,6)}}</option></select></label><button class="primary new-run" @click="createDialog?.showModal()">＋ 新建流程</button></div>
    </header>
    <p v-if="error && !createDialog?.open" class="page-error" role="alert">{{error}} <button v-if="selectedId" @click="select(selectedId)">重新连接</button></p>
    <template v-if="current">
      <section v-show="!focused" class="progress-panel" aria-label="流程进度">
        <div class="run-heading"><div class="dataset-heading"><h1 :title="sourceSummary?.profile.name">{{sourceSummary?.profile.name ?? 'EEG 数据流程'}}</h1><span class="badge" :class="current.status">{{labels[current.status]}}</span></div><div class="progress-summary"><span role="status">{{completedCount}} / 6 个模块已完成</span><button v-if="current.status==='failed'" class="retry-button" :disabled="busy" @click="retry">重试未完成步骤</button></div></div>
        <ol class="stages"><li v-for="(item,index) in current.stages" :key="item.name" :class="item.status"><button :aria-label="`${item.label}：${labels[item.status]}，查看详情`" @click="showStage(item)"><span class="stage-number">{{item.status==='completed'?'✓':item.status==='failed'?'!':index+1}}</span><span class="stage-copy"><strong>{{item.label}}</strong><small>{{labels[item.status]}}</small></span><span class="stage-more">›</span></button></li></ol>
        <div class="activity-strip"><span class="activity-dot" :class="{live:active}"/><span v-if="active" class="activity-label">正在推进</span><span v-else class="activity-label">{{current.status==='completed'?'流程已完成':'运行记录'}}</span><button class="activity-message" :title="latest?.message" @click="view='logs'">{{latest?.message ?? '等待执行记录'}}</button><span v-if="delivered" class="output-summary">{{delivered.shape[0]}} Epoch · {{delivered.shape[1]}} 通道</span></div>
      </section>
      <section class="work-area" aria-label="运行产物工作区">
        <nav v-show="!focused" class="workspace-tabs" aria-label="工作区视图"><button v-for="(label,key) in viewLabels" :key="key" :aria-pressed="view===key" @click="view=key">{{label}}<span v-if="key==='reports'">{{reports.length}}</span><span v-if="key==='files'">{{current.artifacts.length}}</span></button><span class="workspace-caption">{{view==='reports'?'选择报告，在此阅读':view==='files'?'按模块查找全部产物':view==='logs'?'最近的记录显示在前':'下载与复现'}}</span></nav>
        <div class="workspace-body">
          <ReportReader v-show="view==='reports'" :reports="reports" :workflow-id="current.id" :file-url="fileUrl" :focused="focused" @focus="focused=!focused" @exit-focus="focused=false" />
          <ArtifactExplorer v-show="view==='files'" ref="files" :artifacts="current.artifacts" :workflow-id="current.id" :file-url="fileUrl" />
          <section v-show="view==='logs'" class="logs-panel" aria-label="执行日志"><header class="content-toolbar"><div><h2>执行日志</h2><span>{{current.events.length}} 条记录 · 最新在前</span></div><input v-model="logQuery" type="search" placeholder="搜索执行记录…" aria-label="搜索执行记录" /></header><ol class="event-list"><li v-for="event in events" :key="`${current.id}-${event.id}`"><time>{{date(event.time)}}</time><div><span class="event-agent">{{current.stages.find(s=>s.name===event.agent)?.label ?? event.agent}}</span><p>{{event.message}}</p></div></li><li v-if="!events.length" class="empty-message">{{logQuery?'没有匹配的执行记录。':'流程开始后，执行记录会在此更新。'}}</li></ol></section>
          <section v-show="view==='delivery'" class="delivery-panel" aria-label="训练数据"><div v-if="delivered" class="delivery-content"><p class="eyebrow">READY FOR TRAINING</p><h2>训练数据已就绪</h2><p class="muted">数据、标签与复现记录已整理完成。</p><div class="stats"><div><strong>{{delivered.shape[0]}}</strong><span>Epoch</span></div><div><strong>{{delivered.shape[1]}}</strong><span>EEG 通道</span></div><div><strong>{{delivered.shape[2]}}</strong><span>每段时间点</span></div></div><div class="download-actions"><a class="primary" :href="fileUrl('training-data.zip')">↓ 下载训练数据包</a><a :href="fileUrl('delivery/manifest.json')">数据清单 ↗</a></div><div class="delivery-notes"><h3>使用说明</h3><p>训练 / 验证 / 测试按被试分组。候选方法随机选择，本轮未进行质量排名。</p><p>数据包包含 X、y、分组、通道信息、原始事件映射与复现记录。</p></div></div><div v-else class="empty-state"><h2>训练数据尚未就绪</h2><p>处理与校验完成后，可在这里下载数据包。已完成的调研报告可先行阅读。</p><button @click="view='reports'">查看现有报告 →</button></div></section>
        </div>
      </section>
    </template>
    <section v-else class="initial-state"><span class="initial-symbol">▤</span><h1>{{selectedId?'正在载入运行…':'从本地 EEG 到训练数据'}}</h1><p>调研资料、核对数据、执行预处理，在一个工作区中查看结果。</p><button v-if="!selectedId" class="primary" @click="createDialog?.showModal()">新建数据流程</button></section>
    <dialog ref="createDialog" class="create-dialog" aria-labelledby="create-title"><div class="dialog-heading"><div><p class="eyebrow">NEW WORKFLOW</p><h2 id="create-title">开始数据流程</h2></div><button type="button" class="icon-button" aria-label="关闭新建流程" @click="createDialog?.close()">×</button></div><p class="muted">选择本地数据，Agent 将完成调研、处理与交付。</p><form @submit.prevent="start"><label>本地数据目录<input v-model="source" list="source-roots" required placeholder="选择已配置的 EEGMMIDB 目录" aria-label="本地数据目录" /></label><datalist id="source-roots"><option v-for="root in roots" :key="root" :value="root" /></datalist><label>被试数量<input v-model.number="count" type="number" min="1" max="12" required aria-label="被试数量" /></label><div class="form-scope"><span>左右手运动想象</span><span>Run 4 / 8</span><span>训练窗口 0–2 秒</span></div><p v-if="error" class="page-error" role="alert">{{error}}</p><button class="primary submit-run" :disabled="busy || !source">{{busy?'正在提交…':'开始完整流程 →'}}</button></form></dialog>
    <dialog ref="stageDialog" class="stage-dialog" aria-labelledby="stage-title"><template v-if="stage"><div class="dialog-heading"><h2 id="stage-title">{{stage.label}}</h2><button class="icon-button" aria-label="关闭阶段详情" @click="stageDialog?.close()">×</button></div><span class="badge" :class="stage.status">{{labels[stage.status]}}</span><p>{{stageDescriptions[stage.name] ?? '本阶段的处理状态与记录。'}}</p><details v-if="stage.error" class="stage-error" open><summary>错误详情</summary><pre>{{stage.error}}</pre></details><p v-else class="muted">{{stage.status==='pending'?'前序阶段完成后将自动开始。':'完整过程与产物保存在对应模块的记录文件中。'}}</p><div class="dialog-actions"><button v-if="stage.status==='failed'" class="primary" :disabled="busy" @click="retry">重试未完成步骤</button><button @click="showStageFiles">查看本阶段文件 →</button><button @click="view='logs';stageDialog?.close()">执行日志</button></div></template></dialog>
  </main>
</template>

<style scoped>
.workflow-page{height:100dvh;min-height:480px;box-sizing:border-box;display:flex;flex-direction:column;gap:16px;padding:0 28px 20px;background:#f2f5f3;color:#263e31;font:14px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif;overflow:hidden}
.workflow-page *{box-sizing:border-box}button,input,select{font:inherit}button,a,summary{-webkit-tap-highlight-color:transparent}button{cursor:pointer}button:disabled{opacity:.55;cursor:wait}a{color:#356b4f;text-decoration:none}a:hover{text-decoration:underline}h1,h2,h3,p{margin:0}button{border:1px solid #d6e1d9;background:white;border-radius:7px;padding:8px 13px;color:#3e614b}button:hover{background:#edf4ef}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:2px solid #39845b;outline-offset:3px}
.primary{display:inline-block;background:#285e43;border:1px solid #285e43;color:white;padding:9px 16px;border-radius:7px;text-decoration:none;font-size:13px}.primary:hover{background:#1e4c34}
.topbar{display:flex;align-items:center;justify-content:space-between;height:72px;flex-shrink:0;border-bottom:1px solid #dfe7e1;gap:20px}.brand{display:flex;gap:12px;align-items:center}.brand>a{font-size:18px;color:#8c9c91;margin-right:8px}.brand-mark{display:grid;place-items:center;width:30px;height:34px;border-radius:8px;background:#285e43;color:white;font:20px Georgia,serif}.brand strong{font-size:14px;font-weight:650}.brand-caption{display:block;font-size:10px;color:#839388;letter-spacing:.1em}.top-actions{display:flex;align-items:center;gap:20px}.run-picker{display:flex;align-items:center;gap:10px;color:#819084;font-size:11px}.run-picker select{border:0;color:#496151;background:transparent;padding:6px 18px 6px 4px;max-width:270px;font-size:12px}
.progress-panel{flex-shrink:0}.run-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;gap:12px}.dataset-heading{display:flex;align-items:center;gap:12px;min-width:0}.dataset-heading h1{font-size:18px;line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;letter-spacing:-.02em}.badge{display:inline-block;font-size:10px;padding:3px 9px;border-radius:20px;background:#e5ebe7;color:#64766a;white-space:nowrap}.badge.completed{background:#deeee2;color:#2d7045}.badge.failed{background:#f8e5dd;color:#a75030}.badge.running{background:#e1ebe8;color:#286747}.progress-summary{display:flex;gap:12px;align-items:center;font-size:11px;color:#77867c;white-space:nowrap}.retry-button{color:#a15432;border-color:#e7cebe;font-size:11px;padding:4px 9px}
.stages{list-style:none;display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;padding:0;margin:0}.stages li{min-width:0}.stages button{display:flex;align-items:center;gap:9px;width:100%;padding:10px 12px;border:1px solid #dee6e0;background:#fff;border-radius:8px;text-align:left;color:#60776a}.stage-number{width:25px;height:25px;flex-shrink:0;display:grid;place-items:center;border-radius:50%;background:#f0f3f1;color:#91a195;font-size:11px}.stage-copy{min-width:0}.stage-copy strong{display:block;font-size:12px;font-weight:550;white-space:nowrap}.stage-copy small{font-size:10px;color:#91a195}.stage-more{margin-left:auto;color:#bdc9c0}.completed .stage-number{background:#e3f0e7;color:#34734b}.running button{border-color:#74a485;background:#f5faf7}.running .stage-number{background:#2e704b;color:#fff}.running .stage-copy strong{color:#285b3d}.failed button{border-color:#dcae94;background:#fff9f5}.failed .stage-number{background:#f9e5d9;color:#ad6240}
.activity-strip{display:flex;align-items:center;gap:9px;margin-top:10px;color:#72877a;font-size:11px;min-width:0}.activity-dot{height:5px;width:5px;background:#9eb6a5;border-radius:50%;flex-shrink:0}.activity-dot.live{background:#4b9870;box-shadow:0 0 0 3px #e0eee4}.activity-label{white-space:nowrap;color:#667d6d}.activity-message{border:0;background:none;padding:0;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;color:#91a195;text-align:left}.activity-message:hover{color:#376949;background:none}.output-summary{margin-left:auto;white-space:nowrap;font-size:11px;color:#53705d}
.work-area{flex:1;min-height:0;display:flex;flex-direction:column;background:white;border:1px solid #dce6df;border-radius:12px;overflow:hidden;box-shadow:0 3px 14px #1f4c2e04}.workspace-tabs{display:flex;align-items:center;padding:0 20px;border-bottom:1px solid #e3eae5;gap:24px;height:52px;flex-shrink:0}.workspace-tabs button{background:none;border:0;border-bottom:2px solid transparent;border-radius:0;height:100%;padding:0 2px;font-size:12px;color:#809085;white-space:nowrap}.workspace-tabs button[aria-pressed=true]{color:#2a6544;border-bottom-color:#2f7450;font-weight:650}.workspace-tabs button span{font-size:9px;padding:2px 5px;background:#eff4f0;border-radius:5px;margin-left:6px;font-weight:400;color:#79907f}.workspace-caption{margin-left:auto;font-size:10px;color:#99a59d}.workspace-body{flex:1;min-height:0;position:relative}.workspace-body>section{height:100%}.focused{padding:12px;gap:0}.focused .work-area{border-radius:10px}
.page-error{background:#fff0e9;color:#9f5135;padding:8px 14px;border-radius:7px;font-size:12px;max-height:100px;overflow:auto;flex-shrink:0}.logs-panel{display:flex;flex-direction:column;min-height:0}.content-toolbar{display:flex;justify-content:space-between;align-items:center;padding:18px 26px;border-bottom:1px solid #e7ece9;gap:18px}.content-toolbar h2{font-size:15px}.content-toolbar span{font-size:11px;color:#89988d}.content-toolbar input{width:260px;max-width:50%;font-size:12px;padding:9px 12px;border:1px solid #dce5de;border-radius:7px;background:#fafcfb}.event-list{list-style:none;overflow-y:auto;margin:0;padding:0 26px 24px;flex:1;min-height:0}.event-list li{display:flex;gap:28px;padding:16px 0;border-bottom:1px solid #edf1ee;align-items:baseline}.event-list time{font-size:11px;white-space:nowrap;color:#91a095;font-variant-numeric:tabular-nums}.event-agent{font-size:10px;color:#7a9382;background:#f0f5f1;padding:2px 5px;border-radius:3px}.event-list p{font-size:13px;color:#425f4d;margin-top:5px;overflow-wrap:anywhere;white-space:pre-wrap}
.delivery-panel{overflow-y:auto;background:linear-gradient(150deg,#fff 60%,#f2f8f3)}.delivery-content{max-width:780px;margin:0 auto;padding:44px 36px}.eyebrow{font-size:10px;color:#86a18f;letter-spacing:.13em;margin-bottom:10px}.delivery-content h2{font-size:26px;margin-bottom:8px}.muted{font-size:13px;color:#809086}.stats{display:flex;gap:65px;margin:30px 0}.stats strong{display:block;font-size:34px;letter-spacing:-.04em;font-weight:500;color:#315b3e}.stats span{font-size:11px;color:#7f9486}.download-actions{display:flex;gap:22px;align-items:center;font-size:12px}.delivery-notes{border-top:1px solid #e1eae4;margin-top:32px;padding-top:22px}.delivery-notes h3{font-size:13px;margin-bottom:10px}.delivery-notes p{font-size:12px;color:#83968a;margin-top:8px}
.empty-state,.initial-state{display:flex;align-items:center;justify-content:center;flex-direction:column;text-align:center;gap:16px;padding:32px;color:#789080}.empty-state{height:100%}.empty-state h2{font-size:20px;color:#365c43}.empty-state p{font-size:13px;max-width:420px}.initial-state{flex:1}.initial-state h1{font-size:26px;color:#33573e}.initial-state p{font-size:13px}.initial-symbol{font-size:45px;color:#a9beaf}.empty-message{font-size:13px;color:#789080}
dialog{border:1px solid #d9e4dc;border-radius:16px;box-shadow:0 24px 100px #16352630;padding:28px;width:min(520px,calc(100vw - 32px));max-height:85dvh;overflow:auto;color:#314d3b}dialog::backdrop{background:#19342455;backdrop-filter:blur(3px)}.dialog-heading{display:flex;justify-content:space-between;align-items:start;gap:20px;margin-bottom:14px}.dialog-heading h2{font-size:22px}.icon-button{border:0;font-size:23px;line-height:1;background:#f2f6f3;padding:4px 8px;border-radius:50%;color:#7b9182}.create-dialog label{display:block;margin-top:22px;font-size:12px;color:#5a7362}.create-dialog input{display:block;width:100%;padding:11px 12px;margin-top:8px;border:1px solid #d4e0d7;border-radius:7px;font-size:13px}.form-scope{display:flex;gap:7px;flex-wrap:wrap;margin:18px 0 26px}.form-scope span{font-size:10px;background:#f0f5f1;color:#82988a;padding:4px 8px;border-radius:4px}.submit-run{width:100%}.stage-dialog{width:min(650px,calc(100vw - 32px))}.stage-dialog>p{font-size:13px;margin:18px 0}.dialog-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:24px}.dialog-actions button{font-size:12px}.stage-error{margin:18px 0;border:1px solid #eed6c8;padding:12px;border-radius:7px;background:#fff9f5}.stage-error summary{font-size:12px;color:#a45d3d;cursor:pointer}.stage-error pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.7 system-ui;max-height:40dvh;overflow:auto;color:#9b5a3e;margin-bottom:0}
@media(max-width:1000px){.workflow-page{padding:0 16px 14px;gap:12px}.stages button{padding:9px 8px;gap:7px}.stage-more{display:none}.stage-copy strong{font-size:11px}.dataset-heading h1{font-size:16px}.focused{padding:8px}.workspace-caption{display:none}.run-picker>span{display:none}}
@media(max-width:700px){.workflow-page{padding:0 10px 10px;gap:10px}.topbar{height:60px;gap:10px}.brand{gap:7px}.brand>a{margin-right:0}.brand-mark,.brand-caption{display:none}.brand strong{font-size:12px}.top-actions{gap:8px}.run-picker select{font-size:10px;max-width:168px;padding:4px}.new-run{font-size:10px;padding:7px 8px}.run-heading{margin-bottom:10px}.dataset-heading h1{max-width:46vw;font-size:13px}.dataset-heading{gap:6px}.progress-summary{font-size:9px;gap:6px}.stages{gap:5px}.stages button{flex-direction:column;text-align:center;gap:4px;padding:8px 2px}.stage-number{width:20px;height:20px;font-size:10px}.stage-copy strong{font-size:9px}.stage-copy small{display:none}.activity-strip{margin-top:8px}.output-summary{display:none}.workspace-tabs{padding:0 12px;gap:18px;height:44px}.workspace-tabs button{font-size:11px}.workspace-tabs button span{font-size:8px;margin-left:3px}.event-list{padding:0 16px}.event-list li{gap:12px}.content-toolbar{padding:14px 16px}.delivery-content{padding:28px 22px}.stats{gap:35px}.stats strong{font-size:28px}.focused{padding:5px}}
</style>
