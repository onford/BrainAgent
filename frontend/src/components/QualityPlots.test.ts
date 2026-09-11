import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import QualityPlots from './QualityPlots.vue'
import AssessmentPlot from './AssessmentPlot.vue'
import { apiRequest } from '../api/client'
vi.mock('../api/client', () => ({ apiRequest: vi.fn(), apiUrl: (s: string) => s }))
const props = { searchId: 'run', candidateId: 'one', basePath: 'assessment/a1', receiptPath: 'quality/data-quality.json' }
describe('quality drilldown', () => {
  it('keeps the chart stage synchronized with the assessment table', async () => {
    vi.mocked(apiRequest).mockReset().mockResolvedValue({ stages: {} })
    const wrapper = mount(QualityPlots, { props: { ...props, stage: 'source_task' } })
    await flushPromises()
    expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('source_task')
    await wrapper.find('select').setValue('processed_task')
    expect(wrapper.emitted('update:stage')?.[0]).toEqual(['processed_task'])
    await wrapper.setProps({ stage: 'source_raw' })
    expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('source_raw')
  })
  it('ignores a late response from a previous candidate', async () => {
    let first!: (v: any) => void
    vi.mocked(apiRequest).mockReset().mockImplementationOnce(() => new Promise(resolve => { first = resolve })).mockResolvedValueOnce({ stages: { processed_task: { psd: { metricID: 'psd', value: [100], axes: { frequencies_hz: [10] }, unit: 'µV²/Hz', status: 'ok' } } } })
    const wrapper = mount(QualityPlots, { props })
    await wrapper.setProps({ candidateId: 'two' }); await flushPromises()
    first({ stages: { processed_task: { psd: { metricID: 'psd', value: [1], axes: { frequencies_hz: [10] }, unit: 'µV²/Hz', status: 'ok' } } } }); await flushPromises()
    expect(wrapper.findComponent(AssessmentPlot).props('series')[0].points[0].y).toBe(20)
  })
  it('retries failed reads and uses indexed relative record artifacts', async () => {
    vi.mocked(apiRequest).mockReset().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ detail_artifacts: [{ record_id: 'R1', subject: 'S1', path: 'quality-details/r.json' }], stages: {} }).mockResolvedValueOnce({ stages: {} })
    const wrapper = mount(QualityPlots, { props }); await flushPromises()
    expect(wrapper.text()).toContain('offline')
    await wrapper.find('button').trigger('click'); await flushPromises()
    await wrapper.findAll('select')[2]!.setValue('R1'); await flushPromises()
    expect(apiRequest).toHaveBeenLastCalledWith('/api/searches/run/artifacts/candidates/one/assessment/a1/quality/quality-details/r.json?download=false')
    expect(wrapper.text()).toContain('没有该指标记录')
  })
  it('breaks curves at missing data rather than drawing through the gap', () => {
    const wrapper = mount(AssessmentPlot, { props: { title: 'test', caption: 'test', xLabel: 'Hz', yLabel: 'power', series: [{ name: 'PSD', points: [{x: 0,y: 1},{x: 1,y: null},{x: 2,y: 3}] }] } })
    expect(wrapper.find('path').attributes('d').match(/M/g)).toHaveLength(2)
    expect(wrapper.findAll('circle')).toHaveLength(2)
  })
})
