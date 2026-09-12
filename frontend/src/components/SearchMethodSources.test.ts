import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SearchMethodSources from './SearchMethodSources.vue'
import type { SearchState } from '../types/search'

describe('method source trace', () => {
  it('shows removed reference and changed filter together without claiming a single-factor effect', () => {
    const state = {
      id: 'run', status: 'completed', registry: [{ id: 'paper', title: '7–30 Hz', origin: 'literature_adaptation', recipe: { nodes: [] }, deviations: [], edits: [] }],
      literature_participation: { statement: '本轮文献预处理操作已进入真实评价；不等于独立有效性确认。' },
      candidate_contrasts_to_reference: { paper: { removed_operations: ['eeg_reference/set_eeg_reference#1'], added_operations: [], parameter_changes: [{ operation: 'eeg_filter/filter#1', parameter: 'l_freq', before: 8, after: 7 }], shared_operation_order_changed: false, scope_changes: [], interpretation: '配置差异清单，不证明数值差异、因果效应或单因素设计。' } }
    } as unknown as SearchState
    const wrapper = mount(SearchMethodSources, { props: { state } })
    expect(wrapper.text()).toContain('移除：eeg_reference/set_eeg_reference#1')
    expect(wrapper.text()).toContain('l_freq：8 → 7')
    expect(wrapper.text()).toContain('不证明数值差异、因果效应或单因素设计')
    expect(wrapper.text()).toContain('不等于独立有效性确认')
  })
  it('distinguishes evaluated, budget-deferred and blocked methods with original evidence', () => {
    const state = {
      id: 'run', status: 'stopped', stop_reason: 'candidate_budget_exhausted',
      registry: [
        { id: 'base', title: '基础方案', origin: 'basic', recipe: { nodes: [] }, deviations: [], edits: [] },
        { id: 'derived', title: '组合方案', origin: 'derived', parent_ids: ['base', 'paper'],
          lineage: [{ source_id: 'read-1', source_url: 'https://example.org/paper', branch_id: 'mi', method_ref: { id: 'original' }, extraction_path: 'preprocessing/literature-methods/read-1/resolved-extraction.json' }],
          recipe: { nodes: [{ operator: 'bandpass' }] }, deviations: ['公共输出适配'], edits: [{ action: 'combine_fragment' }] }
      ],
      candidates: [{ id: 'base', status: 'evaluated', receipt: {} }],
      protocol: { method_intake: { absence_reasons: [], methods: [
        { title: '未完成筛查的方法', status: 'blocked', reasons: ['缺少 EMG'], lineage: { branch_id: 'mi' }, method_ref: { id: 'blocked' } }
      ] } }
    } as unknown as SearchState
    const wrapper = mount(SearchMethodSources, { props: { state } })
    expect(wrapper.text()).toContain('已评价')
    expect(wrapper.text()).toContain('已推迟')
    expect(wrapper.text()).toContain('父方法：base、paper')
    expect(wrapper.text()).toContain('缺少 EMG')
    expect(wrapper.findAll('a').some(a => a.attributes('href')?.includes('source-methods/original.json'))).toBe(true)
    expect(wrapper.findAll('a').some(a => a.attributes('href')?.includes('literature-methods/read-1/extraction.json'))).toBe(true)
    expect(wrapper.findAll('a').some(a => a.attributes('href')?.includes('literature-methods/read-1/resolved-extraction.json'))).toBe(true)
  })
})
