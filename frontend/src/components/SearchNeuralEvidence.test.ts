import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SearchNeuralEvidence from './SearchNeuralEvidence.vue'

describe('neural evidence provenance', () => {
  it('keeps limited spectral windows and missing full-band results explicit', () => {
    const wrapper = mount(SearchNeuralEvidence, { props: { searchId: 'run', protocol: { neural_priors: { capabilities: {} } },
      diagnostics: [{ id: 'd', spectral_components: { signed_periodic_fraction: { value: null, available_records: 0, expected_records: 2 },
        records: [{ record_id: 'r', status: 'partial', reason: 'requested_band_partially_supported', frequencies_hz: [4, 30], signed_periodic_fraction: -.1 }] } }] } })
    expect(wrapper.text()).toContain('最多 16 秒')
    expect(wrapper.text()).toContain('占比：不可用；完整记录 0 / 2')
    expect(wrapper.text()).toContain('-0.10000')
    expect(wrapper.text()).toContain('不是置信区间')
  })
  it('keeps unidentifiable timing unavailable with its full denominator', () => {
    const wrapper = mount(SearchNeuralEvidence, { props: { searchId: 'run', protocol: { neural_priors: { capabilities: {} } },
      diagnostics: [{ id: 'd', common_view_change: { summary: { lag_ms: { value: null, unit: 'ms', available_records: 0, expected_records: 2 },
        normalized_change: { value: .1, unit: 'ratio', available_records: 2, expected_records: 2 } },
        records: [{ record_id: 'r', status: 'evaluated', expected_trial_channel_pairs: 4, ambiguous_lag_pairs: 2 }] } }] } })
    expect(wrapper.get('table').text()).toContain('波形相关峰偏移不可用ms0 / 2')
    expect(wrapper.text()).toContain('2 个偏移不可辨识')
    expect(wrapper.text()).toContain('不能证明神经信息无损')
  })
  it('distinguishes unavailable measurements, planned branches and revised decisions', () => {
    const wrapper = mount(SearchNeuralEvidence, { props: { searchId: 'run', protocol: { neural_priors: { capabilities: {} } },
      diagnostics: [{ id: 'd', decision_effect: { experiment: { hypothesis: '频谱峰值较高', competing_explanation: '峰值较低', threshold_rationale: '待验证预测' },
        outcome: 'unavailable', value: null, selected_branch: { next_action: 'request_diagnostic', reason: '需补充测量' } } }],
      actions: [{ index: 2, action: 'model_decision', status: 'completed', result: { decision: { action: 'finish' },
        diagnostic_response: { diagnostic_id: 'd', disposition: 'revise', reason: '没有剩余测量预算' } } }] } })
    expect(wrapper.text()).toContain('测量不可用；观测值 不可用')
    expect(wrapper.text()).toContain('预登记下一步：请求诊断')
    expect(wrapper.text()).toContain('实际决定：结束搜索 · 修订计划 · 没有剩余测量预算')
    expect(wrapper.text()).not.toContain('尚未记录后续决定')
  })
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
