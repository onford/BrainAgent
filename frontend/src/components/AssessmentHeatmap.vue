<script setup lang="ts">
import { t } from '../i18n'
import { computed, ref } from 'vue'
import { finite, exportSvg, downloadData } from '../utils/assessmentPlots'
const props = defineProps<{ title: string; rows: string[]; columns: string[]; values: (number | null)[][]; unit: string; caption: string; diverging?: boolean; provenance?: unknown }>()
const svg = ref<SVGSVGElement | null>(null)
const numbers = computed(() => props.values.flat().filter(finite))
const limits = computed(() => {
  if (props.diverging) { const max = numbers.value.reduce((a, v) => Math.max(a, Math.abs(v)), 1e-12); return [-max, max] }
  const min = numbers.value.reduce((a, v) => Math.min(a, v), Infinity), max = numbers.value.reduce((a, v) => Math.max(a, v), -Infinity)
  return [min, max === min ? min + 1 : max]
})
const page = ref(0), size = 24
const pages = computed(() => Math.max(1, Math.ceil(props.rows.length / size)))
const currentPage = computed(() => Math.min(page.value, pages.value - 1))
const visible = computed(() => props.rows.map((label, i) => ({label, i})).slice(currentPage.value*size, (currentPage.value+1)*size))
const columnPage = ref(0), columnSize = 64
const columnPages = computed(() => Math.max(1, Math.ceil(props.columns.length / columnSize)))
const currentColumnPage = computed(() => Math.min(columnPage.value, columnPages.value - 1))
const visibleColumns = computed(() => props.columns.map((label, i) => ({ label, i })).slice(currentColumnPage.value*columnSize, (currentColumnPage.value+1)*columnSize))
const cell = computed(() => Math.max(12, Math.min(45, 620/Math.max(1, visibleColumns.value.length))))
const width = computed(() => Math.max(600, 150+visibleColumns.value.length*cell.value))
const height = computed(() => 145+visible.value.length*23)
function color(v: unknown) {
  if (!finite(v)) return '#e5e7eb'
  const t = (v-limits.value[0]!)/(limits.value[1]!-limits.value[0]!)
  if (props.diverging) return t < .5 ? `hsl(18 65% ${40+100*t}%)` : `hsl(208 60% ${140-100*t}%)`
  return `hsl(159 45% ${96-63*t}%)`
}
const fmt = (v: unknown) => finite(v) ? Number(v.toPrecision(4)).toString() : t('Missing')
</script>
<template>
  <figure v-if="numbers.length" class="heatmap eeg-figure">
    <div class="heading"><strong>{{ title }}</strong><button @click="exportSvg(svg, title + '-page-' + (currentPage+1) + '-columns-' + (currentColumnPage+1))">{{ t('Download this page as SVG') }}</button><button @click="downloadData(title + '.json', { rows, columns, values, unit, caption, provenance })">{{ t('Download all data as JSON') }}</button></div>
    <p v-if="pages > 1"><button :disabled="currentPage === 0" @click="page = currentPage-1">{{ t('Previous page') }}</button>{{ t('{0} / {1} · {2} rows in total', { 0: currentPage+1, 1: pages, 2: rows.length }) }}<button :disabled="currentPage+1 === pages" @click="page = currentPage+1">{{ t('Next page') }}</button></p>
    <p v-if="columnPages > 1"><button :disabled="currentColumnPage === 0" @click="columnPage = currentColumnPage-1">{{ t('Previous columns') }}</button>{{ t('{0} / {1} · {2} columns in total', { 0: currentColumnPage+1, 1: columnPages, 2: columns.length }) }}<button :disabled="currentColumnPage+1 === columnPages" @click="columnPage = currentColumnPage+1">{{ t('Next columns') }}</button></p>
    <div class="scroll"><svg ref="svg" :viewBox="`0 0 ${width} ${height}`" :width="width" :height="height" role="img" :aria-label="title" style="font:11px system-ui,sans-serif;background:white;stroke:none">
      <title>{{ title }}</title><desc>{{ caption }}</desc>
      <text x="12" y="20" fill="#344c40">{{ t('{0} · Shared color limits: {1} to {2} · Gray: missing', { 0: unit, 1: fmt(limits[0]), 2: fmt(limits[1]) }) }}</text>
      <g v-for="(row, r) in visible" :key="row.i"><text x="116" :y="51+r*23" text-anchor="end" fill="#344c40">{{ row.label.length > 19 ? row.label.slice(0,18)+'…' : row.label }}<title>{{ row.label }}</title></text><rect v-for="(col, c) in visibleColumns" :key="c" :x="125+c*cell" :y="36+r*23" :width="cell-1" height="22" :fill="color(values[row.i]?.[col.i])"><title>{{ row.label }} · {{ col.label }} · {{ fmt(values[row.i]?.[col.i]) }} {{ unit }}</title></rect></g>
      <template v-for="(col, c) in visibleColumns" :key="c"><text v-if="visibleColumns.length < 40 || c % Math.ceil(visibleColumns.length/20) === 0" :transform="`translate(${130+c*cell},${48+visible.length*23}) rotate(55)`" fill="#344c40">{{ col.label }}</text></template>
    </svg></div>
    <figcaption>{{ t('{0} Valid cells: {1} / {2}. Missing values are not replaced with zero. Hover for labels and values.', { 0: caption, 1: numbers.length, 2: values.reduce((n, row) => n + row.length, 0) }) }}</figcaption>
  </figure>
  <p v-else class="empty">{{ t('{0}: no finite values to plot.', { 0: title }) }}</p>
</template>
<style scoped>
.scroll { overflow: auto; margin-top: 12px; }
.empty, p { color: #586f75; font-size: 12px; line-height: 1.8; }
</style>
