import { t } from '../i18n'
export interface Point { x: number; y: number | null; label?: string }
export interface Series { name: string; points: Point[]; connect?: boolean }
export const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
export function mean(values: unknown[]): number | null {
  const valid = values.filter(finite)
  return valid.length ? valid.reduce((a, b) => a + b, 0) / valid.length : null
}
export function db(v: unknown): number | null { return finite(v) && v > 0 ? 10 * Math.log10(v) : null }
export function numeric(v: unknown): number | null { return finite(v) ? v : null }
export function curve(name: string, x: unknown[], y: unknown[], convert = numeric): Series {
  if (x.length !== y.length || !x.every(finite)) return { name, points: [] }
  return { name, points: x.map((v, i) => ({ x: v as number, y: convert(y[i]) })) }
}
export function perSubject(receipt: any, stage: string, metric: string): Series {
  return { get name() { return t('By subject') }, connect: false, points: Object.entries(receipt?.bysubject ?? {}).sort(([a], [b]) => a.localeCompare(b)).map(([id, row]: [string, any], i) => ({ x: i + 1, y: numeric(row.stages?.[stage]?.[metric]?.value), label: id })) }
}
// Preserve the recorded frequency/threshold grid; no interpolation or null=>0.
export function metricCurves(row: any, detail = false): { series: Series[]; xLabel: string; yLabel: string } {
  const axes = detail ? row?.details : row?.axes
  const mid = row?.metricID
  const result = { series: [] as Series[], xLabel: '', yLabel: row?.unit ?? '' }
  if (!Array.isArray(row?.value)) return result
  if (['oha', 'thv', 'chv'].includes(mid) && Array.isArray(axes?.thresholds_uv)) {
    return { series: [curve(mid.toUpperCase(), axes.thresholds_uv, row.value)], get xLabel() { return t('Threshold (µV)') }, get yLabel() { return t('Exceedance fraction (0–1)') } }
  }
  if (mid === 'psd' && Array.isArray(axes?.frequencies_hz)) {
    let values = row.value
    if (detail) {
      // Match record reduction: median of channels in linear power, then epoch mean.
      values = axes.frequencies_hz.map((_: unknown, f: number) => mean(row.value.map((epoch: unknown[][]) => {
        if (!Array.isArray(epoch)) return null
        const a = epoch.map(c => Array.isArray(c) ? c[f] : null).filter(finite).sort((a, b) => a - b)
        return a.length ? (a[Math.floor((a.length - 1) / 2)]! + a[Math.floor(a.length / 2)]!) / 2 : null
      })))
    }
    return { series: [curve('PSD', axes.frequencies_hz, values, db)], get xLabel() { return t('Frequency (Hz)') }, yLabel: `dB(${row.unit})` }
  }
  if (mid === 'psd_window_quantiles' && Array.isArray(axes?.frequencies_hz)) {
    return { series: row.value.map((values: unknown[], i: number) => curve(['Q10', 'Q50', 'Q90'][i] ?? String(i), axes.frequencies_hz, values, db)), get xLabel() { return t('Frequency (Hz)') }, yLabel: `dB(${row.unit})` }
  }
  return result
}
export function downloadData(name: string, value: unknown) {
  downloadBlob(name, new Blob([JSON.stringify(value, null, 2)], { type: 'application/json;charset=utf-8' }))
}
export function downloadBlob(name: string, blob: Blob) {
  const url = URL.createObjectURL(blob), a = document.createElement('a')
  a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
}
export function exportSvg(element: SVGSVGElement | null, name: string) {
  if (!element) return
  const clone = element.cloneNode(true) as SVGSVGElement
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  // Keep exported figures interpretable outside the surrounding Vue page.
  const box = (element.getAttribute('viewBox') ?? '').split(/\s+/).map(Number)
  if (box.length === 4 && box.every(Number.isFinite)) {
    let bottom = box[3]!
    const append = (text: string, color = '#29433b') => {
      const node = document.createElementNS('http://www.w3.org/2000/svg', 'text')
      node.setAttribute('x', '14'); node.setAttribute('y', String(bottom + 18))
      node.setAttribute('fill', color); node.setAttribute('font-size', '12')
      node.textContent = text; clone.appendChild(node); bottom += 22
    }
    append(element.querySelector('title')?.textContent ?? name)
    element.closest('figure')?.querySelectorAll<HTMLElement>('.legend span').forEach(label => append(label.textContent ?? '', label.style.color))
    const caption = element.querySelector('desc')?.textContent ?? ''
    const chars = Math.max(25, Math.floor(box[2]! / 12) - 3)
    for (let i = 0; i < caption.length; i += chars) append(caption.slice(i, i + chars))
    clone.setAttribute('height', String(bottom + 14))
    clone.setAttribute('viewBox', `${box[0]} ${box[1]} ${box[2]} ${bottom + 14}`)
  }
  downloadBlob(name + '.svg', new Blob([new XMLSerializer().serializeToString(clone)], { type: 'image/svg+xml;charset=utf-8' }))
}
