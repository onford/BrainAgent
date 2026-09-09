import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import SearchAssessment from './SearchAssessment.vue'
import { apiRequest } from '../api/client'

vi.mock('../api/client', () => ({ apiRequest: vi.fn(), apiUrl: (path: string) => path }))
function props() {
  return { searchId: 'search', candidateId: 'method', basePath: 'assessment/a2', assessment: {
    selection_score: null, core_csp_macro_ba: .8, status: 'partial',
    coverage: { subjects_expected: 109, records_expected: 327, eligible_trials: 4918 },
    utility: { primary_suite: ['csp_lda', 'fbcsp', 'ts_lr'], failure_reasons: ['TS-LR failed; no partial average'], learner_scores: { csp_lda: .8 }, learner_statuses: { csp_lda: 'evaluated', ts_lr: 'failed' }, learner_statistics: {}, learner_coverage: {} },
    quality: { summary: { metrics: { peak_to_peak: { value: 12, unit: 'µV', status: 'ok', denominator: { available_subjects: 108, expected_subjects: 109 } } } }, receipt_artifact: { path: 'quality/data-quality.json' } },
    reconstruction: { summary: { design: 'balanced', subjects_expected: 109, cases_expected: 109, by_case: { 'blink_low': { metrics: { paired_nrmse: { value: null, status: 'not_applicable', n_valid: 0, n_total: 11 } } } } }, receipt_artifact: { path: 'reconstruction/reconstruction_evaluation.json' } },
  } }
}

describe('multi-axis assessment', () => {
  it('does not substitute the CSP score when the fixed primary suite is incomplete', () => {
    const wrapper = mount(SearchAssessment, { props: props() })
    expect(wrapper.find('.summary strong').text()).toBe('—')
    expect(wrapper.text()).toContain('TS-LR failed; no partial average')
    expect(wrapper.text()).toContain('4918')
  })
  it('does not relabel processed measurements as source measurements while loading', async () => {
    let resolve!: (value: any) => void
    vi.mocked(apiRequest).mockImplementation(() => new Promise(done => { resolve = done }))
    const wrapper = mount(SearchAssessment, { props: props() })
    await wrapper.findAll('nav button')[1]!.trigger('click')
    expect(wrapper.find('tbody').text()).toContain('12')
    await wrapper.find('select').setValue('source_raw')
    expect(wrapper.find('tbody').text()).not.toContain('12')
    resolve({ stages: { source_raw: { peak_to_peak: { value: 75, unit: 'µV', status: 'ok' } } } })
    await flushPromises()
    expect(wrapper.find('tbody').text()).toContain('75')
    expect(apiRequest).toHaveBeenCalledWith('/api/searches/search/artifacts/candidates/method/assessment/a2/quality/data-quality.json?download=false')
  })
  it('shows missing reconstruction results with their assigned denominator', async () => {
    const wrapper = mount(SearchAssessment, { props: props() })
    await wrapper.findAll('nav button')[2]!.trigger('click')
    expect(wrapper.find('tbody').text()).toContain('0 / 11')
    expect(wrapper.find('tbody').text()).toContain('不适用')
    expect(wrapper.find('tbody').text()).toContain('—')
    expect(wrapper.find('a').attributes('href')).toContain('assessment/a2/reconstruction/')
  })
})
