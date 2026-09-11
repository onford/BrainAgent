<script setup lang="ts">
import { computed, ref } from 'vue'
import { finite, exportSvg, downloadData, type Series } from '../utils/assessmentPlots'
const props = defineProps<{ title: string; series: Series[]; xLabel: string; yLabel: string; caption: string; yDomain?: [number, number]; reference?: number; provenance?: unknown; equalAspect?: boolean }>()
const svg = ref<SVGSVGElement | null>(null)
const colors = ['#00796b', '#b55d15', '#5168b2', '#9a437b', '#397c99', '#687342']
const values = computed(() => props.series.flatMap(s => s.points).filter(p => finite(p.x) && finite(p.y)))
const bounds = computed(() => {
  const xs = values.value.map(p => p.x), ys = values.value.map(p => p.y as number)
  let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = props.yDomain?.[0] ?? Math.min(...ys), y1 = props.yDomain?.[1] ?? Math.max(...ys)
  if (finite(props.reference)) { y0 = Math.min(y0, props.reference); y1 = Math.max(y1, props.reference) }
  if (x0 === x1) { x0 -= .5; x1 += .5 }
  if (y0 === y1) { const d = Math.max(Math.abs(y0) * .1, .1); y0 -= d; y1 += d }
  if (!props.yDomain) { const d = (y1-y0)*.08; y0 -= d; y1 += d }
  if (props.equalAspect) {
    const scale = Math.max((x1-x0)/650, (y1-y0)/218)
    const xc = (x0+x1)/2, yc = (y0+y1)/2
    x0 = xc-scale*325; x1 = xc+scale*325; y0 = yc-scale*109; y1 = yc+scale*109
  }
  return { x0, x1, y0, y1 }
})
const px = (x: number) => 78 + (x-bounds.value.x0)/(bounds.value.x1-bounds.value.x0)*650
const py = (y: number) => 280 - (y-bounds.value.y0)/(bounds.value.y1-bounds.value.y0)*218
const fmt = (v: number) => Number.isFinite(v) ? Number(v.toPrecision(4)).toLocaleString('zh-CN') : '—'
function path(s: Series) {
  let previous = false
  return s.points.map(p => {
    if (!finite(p.x) || !finite(p.y)) { previous = false; return '' }
    const text = `${previous ? 'L' : 'M'}${px(p.x)},${py(p.y)}`; previous = true; return text
  }).join(' ')
}
</script>
<template>
  <figure v-if="values.length" class="plot">
    <div class="heading"><strong>{{ title }}</strong><div><button @click="exportSvg(svg, title)">导出 SVG</button><button @click="downloadData(title + '.json', { title, xLabel, yLabel, caption, series, provenance })">图数据 JSON</button></div></div>
    <div class="plot-scroll"><svg ref="svg" viewBox="0 0 780 355" role="img" :aria-label="`${title}；${xLabel}；${yLabel}`" style="background:white;font:12px system-ui,sans-serif;color:#29433b" width="780" height="355">
      <title>{{ title }}</title><desc>{{ caption }}</desc>
      <text x="78" y="22" fill="#29433b" font-size="13">{{ yLabel }}</text>
      <g v-for="i in 5" :key="i"><line x1="78" x2="728" :y1="py(bounds.y0+(bounds.y1-bounds.y0)*(i-1)/4)" :y2="py(bounds.y0+(bounds.y1-bounds.y0)*(i-1)/4)" stroke="#e3ebe7" /><text x="68" :y="py(bounds.y0+(bounds.y1-bounds.y0)*(i-1)/4)+4" text-anchor="end" fill="#52675e">{{ fmt(bounds.y0+(bounds.y1-bounds.y0)*(i-1)/4) }}</text><text :x="px(bounds.x0+(bounds.x1-bounds.x0)*(i-1)/4)" y="302" text-anchor="middle" fill="#52675e">{{ fmt(bounds.x0+(bounds.x1-bounds.x0)*(i-1)/4) }}</text></g>
      <line v-if="finite(reference)" x1="78" x2="728" :y1="py(reference)" :y2="py(reference)" stroke="#89978f" stroke-dasharray="5 4" />
      <g v-for="(s, i) in series" :key="s.name"><path v-if="s.connect !== false" :d="path(s)" fill="none" :stroke="colors[i % colors.length]" stroke-width="1.8" :stroke-dasharray="i % 3 === 1 ? '6 3' : i % 3 === 2 ? '2 3' : undefined" /><template v-for="(p, j) in s.points" :key="j"><circle v-if="finite(p.x) && finite(p.y)" :cx="px(p.x)" :cy="py(p.y)" :r="s.connect === false ? 3.5 : 1.7" :fill="colors[i % colors.length]"><title>{{ s.name }} · {{ p.label || fmt(p.x) }} · {{ fmt(p.y) }} {{ yLabel }}</title></circle></template></g>
      <text x="400" y="340" text-anchor="middle" fill="#29433b">{{ xLabel }}</text>
    </svg></div>
    <div class="legend"><span v-for="(s, i) in series" :key="s.name" :style="{ color: colors[i % colors.length] }">{{ ['━', '┄', '┈'][i % 3] }} {{ s.name }} · {{ s.points.filter(p => finite(p.x) && finite(p.y)).length }}/{{ s.points.length }} 点</span></div>
    <figcaption>{{ caption }}</figcaption>
    <details><summary>精确数值与点标签</summary><div class="table-scroll"><table><thead><tr><th>系列</th><th>对象</th><th>{{ xLabel }}</th><th>{{ yLabel }}</th></tr></thead><tbody><template v-for="s in series" :key="s.name"><tr v-for="(p, i) in s.points" :key="i"><td>{{ s.name }}</td><td>{{ p.label || '—' }}</td><td>{{ fmt(p.x) }}</td><td>{{ finite(p.y) ? fmt(p.y) : '缺失' }}</td></tr></template></tbody></table></div></details>
  </figure>
  <p v-else class="unavailable">{{ title }}：没有可绘制的有限值；请查看状态和缺失原因。</p>
</template>
<style scoped>
.plot{margin:18px 0;padding:16px;border:1px solid #dce7e0;border-radius:12px;background:#fff}.heading{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}.heading strong{font-size:14px}.heading button{font:inherit;font-size:12px;background:#f7faf8;color:#35624b;border:1px solid #d9e5de;border-radius:6px;padding:5px 9px;cursor:pointer;margin-left:7px}.plot-scroll{overflow:auto}.plot svg{display:block;width:100%;min-width:580px;height:auto}.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:12px}figcaption,.unavailable{font-size:12px;line-height:1.8;color:#64756b;margin-top:10px}summary{font-size:12px;cursor:pointer;color:#37694f;margin-top:10px}.table-scroll{max-height:220px;overflow:auto}table{font-size:12px;border-collapse:collapse;width:100%}td,th{padding:6px;text-align:left;border-bottom:1px solid #edf0ed}
</style>
