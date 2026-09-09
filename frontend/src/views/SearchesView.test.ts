import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import SearchesView from './SearchesView.vue'
import WorkflowsView from './WorkflowsView.vue'
import { searchArtifactUrl } from '../api/searches'
import type { SearchState } from '../types/search'

const { apiRequest } = vi.hoisted(() => ({ apiRequest: vi.fn() }))
vi.mock('../api/client', () => ({ apiRequest, apiUrl: (path: string) => `https://api.example.test${path}` }))

function state(overrides: Partial<SearchState> = {}): SearchState {
  return {
    schema_version: '1', id: 'search-1', workflow_id: 'source-1', status: 'completed',
    created_at: '2026-09-09T08:00:00Z', updated_at: '2026-09-09T08:10:00Z',
    request: { workflow_id: 'source-1', strategy: 'adaptive', seed: 42,
      budget: { max_candidates: 6, max_proposals: 8, max_evidence_reads: 2, max_seconds: 3600, max_memory_mb: null, max_disk_mb: null } },
    usage: { candidates: 2, proposals: 3, evidence_reads: 1, llm_calls: 4, elapsed_seconds: 125.5, retries: 0 },
    phase: '评估完成', message: '已完成开发面板比较', panel: '训练 2 人，开发 2 人',
    candidates: [
      { id: 'c1', title: '宽频平均参考', status: 'completed', job_id: 'job-1', parameters: { l_freq: 1, h_freq: 40, reference: 'average' },
        receipt: { status: 'completed', macro_ba: .725, mean_delta: .025,
          coverage: { original: 110, eligible: 100, predicted: 98, missing: 2 },
          diagnostics: { floor_fraction: .1, converged: true }, subjects: { S003: { ba: .75, delta: .05, eligible_trials: 50 }, S004: { ba: .7, delta: 0 } } } },
      { id: 'c2', title: '窄频原始参考', status: 'failed', parameters: { l_freq: 8, h_freq: 30, reference: 'original' }, error: '该候选评估失败' },
    ],
    selected_candidate_id: 'c1', stop_reason: '达到候选预算',
    actions: [{ index: 0, action: '评估候选', status: 'completed', reason: '比较参考方式', cost_seconds: 25,
      base_candidate_id: 'baseline', candidate_id: 'c1', expected_result: '开发 BA 改善', decision_branches: { improved: '继续搜索', otherwise: '保留基线' } },
    { index: 1, action: '提出候选', status: 'failed', reason: '探索窄频', cost_seconds: 2, candidate_id: 'c2', error: '参数不可行' }],
    artifacts: [{ name: 'report/report.html', description: '搜索评估报告', url: '/api/searches/search-1/artifacts/report/report.html?download=true' }, { name: 'records/候选 清单.json', description: '完整候选记录' }],
    ...overrides,
  }
}

