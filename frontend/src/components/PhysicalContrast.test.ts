import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PhysicalContrast from './PhysicalContrast.vue'
import AssessmentPlot from './AssessmentPlot.vue'

describe('physical contrast', () => {
  it('shows aligned views at one scale and links full voltage arrays', () => {
    const views = Object.fromEntries(['source', 'processed', 'difference'].map((key, i) => [key, { preview: { channels: ['C3', 'C4'], trial_id: 'trial1', waveform: { times_seconds: [0, 1], values_uv: [[i + 1, i + 2], [10, -10]] } } }]))
    const wrapper = mount(PhysicalContrast, { props: { searchId: 'run', folder: 'candidates/c/assessment/a1/quality', recordId: 'r', contrast: { status: 'evaluated', paired_trials: 2, expected_trials: 2, contract: { time_window: [-.2, 1], space: { band_hz: [8, 30] } }, views, artifacts: [{ view: 'difference', path: 'physical-contrast/r/difference.npy' }] } } })
    const charts = wrapper.findAllComponents(AssessmentPlot)
    expect(charts).toHaveLength(3)
    expect(charts.every(c => JSON.stringify(c.props('yDomain')) === JSON.stringify(charts[0]!.props('yDomain')))).toBe(true)
    expect(charts[0]!.props('series')[0].points[0].x).toBe(-.2)
    expect(wrapper.text()).toContain('不等于纯伪迹')
    expect(wrapper.find('a').attributes('href')).toContain('/physical-contrast/r/difference.npy')
  })
  it('does not draw a fabricated difference for unavailable geometry', () => {
    const wrapper = mount(PhysicalContrast, { props: { searchId: 'run', folder: 'quality', recordId: 'r', contrast: { status: 'not_comparable', reason: 'original_sample_map_unavailable' } } })
    expect(wrapper.findComponent(AssessmentPlot).exists()).toBe(false)
    expect(wrapper.text()).toContain('未生成信号差值')
  })
})
