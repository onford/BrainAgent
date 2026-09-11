import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import WorkflowEvidence from './WorkflowEvidence.vue'
import { apiRequest } from '../../api/client'
vi.mock('../../api/client', () => ({ apiRequest: vi.fn() }))
const global = { stubs: { RouterLink: { props: ['to'], template: '<a :href="JSON.stringify(to)"><slot /></a>' } } }

describe('workflow evidence attribution', () => {
  it('distinguishes loading from an empty list and can retry a failed request', async () => {
    let reject!: (error: Error) => void
    vi.mocked(apiRequest).mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail }))
    const wrapper = mount(WorkflowEvidence, { props: { workflowId: 'w', reportCount: 7 }, global })
    expect(wrapper.get('[role="status"]').text()).toContain('正在加载')
    expect(wrapper.text()).not.toContain('暂无搜索记录')
    reject(new Error('offline'))
    await flushPromises()
    vi.mocked(apiRequest).mockResolvedValueOnce([])
    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('暂无搜索记录')
    wrapper.unmount()
  })
  it('requires an explicit choice among searches from the same workflow', async () => {
    vi.mocked(apiRequest).mockResolvedValue([
      { id: 'related', workflow_id: 'w', created_at: '2026-09-10', status: 'failed' },
      { id: 'unrelated', workflow_id: 'other', created_at: '2026-09-10', status: 'completed' },
    ])
    const wrapper = mount(WorkflowEvidence, { props: { workflowId: 'w', reportCount: 7 }, global })
    await flushPromises()
    expect(wrapper.findAll('a')).toHaveLength(0)
    expect(wrapper.findAll('option')).toHaveLength(2)
    await wrapper.get('select').setValue('related')
    expect(wrapper.findAll('a')).toHaveLength(5)
    expect(wrapper.get('a').attributes('href')).toContain('related')
    expect(wrapper.text()).toContain('结果与本流程的原交付分别记录')
    wrapper.unmount()
  })
  it('keeps offline navigation local without requesting searches', async () => {
    vi.mocked(apiRequest).mockClear()
    const wrapper = mount(WorkflowEvidence, { props: { workflowId: 'w', searchId: 'search', reportCount: 7, offline: true }, global })
    await flushPromises()
    expect(apiRequest).not.toHaveBeenCalled()
    expect(wrapper.findAll('a')).toHaveLength(0)
    expect(wrapper.text()).toContain('搜索图表和决策详情需在线查看')
    wrapper.unmount()
  })
})