const wrappers: VueWrapper[] = []
async function open(path: string, component = SearchesView) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/searches', component: SearchesView }, { path: '/workflows', component: WorkflowsView }, { path: '/', component: { template: '<div />' } },
  ] })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(component, { global: { plugins: [router] } })
  wrappers.push(wrapper)
  await flushPromises()
  return { wrapper, router }
}
function button(wrapper: VueWrapper, text: string) {
  const result = wrapper.findAll('button').find(item => item.text().includes(text))
  if (!result) throw new Error(`Missing button: ${text}`)
  return result
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

describe('SearchesView', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    apiRequest.mockReset().mockImplementation(async (path: string) => path === '/api/searches' ? [] : state())
  })
  afterEach(() => {
    wrappers.splice(0).forEach(wrapper => wrapper.unmount())
    vi.useRealTimers()
  })

  it('creates from the workflow query with the exact default budget and opens the returned state', async () => {
    apiRequest.mockImplementation(async (path: string, init?: RequestInit) => path === '/api/searches' && !init ? [] : state({ status: 'preparing' }))
    const { wrapper, router } = await open('/searches?workflow=source-1')
    expect((wrapper.get('input[aria-label="来源流程 ID"]').element as HTMLInputElement).value).toBe('source-1')
    expect(wrapper.find('select').exists()).toBe(false)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const post = apiRequest.mock.calls.find(([, init]) => init?.method === 'POST')!
    expect(post[0]).toBe('/api/searches')
    expect(JSON.parse(post[1].body)).toEqual({ workflow_id: 'source-1', strategy: 'adaptive', seed: 42,
      budget: { max_candidates: 6, max_proposals: 8, max_evidence_reads: 2, max_seconds: 3600, max_memory_mb: null, max_disk_mb: null } })
    expect(router.currentRoute.value.query).toEqual({ id: 'search-1' })
    expect(wrapper.get('h1').text()).toContain('准备中')
    expect(wrapper.get('nav[aria-label="选择搜索"]').text()).toContain('search-1')
    expect(wrapper.text()).toContain('开发面板选择，不代表独立泛化或神经信号质量')
    expect(apiRequest).not.toHaveBeenCalledWith('/api/searches/search-1')
  })

  it.each(['random', 'exhaustive'])('submits edited budgets and optional subject IDs with strategy %s', async selectedStrategy => {
    apiRequest.mockImplementation(async (_path: string, init?: RequestInit) => init ? state() : [])
    const { wrapper } = await open('/searches?workflow=source-1')
    await wrapper.get(`input[value="${selectedStrategy}"]`).setValue(true)
    for (const [name, value] of [['候选数', '9'], ['提议数', '12'], ['证据读取数', '0'], ['时限（秒）', '900'], ['内存上限（MB）', '2048'], ['磁盘上限（MB）', '4096'], ['随机种子', '7'], ['训练被试', 'S001, S002 S001'], ['开发被试', 'S003，S004']]) {
      await wrapper.get(`input[aria-label="${name}"]`).setValue(value)
    }
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const post = apiRequest.mock.calls.find(([, init]) => init?.method === 'POST')!
    expect(JSON.parse(post[1].body)).toEqual({ workflow_id: 'source-1', strategy: selectedStrategy, seed: 7,
      budget: { max_candidates: 9, max_proposals: 12, max_evidence_reads: 0, max_seconds: 900, max_memory_mb: 2048, max_disk_mb: 4096 },
      train_subjects: ['S001', 'S002'], development_subjects: ['S003', 'S004'] })
  })

  it('rejects invalid budgets and overlapping subject panels before posting', async () => {
    const { wrapper } = await open('/searches?workflow=source-1')
    await wrapper.get('input[aria-label="候选数"]').setValue(0)
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[role="alert"]').text()).toContain('候选数需为不小于 1 的整数')
    await wrapper.get('input[aria-label="候选数"]').setValue(6)
    await wrapper.get('input[aria-label="训练被试"]').setValue('S001')
    await wrapper.get('input[aria-label="开发被试"]').setValue('S001')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[role="alert"]').text()).toContain('不能重叠')
    expect(apiRequest.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  })

  it('preserves the form after a creation failure and prevents duplicate submissions', async () => {
    const pending = deferred<SearchState>()
    apiRequest.mockRejectedValueOnce(new Error('列表不可用'))
    const { wrapper } = await open('/searches?workflow=source-1')
    apiRequest.mockRejectedValueOnce(new Error('来源流程尚未完成数据接入'))
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(wrapper.text()).toContain('来源流程尚未完成数据接入')
    expect(wrapper.find('form').exists()).toBe(true)
    apiRequest.mockReturnValueOnce(pending.promise)
    await wrapper.get('form').trigger('submit')
    await wrapper.get('form').trigger('submit')
    expect(apiRequest.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(2)
    expect(button(wrapper, '正在创建').attributes('disabled')).toBeDefined()
    pending.resolve(state()); await flushPromises()
    expect(wrapper.find('form').exists()).toBe(false)
  })

  it('opens a deep link, presents backend selection and budgets, and separates subjects, rounds and artifacts', async () => {
    const { wrapper } = await open('/searches?id=search-1')
    expect(apiRequest).toHaveBeenCalledWith('/api/searches/search-1')
    const meters = wrapper.findAll('[role="progressbar"]')
    expect(meters.map(meter => meter.attributes('aria-valuetext'))).toEqual(['2 / 6', '3 / 8', '1 / 2', '125.5 / 3,600'])
    expect(wrapper.text()).toContain('内存 自动')
    expect(wrapper.text()).toContain('LLM 调用 4')
    expect(wrapper.text()).toContain('停止原因：达到候选预算')
    expect(wrapper.text()).toContain('训练 2 人，开发 2 人')
    expect(wrapper.get('tr.selected').text()).toContain('72.5%')
    expect(wrapper.get('tr.selected').text()).toContain('+2.5 pp')
    expect(wrapper.get('tr.selected').text()).toContain('98 / 100')
    expect(wrapper.get('tr.selected').text()).toContain('后端选中')
    expect(wrapper.findAll('tbody tr')[1]!.text()).toContain('—')
    await wrapper.get('button[aria-label="查看候选 c1 的开发被试"]').trigger('click')
    expect(wrapper.get('section[aria-label="开发被试明细"]').text()).toContain('S003')
    expect(wrapper.text()).toContain('下限比例 10.0%')
    expect(wrapper.text()).toContain('收敛 是')
    expect(wrapper.text()).toContain('0.0 pp')
    await button(wrapper, '窄频原始参考').trigger('click')
    expect(wrapper.text()).toContain('该候选暂无开发被试回执')
    expect(wrapper.text()).toContain('后端选中 c1')
    await button(wrapper, '轮次时间线').trigger('click')
    expect(wrapper.get('.timeline').text()).toContain('比较参考方式')
    expect(wrapper.get('.timeline').text()).toContain('开发 BA 改善')
    expect(wrapper.get('.timeline').text()).toContain('继续搜索')
    expect(wrapper.get('.timeline').text()).toContain('参数不可行')
    await button(wrapper, '报告 / 文件').trigger('click')
    expect(wrapper.get('iframe').attributes('src')).toBe('https://api.example.test/api/searches/search-1/artifacts/report/report.html?download=false')
    expect(wrapper.get('iframe').attributes('sandbox')).not.toContain('allow-scripts')
    expect(wrapper.findAll('.artifact-list a').map(a => a.attributes('href'))).toEqual([
      'https://api.example.test/api/searches/search-1/artifacts/report/report.html?download=true',
      `https://api.example.test/api/searches/search-1/artifacts/records/${encodeURIComponent('候选 清单.json')}?download=true`,
    ])
    expect(apiRequest.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  })

  it('stops an active run then retries using the returned state and resumes polling', async () => {
    let latest = state({ status: 'running' })
    apiRequest.mockImplementation(async (path: string) => {
      if (path === '/api/searches') return [latest]
      if (path.endsWith('/cancel')) latest = state({ status: 'cancelled', stop_reason: '用户停止' })
      if (path.endsWith('/retry')) latest = state({ status: 'preparing', stop_reason: null, usage: { retries: 1 } })
      return latest
    })
    const { wrapper } = await open('/searches?id=search-1')
    await button(wrapper, '停止搜索').trigger('click'); await flushPromises()
    expect(apiRequest).toHaveBeenCalledWith('/api/searches/search-1/cancel', { method: 'POST' })
    expect(wrapper.get('h1').text()).toContain('已取消')
    expect(wrapper.text()).toContain('用户停止')
    const calls = apiRequest.mock.calls.length
    await vi.advanceTimersByTimeAsync(6000)
    expect(apiRequest).toHaveBeenCalledTimes(calls)
    await button(wrapper, '重试搜索').trigger('click'); await flushPromises()
    expect(apiRequest).toHaveBeenCalledWith('/api/searches/search-1/retry', { method: 'POST' })
    expect(wrapper.get('h1').text()).toContain('准备中')
    expect(wrapper.text()).toContain('重试 1')
    latest = state({ status: 'completed' })
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(wrapper.get('h1').text()).toContain('已完成')
    const completedCalls = apiRequest.mock.calls.length
    await vi.advanceTimersByTimeAsync(6000)
    expect(apiRequest).toHaveBeenCalledTimes(completedCalls)
  })

  it.each(['failed', 'interrupted', 'cancelled'] as const)('allows retry for a %s run and displays operation errors', async status => {
    apiRequest.mockImplementation(async (path: string) => {
      if (path === '/api/searches') return []
      if (path.endsWith('/retry')) throw new Error('重试暂不可用')
      return state({ status, error: status === 'failed' ? '磁盘预算不足' : null })
    })
    const { wrapper } = await open('/searches?id=search-1')
    await button(wrapper, '重试搜索').trigger('click'); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('重试暂不可用')
    expect(button(wrapper, '重试搜索').attributes('disabled')).toBeUndefined()
    if (status === 'failed') expect(wrapper.text()).toContain('磁盘预算不足')
  })

  it('handles partial states without treating missing metrics as zero and shows structured panel data', async () => {
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : state({ usage: undefined, candidates: undefined, actions: undefined, artifacts: undefined, selected_candidate_id: null, panel: { train_subjects: ['S001'], development_subjects: ['S003'] }, budget: { ...state().request.budget, max_evidence_reads: 0, max_memory_mb: 2048, max_disk_mb: 4096 } }))
    const { wrapper } = await open('/searches?id=search-1')
    expect(wrapper.text()).toContain('尚无候选')
    expect(wrapper.text()).toContain('尚未选择')
    expect(wrapper.text()).toContain('内存 2,048 MB')
    expect(wrapper.text()).toContain('磁盘 4,096 MB')
    expect(wrapper.get('.panel-summary details').text()).toContain('S003')
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBeUndefined()
    expect(wrapper.findAll('[role="progressbar"]')[2]!.attributes('aria-valuetext')).toBe('— / 0')
    expect(wrapper.html()).not.toContain('NaN')
    await button(wrapper, '轮次时间线').trigger('click')
    expect(wrapper.text()).toContain('尚无轮次记录')
    await button(wrapper, '开发被试').trigger('click')
    expect(wrapper.text()).toContain('候选生成后可查看开发被试')
    await button(wrapper, '报告 / 文件').trigger('click')
    expect(wrapper.text()).toContain('尚无报告或文件')
  })

  it('keeps detail loading independent from list failures and reconnects after a detail failure', async () => {
    apiRequest.mockRejectedValue(new Error('连接中断'))
    const { wrapper } = await open('/searches?id=search-1')
    expect(wrapper.text()).toContain('连接中断')
    apiRequest.mockResolvedValue(state())
    await button(wrapper, '重新连接').trigger('click'); await flushPromises()
    expect(wrapper.get('h1').text()).toContain('已完成')
    expect(wrapper.get('.sidebar').text()).toContain('连接中断')
    apiRequest.mockResolvedValue([state()])
    await wrapper.get('button[aria-label="刷新搜索列表"]').trigger('click'); await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('recovers from polling errors, then stops polling when unmounted', async () => {
    const { wrapper } = await (async () => {
      apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : state({ status: 'running' }))
      return open('/searches?id=search-1')
    })()
    apiRequest.mockRejectedValueOnce(new Error('临时离线'))
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('临时离线')
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    wrappers.splice(wrappers.indexOf(wrapper), 1); wrapper.unmount()
    const calls = apiRequest.mock.calls.length
    await vi.advanceTimersByTimeAsync(6000)
    expect(apiRequest).toHaveBeenCalledTimes(calls)
  })

  it('ignores an old poll after navigation and reacts to workflow query changes', async () => {
    const oldPoll = deferred<SearchState>()
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [state(), state({ id: 'search-2' })] : state({ status: 'running' }))
    const { wrapper, router } = await open('/searches?id=search-1')
    apiRequest.mockReturnValueOnce(oldPoll.promise)
    await vi.advanceTimersByTimeAsync(2000)
    apiRequest.mockResolvedValue(state({ id: 'search-2', status: 'completed', message: '第二条记录' }))
    await router.push('/searches?id=search-2'); await flushPromises()
    oldPoll.resolve(state({ status: 'running', message: '过期记录' })); await flushPromises()
    expect(wrapper.get('.page-heading').text()).toContain('search-2')
    expect(wrapper.text()).toContain('第二条记录')
    expect(wrapper.text()).not.toContain('过期记录')
    await router.push('/searches?workflow=source-2'); await flushPromises()
    expect((wrapper.get('input[aria-label="来源流程 ID"]').element as HTMLInputElement).value).toBe('source-2')
    expect(wrapper.find('section[aria-label="进度与预算"]').exists()).toBe(false)
  })

  it('does not let an in-flight poll undo cancellation', async () => {
    const oldPoll = deferred<SearchState>()
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : state({ status: 'running' }))
    const { wrapper } = await open('/searches?id=search-1')
    apiRequest.mockReturnValueOnce(oldPoll.promise)
    await vi.advanceTimersByTimeAsync(2000)
    apiRequest.mockResolvedValueOnce(state({ status: 'cancelled' }))
    await button(wrapper, '停止搜索').trigger('click'); await flushPromises()
    oldPoll.resolve(state({ status: 'running' })); await flushPromises()
    expect(wrapper.get('h1').text()).toContain('已取消')
  })

  it('accepts backend subject maps and panel summaries and hides successful model-decision wrappers', async () => {
    const latest = state({ status: 'stopped', stop_reason: 'candidate_budget_exhausted',
      request: { ...state().request, strategy: 'one_shot' },
      panel: { trial_count: 200, eligible_count: 180, train_subjects: ['S001', 'S002'], development_subjects: ['S003'], records: {}, output_contract: { sfreq: 160 }, panel_hash: 'hash' },
      candidates: [{ id: 'c1', status: 'evaluated', receipt: { subjects: { S003: { ba: .75, delta: .03, eligible_trials: 40 } }, coverage: { original: 45, eligible: 40, predicted: 40, missing: 0, train: { original: 80, eligible: 75 }, development: { original: 45, eligible: 40, predicted: 40 } } } }],
      actions: [{ index: 0, action: 'model_decision', status: 'completed', reason: '不重复展示的包装记录', result: { decision: { action: 'propose_candidate' } } },
        { index: 1, action: 'propose_candidate', status: 'completed', reason: '开发评估后提出候选', result: { candidate_id: 'c1' } },
        { index: 2, action: 'model_decision', status: 'failed', error: 'LLM 超时' }],
    })
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : latest)
    const { wrapper } = await open('/searches?id=search-1')
    expect(wrapper.text()).toContain('一次性 LLM 对照')
    expect(wrapper.text()).toContain('训练被试 2')
    expect(wrapper.text()).toContain('开发被试 1')
    expect(wrapper.text()).toContain('原始 trial 200')
    expect(wrapper.text()).toContain('候选预算耗尽')
    expect(wrapper.findAll('button').some(item => item.text() === '重试搜索')).toBe(false)
    await button(wrapper, '开发被试').trigger('click')
    expect(wrapper.get('tbody').text()).toContain('S003')
    expect(wrapper.get('tbody').text()).toContain('75.0%')
    expect(wrapper.get('tbody').text()).toContain('+3.0 pp')
    expect(wrapper.get('section[aria-label="开发被试明细"]').text()).toContain('合格（开发） 40')
    expect(wrapper.text()).toContain('训练 / 开发覆盖明细')
    await button(wrapper, '轮次时间线').trigger('click')
    expect(wrapper.findAll('.timeline li')).toHaveLength(2)
    expect(wrapper.get('.timeline').text()).not.toContain('不重复展示的包装记录')
    expect(wrapper.get('.timeline').text()).toContain('开发评估后提出候选')
    expect(wrapper.get('.timeline').text()).toContain('LLM 超时')
  })

  it('enforces paired subjects and backend resource limits while allowing zero proposals', async () => {
    const { wrapper } = await open('/searches?workflow=source-1')
    await wrapper.get('input[aria-label="训练被试"]').setValue('S001')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[role="alert"]').text()).toContain('须同时指定')
    await wrapper.get('input[aria-label="训练被试"]').setValue('')
    await wrapper.get('input[aria-label="内存上限（MB）"]').setValue(63)
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[role="alert"]').text()).toContain('至少 64 MB')
    await wrapper.get('input[aria-label="内存上限（MB）"]').setValue('')
    await wrapper.get('input[aria-label="候选数"]').setValue(33)
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[role="alert"]').text()).toContain('不能超过 32')
    await wrapper.get('input[aria-label="候选数"]').setValue(6)
    await wrapper.get('input[aria-label="提议数"]').setValue(0)
    apiRequest.mockResolvedValueOnce(state())
    await wrapper.get('form').trigger('submit'); await flushPromises()
    const post = apiRequest.mock.calls.find(([, init]) => init?.method === 'POST')!
    expect(JSON.parse(post[1].body).budget.max_proposals).toBe(0)
  })

  it('still renders legacy subject arrays without changing the official dictionary contract', async () => {
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : {
      ...state(), candidates: [{ id: 'c1', status: 'evaluated', receipt: { subjects: [{ subject: 'legacy-S001', ba: 0, delta: -.02 }] } }],
    })
    const { wrapper } = await open('/searches?id=search-1')
    await button(wrapper, '开发被试').trigger('click')
    expect(wrapper.get('tbody').text()).toContain('legacy-S001')
    expect(wrapper.get('tbody').text()).toContain('0.0%')
    expect(wrapper.get('tbody').text()).toContain('-2.0 pp')
  })
})

