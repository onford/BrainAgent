<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { artifactDescription, groupArtifactFiles, type WorkflowArtifact } from '../../utils/artifacts'

const props = defineProps<{ artifacts: WorkflowArtifact[]; workflowId: string; fileUrl: (name: string, download?: boolean) => string }>()
const query = ref(''), group = ref('all')
const opened = ref<Record<string, boolean>>({}), limits = ref<Record<string, number>>({})
watch([query, group, () => props.workflowId], () => { opened.value = {}; limits.value = {} })
const names: Record<string,string> = { process:'流程索引',survey:'数据调研',collection:'数据接入',preprocessing:'预处理',evaluation:'结果选择',report:'数据报告',delivery:'训练数据',workflow:'运行与数据包' }
const category = (name: string) => name.includes('/') ? name.split('/')[0]! : 'workflow'
function selectGroup(value: string) { group.value = value; query.value = '' }
defineExpose({ selectGroup })
watch(() => props.workflowId, () => { group.value = 'all'; query.value = '' })
const groups = computed(() => Object.entries(names).map(([key,label]) => ({key,label,count:props.artifacts.filter(a=>category(a.name)===key).length})).filter(g=>g.count))
const matched = computed(() => props.artifacts.filter(a => (group.value==='all' || category(a.name)===group.value) && `${a.name} ${artifactDescription(a.name)}`.toLowerCase().includes(query.value.toLowerCase().trim())))
const families = computed(() => groupArtifactFiles(matched.value))
const size = (bytes: number) => bytes < 1024 ? `${bytes} B` : bytes < 1024**2 ? `${(bytes/1024).toFixed(1)} KB` : `${(bytes/1024**2).toFixed(1)} MB`
</script>

<template>
  <section class="files-panel" aria-label="全部产出文件">
    <nav aria-label="按模块筛选文件"><button :aria-pressed="group==='all'" @click="group='all'">全部记录 <span>{{artifacts.length}}</span></button><button v-for="item in groups" :key="item.key" :aria-pressed="group===item.key" @click="group=item.key">{{item.label}} <span>{{item.count}}</span></button></nav>
    <div class="file-content"><header><label>查找文件<input v-model="query" type="search" placeholder="输入文件名或说明…" aria-label="查找文件" /></label><span>{{matched.length}} 个文件</span></header>
      <div class="file-list"><p class="hint">同类文件合并展示，展开即可逐个下载。文件名旁是内容概要。</p><p v-if="!matched.length" class="empty">{{artifacts.length?'没有匹配的文件，试试其他关键词或模块。':'尚未生成记录文件。'}}</p>
        <div v-for="family in families" :key="workflowId+family.key" class="file-group">
          <div v-if="family.files.length===1" v-for="file in family.files" :key="file.name" class="file-row"><div><a :href="fileUrl(file.name)">{{file.name}}</a><span class="file-description">{{artifactDescription(file.name)}}</span></div><small>{{size(file.bytes)}}</small></div>
          <details v-else class="file-family" :open="!!opened[family.key]" @toggle="opened[family.key]=($event.target as HTMLDetailsElement).open"><summary><strong>{{family.label}}</strong><span class="file-description">{{family.description}}</span><small>{{family.files.length}} 个文件 · {{size(family.bytes)}}</small></summary><template v-if="opened[family.key]"><div v-for="file in family.files.slice(0,limits[family.key] ?? 30)" :key="file.name" class="file-row"><div><a :href="fileUrl(file.name)">{{file.name}}</a><span class="file-description">{{artifactDescription(file.name)}}</span></div><small>{{size(file.bytes)}}</small></div><button v-if="family.files.length>(limits[family.key] ?? 30)" class="more-files" @click="limits[family.key]=(limits[family.key] ?? 30)+30">再显示 30 个（剩余 {{family.files.length-(limits[family.key] ?? 30)}} 个）</button></template></details>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.files-panel{display:grid;grid-template-columns:180px minmax(0,1fr);height:100%;min-height:0}nav{padding:18px 12px;background:#f7f9f8;border-right:1px solid #e4eae6;overflow:auto}nav button{display:flex;justify-content:space-between;gap:14px;width:100%;padding:10px 12px;background:none;border:0;border-radius:7px;margin:3px 0;font:inherit;font-size:13px;color:#50665a;cursor:pointer}nav button[aria-pressed=true]{background:#e1eee6;color:#1b5b3e;font-weight:650}nav span{font-size:11px;opacity:.7}.file-content{display:flex;flex-direction:column;min-width:0;min-height:0}header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:16px 24px;border-bottom:1px solid #e7ece9}header label{font-size:12px;color:#63766a;display:flex;align-items:center;gap:14px;flex:1}input{font:inherit;font-size:13px;padding:9px 12px;border:1px solid #d7e1da;border-radius:7px;max-width:350px;width:100%;min-width:0;background:#fafcfb}header>span{font-size:12px;color:#738279;white-space:nowrap}.file-list{flex:1;overflow:auto;min-height:0;padding:6px 24px 20px}.hint,.empty{font-size:12px;color:#738279}.file-group{border-bottom:1px solid #e8eeea}.file-row{display:flex;justify-content:space-between;gap:16px;padding:13px 4px;font-size:13px;align-items:center}.file-row>div{min-width:0}.file-row a{color:#315e45;text-decoration:none;overflow-wrap:anywhere}.file-row a:hover{text-decoration:underline}.file-description{display:block;font-size:12px;font-weight:400;color:#78877e;margin-top:3px;overflow-wrap:anywhere}small{font-size:11px;color:#849188;white-space:nowrap}.file-family{padding:12px 4px}.file-family summary{cursor:pointer;font-size:13px;color:#395b46}.file-family summary small{float:right}.file-family[open]>.file-row{margin-left:16px}.file-family[open]>summary{padding-bottom:12px}.file-family summary .file-description{display:inline;margin-left:10px}button:focus-visible,a:focus-visible,input:focus-visible,summary:focus-visible{outline:2px solid #438a64;outline-offset:3px}@media(max-width:650px){.files-panel{display:flex;flex-direction:column}nav{display:flex;padding:8px;overflow-x:auto;flex-shrink:0;border-right:0;border-bottom:1px solid #e4eae6}nav button{width:auto;white-space:nowrap}.file-content{flex:1}header{padding:12px}header label{font-size:0;gap:0}.file-list{padding:8px 14px}.file-family summary small{float:none;display:block;margin:5px 0}}
.more-files{margin:10px 16px;padding:8px 12px;border:1px solid #d7e1da;background:#f4f8f5;color:#315e45;border-radius:6px;cursor:pointer}
</style>
