<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { computed, ref, watch } from 'vue'
import { apiRequest } from '../../api/client'
import type { SavedWorkflowEvaluation, SearchSummary } from '../../types/search'
const props = defineProps<{ workflowId: string; searchId?: string | null; evaluation?: SavedWorkflowEvaluation; reportCount: number; offline?: boolean }>()
const related = ref<SearchSummary[]>([]), inspectedSearch = ref(''), retrievalError = ref(false)
const evidenceSearchId = computed(() => props.searchId || inspectedSearch.value)
let serial = 0
watch(() => [props.workflowId, props.searchId, props.offline], async () => {
  const token = ++serial
  related.value = []; inspectedSearch.value = ''; retrievalError.value = false
  if (props.searchId || props.offline) return
  try {
    const rows = await apiRequest<SearchSummary[]>('/api/searches')
    if (token === serial && Array.isArray(rows)) related.value = rows.filter(row => row.workflow_id === props.workflowId)
  } catch { if (token === serial) retrievalError.value = true }
}, { immediate: true })
const emit = defineEmits<{ reports: []; files: [] }>()
const destinations = [
  { title: '决策概览', view: 'overview', axis: '', summary: '先看是否选定方案、采用什么评分规则，以及目前证据的完整程度。', contents: '所选方案 · 候选得分图 · 决策核验' },
  { title: '信号图表', view: 'assessment', axis: 'quality', summary: '比较信号在不同处理阶段的变化，结合单位、频带和参考方式解读图形。', contents: '功率谱 · 幅度与通道关系 · 测量参数' },
  { title: '评价指标', view: 'assessment', axis: 'utility', summary: '核对主评分、种子和被试差异；分别查看信号质量与重建结果。', contents: '训练效用 · 覆盖与缺失 · 重建实验' },
  { title: '预处理方案', view: 'assessment', axis: 'parameters', summary: '了解处理顺序、每一步的参数，以及哪些记录实际应用、跳过或失败。', contents: '算子顺序 · 参数依据 · 执行回执' },
  { title: 'Agent 决策记录', view: 'rounds', axis: '', summary: '追溯提案理由、竞争解释、预先预测和实测核验，理解选择如何推进。', contents: '观测依据 · 方案提案 · 预测是否成立' },
]
</script>
<template>
  <section class="workflow-evidence" aria-label="流程与证据">
    <header><p class="eyebrow">阅读本次流程</p><h2>看结果，也看它的依据</h2><p>图表呈现信号变化，指标用于检验效果，决策记录说明方案如何产生。报告与页面共同保留这条证据链。</p></header>
    <div v-if="!searchId" class="availability"><p>本流程未绑定唯一的策略搜索。{{ evaluation?.selection_policy === 'random' ? '流程保存的选择方式为随机选择，不应解释为指标择优。' : '流程选择方式以当时保存的报告与记录为准。' }}已有 {{ reportCount }} 篇报告可阅读。</p><label v-if="related.length">查看使用相同数据流程的搜索 <select v-model="inspectedSearch"><option value="">请选择一条搜索记录</option><option v-for="item in related" :key="item.id" :value="item.id">{{ item.created_at.slice(0,10) }} · {{ item.id }} · {{ ({completed:'已完成',failed:'失败',stopped:'已停止',cancelled:'已取消',running:'执行中',interrupted:'已中断',preparing:'准备中'})[item.status] || item.status }}</option></select></label><p v-if="related.length">这些搜索独立保存；查看其结果不会改变本流程原有的选择与交付。</p><p v-else>{{ retrievalError ? '相关搜索列表暂时无法读取。' : offline ? '离线文件未包含其他搜索记录。' : '尚未找到可关联的搜索记录。' }}</p></div>
    <p v-else-if="offline" class="availability">此离线文件未嵌入关联搜索页面。可阅读已收录报告；完整图表与决策记录请在在线工作区查看。</p>
    <div class="evidence-grid"><article v-for="(item, i) in destinations" :key="item.view + item.axis"><span class="step">0{{ i+1 }}</span><h3>{{ item.title }}</h3><p>{{ item.summary }}</p><small>{{ item.contents }}</small><RouterLink v-if="evidenceSearchId && !offline" :to="{path:'/searches', query:{id:evidenceSearchId, view:item.view, ...(item.axis ? {axis:item.axis} : {})}}">打开{{ item.title }} →</RouterLink><span v-else class="unavailable">{{ evidenceSearchId ? '在线工作区可查看' : '请先选择搜索记录' }}</span></article><article><span class="step">06</span><h3>报告与原始记录</h3><p>按主题阅读 {{ reportCount }} 篇已生成报告，或核对原始测量、文件哈希和交付内容。</p><small>调研报告 · 处理报告 · 文件来源</small><div><button @click="emit('reports')">阅读报告 →</button><button @click="emit('files')">查看文件 →</button></div></article></div>
    <footer><strong>如何判断结论支持到哪里</strong><p>先确认是当前候选还是正式选定方案，再看评价是否完整，最后核对分数的协议与范围。开发得分、图形变化和机制假设各有不同用途；未保存或未完成的证据不能当作成功。</p></footer>
  </section>
</template>
<style scoped>
.workflow-evidence{height:100%;box-sizing:border-box;overflow:auto;padding:28px 32px;color:#2a453c;line-height:1.8}.eyebrow{font-size:11px;letter-spacing:.06em;color:#4e8370;margin:0}header h2{font-size:25px;margin:5px 0 10px;font-weight:600}header>p:last-child{color:#5d766b;font-size:14px;max-width:780px}.availability select{display:block;max-width:100%;padding:8px;border:1px solid #d6c9af;border-radius:6px;font:inherit;background:white;color:#5e523e}.availability{background:#f8f4eb;color:#7b653e;border:1px solid #e9dfc9;padding:14px 18px;border-radius:9px;font-size:13px}.evidence-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-top:24px}article{display:flex;flex-direction:column;align-items:start;padding:22px;border:1px solid #dae5df;border-radius:12px;background:#fafcfb}.step{font-size:12px;color:#769789}h3{font-size:17px;margin:4px 0}article p{font-size:13px;color:#587164;flex:1;margin:8px 0 15px}small{font-size:11px;color:#607b6e;margin-bottom:18px}.unavailable{font-size:12px;color:#7c8379}a,button{font:inherit;font-size:12px;color:#236b4e;background:white;border:1px solid #cddfd4;border-radius:6px;padding:7px 10px;text-decoration:none;cursor:pointer}article>div{display:flex;flex-wrap:wrap;gap:8px}a:hover,button:hover{background:#eaf3ee}footer{margin-top:26px;background:#eff5f1;border-radius:10px;padding:18px 22px;font-size:13px}footer p{color:#587164;margin:5px 0} @media(max-width:1100px){.evidence-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:650px){.workflow-evidence{padding:20px 16px}.evidence-grid{grid-template-columns:1fr}header h2{font-size:21px}}
</style>
