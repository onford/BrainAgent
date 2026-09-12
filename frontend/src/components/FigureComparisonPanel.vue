<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { t } from '../i18n'
import AssessmentPlot from './AssessmentPlot.vue'
import AssessmentHeatmap from './AssessmentHeatmap.vue'
import { comparisonFigures, useFigureComparison, type ComparisonEntry } from '../utils/figureComparison'
const { entries, remove, clear } = useFigureComparison()
const expanded = ref(false), groupKey = ref(''), enlarged = ref(false)
const panel = ref<HTMLElement | null>(null)
function showComparison() { expanded.value = true; panel.value?.scrollIntoView({ block: 'start' }) }
const groups = computed(() => {
  const map = new Map<string, ComparisonEntry[]>()
  for (const entry of entries.value) map.set(entry.group, [...(map.get(entry.group) ?? []), entry])
  return [...map].map(([key, items]) => ({ key, items, label: items[0]!.figure.comparisonLabel ?? items[0]!.figure.title }))
})
watch(groups, value => { if (!value.some(g => g.key === groupKey.value)) groupKey.value = value[0]?.key ?? '' }, { immediate: true })
const active = computed(() => groups.value.find(g => g.key === groupKey.value))
const figures = computed(() => comparisonFigures(active.value?.items ?? []))
const source = (entry: ComparisonEntry) => (entry.figure.provenance ?? {}) as Record<string, any>
const stages: Record<string, string> = { processed_task: 'Processed task epochs', source_task: 'Source task epochs', source_raw: 'Source continuous data', processed_continuous: 'Processed continuous data', source_precue: 'Source pre-cue baseline', processed_precue: 'Matched processed pre-cue baseline' }
</script>
<template>
  <aside ref="panel" class="figure-comparison" :class="{ expanded, empty: !entries.length }" :aria-label="t('Figure comparison')">
    <div class="comparison-toolbar">
      <strong>{{ t('Figure comparison') }} <span v-if="entries.length" aria-live="polite">{{ t('{0} selected', { 0: entries.length }) }}</span></strong>
      <div v-if="entries.length"><button :aria-expanded="expanded" @click="expanded = !expanded">{{ expanded ? t('Collapse comparison') : t('Compare selected figures') }}</button><button v-if="entries.length" @click="clear">{{ t('Clear selection') }}</button></div>
    </div>
    <p v-if="!entries.length" class="comparison-hint">{{ t('Select charts to compare across candidates or records. Up to 12; cleared on refresh.') }}</p>
    <template v-if="expanded && entries.length">
      <div class="comparison-groups" role="group" :aria-label="t('Figure groups')"><button v-for="group in groups" :key="group.key" :aria-pressed="group.key === groupKey" @click="groupKey = group.key">{{ group.label }} · {{ group.items.length }}</button></div>
      <p class="comparison-hint">{{ t('Same-type figures share axis or color limits. Each panel retains its original observations and source; this comparison does not establish a treatment effect.') }}</p>
      <p v-if="figures.length < 2" role="status">{{ t('Select another figure of this type to compare.') }}</p>
      <div class="comparison-layout" role="group" :aria-label="t('Comparison layout')"><button :aria-pressed="!enlarged" @click="enlarged = false">{{ t('Side by side') }}</button><button :aria-pressed="enlarged" @click="enlarged = true">{{ t('Enlarge figures') }}</button></div>
      <div class="comparison-grid" :class="{ enlarged }">
        <article v-for="(entry, index) in active?.items ?? []" :key="entry.identity" class="comparison-card">
          <div class="comparison-source">
            <strong>{{ t('Candidate') }}: {{ source(entry).candidate_id ?? source(entry).candidateId }}</strong>
            <span>{{ source(entry).stage ? (stages[source(entry).stage] ? t(stages[source(entry).stage] as any) : source(entry).stage) : '' }}<template v-if="source(entry).record_id"> · {{ source(entry).record_id }}</template><template v-else-if="source(entry).stage"> · {{ t('Equal-subject aggregate') }}</template><template v-if="source(entry).channel"> · {{ source(entry).channel }}</template></span>
            <small>{{ source(entry).assessment_path ?? source(entry).basePath ?? source(entry).path }}</small>
            <button :aria-label="t('Remove from comparison: {0}', { 0: entry.figure.title })" @click="remove(entry.identity)">{{ t('Remove') }}</button>
          </div>
          <AssessmentPlot v-if="figures[index]?.kind === 'series'" v-bind="figures[index] as any" />
          <AssessmentHeatmap v-else v-bind="figures[index] as any" />
          <details><summary>{{ t('Source and parameters') }}</summary><pre>{{ JSON.stringify(entry.figure.provenance, null, 2) }}</pre></details>
        </article>
      </div>
    </template>
  </aside>
  <button v-if="entries.length" class="comparison-shortcut" @click="showComparison">{{ t('Figure comparison') }} · {{ entries.length }} ↑</button>
</template>
<style scoped>
.figure-comparison { margin: 20px 0; border: 1px solid #c9ddd9; border-radius: 10px; padding: 14px; background: #f6fbf9; color: #274b43; }
.figure-comparison.empty { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px 16px; padding: 10px 14px; }
.figure-comparison.empty .comparison-hint { margin: 0; }
.comparison-toolbar, .comparison-toolbar > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.comparison-toolbar strong { font-size: 14px; }.comparison-toolbar strong span { font-weight: 400; margin-left: 10px; }
button { border: 1px solid #b7cec8; border-radius: 6px; padding: 7px 10px; background: white; color: #246452; cursor: pointer; font: inherit; font-size: 12px; }
button:disabled { opacity: .5; cursor: default; }button:focus-visible { outline: 2px solid #0072b2; outline-offset: 3px; }
.comparison-hint { font-size: 12px; color: #58746b; line-height: 1.7; margin: 10px 0 0; }
.comparison-groups { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }.comparison-groups [aria-pressed=true] { color: white; background: #246b59; }
.comparison-layout { display: flex; gap: 8px; margin-top: 12px; }.comparison-layout [aria-pressed=true] { border-color: #246b59; background: #e7f2ed; }
.comparison-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: start; gap: 18px; margin-top: 16px; }
.comparison-grid.enlarged { grid-template-columns: 1fr; }
.comparison-card { min-width: 0; padding: 12px; border: 1px solid #dbe5e2; border-radius: 8px; background: white; }
.comparison-source { display: flex; flex-direction: column; align-items: flex-start; gap: 7px; overflow-wrap: anywhere; font-size: 12px; line-height: 1.5; }
.comparison-source strong { font-size: 12px; }.comparison-source small { color: #667e75; }
.comparison-card :deep(.eeg-figure) { margin: 12px 0; padding: 8px; border: 0; }
.comparison-card :deep(.plot > .plot-scroll > svg), .comparison-card :deep(.heatmap .scroll > svg) { min-width: 0; }
.comparison-card summary { cursor: pointer; font-size: 12px; }.comparison-card pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow: auto; font-size: 11px; }
.comparison-shortcut { position: fixed; bottom: 20px; right: 24px; z-index: 30; background: #246b59; color: white; padding: 11px 16px; box-shadow: 0 3px 14px #173f3826; }
@media(max-width: 850px) {
  .comparison-grid { grid-template-columns: 1fr; }
  .comparison-card :deep(.plot > .plot-scroll > svg) { min-width: 580px; }
  .comparison-card :deep(.heatmap .scroll > svg) { min-width: 720px; }
}
</style>
