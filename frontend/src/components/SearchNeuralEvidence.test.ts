import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SearchNeuralEvidence from './SearchNeuralEvidence.vue'

describe('neural evidence provenance', () => {
  it('does not imply historical or unexecuted use', () => {
    const wrapper = mount(SearchNeuralEvidence, { props: { searchId: 'run', protocol: {} } })
    expect(wrapper.text()).toContain('未冻结神经先验包')
    expect(wrapper.find('a').exists()).toBe(false)
  })
  it('shows uncertainty, alternative causes and actual citation evidence', () => {
    const wrapper = mount(SearchNeuralEvidence, { props: { searchId: 'run', protocol: { neural_priors: {
      capabilities: { catalog_units: 52, enabled_units: 11, enabled_operations: 14, search_operators: 10 },
      sources: [{ id: 's', title: '原始来源', url: 'https://example.org/paper' }] } },
      diagnostics: [{ id: 'd', candidate_id: 'c', stage: 'source_raw', question: '工频可测吗',
        artifact: { path: 'diagnostics/d.json' }, prior_evaluation: { rules: [{ id: 'r', title: '工频', condition_state: 'unknown',
        observed: { value: null }, reason: 'band_unavailable', alternative: '神经窄带活动', protection: '不能制造典型ERD', source_ids: ['s'] }] } }],
      actions: [{ index: 1, result: { prior_evidence: { status: 'cited_by_agent', diagnostic_ids: ['d'], prior_rule_ids: ['r'] } } }] } })
    expect(wrapper.text()).toContain('工频：未知')
    expect(wrapper.text()).toContain('神经窄带活动')
    expect(wrapper.text()).toContain('1 个决策')
    expect(wrapper.findAll('a').some(a => a.attributes('href')?.includes('diagnostics/d.json'))).toBe(true)
  })
})
