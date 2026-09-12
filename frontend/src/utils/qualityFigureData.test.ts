import { describe, expect, it } from 'vitest'
import { electricalMatrix, epochSeries, fractionDomain } from './qualityFigureData'

describe('measurement-aware chart selection', () => {
  it('makes small fractions visible without excluding zero or clipping invalid large observations', () => {
    expect(fractionDomain([0, .0115, null])).toEqual([0, .015])
    expect(fractionDomain([0, 0])).toEqual([0, 1])
    expect(fractionDomain([0, 1])).toEqual([0, 1])
    expect(fractionDomain([2])[1]).toBeGreaterThan(2)
    expect(fractionDomain(Array(200000).fill(.01))[1]).toBeGreaterThan(.01)
  })
  it('retains original epoch IDs and gaps in one-dimensional measurements', () => {
    const row = { metricID: 'numerical_rank', value: [63, null, 62], details: { valid_epoch_indices: [1, 4, 7] } }
    expect(epochSeries(row)[0]?.points).toEqual([{ x: 1, y: 63, label: 'E1' }, { x: 4, y: null, label: 'E4' }, { x: 7, y: 62, label: 'E7' }])
    expect(epochSeries({ ...row, details: { valid_epoch_indices: [1] } })).toEqual([])
  })
  it('uses pair identities, finite epoch means and unmeasured diagonals in the electrode matrix', () => {
    const row = { metricID: 'electrical_distance', unit: 'µV²', value: [[2, 8, null], [4, null, 10]], details: { channel_pairs: [['B', 'A'], ['C', 'B'], ['A', 'C']] } }
    expect(electricalMatrix(row, ['A', 'B', 'C'])?.values).toEqual([[null, 3, 10], [3, null, 8], [10, 8, null]])
    expect(electricalMatrix(row, ['A', 'B'])).toBeNull()
    expect(electricalMatrix({ ...row, value: [[1, 2]] }, ['A', 'B', 'C'])).toBeNull()
  })
})
