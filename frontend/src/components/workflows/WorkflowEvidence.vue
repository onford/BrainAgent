<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { apiRequest } from '../../api/client'
import type { SavedWorkflowEvaluation, SearchSummary } from '../../types/search'
const props = defineProps<{ workflowId: string; searchId?: string | null; evaluation?: SavedWorkflowEvaluation; reportCount: number; offline?: boolean }>()
const related = ref<SearchSummary[]>([]), inspectedSearch = ref(''), retrievalError = ref(false), loading = ref(false)
const evidenceSearchId = computed(() => props.searchId || inspectedSearch.value)
let serial = 0
async function loadRelated() {
  const token = ++serial
  retrievalError.value = false
  if (props.searchId || props.offline) { loading.value = false; return }
  loading.value = true
  try {
    const rows = await apiRequest<SearchSummary[]>('/api/searches')
    if (!Array.isArray(rows)) throw new Error('Invalid search list')
    if (token === serial) related.value = rows.filter(row => row.workflow_id === props.workflowId)
  } catch { if (token === serial) retrievalError.value = true }
  finally { if (token === serial) loading.value = false }
}
watch(() => [props.workflowId, props.searchId, props.offline], () => {
  related.value = []; inspectedSearch.value = ''
  void loadRelated()
}, { immediate: true })
onBeforeUnmount(() => { serial++ })
const searchLabel = (item: SearchSummary) => `${new Date(item.created_at).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})} · ${item.id.slice(0,8)} · ${{completed:'已完成',failed:'失败',stopped:'已停止',cancelled:'已取消',running:'执行中',interrupted:'已中断',preparing:'准备中'}[item.status] || item.status}`
const emit = defineEmits<{ reports: []; files: [] }>()
const destinations = [
  { title: '决策概览', view: 'overview', axis: '', summary: '所选方案、评分规则与候选比较。' },
  { title: '信号图表', view: 'assessment', axis: 'quality', summary: '各处理阶段的功率谱、幅度与通道关系。' },
  { title: '评价指标', view: 'assessment', axis: 'utility', summary: '模型表现、被试差异、信号质量与重建结果。' },
  { title: '预处理方案', view: 'assessment', axis: 'parameters', summary: '处理步骤、参数及逐记录执行情况。' },
  { title: 'Agent 决策记录', view: 'rounds', axis: '', summary: '提案理由、竞争解释与实测核验。' },
]
</script>
<template>
  <section class="workflow-evidence" aria-label="流程与证据">
    <header><h2>分析结果</h2><p>图表、评价指标、处理方案与报告。</p></header>
    <div v-if="!searchId" class="availability">
      <p v-if="loading" role="status">正在加载搜索记录…</p>
      <p v-else-if="retrievalError" role="alert">搜索记录加载失败。<button @click="loadRelated">重试</button></p>
      <template v-else-if="related.length">
        <label>搜索记录 <select v-model="inspectedSearch"><option value="">选择要查看的搜索</option><option v-for="item in related" :key="item.id" :value="item.id">{{ searchLabel(item) }}</option></select></label>
        <small>这些搜索使用本流程的数据；结果与本流程的原交付分别记录。</small>
      </template>
      <p v-else>{{ offline ? '此离线版仅收录流程报告。' : '暂无搜索记录，可查看已有报告与文件。' }}</p>
      <p v-if="evaluation?.selection_policy === 'random'" class="selection-note">原交付采用随机选择，未按指标择优。</p>
    </div>
    <p v-else-if="offline" class="availability">离线版可阅读已收录报告，搜索图表和决策详情需在线查看。</p>
    <div class="evidence-grid"><article v-for="item in destinations" :key="item.view + item.axis"><h3>{{ item.title }}</h3><p>{{ item.summary }}</p><RouterLink v-if="evidenceSearchId && !offline" :to="{path:'/searches', query:{id:evidenceSearchId, view:item.view, ...(item.axis ? {axis:item.axis} : {})}}">打开{{ item.title }} →</RouterLink><span v-else class="unavailable">{{ offline ? '仅在线查看' : '暂不可用' }}</span></article><article><h3>报告与原始记录</h3><p>{{ reportCount }} 篇报告，以及测量、模型和交付文件。</p><div><button @click="emit('reports')">阅读报告 →</button><button @click="emit('files')">查看文件 →</button></div></article></div>
  </section>
</template>
<style scoped>
.workflow-evidence{height:100%;box-sizing:border-box;overflow:auto;padding:28px 32px;color:#2a453c;line-height:1.8}header h2{font-size:25px;margin:5px 0 10px;font-weight:600}header>p:last-child{color:#5d766b;font-size:14px;max-width:780px}.availability select{display:block;max-width:100%;padding:8px;border:1px solid #d6c9af;border-radius:6px;font:inherit;background:white;color:#5e523e}.availability{background:#f4f7f5;color:#516b5e;border:1px solid #dce6df;padding:12px 16px;border-radius:9px;font-size:13px}.availability p{margin:4px 0}.availability small{display:block;margin:8px 0 0}.availability button{margin-left:8px}.selection-note{font-size:12px;color:#76613f}.evidence-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-top:24px}article{display:flex;flex-direction:column;align-items:start;padding:22px;border:1px solid #dae5df;border-radius:12px;background:#fafcfb}h3{font-size:17px;margin:4px 0}article p{font-size:13px;color:#587164;flex:1;margin:8px 0 15px}small{font-size:11px;color:#607b6e;margin-bottom:18px}.unavailable{font-size:12px;color:#7c8379}a,button{font:inherit;font-size:12px;color:#236b4e;background:white;border:1px solid #cddfd4;border-radius:6px;padding:7px 10px;text-decoration:none;cursor:pointer}article>div{display:flex;flex-wrap:wrap;gap:8px}a:hover,button:hover{background:#eaf3ee} @media(max-width:1100px){.evidence-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:650px){.workflow-evidence{padding:20px 16px}.evidence-grid{grid-template-columns:1fr}header h2{font-size:21px}}
</style>