describe('search entry and artifact links', () => {
  beforeEach(() => {
    apiRequest.mockReset()
    HTMLDialogElement.prototype.showModal = function() { this.setAttribute('open', '') }
    HTMLDialogElement.prototype.close = function() { this.removeAttribute('open') }
  })
  afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

  it.each([true, false])('shows the workflow entry only when data_collection exists (%s), preserving random selection copy', async collected => {
    const workflow = { id: 'source-1', status: 'completed', created_at: '2026-09-09T08:00:00Z', updated_at: '2026-09-09T08:00:00Z',
      request: { source_root: 'E:/data' }, stages: [], events: [], artifacts: [], error: null,
      outputs: { data_delivery: { shape: [90, 64, 321] }, ...(collected ? { data_collection: { path: 'collection' } } : {}) } }
    apiRequest.mockImplementation(async (path: string) => path.endsWith('/sources') ? { allowed_roots: [] } : path === '/api/workflows' ? [workflow] : workflow)
    const { wrapper } = await open('/workflows?id=source-1', WorkflowsView)
    const entry = wrapper.find('[aria-label="预算搜索入口"]')
    expect(entry.exists()).toBe(collected)
    if (collected) {
      expect(entry.get('a').attributes('href')).toBe('/searches?workflow=source-1')
      expect(entry.get('a').text()).toContain('预算预处理搜索')
    }
    expect(wrapper.text()).toContain('候选方法随机选择，本轮未进行质量排名')
  })

  it('preserves artifact query parameters, handles API bases, and excludes executable links', () => {
    expect(searchArtifactUrl('id/1', { name: 'report.html', url: 'https://files.test/report.html?v=3&download=false#page=2' })).toBe('https://files.test/report.html?v=3&download=true#page=2')
    expect(searchArtifactUrl('id/1', { name: '子目录/文件.json' })).toContain(`/api/searches/id%2F1/artifacts/${encodeURIComponent('子目录')}/${encodeURIComponent('文件.json')}?download=true`)
    expect(searchArtifactUrl('id/1', { name: 'bad.html', url: 'javascript:alert(1)' })).toBe('')
  })
})
