<script setup lang="ts">
import { t } from '../i18n'
import { computed, ref } from 'vue'
import FigureComparisonSelect from './FigureComparisonSelect.vue'
import FigureExport from './FigureExport.vue'
import { finite, exportSvg, downloadData, type Series } from '../utils/assessmentPlots'
import { FIGURE_VERSION, FONT, INK, MUTED, axisDomain, axisTicks, categoricalTicks, formatTick, seriesStyle, shortLabel, type Domain, type Tick } from '../utils/figureStyle'
import '../styles/assessment-figures.css'
const props = defineProps<{ title: string; series: Series[]; xLabel: string; yLabel: string; caption: string; xDomain?: Domain; yDomain?: Domain; xTicks?: Tick[]; categorical?: boolean; reference?: number; provenance?: unknown; equalAspect?: boolean; comparisonKey?: string; comparisonLabel?: string }>()
const svg = ref<SVGSVGElement | null>(null)
const plot = computed(() => ({ left: 90, top: 72, width: 642, height: props.equalAspect ? 420 : 240 }))
const values = computed(() => props.series.flatMap(s => s.points).filter(p => finite(p.x) && finite(p.y)))
const categories = computed(() => props.categorical ? categoricalTicks(props.series) : undefined)
const bounds = computed(() => {
  // Missing endpoints retain their x positions. No viewport or clock input.
  const points = props.series.flatMap(s => s.points)
  const labels = categories.value
  const categoricalDomain: Domain | undefined = labels?.length ? [labels[0]!.value - .5, labels[labels.length - 1]!.value + .5] : undefined
  const x = axisDomain(points.map(p => p.x), props.xDomain ?? categoricalDomain)
  const y = axisDomain([...values.value.map(p => p.y), props.reference], props.yDomain, .04)
  if (props.equalAspect) {
    const scale = Math.max((x[1] - x[0]) / plot.value.width, (y[1] - y[0]) / plot.value.height)
    const xc = (x[0] + x[1]) / 2, yc = (y[0] + y[1]) / 2
    return { x: [xc - scale * plot.value.width / 2, xc + scale * plot.value.width / 2] as Domain, y: [yc - scale * plot.value.height / 2, yc + scale * plot.value.height / 2] as Domain }
  }
  return { x, y }
})
const xTicks = computed(() => props.xTicks ?? categories.value ?? axisTicks(bounds.value.x))
const yTicks = computed(() => axisTicks(bounds.value.y))
const tickRotation = computed(() => props.categorical && (props.xTicks ?? categories.value ?? []).length > 6 ? 45 : 0)
const extraBottom = computed(() => tickRotation.value ? 58 : 0)
const bottom = computed(() => plot.value.top + plot.value.height)
const height = computed(() => bottom.value + 80 + extraBottom.value + Math.ceil(props.series.length / 2) * 24)
const styles = computed(() => props.series.map(s => seriesStyle(s.id ?? s.name)))
const px = (x: number) => plot.value.left + (x - bounds.value.x[0]) / (bounds.value.x[1] - bounds.value.x[0]) * plot.value.width
const py = (y: number) => plot.value.top + plot.value.height - (y - bounds.value.y[0]) / (bounds.value.y[1] - bounds.value.y[0]) * plot.value.height
const spec = computed(() => ({ schema_version: FIGURE_VERSION, kind: 'series', title: props.title, xLabel: props.xLabel, yLabel: props.yLabel, caption: props.caption, series: props.series, provenance: props.provenance, rendering: { width_mm: 183, viewBox: [0, 0, 780, height.value], font: FONT, xDomain: bounds.value.x, yDomain: bounds.value.y, xTicks: xTicks.value, xTickRotation: tickRotation.value, yTicks: yTicks.value, styles: styles.value, reference: props.reference, equalAspect: !!props.equalAspect, missing: 'gap; never zero', smoothing: 'none' } }))
function path(s: Series) {
  let previous = false
  return s.points.map(p => {
    if (!finite(p.x) || !finite(p.y)) { previous = false; return '' }
    const text = `${previous ? 'L' : 'M'}${px(p.x)},${py(p.y)}`; previous = true; return text
  }).join(' ')
}
function marker(shape: string, x: number, y: number) {
  if (shape === 'square') return `M${x-3.5},${y-3.5}h7v7h-7Z`
  if (shape === 'triangle') return `M${x},${y-4.5}l4.2,7.5h-8.4Z`
  return `M${x},${y-4.5}l4.5,4.5l-4.5,4.5l-4.5,-4.5Z`
}
</script>
<template>
  <figure v-if="values.length" class="plot eeg-figure">
    <div class="heading"><strong>{{ title }}</strong><div><FigureComparisonSelect :figure="{ ...props, kind: 'series', xDomain: bounds.x, yDomain: bounds.y }" /><FigureExport><button @click="exportSvg(svg, title)">{{ t('Download SVG') }}</button><button @click="downloadData(title + '.json', spec)">{{ t('Download JSON') }}</button></FigureExport></div></div>
    <div class="plot-scroll"><svg ref="svg" :viewBox="`0 0 780 ${height}`" role="img" :aria-label="`${title}；${xLabel}；${yLabel}`" :style="{ background: 'white', fontFamily: FONT, fontSize: '12px', color: INK, stroke: 'none' }" width="780" :height="height">
      <title>{{ title }}</title><desc>{{ caption }}</desc><metadata>{{ JSON.stringify(spec) }}</metadata>
      <rect width="780" :height="height" fill="#ffffff" />
      <text x="90" y="26" :fill="INK" font-size="16" font-weight="600">{{ shortLabel(title, 65) }}</text>
      <text x="90" y="51" :fill="MUTED" font-size="12">{{ yLabel }}</text>
      <g v-for="tick in yTicks" :key="tick.value"><line :x1="plot.left" :x2="plot.left+plot.width" :y1="py(tick.value)" :y2="py(tick.value)" stroke="#e6eaee" stroke-width=".8" /><text x="78" :y="py(tick.value)+4" text-anchor="end" :fill="MUTED">{{ tick.label }}</text></g>
      <line :x1="plot.left" :x2="plot.left" :y1="plot.top" :y2="plot.top+plot.height" stroke="#596873" stroke-width="1" />
      <line :x1="plot.left" :x2="plot.left+plot.width" :y1="plot.top+plot.height" :y2="plot.top+plot.height" stroke="#596873" stroke-width="1" />
      <g v-for="tick in xTicks" :key="tick.value"><line :x1="px(tick.value)" :x2="px(tick.value)" :y1="bottom" :y2="bottom+5" stroke="#596873" /><text :transform="`translate(${px(tick.value)},${bottom+23}) rotate(${tickRotation})`" :text-anchor="tickRotation ? 'start' : 'middle'" :fill="MUTED">{{ shortLabel(tick.label, 14) }}<title>{{ tick.label }}</title></text></g>
      <line v-if="finite(reference)" :x1="plot.left" :x2="plot.left+plot.width" :y1="py(reference)" :y2="py(reference)" stroke="#68727c" stroke-width="1" stroke-dasharray="5 4" />
      <svg :x="plot.left-5" :y="plot.top-5" :width="plot.width+10" :height="plot.height+10" :viewBox="`${plot.left-5} ${plot.top-5} ${plot.width+10} ${plot.height+10}`" overflow="hidden">
        <g v-for="(s, i) in series" :key="s.id ?? s.name" :data-series="s.id ?? s.name">
          <path v-if="s.connect !== false" class="data-line" :d="path(s)" fill="none" :stroke="styles[i]!.color" stroke-width="1.9" :stroke-dasharray="styles[i]!.dash || undefined" stroke-linejoin="round" />
          <template v-if="s.connect === false || s.points.length <= 24">
            <template v-for="(p, j) in s.points" :key="j"><template v-if="finite(p.x) && finite(p.y)">
              <circle v-if="styles[i]!.marker === 'circle'" class="data-marker" :cx="px(p.x)" :cy="py(p.y)" r="3.5" :fill="styles[i]!.color" stroke="#ffffff" stroke-width=".7"><title>{{ s.name }} · {{ p.label || formatTick(p.x) }} · {{ formatTick(p.y) }} {{ yLabel }}</title></circle>
              <path v-else class="data-marker" :d="marker(styles[i]!.marker, px(p.x), py(p.y))" :fill="styles[i]!.color" stroke="#ffffff" stroke-width=".7"><title>{{ s.name }} · {{ p.label || formatTick(p.x) }} · {{ formatTick(p.y) }} {{ yLabel }}</title></path>
              <text v-if="p.annotation" :x="px(p.x)+6" :y="py(p.y)-6" :fill="INK" font-size="12">{{ p.annotation }}</text>
            </template></template>
          </template>
        </g>
      </svg>
      <text x="411" :y="bottom+54+extraBottom" text-anchor="middle" :fill="INK" font-size="13">{{ shortLabel(xLabel, 90) }}<title>{{ xLabel }}</title></text>
      <g v-for="(s, i) in series" :key="s.id ?? s.name" class="series-legend" :transform="`translate(${90+(i%2)*326},${bottom+81+extraBottom+Math.floor(i/2)*24})`">
        <line v-if="s.connect !== false" x1="0" x2="26" y1="0" y2="0" :stroke="styles[i]!.color" stroke-width="1.9" :stroke-dasharray="styles[i]!.dash || undefined" />
        <circle v-if="styles[i]!.marker === 'circle'" cx="13" cy="0" r="3" :fill="styles[i]!.color" /><path v-else :d="marker(styles[i]!.marker, 13, 0)" :fill="styles[i]!.color" />
        <text x="35" y="4" :fill="INK" font-size="11">{{ shortLabel(s.name, 32) }} · {{ s.points.filter(p => finite(p.x) && finite(p.y)).length }}/{{ s.points.length }}<title>{{ s.name }}</title></text>
      </g>
    </svg></div>
    <figcaption>{{ caption }}</figcaption>
    <details><summary>{{ t('Point labels and values') }}</summary><div class="table-scroll"><table><thead><tr><th>{{ t('Series') }}</th><th>{{ t('Item') }}</th><th>{{ xLabel }}</th><th>{{ yLabel }}</th></tr></thead><tbody><template v-for="s in series" :key="s.id ?? s.name"><tr v-for="(p, i) in s.points" :key="i"><td>{{ s.name }}</td><td>{{ p.label || '—' }}</td><td>{{ finite(p.x) ? String(p.x) : t('Missing') }}</td><td>{{ finite(p.y) ? String(p.y) : t('Missing') }}</td></tr></template></tbody></table></div></details>
  </figure>
  <p v-else class="unavailable">{{ t('{0}: no finite values to plot. See the status and reasons for missing data.', { 0: title }) }}</p>
</template>
<style scoped>
.plot-scroll { overflow-x: auto; }
.plot > .plot-scroll > svg { display: block; width: 100%; min-width: 580px; height: auto; }
.unavailable { padding: 18px; background: #f5f8f9; color: #586f75; font-size: 13px; border-radius: 8px; }
</style>
