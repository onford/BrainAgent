import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import SearchInterpretation from './SearchInterpretation.vue'
import SearchParameters from './SearchParameters.vue'
import AssessmentHeatmap from './AssessmentHeatmap.vue'
import { apiRequest } from '../api/client'
vi.mock('../api/client', () => ({ apiRequest: vi.fn() }))
beforeEach(() => vi.clearAllMocks())

it('uses the saved guide for frozen runs and labels current guidance on history', async () => {
  vi.mocked(apiRequest).mockResolvedValue({ cards: [], sources: [] })
  const wrapper = mount(SearchInterpretation, { props: { searchId: 'new', frozen: true } })
  const details = wrapper.get('details')
  ;(details.element as HTMLDetailsElement).open = true
  await details.trigger('toggle'); await flushPromises()
  expect(apiRequest).toHaveBeenLastCalledWith('/api/searches/new/artifacts/interpretation-guide.json?download=false')
  await wrapper.setProps({ searchId: 'old', frozen: false }); await flushPromises()
  expect(apiRequest).toHaveBeenLastCalledWith('/api/searches/interpretation-guide')
  expect(wrapper.text()).toContain('此运行没有配套指南')
})

it('shows recorded seeds and domain provenance without inventing missing values', () => {
  const wrapper = mount(SearchParameters, { props: { protocol: { utility_protocol: { seeds: [17,42,2026] }, space: { operators: [{ id: 'filter', domains: { cutoff: { kind: 'number', minimum: 1, maximum: 40, unit: 'Hz', origin: 'engineering', rationale: 'bounded test domain' } } }] } }, recipe: { nodes: [{ id: 'node', operator: 'filter', parameters: { cutoff: 8 } }] } } })
  expect(wrapper.text()).toContain('[17,42,2026]')
  expect(wrapper.text()).toContain('工程约定 · bounded test domain')
  expect(wrapper.text()).toContain('未记录')
})

it('paginates large channel-pair matrices using global color limits', async () => {
  const wrapper = mount(AssessmentHeatmap, { props: { title: 'pairs', rows: ['epoch'], columns: Array.from({length: 130}, (_, i) => String(i)), values: [Array.from({length: 130}, (_, i) => i)], unit: 'uV', caption: 'test' } })
  expect(wrapper.findAll('rect')).toHaveLength(64)
  expect(wrapper.text()).toContain('0 ～ 129')
  await wrapper.findAll('button').find(b => b.text() === '下一组列')!.trigger('click')
  expect(wrapper.find('rect title').text()).toContain('64')
  expect(wrapper.text()).toContain('0 ～ 129')
})
