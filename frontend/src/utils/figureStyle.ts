import palettes from './figurePalettes.json'
import { finite, type Series } from './assessmentPlots'

export const FIGURE_VERSION = 'assessment-figure-2'
export const FONT = 'Arial, "Microsoft YaHei", sans-serif'
export const INK = '#243746'
export const MUTED = '#52616b'
export const MISSING = '#d5d9df'
export type Domain = [number, number]
export interface Tick { value: number; label: string }
export const validDomain = (v?: Domain): v is Domain => !!v && v.every(finite) && v[1] > v[0]

// Stable 1/2/2.5/5/10 tick intervals. Neither viewport nor clock participates.
export function tickStep(span: number, count = 5): number {
  if (!finite(span) || span <= 0) return 1
  const raw = span / Math.max(1, count - 1), power = 10 ** Math.floor(Math.log10(raw))
  return ([1, 2, 2.5, 5, 10].find(n => n * power >= raw - raw * 1e-12) ?? 10) * power
}
export function extent(values: Iterable<unknown>, fallback: Domain = [0, 1]): Domain {
  let lo = Infinity, hi = -Infinity
  for (const v of values) if (finite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v) }
  return lo === Infinity ? [...fallback] : [lo, hi]
}
export function axisDomain(values: Iterable<unknown>, requested?: Domain, pad = 0): Domain {
  if (validDomain(requested)) return [...requested]
  let [lo, hi] = extent(values)
  if (lo === hi) { const d = Math.abs(lo) > 0 ? Math.abs(lo) * .1 : .5; lo -= d; hi += d }
  const margin = (hi - lo) * pad
  lo -= margin; hi += margin
  const step = tickStep(hi - lo)
  return [Number((Math.floor(lo / step + 1e-10) * step).toPrecision(12)), Number((Math.ceil(hi / step - 1e-10) * step).toPrecision(12))]
}
export function formatTick(value: number): string {
  if (!finite(value)) return '—'
  if (Math.abs(value) < 1e-14) return '0'
  return Math.abs(value) >= 10000 || Math.abs(value) < .001
    ? value.toExponential(2).replace(/\.0+(?=e)/, '').replace('e+', 'e')
    : String(Number(value.toPrecision(5)))
}
export function axisTicks(domain: Domain): Tick[] {
  const step = tickStep(domain[1] - domain[0]), ticks: Tick[] = []
  const first = Math.ceil(domain[0] / step - 1e-10)
  for (let i = 0; i < 12; i++) {
    const value = Number(((first + i) * step).toPrecision(12))
    if (value > domain[1] + step * 1e-9) break
    ticks.push({ value, label: formatTick(value) })
  }
  return ticks
}
export function categoricalTicks(series: Series[]): Tick[] | undefined {
  if (!series.length || series.some(s => s.connect !== false)) return undefined
  const ticks = new Map<number, string>()
  for (const s of series) for (const p of s.points) {
    if (!finite(p.x) || !p.label) return undefined
    if (ticks.has(p.x) && ticks.get(p.x) !== p.label) return undefined
    ticks.set(p.x, p.label)
  }
  if (!ticks.size || ticks.size > 12) return undefined
  return [...ticks].sort(([a], [b]) => a - b).map(([value, label]) => ({ value, label }))
}

// Okabe–Ito hues plus shape/dash redundancy for grayscale. IDs, not array order.
const colors = ['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#E69F00', '#56B4E9', '#333333']
const slots: Record<string, number> = { PSD: 0, Q10: 1, Q50: 0, Q90: 2, eegnet: 0, csp_lda: 1, subjects: 0, C3: 0, Cz: 1, C4: 2, 'window-min': 0, 'window-max': 1 }
export function seriesStyle(id: string) {
  let hash = 2166136261
  for (const c of id) hash = Math.imul(hash ^ c.charCodeAt(0), 16777619)
  const slot = slots[id] ?? ((hash >>> 0) % 21)
  return { color: colors[slot % colors.length]!, dash: ['', '6 3', '2 3'][slot % 3]!, marker: ['circle', 'square', 'triangle', 'diamond'][slot % 4]! }
}
export function colorDomain(values: Iterable<unknown>, diverging = false, requested?: Domain): Domain {
  if (validDomain(requested)) return [...requested]
  const [lo, hi] = extent(values)
  if (diverging) { const max = Math.max(Math.abs(lo), Math.abs(hi)); return max ? [-max, max] : [-1, 1] }
  if (lo === hi) { const pad = Math.abs(lo) * .05 || .5; return [lo - pad, hi + pad] }
  return [lo, hi]
}
export function heatColor(value: unknown, limits: Domain, diverging = false): string {
  if (!finite(value)) return MISSING
  const fraction = Math.max(0, Math.min(1, (value - limits[0]) / (limits[1] - limits[0])))
  return palettes[diverging ? 'RdBu_r' : 'viridis'][Math.round(fraction * 255)]!
}
export function shortLabel(label: string, max = 22): string { return label.length > max ? label.slice(0, max - 1) + '…' : label }
