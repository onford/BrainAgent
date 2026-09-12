import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MetricReading from './MetricReading.vue'
import { apiRequest } from '../api/client'

vi.mock('../api/client', () => ({ apiRequest: vi.fn() }))
const props = { searchId: 's', candidateId: 'c', stage: 'processed_task', metricId: 'flat_fraction', row: { value: null, denominator: { available_subjects: 0, expected_subjects: 4 } } }
const reply = { model: { name: 'model' }, reading: { claims: [{ text: '任务片段不足五秒，无法评估持续平坦。', source_ids: ['prep'] }], next_check: null }, context: { sources: [{ id: 'prep', title: 'PREP', url: 'https://example.test/prep' }], cards: [] } }
async function open(wrapper: ReturnType<typeof mount>) {
  const details = wrapper.find('details')
  ;(details.element as HTMLDetailsElement).open = true
  await details.trigger('toggle')
  await flushPromises()
}
beforeEach(() => vi.mocked(apiRequest).mockReset())
describe('evidence-based metric reading', () => {
  it('loads on demand, preserves zero coverage and links the cited theory', async () => {
    vi.mocked(apiRequest).mockResolvedValue(reply)
    const wrapper = mount(MetricReading, { props })
    expect(apiRequest).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('0 / 4')
    await open(wrapper)
    expect(apiRequest).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.claim').text()).toContain('不足五秒')
    expect(wrapper.find('.citation').attributes('href')).toBe('https://example.test/prep')
    expect(wrapper.find('.next-check').exists()).toBe(false)
    await open(wrapper)
    expect(apiRequest).toHaveBeenCalledTimes(1)
  })
  it('does not fill unknown coverage with zero or fabricate a fallback conclusion', async () => {
    vi.mocked(apiRequest).mockRejectedValue(new Error('offline'))
    const wrapper = mount(MetricReading, { props: { ...props, row: {} } })
    await open(wrapper)
    expect(wrapper.text()).toContain('— / —')
    expect(wrapper.find('[role=alert]').text()).toContain('offline')
    expect(wrapper.find('.claim').exists()).toBe(false)
    vi.mocked(apiRequest).mockResolvedValue(reply)
    await wrapper.find('button').trigger('click'); await flushPromises()
    expect(wrapper.find('.claim').exists()).toBe(true)
  })
  it('rejects late replies when the candidate changes', async () => {
    let resolve!: (r: any) => void
    vi.mocked(apiRequest).mockImplementationOnce(() => new Promise(done => { resolve = done })).mockResolvedValue({ ...reply, reading: { claims: [{ text: '新候选解读', source_ids: ['prep'] }] } })
    const wrapper = mount(MetricReading, { props })
    await open(wrapper)
    await wrapper.setProps({ candidateId: 'next' }); await flushPromises()
    resolve(reply); await flushPromises()
    expect(wrapper.find('.claim').text()).toContain('新候选解读')
    expect(wrapper.find('.claim').text()).not.toContain('不足五秒')
    expect(JSON.parse(vi.mocked(apiRequest).mock.calls[1]![1]!.body as string).candidate_id).toBe('next')
  })
})
