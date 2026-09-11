import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SearchDecisionOverview from './SearchDecisionOverview.vue'
import type { SearchState } from '../types/search'

describe('SearchDecisionOverview', () => {
  it('does not select the highest candidate locally and exposes failed predictions', async () => {
    const state = { id: 'run', status: 'failed', protocol: { utility_version: 2 }, selected_candidate_id: null,
      candidates: [{ id: 'c1', title: '待核验方案', status: 'evaluated', receipt: { assessment: { selection_score: .75 } } }],
      actions: [{ index: 1, action: 'propose_candidate', status: 'failed', candidate_id: 'c1', reason: '检查频带', result: { prediction_checks: { checks: [{ metric: 'x', explanation: '预期改善', status: 'contradicted', before: .2, after: .1 }] } } }],
    } as unknown as SearchState
    const wrapper = mount(SearchDecisionOverview, { props: { state } })
    expect(wrapper.get('.decision-result').text()).toContain('尚未选定方案')
    expect(wrapper.text()).toContain('与预测不符')
    expect(wrapper.text()).toContain('尚未正常完成')
    await wrapper.get('.candidate-list button').trigger('click')
    expect(wrapper.emitted('navigate')![0]).toEqual(['assessment', 'c1', 'utility'])
    wrapper.unmount()
  })
})
