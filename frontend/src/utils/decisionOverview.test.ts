import { describe, expect, it } from 'vitest'
import { decisionScore, protocolLabel } from './decisionOverview'
import type { SearchState } from '../types/search'

describe('decision score provenance', () => {
  const state = { protocol: { utility_version: 2 } } as SearchState
  it('never fills a missing EEGNet score from the CSP anchor or nonfinite values', () => {
    for (const value of [null, undefined, NaN, Infinity, -1, 1.1]) {
      expect(decisionScore(state, { id: 'c', status: 'failed', receipt: { macro_ba: .9, assessment: { selection_score: value as number } } })).toBeNull()
    }
  })
  it('retains legacy assessment semantics and zero-valued recorded scores', () => {
    const candidate = { id: 'old', status: 'evaluated', receipt: { assessment: { schema_version: 'assessment-v1', selection_score: 0 }, macro_ba: .7 } }
    expect(decisionScore(state, candidate)).toBe(0)
    expect(protocolLabel(state, candidate)).toContain('历史协议')
    expect(decisionScore({} as SearchState, { id: 'old', status: 'completed', receipt: { macro_ba: .63 } })).toBe(.63)
    expect(protocolLabel({ protocol: { assessment: { version: 2 } } } as SearchState)).toContain('EEGNet')
  })
})
