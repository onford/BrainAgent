import { computed, inject, shallowRef, type InjectionKey, type Ref } from 'vue'
import type { Series } from './assessmentPlots'
import type { Domain, Tick } from './figureStyle'

interface FigureBase {
  title: string
  caption: string
  provenance?: unknown
  comparisonKey?: string
  comparisonLabel?: string
}
export interface SeriesFigure extends FigureBase {
  kind: 'series'
  series: Series[]
  xLabel: string
  yLabel: string
  xDomain?: Domain
  yDomain?: Domain
  xTicks?: Tick[]
  categorical?: boolean
  reference?: number
  equalAspect?: boolean
}
export interface HeatmapFigure extends FigureBase {
  kind: 'heatmap'
  rows: string[]
  columns: string[]
  values: (number | null)[][]
  unit: string
  diverging?: boolean
  colorLimits?: Domain
  reverseRows?: boolean
  fullMatrix?: boolean
  xLabel?: string
  yLabel?: string
}
export type ComparisonFigure = SeriesFigure | HeatmapFigure
export interface ComparisonEntry { identity: string; group: string; figure: ComparisonFigure }
export const comparisonScope: InjectionKey<Readonly<Ref<string>>> = Symbol('assessment-comparison-scope')
export const MAX_COMPARISON_FIGURES = 12
// Page-session snapshots survive candidate component remounts, and are isolated by search.
const selections = shallowRef<Record<string, ComparisonEntry[]>>({})

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`
  if (value && typeof value === 'object') return `{${Object.entries(value).filter(([, v]) => v !== undefined).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(',')}}`
  return JSON.stringify(value) ?? 'null'
}
export function comparisonIdentity(figure: ComparisonFigure): string {
  return canonical([figure.kind, figure.comparisonKey, figure.provenance])
}
export function useFigureComparison(scope = inject(comparisonScope, undefined)) {
  const entries = computed(() => scope ? selections.value[scope.value] ?? [] : [])
  function remove(identity: string) {
    if (scope) selections.value = { ...selections.value, [scope.value]: entries.value.filter(e => e.identity !== identity) }
  }
  function clear() { if (scope) selections.value = { ...selections.value, [scope.value]: [] } }
  function toggle(figure: ComparisonFigure) {
    if (!scope || !figure.comparisonKey || !figure.provenance) return
    const identity = comparisonIdentity(figure)
    if (entries.value.some(e => e.identity === identity)) { remove(identity); return }
    if (entries.value.length >= MAX_COMPARISON_FIGURES) return
    const snapshot = JSON.parse(JSON.stringify(figure)) as ComparisonFigure
    selections.value = { ...selections.value, [scope.value]: [...entries.value, { identity, group: `${figure.kind}:${figure.comparisonKey}`, figure: snapshot }] }
  }
  return { enabled: !!scope, entries, toggle, remove, clear }
}

function unionDomains(domains: (Domain | undefined)[]): Domain | undefined {
  const valid = domains.filter((d): d is Domain => !!d)
  return valid.length ? [Math.min(...valid.map(d => d[0])), Math.max(...valid.map(d => d[1]))] : undefined
}

/** Re-render only: source samples, statistics, gaps and provenance remain untouched. */
export function comparisonFigures(entries: ComparisonEntry[]): ComparisonFigure[] {
  if (!entries.length) return []
  if (entries[0]!.figure.kind === 'heatmap') {
    const figures = entries.map(e => e.figure as HeatmapFigure)
    let colorLimits = unionDomains(figures.map(f => f.colorLimits))
    if (colorLimits && figures.some(f => f.diverging)) {
      const max = Math.max(Math.abs(colorLimits[0]), Math.abs(colorLimits[1]))
      colorLimits = [-max, max]
    }
    return figures.map(f => ({ ...f, colorLimits, comparisonKey: undefined }))
  }
  const figures = entries.map(e => e.figure as SeriesFigure)
  const yDomain = unionDomains(figures.map(f => f.yDomain))
  const xDomain = unionDomains(figures.map(f => f.xDomain))
  const points = figures.flatMap(f => f.series.flatMap(s => s.points))
  // Align categories by their identities, never by a candidate's local array index.
  if (figures.every(f => f.categorical && f.series.every(s => s.connect === false)) && points.every(p => !!p.label)) {
    const labels = [...new Set(points.map(p => p.label!))]
    const positions = new Map(labels.map((label, i) => [label, i + 1]))
    const ticks = labels.map((label, i) => ({ value: i + 1, label })).filter((_, i) => i % Math.max(1, Math.ceil(labels.length / 12)) === 0 || i === labels.length - 1)
    return figures.map(f => ({ ...f, comparisonKey: undefined, yDomain, xDomain: [.5, labels.length + .5], xTicks: ticks, series: f.series.map(s => ({ ...s, points: s.points.map(p => ({ ...p, x: positions.get(p.label!)! })) })) }))
  }
  return figures.map(f => ({ ...f, comparisonKey: undefined, xDomain, yDomain }))
}
