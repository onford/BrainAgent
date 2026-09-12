<script setup lang="ts">
import { computed } from 'vue'
import { t } from '../i18n'
import { comparisonIdentity, MAX_COMPARISON_FIGURES, useFigureComparison, type ComparisonFigure } from '../utils/figureComparison'
const props = defineProps<{ figure: ComparisonFigure }>()
const { enabled, entries, toggle } = useFigureComparison()
const selected = computed(() => entries.value.some(e => e.identity === comparisonIdentity(props.figure)))
const full = computed(() => !selected.value && entries.value.length >= MAX_COMPARISON_FIGURES)
</script>
<template>
  <label v-if="enabled && figure.comparisonKey && figure.provenance" class="comparison-select" :title="full ? t('Select up to {0} figures. Remove one to add another.', { 0: MAX_COMPARISON_FIGURES }) : undefined">
    <input type="checkbox" :checked="selected" :disabled="full" :aria-label="t('Compare: {0}', { 0: figure.title })" @change="toggle(figure)">
    {{ selected ? t('Selected for comparison') : t('Select for comparison') }}
  </label>
</template>
<style scoped>
.comparison-select { display: inline-flex; align-items: center; gap: 7px; color: #176b63; font-size: 12px; cursor: pointer; }
.comparison-select input { width: 16px; height: 16px; margin: 0; padding: 0; accent-color: #167568; }
.comparison-select:has(input:disabled) { opacity: .55; cursor: default; }
</style>
