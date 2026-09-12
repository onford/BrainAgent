<script setup lang="ts">
import { t } from '../i18n'
import { computed, ref, watch } from 'vue'
import FigureComparisonSelect from './FigureComparisonSelect.vue'
import FigureExport from './FigureExport.vue'
import { finite, exportSvg, downloadData } from '../utils/assessmentPlots'
import { FIGURE_VERSION, FONT, INK, MUTED, MISSING, colorDomain, heatColor, formatTick, shortLabel, type Domain } from '../utils/figureStyle'
import '../styles/assessment-figures.css'
const props = defineProps<{ title: string; rows: string[]; columns: string[]; values: (number | null)[][]; unit: string; caption: string; diverging?: boolean; colorLimits?: Domain; reverseRows?: boolean; fullMatrix?: boolean; xLabel?: string; yLabel?: string; provenance?: unknown; comparisonKey?: string; comparisonLabel?: string }>()
const svg = ref<SVGSVGElement | null>(null)
const numbers = computed(() => props.values.flat().filter(finite))
const limits = computed(() => colorDomain(numbers.value, props.diverging, props.colorLimits))
const page = ref(0), columnPage = ref(0)
const size = computed(() => props.fullMatrix ? Math.max(1, props.rows.length) : 24)
const columnSize = computed(() => props.fullMatrix ? Math.max(1, props.columns.length) : 64)
watch(() => [props.rows, props.columns], () => { page.value = 0; columnPage.value = 0 })
const pages = computed(() => Math.max(1, Math.ceil(props.rows.length / size.value)))
const currentPage = computed(() => Math.min(page.value, pages.value - 1))
const ordered = computed(() => { const rows = props.rows.map((label, i) => ({label, i})); return props.reverseRows ? rows.reverse() : rows })
const visible = computed(() => ordered.value.slice(currentPage.value * size.value, (currentPage.value + 1) * size.value))
const columnPages = computed(() => Math.max(1, Math.ceil(props.columns.length / columnSize.value)))
const currentColumnPage = computed(() => Math.min(columnPage.value, columnPages.value - 1))
const visibleColumns = computed(() => props.columns.map((label, i) => ({label, i})).slice(currentColumnPage.value * columnSize.value, (currentColumnPage.value + 1) * columnSize.value))
// Page geometry depends on the full matrix, not the number of cells on this page.
const cell = computed(() => 642 / Math.max(1, Math.min(columnSize.value, props.columns.length)))
const rowSlots = computed(() => Math.min(size.value, props.rows.length))
const width = 900, top = 104, left = 178
const rowHeight = computed(() => props.fullMatrix ? Math.min(20, 480 / Math.max(1, rowSlots.value)) : 20)
const height = computed(() => 228 + rowSlots.value * rowHeight.value)
const color = (v: unknown) => heatColor(v, limits.value, props.diverging)
const fmt = (v: unknown) => finite(v) ? formatTick(v) : t('Missing')
const spec = computed(() => ({ schema_version: FIGURE_VERSION, kind: 'heatmap', title: props.title, rows: props.rows, columns: props.columns, values: props.values, unit: props.unit, caption: props.caption, xLabel: props.xLabel, yLabel: props.yLabel, provenance: props.provenance, rendering: { width_mm: 183, viewBox: [0, 0, width, height.value], font: FONT, colorLimits: limits.value, colormap: props.diverging ? 'RdBu_r' : 'viridis', missing_color: MISSING, rowIndices: visible.value.map(r => r.i), columnIndices: visibleColumns.value.map(c => c.i), reverse_rows: !!props.reverseRows, row_slots: rowSlots.value, column_slots: Math.min(columnSize.value, props.columns.length), full_matrix: !!props.fullMatrix, page: currentPage.value + 1, column_page: currentColumnPage.value + 1, limits_scope: props.colorLimits ? 'explicit shared scope' : 'full matrix, all pages', interpolation: 'none' } }))

