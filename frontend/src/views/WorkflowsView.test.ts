import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import WorkflowsView from './WorkflowsView.vue'

const { request, replace } = vi.hoisted(() => ({ request: vi.fn(), replace: vi.fn() }))
vi.mock('../api/client', () => ({ apiRequest: request, apiUrl: (path: string) => path }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ replace }),
  RouterLink: { template: '<a><slot /></a>' },
}))

function workflow(status: string) {
  return {
    id: 'abc123', status, created_at: '2026-09-08T08:00:00Z', updated_at: '2026-09-08T08:00:00Z',
    request: { source_root: 'E:/dataset/eeg/EEGMMIDB' }, error: null, artifacts: [], events: [],
    stages: ['数据调研', '数据接入', '数据预处理', '结果选择', '数据报告', '数据交付'].map((label, i) => ({
      name: `stage${i}`, label, status: status === 'completed' ? 'completed' : i === 4 ? 'failed' : 'pending',
    })),
    outputs: status === 'completed' ? { data_delivery: { shape: [90, 64, 321] } } : {},
  }
}

describe('WorkflowsView', () => {
  beforeEach(() => { request.mockReset(); replace.mockReset().mockResolvedValue(undefined) })

  it('starts the configured training workflow and exposes completed downloads and report', async () => {
    const completed = workflow('completed')
    request.mockImplementation(async (path: string, options?: RequestInit) => {
      if (path.endsWith('/sources')) return { allowed_roots: ['E:/dataset/eeg/EEGMMIDB'] }
      if (path === '/api/workflows' && !options) return []
      return completed
    })
    const wrapper = mount(WorkflowsView)
    await flushPromises()
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const submitted = request.mock.calls.find(([, options]) => options?.method === 'POST')
    expect(JSON.parse(submitted![1].body)).toMatchObject({
      source_root: 'E:/dataset/eeg/EEGMMIDB', max_subjects: 3, runs: [4, 8], seed: 42,
    })
    expect(wrapper.text()).toContain('6 / 6 个模块已完成')
    expect(wrapper.text()).toContain('训练数据已就绪')
    expect(wrapper.get('iframe').attributes('src')).toContain('report/report.html?download=false')
    expect(wrapper.get('a.primary').attributes('href')).toContain('training-data.zip')
    expect(wrapper.text()).toContain('未进行质量排名')
    wrapper.unmount()
  })

  it('retries a failed stage and updates the result', async () => {
    let state = workflow('failed')
    request.mockImplementation(async (path: string) => {
      if (path.endsWith('/sources')) return { allowed_roots: [] }
      if (path === '/api/workflows') return [state]
      if (path.endsWith('/retry')) state = workflow('completed')
      return state
    })
    const wrapper = mount(WorkflowsView)
    await flushPromises()
    expect(wrapper.find('iframe').exists()).toBe(false)
    await wrapper.get('.progress-panel button').trigger('click')
    await flushPromises()
    expect(request).toHaveBeenCalledWith('/api/workflows/abc123/retry', { method: 'POST' })
    expect(wrapper.text()).toContain('训练数据已就绪')
    wrapper.unmount()
  })

  it('opens available survey reports before the entire workflow finishes', async () => {
    const state = { ...workflow('failed'), artifacts: [
      'survey/reports/dataset-basic.html', 'survey/reports/literature-usage.html',
    ].map(name => ({ name, bytes: 500, sha256: 'abc' })) }
    request.mockImplementation(async (path: string) => path.endsWith('/sources') ? { allowed_roots: [] } : path === '/api/workflows' ? [state] : state)
    const wrapper = mount(WorkflowsView)
    await flushPromises()
    const links = wrapper.findAll('.survey-reports a')
    expect(links).toHaveLength(2)
    expect(links[0]!.text()).toBe('数据集基本信息')
    expect(links.every(link => link.attributes('href')?.endsWith('?download=false'))).toBe(true)
    expect(wrapper.find('iframe').exists()).toBe(false)
    wrapper.unmount()
  })

  it('keeps long stage errors collapsed outside the stage grid', async () => {
    const state = workflow('failed')
    const message = 'quote must occur verbatim in its retrieved source; '.repeat(30)
    Object.assign(state.stages[4], { error: message })
    request.mockImplementation(async (path: string) => path.endsWith('/sources') ? { allowed_roots: [] } : path === '/api/workflows' ? [state] : state)
    const wrapper = mount(WorkflowsView)
    await flushPromises()
    const details = wrapper.get('details.stage-error')
    expect(details.attributes('open')).toBeUndefined()
    expect(details.get('summary').text()).toContain('数据报告：查看错误详情')
    expect(details.get('.error').text()).toBe(message.trim())
    expect(wrapper.get('.stages').text()).not.toContain('quote must occur')
    wrapper.unmount()
  })

  it('shows every artifact while a workflow is incomplete, including all provenance and candidates', async () => {
    const state = {
      ...workflow('failed'),
      artifacts: ['survey/survey.json', 'collection/bids/sub-001/file.vhdr',
        'preprocessing/runs/job/r0000/a1/provenance.json', 'preprocessing/runs/job/r0001/a1/events.json',
        'delivery/provenance/S001R04/delta.json', 'process/index.json'].map(name => ({name, bytes: 2048, sha256: 'abc'})),
    }
    request.mockImplementation(async (path: string) => {
      if (path.endsWith('/sources')) return {allowed_roots: []}
      if (path === '/api/workflows') return [state]
      return state
    })
    const wrapper = mount(WorkflowsView)
    await flushPromises()
    const links = wrapper.findAll('.file-group a')
    expect(links).toHaveLength(state.artifacts.length)
    expect(links.map(link => link.text()).sort()).toEqual(state.artifacts.map(a => a.name).sort())
    expect(wrapper.get('.files-panel').text()).toContain('6 个文件')
    expect(wrapper.findAll('.file-group').every(group => group.attributes('open') !== undefined)).toBe(true)
    wrapper.unmount()
  })

  it('collapses repeated files and preserves the expanded group when polling adds another record', async () => {
    vi.useFakeTimers()
    const file = (run: string) => ({
      name: `collection/bids/sub-001/eeg/sub-001_task-mi_run-${run}_eeg.eeg`, bytes: 1024, sha256: null,
    })
    let state = {...workflow('running'), artifacts: [file('04'), file('08')]}
    request.mockImplementation(async (path: string) => {
      if (path.endsWith('/sources')) return {allowed_roots: []}
      if (path === '/api/workflows') return [state]
      return state
    })
    const wrapper = mount(WorkflowsView)
    try {
      await flushPromises()
      const group = wrapper.get('.file-family')
      expect(group.attributes('open')).toBeUndefined()
      expect(group.get('summary').text()).toContain('2 个文件')
      await group.get('summary').trigger('click')
      expect(group.attributes('open')).toBeDefined()
      state = {...state, artifacts: [...state.artifacts, file('12')]}
      await vi.advanceTimersByTimeAsync(2000)
      await flushPromises()
      expect(wrapper.get('.file-family').attributes('open')).toBeDefined()
      expect(wrapper.findAll('.file-family a')).toHaveLength(3)
      expect(wrapper.get('.file-family summary').text()).toContain('3 个文件')
      await wrapper.get('.file-family summary').trigger('click')
      expect(wrapper.get('.file-family').attributes('open')).toBeUndefined()
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })
})
