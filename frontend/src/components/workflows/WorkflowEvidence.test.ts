import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import WorkflowEvidence from './WorkflowEvidence.vue'
import { apiRequest } from '../../api/client'
vi.mock('../../api/client', () => ({ apiRequest: vi.fn() }))
const global = { stubs: { RouterLink: { props: ['to'], template: '<a :href="JSON.stringify(to)"><slot /></a>' } } }

describe('workflow evidence attribution', () => {
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
    expect(wrapper.text()).toContain('不会改变本流程原有的选择与交付')
    wrapper.unmount()
  })
  it('keeps offline navigation local without requesting searches', async () => {
    vi.mocked(apiRequest).mockClear()
    const wrapper = mount(WorkflowEvidence, { props: { workflowId: 'w', searchId: 'search', reportCount: 7, offline: true }, global })
    await flushPromises()
    expect(apiRequest).not.toHaveBeenCalled()
    expect(wrapper.findAll('a')).toHaveLength(0)
    expect(wrapper.text()).toContain('未嵌入关联搜索页面')
    wrapper.unmount()
  })
})
