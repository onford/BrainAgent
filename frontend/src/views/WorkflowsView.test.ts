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
    id: 'abc123', schema_version: '1', engine: 'diagnostic-policy-search-v2', status, created_at: '2026-09-08T08:00:00Z', updated_at: '2026-09-08T08:00:00Z',
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

  it.each([
    { schema_version: '0', engine: 'diagnostic-policy-search-v2' },
    { schema_version: '1', engine: 'cognitive-workflow' },
    { schema_version: undefined, engine: undefined },
  ])('keeps historical records neutral and read-only for %j', async version => {
    vi.useFakeTimers()
    const state = { ...workflow('failed'), ...version, outputs: {
      data_collection: {}, data_delivery: { shape: [90, 64, 321] },
      data_evaluation: { selection_policy: 'random', quality_evaluated: false, score: .99, selected_method_ref: { id: 'saved-method' } },
    }, artifacts: [{ name: 'evaluation/selection.json', bytes: 500, sha256: null }, { name: 'report/report.html', bytes: 500, sha256: null }],
      stages: [{ name: 'data_evaluation', label: '结果选择', status: 'failed' }] }
    request.mockImplementation(async (path: string) => path.endsWith('/sources') ? { allowed_roots: [] } : path === '/api/workflows' ? [state] : state)
    const wrapper = mount(WorkflowsView)
    try {
      await flushPromises()
      expect(wrapper.find('.retry-button').exists()).toBe(false)
      expect(wrapper.find('[aria-label="预算搜索入口"]').exists()).toBe(false)
      expect(wrapper.get('.delivery-panel').text()).toContain('saved-method')
      expect(wrapper.get('.delivery-panel').text()).toContain('方法与分组信息以保存的交付记录为准')
      expect(wrapper.get('.delivery-panel').text()).not.toContain('开发 BA')
      expect(wrapper.get('.files-panel').text()).not.toContain('开发评估')
      expect(wrapper.get('iframe').attributes('src')).toContain('report/report.html?download=false')
      await wrapper.get('.stages button').trigger('click'); await flushPromises()
      expect(wrapper.get('.stage-dialog').text()).toContain('保存的记录')
      expect(wrapper.get('.stage-dialog').text()).not.toContain('CSP')
      expect(wrapper.findAll('button').some(button => button.text().includes('重试未完成步骤'))).toBe(false)
      await vi.advanceTimersByTimeAsync(6000)
      expect(request.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
    } finally { wrapper.unmount(); vi.useRealTimers() }
  })

  it.each([
    { selection_policy: 'random', quality_evaluated: true, evaluation_scope: 'development' },
    { selection_policy: 'development_score', quality_evaluated: false, evaluation_scope: 'development' },
    { selection_policy: 'development_score', quality_evaluated: true, evaluation_scope: undefined },
  ])('does not infer measured evaluation from a numeric score alone: %j', async evaluation => {
    const state = { ...workflow('completed'), outputs: { data_delivery: { shape: [90, 64, 321] }, data_evaluation: { ...evaluation, score: .9 } } }
    request.mockImplementation(async (path: string) => path.endsWith('/sources') ? { allowed_roots: [] } : path === '/api/workflows' ? [state] : state)
    const wrapper = mount(WorkflowsView)
    await flushPromises()
    expect(wrapper.get('.delivery-panel').text()).not.toContain('开发 BA')
    expect(wrapper.get('.delivery-panel').text()).not.toContain('方法按开发评估分数选择')
    wrapper.unmount()
  })

  it('prefers original artifact URLs and descriptions, preserving query parameters and safe downloads', async () => {
    const state = { ...workflow('completed'), artifacts: [
      { name: 'preprocessing/search/report.html', bytes: null, sha256: null, url: '/api/searches/search-1/artifacts/report.html?v=abc&download=false#details', description: '实测预测核验' },
      { name: 'preprocessing/search/unsafe.html', bytes: 0, sha256: null, url: 'javascript:alert(1)' },
      { name: 'report/report.html', bytes: 500, sha256: null, url: 'https://reports.example.test/report.html?v=saved&download=true#summary', description: '保存的流程报告' },
    ] }
    request.mockImplementation(async (path: string) => path.endsWith('/sources') ? { allowed_roots: [] } : path === '/api/workflows' ? [state] : state)
    const wrapper = mount(WorkflowsView)
    await flushPromises()
    const link = wrapper.findAll('.file-row a').find(a => a.text() === 'preprocessing/search/report.html')!
    expect(link.attributes('href')).toBe('/api/searches/search-1/artifacts/report.html?v=abc&download=true#details')
    expect(wrapper.get('iframe').attributes('src')).toBe('https://reports.example.test/report.html?v=saved&download=false#summary')
    expect(wrapper.findAll('.file-row a').some(a => a.text().includes('unsafe'))).toBe(false)
    await wrapper.get('input[aria-label="查找文件"]').setValue('实测预测核验')
    expect(wrapper.findAll('.file-row')).toHaveLength(1)
    expect(wrapper.get('.file-row').text()).toContain('大小未知')
    wrapper.unmount()
  })

  it('updates the linked search summary with workflow polling while retaining the existing search link', async () => {
    vi.useFakeTimers()
    const summary = { id: 'search-1', status: 'running', message: '正在核验预测', selected_candidate_id: null as string | null,
      usage: { candidates: 2, proposals: 3, evidence_reads: 1, elapsed_seconds: 12.5 },
      budget: { max_candidates: 6, max_proposals: 8, max_evidence_reads: 2, max_seconds: 3600, max_memory_mb: null, max_disk_mb: null } }
    let state = { ...workflow('running'), search_id: 'search-1', search_summary: summary }
    request.mockImplementation(async (path: string) => path.endsWith('/sources') ? { allowed_roots: [] } : path === '/api/workflows' ? [state] : state)
    const wrapper = mount(WorkflowsView)
    try {
      await flushPromises()
      const panel = wrapper.get('[aria-label="关联搜索进度"]')
      expect(panel.text()).toContain('执行中 · 正在核验预测')
      expect(panel.text()).toContain('候选 2 / 6')
      expect(panel.text()).toContain('提议 3 / 8')
      expect(panel.text()).toContain('证据读取 1 / 2')
      expect(panel.text()).toContain('耗时 12.5 / 3,600 秒')
      state = { ...state, search_summary: { ...summary, status: 'completed', message: '评估完成', selected_candidate_id: 'chosen-1', usage: { ...summary.usage, candidates: 4 } } }
      await vi.advanceTimersByTimeAsync(2000); await flushPromises()
      expect(panel.text()).toContain('已完成 · 评估完成')
      expect(panel.text()).toContain('候选 4 / 6')
      expect(panel.text()).toContain('所选候选 chosen-1')
      expect(request.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
    } finally { wrapper.unmount(); vi.useRealTimers() }
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
      source_root: 'E:/dataset/eeg/EEGMMIDB', seed: 42,
    })
    expect(JSON.parse(submitted![1].body)).not.toHaveProperty('max_subjects')
    expect(JSON.parse(submitted![1].body)).not.toHaveProperty('runs')
    expect(wrapper.find('input[aria-label="被试数量"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('6 / 6 个模块已完成')
    expect(wrapper.text()).toContain('训练数据已就绪')
    expect(wrapper.get('iframe').attributes('src')).toContain('report/report.html?download=false')
    expect(wrapper.get('a.primary').attributes('href')).toContain('training-data.zip')
    expect(wrapper.text()).toContain('方法与分组信息以保存的交付记录为准')
    expect(wrapper.text()).not.toContain('随机选择')
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