const columnTicks = computed(() => new Set(Array.from({ length: Math.min(11, visibleColumns.value.length) }, (_, i) => Math.round(i * (visibleColumns.value.length - 1) / Math.max(1, Math.min(11, visibleColumns.value.length) - 1)))))
</script>
<template>
  <figure v-if="numbers.length" class="heatmap eeg-figure">
    <div class="heading"><strong>{{ title }}</strong><div><FigureComparisonSelect :figure="{ ...props, kind: 'heatmap', colorLimits: limits }" /><FigureExport><button @click="exportSvg(svg, title + '-page-' + (currentPage+1) + '-columns-' + (currentColumnPage+1))">{{ t('Download this page as SVG') }}</button><button @click="downloadData(title + '.json', spec)">{{ t('Download all data as JSON') }}</button></FigureExport></div></div>
    <div class="pagination">
      <p v-if="pages > 1"><button :disabled="currentPage === 0" @click="page = currentPage-1">{{ t('Previous page') }}</button><span>{{ t('{0} / {1} · {2} rows in total', { 0: currentPage+1, 1: pages, 2: rows.length }) }}</span><button :disabled="currentPage+1 === pages" @click="page = currentPage+1">{{ t('Next page') }}</button></p>
      <p v-if="columnPages > 1"><button :disabled="currentColumnPage === 0" @click="columnPage = currentColumnPage-1">{{ t('Previous columns') }}</button><span>{{ t('{0} / {1} · {2} columns in total', { 0: currentColumnPage+1, 1: columnPages, 2: columns.length }) }}</span><button :disabled="currentColumnPage+1 === columnPages" @click="columnPage = currentColumnPage+1">{{ t('Next columns') }}</button></p>
    </div>
    <div class="scroll"><svg ref="svg" :viewBox="`0 0 ${width} ${height}`" :width="width" :height="height" role="img" :aria-label="title" :style="{ fontFamily: FONT, fontSize: '12px', background: 'white', stroke: 'none' }">
      <title>{{ title }}</title><desc>{{ caption }}</desc><metadata>{{ JSON.stringify(spec) }}</metadata>
      <rect :width="width" :height="height" fill="#ffffff" />
      <text :x="left" y="27" :fill="INK" font-size="16" font-weight="600">{{ shortLabel(title, 60) }}</text>
      <text :x="left" y="54" :fill="MUTED" font-size="11">{{ unit }} · {{ props.diverging ? 'RdBu_r' : 'viridis' }}</text>
      <g class="colorbar"><rect v-for="i in 128" :key="i" :x="560+(i-1)*2" y="48" width="2.1" height="10" :fill="color(limits[0]+(limits[1]-limits[0])*(i-1)/127)" /><text x="560" y="75" :fill="MUTED" text-anchor="start" font-size="11">{{ fmt(limits[0]) }}</text><text x="688" y="75" :fill="MUTED" text-anchor="middle" font-size="11">{{ fmt((limits[0]+limits[1])/2) }}</text><text x="816" y="75" :fill="MUTED" text-anchor="end" font-size="11">{{ fmt(limits[1]) }}</text></g>
      <rect :x="left" y="65" width="10" height="10" :fill="MISSING" /><text :x="left+16" y="74" :fill="MUTED" font-size="11">{{ t('Missing') }}</text>
      <text v-if="yLabel" x="16" y="96" :fill="INK" font-size="12">{{ yLabel }}</text>
      <rect :x="left" :y="top" width="642" :height="rowSlots*rowHeight" fill="#f8fafb" stroke="#cdd5dd" stroke-width=".6" />
      <g v-for="(row, r) in visible" :key="row.i" class="heatmap-row">
        <text v-if="r % Math.max(1,Math.ceil(visible.length/24)) === 0" :x="left-12" :y="top+rowHeight*.5+4+r*rowHeight" text-anchor="end" :fill="INK" font-size="11">{{ shortLabel(row.label, 24) }}<title>{{ row.label }}</title></text>
        <rect v-for="(col, c) in visibleColumns" :key="col.i" class="heatmap-cell" :data-row="row.i" :data-column="col.i" :x="left+c*cell" :y="top+r*rowHeight" :width="cell" :height="rowHeight" :fill="color(values[row.i]?.[col.i])"><title>{{ row.label }} · {{ col.label }} · {{ finite(values[row.i]?.[col.i]) ? values[row.i]?.[col.i] : t('Missing') }} {{ unit }}</title></rect>
      </g>
      <template v-for="(col, c) in visibleColumns" :key="col.i"><text v-if="columnTicks.has(c)" :transform="`translate(${left+(c+.5)*cell},${top+rowSlots*rowHeight+14}) rotate(45)`" :fill="INK" font-size="11">{{ shortLabel(col.label, 16) }}<title>{{ col.label }}</title></text></template>
      <text v-if="xLabel" x="499" :y="height-27" :fill="INK" text-anchor="middle" font-size="13">{{ xLabel }}</text>
      <text :x="left" :y="height-8" :fill="MUTED" font-size="10">{{ t('{0} · Shared color limits: {1} to {2} · Gray: missing', { 0: unit, 1: fmt(limits[0]), 2: fmt(limits[1]) }) }}</text>
    </svg></div>
    <figcaption>{{ t('{0} Valid cells: {1} / {2}. Missing values are not replaced with zero. Hover for labels and values.', { 0: caption, 1: numbers.length, 2: rows.length * columns.length }) }}</figcaption>
  </figure>
  <p v-else class="empty">{{ t('{0}: no finite values to plot.', { 0: title }) }}</p>
</template>
<style scoped>
.scroll { overflow: auto; margin-top: 12px; }
.scroll > svg { display: block; width: 100%; min-width: 720px; height: auto; }
.pagination { display: flex; flex-wrap: wrap; gap: 6px 20px; }
.pagination p { display: flex; gap: 10px; align-items: center; margin: 4px 0; }
.empty, p { color: #52616b; font-size: 12px; line-height: 1.8; }
</style>
