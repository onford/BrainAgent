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
</script>
<template>
  <details class="guide" @toggle="expanded = ($event.target as HTMLDetailsElement).open; expanded && load()"><summary>如何读图和指标 · 参数依据与文献知识库</summary>
    <p class="note">{{ frozen ? '本次运行冻结的知识版本。' : '当前审阅知识供阅读参考；此历史运行未冻结该知识，不能声称运行时 agent 已使用。' }} 观察 → 条件核对 → 竞争解释 → 下一项核查；不从图形直接生成质量等级。</p>
    <p v-if="loading">读取知识卡…</p><p v-if="error" role="alert">{{ error }} <button @click="load">重试知识库读取</button></p>
    <template v-if="guide"><label>检索指标、图形或参数 <input v-model="query" placeholder="例如 PSD、ASR、基线、0.4" /></label><p class="note">{{ guide.schema_version }} · 审阅 {{ guide.reviewed_at }} · {{ cards.length }} 张卡</p>
      <article v-for="card in cards" :key="card.id"><h4>{{ card.title }}</h4><p>{{ card.reading }}</p><p class="note">适用条件：{{ card.conditions.join('；') }}</p><p><strong>竞争解释：</strong>{{ card.alternatives.join('；') }}</p><p><strong>下一项核查：</strong>{{ card.checks.join('；') }}</p><p class="limit">{{ card.forbidden_inference }}</p><dl><template v-for="(value, key) in card.parameters" :key="key"><dt>{{ key }}</dt><dd>{{ value }}</dd></template></dl><p class="note">依据类型：{{ card.evidence_level }} · 以下是解释依据，实际采用值以本运行记录为准。</p><ul><li v-for="source in sources(card.source_ids)" :key="source.id"><a :href="source.url" target="_blank" rel="noopener">{{ source.title }}</a><small>{{ source.locator }} · {{ source.evidence }}</small></li></ul></article>
      <details><summary>未实现内容与审阅差异</summary><p v-for="gap in guide.research_gaps" :key="gap.topic"><strong>{{ gap.topic }}：</strong>{{ gap.decision }}</p></details>
    </template>
  </details>
</template>
<style scoped>
.guide{margin:20px 0;padding:15px 18px;background:#f7faf7;border:1px solid #dce7dd;border-radius:10px;font-size:13px;line-height:1.8}summary{cursor:pointer;color:#315f45;font-weight:600}.note,small{font-size:12px;color:#687b6c}small{display:block}input{padding:7px 10px;border:1px solid #d0ded3;border-radius:6px;margin-left:10px}article{background:white;border:1px solid #e0e8e1;border-radius:8px;padding:14px 18px;margin:14px 0}h4{margin:0}p{margin:8px 0}.limit{padding:9px;background:#faf5ea;color:#79623a}dl{display:grid;grid-template-columns:minmax(80px,140px) 1fr;gap:8px}dt{color:#375f44}dd{margin:0}a{color:#267258;overflow-wrap:anywhere}ul{padding-left:18px}
</style>
