<script setup lang="ts">
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
const fmt = (v: unknown) => finite(v) ? Number(v.toPrecision(4)).toString() : '缺失'
</script>
<template>
  <figure v-if="numbers.length" class="heatmap eeg-figure">
    <div class="heading"><strong>{{ title }}</strong><button @click="exportSvg(svg, title + '-page-' + (currentPage+1) + '-columns-' + (currentColumnPage+1))">下载本页 SVG</button><button @click="downloadData(title + '.json', { rows, columns, values, unit, caption, provenance })">下载全部数据 JSON</button></div>
    <p v-if="pages > 1"><button :disabled="currentPage === 0" @click="page = currentPage-1">上一页</button> {{ currentPage+1 }} / {{ pages }} · 全部 {{ rows.length }} 行 <button :disabled="currentPage+1 === pages" @click="page = currentPage+1">下一页</button></p>
    <p v-if="columnPages > 1"><button :disabled="currentColumnPage === 0" @click="columnPage = currentColumnPage-1">上一组列</button> {{ currentColumnPage+1 }} / {{ columnPages }} · 全部 {{ columns.length }} 列 <button :disabled="currentColumnPage+1 === columnPages" @click="columnPage = currentColumnPage+1">下一组列</button></p>
    <div class="scroll"><svg ref="svg" :viewBox="`0 0 ${width} ${height}`" :width="width" :height="height" role="img" :aria-label="title" style="font:11px system-ui,sans-serif;background:white;stroke:none">
      <title>{{ title }}</title><desc>{{ caption }}</desc>
      <text x="12" y="20" fill="#344c40">{{ unit }} · 全部页共同色限 {{ fmt(limits[0]) }} ～ {{ fmt(limits[1]) }} · 灰色 = 缺失</text>
      <g v-for="(row, r) in visible" :key="row.i"><text x="116" :y="51+r*23" text-anchor="end" fill="#344c40">{{ row.label.length > 19 ? row.label.slice(0,18)+'…' : row.label }}<title>{{ row.label }}</title></text><rect v-for="(col, c) in visibleColumns" :key="c" :x="125+c*cell" :y="36+r*23" :width="cell-1" height="22" :fill="color(values[row.i]?.[col.i])"><title>{{ row.label }} · {{ col.label }} · {{ fmt(values[row.i]?.[col.i]) }} {{ unit }}</title></rect></g>
      <template v-for="(col, c) in visibleColumns" :key="c"><text v-if="visibleColumns.length < 40 || c % Math.ceil(visibleColumns.length/20) === 0" :transform="`translate(${130+c*cell},${48+visible.length*23}) rotate(55)`" fill="#344c40">{{ col.label }}</text></template>
    </svg></div>
    <figcaption>{{ caption }} 有效单元格 {{ numbers.length }} / {{ values.reduce((n, row) => n + row.length, 0) }}；缺失不填零。鼠标悬停可查看完整标签及数值。</figcaption>
  </figure>
  <p v-else class="empty">{{ title }}：没有可绘制的有限值。</p>
</template>
<style scoped>
.scroll { overflow: auto; margin-top: 12px; }
.empty, p { color: #586f75; font-size: 12px; line-height: 1.8; }
</style>
