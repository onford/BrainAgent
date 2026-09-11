import { describe, expect, it } from 'vitest'
import { curve, db, metricCurves, perSubject } from './assessmentPlots'

describe('faithful plot data', () => {
  it('does not turn missing or zero power into a finite dB value', () => {
    expect([null, 0, -1, NaN, Infinity].map(db)).toEqual([null, null, null, null, null])
    expect(db(100)).toBe(20)
    expect(curve('bad axes', [1, 2], [3]).points).toEqual([])
  })
  it('reduces PSD in linear space before dB and preserves the real frequency grid', () => {
    const output = metricCurves({ metricID: 'psd', unit: 'µV²/Hz', details: { frequencies_hz: [0, .5] }, value: [[[1, 10], [3, 30]], [[5, 50], [7, 70]]] }, true)
    expect(output.series[0]!.points[0]!.y).toBeCloseTo(10*Math.log10(4))
    expect(output.series[0]!.points[1]!.x).toBe(.5)
    expect(output.series[0]!.points[1]!.y).toBeCloseTo(10*Math.log10(40))
  })
  it('keeps absent subjects and does not use processed values in source views', () => {
    const receipt = { bysubject: { S2: { stages: { processed_task: { peak_to_peak: { value: 7 } } } }, S1: { stages: { source_raw: { peak_to_peak: { value: 4 } } } } } }
    expect(perSubject(receipt, 'source_raw', 'peak_to_peak').points).toEqual([{ x: 1, y: 4, label: 'S1' }, { x: 2, y: null, label: 'S2' }])
  })
})
