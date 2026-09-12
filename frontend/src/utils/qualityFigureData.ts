import { finite, mean, numeric, type Series } from './assessmentPlots'
import { tickStep, type Domain } from './figureStyle'

// A zero-based, explicit fraction scale that retains small but nonzero rates.
export function fractionDomain(values: unknown[]): Domain {
  let max = 0
  for (const value of values) if (finite(value)) max = Math.max(max, value)
  if (!max) return [0, 1]
  const step = tickStep(max * 1.05)
  const upper = Number((Math.ceil(max * 1.05 / step) * step).toPrecision(12))
  return [0, max > 1 ? upper : Math.min(1, upper)]
}

export function epochSeries(row: any): Series[] {
  if (!['numerical_rank', 'participation_rank', 'covariance_trace', 'covariance_condition'].includes(row?.metricID)
      || !Array.isArray(row.value) || row.value.some((v: unknown) => v !== null && !finite(v))) return []
  const indices = row.details?.valid_epoch_indices ?? row.denominator?.valid_epoch_indices
  if (!Array.isArray(indices) || indices.length !== row.value.length) return []
  return [{ id: row.metricID, name: row.metricID, connect: false,
    points: row.value.map((v: unknown, i: number) => ({ x: indices[i], y: numeric(v), label: `E${indices[i]}` })) }]
}

export function electricalMatrix(row: any, channels: string[]) {
  if (row?.metricID !== 'electrical_distance' || !Array.isArray(row.value) || !row.value.length) return null
  const pairs = row.details?.channel_pairs
  if (!Array.isArray(pairs) || !row.value.every((v: unknown) => Array.isArray(v) && v.length === pairs.length)) return null
  const index = new Map(channels.map((c, i) => [c, i]))
  if (index.size !== channels.length) return null
  const values: (number | null)[][] = channels.map(() => channels.map(() => null))
  for (let p = 0; p < pairs.length; p++) {
    const [a, b] = pairs[p], i = index.get(a), j = index.get(b)
    if (i === undefined || j === undefined || i === j) return null
    values[i]![j] = values[j]![i] = mean(row.value.map((v: unknown[]) => v[p]))
  }
  return { rows: channels, columns: channels, values, unit: row.unit }
}
