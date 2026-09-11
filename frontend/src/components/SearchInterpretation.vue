<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { apiRequest } from '../api/client'
const props = defineProps<{ searchId: string; frozen?: boolean }>()
const guide = ref<any>(null), query = ref(''), error = ref(''), loading = ref(false)
const expanded = ref(false)
let serial = 0
watch(() => [props.searchId, props.frozen], () => { serial++; guide.value = null; error.value = ''; loading.value = false; if (expanded.value) void load() })
async function load() {
  if (guide.value || loading.value) return
  const token = ++serial; loading.value = true; error.value = ''
  try {
    const result = await apiRequest<any>(props.frozen ? `/api/searches/${encodeURIComponent(props.searchId)}/artifacts/interpretation-guide.json?download=false` : '/api/searches/interpretation-guide')
    if (token === serial) guide.value = result
  } catch (e) { if (token === serial) error.value = String(e) }
  finally { if (token === serial) loading.value = false }
}
const cards = computed(() => (guide.value?.cards ?? []).filter((c: any) => JSON.stringify(c).toLowerCase().includes(query.value.toLowerCase())))
const sources = (ids: string[]) => (guide.value?.sources ?? []).filter((s: any) => ids.includes(s.id))
const evidenceLabels: Record<string, string> = {
  method_documentation_and_primary_abstract: '方法文档与研究摘要',
  engineering_descriptive: '描述性工程参数',
  conditional_primary_method: '有适用条件的原始方法',
  mathematical_definition_and_engineering: '数学定义与工程约定',
  engineering_proxy: '间接诊断指标',
  method_documentation_and_engineering: '方法文档与工程约定',
  project_paired_counterfactual_design: '本项目重建实验设计',
  frozen_project_protocol: '本运行评价协议',
}
</script>
<template>
  <details class="guide" @toggle="expanded = ($event.target as HTMLDetailsElement).open; expanded && load()">
    <summary>阅读指南 <span>指标含义 · 参数依据 · 参考文献</span></summary>
    <p class="note">{{ frozen ? '本运行的指标说明。' : '此运行没有配套指南，以下为现行说明。' }}</p>
    <p v-if="loading" role="status">正在加载阅读指南…</p>
    <p v-if="error" role="alert">指南暂时无法加载。<button @click="load">重新加载</button></p>
    <template v-if="guide">
      <div class="guide-toolbar">
        <label>查找主题 <input v-model="query" type="search" placeholder="例如：功率谱、基线、相关性" /></label>
        <small>{{ cards.length }} 个主题 · 审阅于 {{ guide.reviewed_at }}</small>
      </div>
      <p v-if="!cards.length" class="note" role="status">没有匹配的主题，请尝试指标名称或参数关键词。</p>
      <div class="guide-cards">
        <details v-for="card in cards" :key="card.id" class="knowledge-card">
          <summary><strong>{{ card.title }}</strong><p>{{ card.reading }}</p></summary>
          <div class="card-body">
            <p class="conditions"><strong>适用条件</strong>{{ card.conditions.join('；') }}</p>
            <div class="reading-columns">
              <section><h4>其他可能原因</h4><ul><li v-for="item in card.alternatives" :key="item">{{ item }}</li></ul></section>
              <section><h4>建议核查</h4><ul><li v-for="item in card.checks" :key="item">{{ item }}</li></ul></section>
            </div>
            <p class="limit"><strong>解释边界</strong>{{ card.forbidden_inference }}</p>
            <dl><template v-for="(value, key) in card.parameters" :key="key"><dt>{{ key }}</dt><dd>{{ value }}</dd></template></dl>
            <p class="note">{{ evidenceLabels[card.evidence_level] || '参考依据' }} · 实际采用值见运行参数与测量记录。</p>
            <details class="references"><summary>参考文献与定位 · {{ card.source_ids.length }}</summary>
              <ul><li v-for="source in sources(card.source_ids)" :key="source.id"><a :href="source.url" target="_blank" rel="noopener">{{ source.title }} ↗</a><small>{{ source.locator }} · {{ source.evidence }}</small></li></ul>
            </details>
          </div>
        </details>
      </div>
      <details class="scope"><summary>适用范围与限制</summary><p v-for="gap in guide.research_gaps" :key="gap.topic"><strong>{{ gap.topic }}：</strong>{{ gap.decision }}</p><small>知识版本 {{ guide.schema_version }}</small></details>
    </template>
  </details>
</template>
<style scoped>
.guide { margin: 16px 0; padding: 18px 20px; border: 1px solid #dce5e7; border-radius: 12px; background: #fff; color: #253e43; font-size: 13px; line-height: 1.8; }
summary { cursor: pointer; color: #253e43; }
.guide > summary { font-size: 15px; font-weight: 600; }
.guide > summary span { display: inline-block; font-size: 12px; font-weight: 400; color: #586f75; margin-left: 12px; }
.note, small { color: #586f75; font-size: 12px; }
small { display: block; }
.guide-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; padding: 14px 0; }
input { display: block; width: min(320px, 100%); margin-top: 5px; padding: 9px 12px; border: 1px solid #cbd9dd; border-radius: 7px; background: #fff; color: #253e43; font: inherit; }
.guide-cards { display: grid; gap: 10px; }
.knowledge-card { border: 1px solid #e0e7e9; border-radius: 8px; }
.knowledge-card > summary { padding: 14px 16px; }
.knowledge-card > summary:hover { background: #f5f8f9; }
.knowledge-card > summary p { margin: 5px 0 0 18px; color: #586f75; font-size: 13px; font-weight: 400; }
.card-body { padding: 0 18px 18px; border-top: 1px solid #edf1f2; }
.conditions strong, .limit strong { display: block; font-size: 12px; margin-bottom: 4px; }
.reading-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
h4 { font-size: 13px; margin: 8px 0; }
ul { margin: 8px 0; padding-left: 20px; }
li { margin: 6px 0; }
.limit { padding: 12px 14px; border-radius: 6px; background: #faf6ec; color: #745c2c; }
dl { display: grid; grid-template-columns: minmax(90px, 140px) minmax(0, 1fr); gap: 10px; padding: 14px; background: #f5f8f9; border-radius: 6px; }
dt { color: #586f75; } dd { margin: 0; overflow-wrap: anywhere; }
a { color: #176e65; text-decoration: underline; text-underline-offset: 3px; }
.references summary, .scope summary { color: #176e65; font-size: 12px; }
.scope { margin-top: 20px; padding-top: 14px; border-top: 1px solid #e0e7e9; }
@media(max-width: 640px) { .guide { padding: 14px; } .reading-columns { grid-template-columns: 1fr; gap: 0; } }
</style>
