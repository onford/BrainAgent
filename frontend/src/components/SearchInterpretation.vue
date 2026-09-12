<script setup lang="ts">
import { t } from '../i18n'
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
  get method_documentation_and_primary_abstract() { return t('Method documentation and research abstract') },
  get engineering_descriptive() { return t('Descriptive engineering parameters') },
  get conditional_primary_method() { return t('Primary method with applicability conditions') },
  get mathematical_definition_and_engineering() { return t('Mathematical definition and engineering convention') },
  get engineering_proxy() { return t('Indirect diagnostic proxy') },
  get method_documentation_and_engineering() { return t('Method documentation and engineering convention') },
  get project_paired_counterfactual_design() { return t('Project reconstruction design') },
  get frozen_project_protocol() { return t('Run evaluation protocol') },
}
</script>
<template>
  <details class="guide" @toggle="expanded = ($event.target as HTMLDetailsElement).open; expanded && load()">
    <summary>{{ t('Interpretation guide') }}<span>{{ t('Metric definitions · Parameter rationale · References') }}</span></summary>
    <p class="note">{{ frozen ? t('Metric guidance saved with this run.') : t('This run has no saved guide. Current guidance is shown below.') }}</p>
    <p v-if="loading" role="status">{{ t('Loading interpretation guide…') }}</p>
    <p v-if="error" role="alert">{{ t('The guide could not be loaded.') }}<button @click="load">{{ t('Reload') }}</button></p>
    <template v-if="guide">
      <div class="guide-toolbar">
        <label>{{ t('Find a topic') }}<input v-model="query" type="search" :placeholder="t('For example: PSD, baseline, correlation')" /></label>
        <small>{{ t('{0} topics · Reviewed {1}', { 0: cards.length, 1: guide.reviewed_at }) }}</small>
      </div>
      <p v-if="!cards.length" class="note" role="status">{{ t('No matching topics. Try a metric name or parameter keyword.') }}</p>
      <div class="guide-cards">
        <details v-for="card in cards" :key="card.id" class="knowledge-card">
          <summary><strong>{{ card.title }}</strong></summary>
          <div class="card-body">
            <p>{{ card.reading }}</p>
            <p class="conditions"><strong>{{ t('Applicability') }}</strong>{{ card.conditions.join('；') }}</p>
            <div class="reading-columns">
              <section><h4>{{ t('Alternative explanations') }}</h4><ul><li v-for="item in card.alternatives" :key="item">{{ item }}</li></ul></section>
              <section><h4>{{ t('Suggested checks') }}</h4><ul><li v-for="item in card.checks" :key="item">{{ item }}</li></ul></section>
            </div>
            <p class="limit"><strong>{{ t('Interpretation limits') }}</strong>{{ card.forbidden_inference }}</p>
            <dl><template v-for="(value, key) in card.parameters" :key="key"><dt>{{ key }}</dt><dd>{{ value }}</dd></template></dl>
            <p class="note">{{ t('{0} · Actual values are recorded in run parameters and measurements.', { 0: evidenceLabels[card.evidence_level] || t('Supporting evidence') }) }}</p>
            <details class="references"><summary>{{ t('References and locations · {0}', { 0: card.source_ids.length }) }}</summary>
              <ul><li v-for="source in sources(card.source_ids)" :key="source.id"><a :href="source.url" target="_blank" rel="noopener">{{ source.title }} ↗</a><small>{{ source.locator }} · {{ source.evidence }}</small></li></ul>
            </details>
          </div>
        </details>
      </div>
      <details class="scope"><summary>{{ t('Scope and limitations') }}</summary><p v-for="gap in guide.research_gaps" :key="gap.topic"><strong>{{ gap.topic }}：</strong>{{ gap.decision }}</p><small>{{ t('Knowledge version {0}', { 0: guide.schema_version }) }}</small></details>
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
