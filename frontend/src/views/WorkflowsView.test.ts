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
    request: { source_root: 'E:/dataset/eeg/EEGMMIDB' }, error: null,
    artifacts: status === 'completed' ? [{name:'report/report.html',bytes:500,sha256:'abc'}] : [], events: [],
    stages: ['数据调研', '数据接入', '数据预处理', '结果选择', '数据报告', '数据交付'].map((label, i) => ({
      name: `stage${i}`, label, status: status === 'completed' ? 'completed' : i === 4 ? 'failed' : 'pending',
    })),
    outputs: status === 'completed' ? { data_delivery: { shape: [90, 64, 321] } } : {},
  }
}

describe('WorkflowsView', () => {
  beforeEach(() => {
    request.mockReset(); replace.mockReset().mockResolvedValue(undefined)
    HTMLDialogElement.prototype.showModal = function() { this.setAttribute('open','') }
    HTMLDialogElement.prototype.close = function() { this.removeAttribute('open') }
  })

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
    const choices = wrapper.findAll('nav[aria-label="选择报告"] button')
    expect(choices).toHaveLength(2)
    expect(choices[0]!.text()).toContain('数据集基本信息')
    expect(wrapper.get('iframe').attributes('src')).toContain('dataset-basic.html?download=false')
    await choices[1]!.trigger('click')
    expect(wrapper.get('iframe').attributes('src')).toContain('literature-usage.html?download=false')
    await wrapper.get('.reader-actions button').trigger('click')
    expect(wrapper.get('main').classes()).toContain('focused')
    document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))
    await flushPromises()
    expect(wrapper.get('main').classes()).not.toContain('focused')
    wrapper.unmount()
  })

  it('opens long errors in a stage dialog without expanding the progress layout', async () => {
    const state = workflow('failed')
    const message = 'quote must occur verbatim in its retrieved source; '.repeat(30)
    Object.assign(state.stages[4], { error: message })
    request.mockImplementation(async (path: string) => path.endsWith('/sources') ? { allowed_roots: [] } : path === '/api/workflows' ? [state] : state)
    const wrapper = mount(WorkflowsView)
    await flushPromises()
    expect(wrapper.get('.stage-dialog').attributes('open')).toBeUndefined()
    await wrapper.findAll('.stages button')[4]!.trigger('click')
    await flushPromises()
    expect(wrapper.get('.stage-dialog').attributes('open')).toBeDefined()
    expect(wrapper.get('.stage-dialog h2').text()).toBe('数据报告')
    expect(wrapper.get('.stage-error pre').text()).toBe(message.trim())
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
    await wrapper.findAll('.workspace-tabs button')[1]!.trigger('click')
    await wrapper.get('input[aria-label="查找文件"]').setValue('事件')
    expect(wrapper.findAll('.file-group a')).toHaveLength(2)
    await wrapper.get('input[aria-label="查找文件"]').setValue('')
    const filter = wrapper.findAll('.files-panel nav button').find(b=>b.text().startsWith('数据调研'))!
    await filter.trigger('click')
    expect(wrapper.findAll('.file-group a')).toHaveLength(1)
    expect(wrapper.get('.file-group a').text()).toBe('survey/survey.json')
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
