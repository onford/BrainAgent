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
  it('plots reconstruction conditions separately and follows the selected metric', async () => {
    const wrapper = mount(SearchAssessment, { props: props() })
    await wrapper.findAll('nav button')[2]!.trigger('click')
    const plot = wrapper.findComponent({ name: 'AssessmentPlot' })
    expect(plot.props('categorical')).toBe(true)
    expect(plot.props('series')[0].points[0]).toEqual({x:1,y:null,label:'blink_low'})
  })
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

function v2Props() {
  const result: any = props()
  result.assessment.schema_version = 'assessment-v2'
  result.assessment.selection_score = .7
  result.assessment.utility = {
    utility_version: 2, primary_suite: ['eegnet'], primary_models_available: 1, primary_models_expected: 1,
    primary_trial_predictions_available: 14754, primary_trial_predictions_expected: 14754,
    seed_summary: { seeds: [17, 42, 2026], mean_ba: .7, seed_sd: .08165, minimum_ba: .6, maximum_ba: .8 },
    learner_statuses: { eegnet: 'evaluated', csp_lda: 'evaluated' }, learner_statistics: { eegnet: { ba: { mean: .7, lower_quartile: .65, subject_sd: .1 } } },
    learner_coverage: {}, receipt_artifact: { path: 'utility/utility.json' },
  }
  return result
}
const nativeSeeds = { utility_version: 2, learners: { eegnet: { folds: [], seeds: Object.fromEntries([17, 42, 2026].map((seed, i) => [String(seed), {
  seed, status: 'evaluated', summary: { ba: { mean: .6 + i / 10, lower_quartile: .55, subject_sd: .1 } },
  subjects: { S1: { ba: .6, n_trials: 12 } }, folds: [{ model: { path: `seed-${seed}/model.pt` } }],
  metadata: { path: `seed-${seed}/metadata.json` }, predictions: { path: `seed-${seed}/predictions.json` },
}])) } } }

describe('EEGNet v2 presentation', () => {
  it('keeps historical v1 labels and never calls them EEGNet', () => {
    const wrapper = mount(SearchAssessment, { props: props() })
    expect(wrapper.text()).toContain('历史 v1')
    expect(wrapper.text()).not.toContain('EEGNet')
    expect(wrapper.findAll('tbody tr')).toHaveLength(6)
  })
  it('shows one model, three seeds and subject Q25; lazily reads seed metrics and provenance', async () => {
    vi.mocked(apiRequest).mockReset().mockResolvedValue(nativeSeeds)
    const wrapper = mount(SearchAssessment, { props: v2Props() })
    expect(apiRequest).not.toHaveBeenCalled()
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    expect(wrapper.text()).toContain('1 / 1')
    expect(wrapper.text()).toContain('14754 / 14754')
    expect(wrapper.text()).toContain('0.65')
    expect(wrapper.text()).toContain('种子 SD 0.08165')
    expect(wrapper.text()).not.toContain('FBCSP')
    await wrapper.findAll('button').find(b => b.text().includes('读取逐种子'))!.trigger('click')
    await flushPromises()
    expect(apiRequest).toHaveBeenCalledWith('/api/searches/search/artifacts/candidates/method/assessment/a2/utility/utility.json?download=false')
    for (const seed of [17, 42, 2026]) expect(wrapper.text()).toContain(`seed-${seed}/model.pt`)
    expect(wrapper.text()).toContain('被试 Q25 0.55')
    expect(wrapper.text()).toContain('被试均值 0.8')
  })
  it('does not replace an incomplete score with a benchmark or partial seed mean', () => {
    const input = v2Props()
    input.assessment.selection_score = null
    input.assessment.utility.primary_models_available = 0
    input.assessment.utility.primary_trial_predictions_available = 0
    input.assessment.utility.seed_summary = null
    const wrapper = mount(SearchAssessment, { props: input })
    expect(wrapper.find('.summary strong').text()).toBe('—')
    expect(wrapper.text()).toContain('0 / 14754')
    expect(wrapper.text()).toContain('种子 BA 均值 —')
  })
  it('discards stale seed responses and allows retry after a failed read', async () => {
    let resolve!: (value: any) => void
    vi.mocked(apiRequest).mockReset().mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const wrapper = mount(SearchAssessment, { props: v2Props() })
    const load = () => wrapper.findAll('button').find(b => b.text().includes('读取逐种子'))!.trigger('click')
    await load()
    await wrapper.setProps({ candidateId: 'other' })
    resolve(nativeSeeds)
    await flushPromises()
    expect(wrapper.text()).not.toContain('seed-17/model.pt')
    vi.mocked(apiRequest).mockRejectedValueOnce(new Error('read failed'))
    await load(); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('read failed')
    vi.mocked(apiRequest).mockResolvedValueOnce(nativeSeeds)
    await load(); await flushPromises()
    expect(wrapper.text()).toContain('seed-17/model.pt')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })
})
