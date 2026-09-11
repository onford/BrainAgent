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
    schema_version: '1', protocol: { version: '2', evaluator: 'csp-shrinkage-lda-v2' }, id: 'search-1', workflow_id: 'source-1', status: 'completed',
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

  it('opens the decision overview first and navigates to a candidate evidence view', async () => {
    const { wrapper } = await open('/searches?id=search-1')
    expect(wrapper.get('[aria-label="决策概览"]').text()).toContain('这次预处理是怎样决定的')
    await button(wrapper, '查看处理与参数').trigger('click')
    expect(wrapper.findComponent({ name: 'SearchAssessment' }).props('initialAxis')).toBe('parameters')
    expect(wrapper.findComponent({ name: 'SearchAssessment' }).props('candidateId')).toBe('c1')
  })

  it('opens the exact evidence destination from a workflow link', async () => {
    const { wrapper } = await open('/searches?id=search-1&view=assessment&axis=quality')
    expect(wrapper.findComponent({ name: 'SearchAssessment' }).props('initialAxis')).toBe('quality')
    expect(wrapper.find('[aria-label="决策概览"]').exists()).toBe(false)
  })

  it('creates from the workflow query with the exact default budget and opens the returned state', async () => {
    apiRequest.mockImplementation(async (path: string, init?: RequestInit) => path === '/api/searches' && !init ? [] : state({ status: 'preparing' }))
    const { wrapper, router } = await open('/searches?workflow=source-1')
    expect((wrapper.get('input[aria-label="来源流程 ID"]').element as HTMLInputElement).value).toBe('source-1')
    expect(wrapper.find('select').exists()).toBe(false)
    expect(wrapper.findAll('input[name="strategy"]').map(input => input.attributes('value'))).toEqual(['adaptive', 'random', 'exhaustive', 'one_shot'])
    expect((wrapper.get('input[value="adaptive"]').element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.get('fieldset').text()).toContain('一次性提案对照')
    expect(wrapper.get('[aria-label="默认评估方式"]').text()).toContain('最多 5 折')
    expect(wrapper.get('[aria-label="默认评估方式"]').text()).toContain('EEGNet 固定种子 17、42、2026')
    expect(wrapper.get('[aria-label="默认评估方式"]').text()).not.toContain('FBCSP')
    expect(wrapper.get('[aria-label="默认评估方式"]').text()).toContain('全部被试各作为开发被试一次')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const post = apiRequest.mock.calls.find(([, init]) => init?.method === 'POST')!
    expect(post[0]).toBe('/api/searches')
    expect(JSON.parse(post[1].body)).toEqual({ workflow_id: 'source-1', strategy: 'adaptive', seed: 42,
      budget: { max_candidates: 48, max_proposals: 128, max_evidence_reads: 32, max_seconds: 86400, max_memory_mb: null, max_disk_mb: null } })
    expect(router.currentRoute.value.query).toEqual({ id: 'search-1' })
    expect(wrapper.get('h1').text()).toContain('准备中')
    expect(wrapper.get('nav[aria-label="选择搜索"]').text()).toContain('search-1')
    expect(wrapper.text()).toContain('开发评估用于策略选择，不是独立测试结果')
    expect(apiRequest.mock.calls.some(([path]) => path.startsWith('/api/searches/search-1?'))).toBe(false)
  })

  it.each(['random', 'exhaustive', 'one_shot'])('submits edited budgets and optional subject IDs with strategy %s', async selectedStrategy => {
    apiRequest.mockImplementation(async (_path: string, init?: RequestInit) => init ? state() : [])
    const { wrapper } = await open('/searches?workflow=source-1')
    await wrapper.get(`input[value="${selectedStrategy}"]`).setValue(true)
    if (selectedStrategy === 'random') expect(wrapper.get('.strategy-hint').text()).toContain('最终仍按开发主评分选择')
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

  it('creates a one-shot comparison with unchanged default budgets and displays the returned strategy', async () => {
    apiRequest.mockImplementation(async (_path: string, init?: RequestInit) => init ? state({ request: JSON.parse(init.body as string) }) : [])
    const { wrapper, router } = await open('/searches?workflow=source-1')
    await wrapper.get('input[value="one_shot"]').setValue(true)
    expect(wrapper.get('.strategy-hint').text()).toContain('不根据中途评价调整提案')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    const post = apiRequest.mock.calls.find(([, init]) => init?.method === 'POST')!
    expect(JSON.parse(post[1].body)).toEqual({ ...state().request, strategy: 'one_shot', budget: { max_candidates: 48, max_proposals: 128, max_evidence_reads: 32, max_seconds: 86400, max_memory_mb: null, max_disk_mb: null } })
    expect(router.currentRoute.value.query).toEqual({ id: 'search-1' })
    expect(wrapper.get('.page-heading').text()).toContain('一次性提案对照')
  })

  it('accepts fractional positive seconds and rejects zero, negative and empty time budgets', async () => {
    const { wrapper } = await open('/searches?workflow=source-1')
    const seconds = wrapper.get('input[aria-label="时限（秒）"]')
    expect(seconds.attributes('step')).toBe('any')
    for (const value of ['0', '-1', '']) {
      await seconds.setValue(value)
      await wrapper.get('form').trigger('submit')
      expect(wrapper.get('[role="alert"]').text()).toContain('时限（秒）需为大于 0 的数值')
    }
    expect(apiRequest.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
    apiRequest.mockResolvedValueOnce(state())
    await seconds.setValue('0.25')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    const post = apiRequest.mock.calls.find(([, init]) => init?.method === 'POST')!
    expect(JSON.parse(post[1].body).budget.max_seconds).toBe(.25)
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
    expect(apiRequest).toHaveBeenCalledWith('/api/searches/search-1?include_artifacts=true')
    const meters = wrapper.findAll('[role="progressbar"]')
    expect(meters.map(meter => meter.attributes('aria-valuetext'))).toEqual(['2 / 6', '3 / 8', '1 / 2', '125.5 / 3,600'])
    expect(wrapper.text()).toContain('内存 自动')
    expect(wrapper.text()).toContain('LLM 调用 4')
    expect(wrapper.text()).toContain('停止原因：达到候选预算')
    expect(wrapper.text()).toContain('训练 2 人，开发 2 人')
    await button(wrapper, '候选比较').trigger('click')
    expect(wrapper.get('tr.selected').text()).toContain('72.5%')
    expect(wrapper.get('tr.selected').text()).toContain('+2.5 pp')
    expect(wrapper.get('tr.selected').text()).toContain('98 / 100')
    expect(wrapper.get('tr.selected').text()).toContain('开发评估选中')
    expect(wrapper.findAll('tbody tr')[1]!.text()).toContain('—')
    await wrapper.get('button[aria-label="查看候选 c1 的开发被试"]').trigger('click')
    expect(wrapper.get('section[aria-label="开发被试明细"]').text()).toContain('S003')
    expect(wrapper.text()).toContain('下限比例 10.0%')
    expect(wrapper.text()).toContain('收敛 是')
    expect(wrapper.text()).toContain('0.0 pp')
    await button(wrapper, '窄频原始参考').trigger('click')
    expect(wrapper.text()).toContain('该候选暂无开发被试回执')
    expect(wrapper.text()).toContain('开发评估选中 c1')
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
    expect(wrapper.find('[aria-label="进度与预算"]').exists()).toBe(false)
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

  it('shows actual CV folds without presenting the empty top-level training list as no training', async () => {
    const latest = state({ panel: { evaluation_mode: 'group_cross_validation', train_subjects: [], development_subjects: ['S001', 'S002', 'S003'],
      folds: [
        { id: 'fold-01', train_subjects: ['S002', 'S003'], development_subjects: ['S001'] },
        { id: 'fold-02', train_subjects: ['S001', 'S003'], development_subjects: ['S002'] },
        { id: 'fold-03', train_subjects: ['S001', 'S002'], development_subjects: ['S003'] },
      ] } })
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : latest)
    const { wrapper } = await open('/searches?id=search-1')
    const panel = wrapper.get('[aria-label="评估面板"]')
    expect(panel.text()).toContain('按被试分组交叉验证')
    expect(panel.text()).toContain('3 折')
    expect(panel.text()).toContain('参与交叉验证的被试 3')
    expect(panel.text()).not.toContain('训练被试 0')
    const folds = panel.findAll('tbody tr')
    expect(folds).toHaveLength(3)
    expect(folds[0]!.get('td').text()).toBe('fold-01')
    expect(folds[0]!.findAll('summary').map(summary => summary.text())).toEqual(['2 人', '1 人'])
    expect(wrapper.get('[aria-label="评分与适配含义"]').text()).toContain('CSP 与分类器在每折训练被试上拟合')
    expect(wrapper.text()).toContain('不是独立测试结果')
    expect(wrapper.find('form').exists()).toBe(false)
  })

  it.each([
    { schema_version: '1', protocol: { version: '1', evaluator: 'logvariance-scaler-logistic-v1' } },
    { schema_version: '0', protocol: { version: '2', evaluator: 'csp-shrinkage-lda-v2' } },
    { schema_version: undefined, protocol: undefined },
  ])('renders saved learner scores without enabling controls for historical search %j', async version => {
    const latest = state({ ...version, status: 'failed', candidates: [{ ...state().candidates![0]!, receipt: { ...state().candidates![0]!.receipt!, evaluator_version: 1 } }] })
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : latest)
    const { wrapper } = await open('/searches?id=search-1')
    expect(wrapper.get('h1').text()).toContain('预算搜索记录')
    expect(wrapper.get('.run-controls').text()).toContain('只读记录')
    expect(wrapper.get('.run-controls').findAll('button')).toHaveLength(0)
    expect(wrapper.get('[aria-label="评分与适配含义"]').text()).toContain('对数方差 + 标准化 + 逻辑回归')
    expect(wrapper.text()).not.toContain('CSP')
    await button(wrapper, '候选比较').trigger('click')
    expect(wrapper.get('tr.selected').text()).toContain('72.5%')
    await button(wrapper, '报告 / 文件').trigger('click'); await flushPromises()
    expect(wrapper.get('iframe').attributes('src')).toContain('/api/searches/search-1/artifacts/report/report.html?download=false')
    expect(wrapper.text()).not.toContain('正在整理产物')
    const calls = apiRequest.mock.calls.length
    await vi.advanceTimersByTimeAsync(6000)
    expect(apiRequest).toHaveBeenCalledTimes(calls)
    expect(apiRequest.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  })

  it('keeps a historical running search read-only and uses neutral evaluator copy if no learner was saved', async () => {
    const latest = state({ status: 'running', protocol: undefined, candidates: [{ id: 'c1', status: 'completed', receipt: { macro_ba: .62 } }] })
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : latest)
    const { wrapper } = await open('/searches?id=search-1')
    expect(wrapper.get('.run-controls').findAll('button')).toHaveLength(0)
    expect(wrapper.get('[aria-label="评分与适配含义"]').text()).toContain('保存的评价器')
    await button(wrapper, '候选比较').trigger('click')
    expect(wrapper.get('tr.selected').text()).toContain('62.0%')
    expect(wrapper.text()).not.toContain('CSP')
    const calls = apiRequest.mock.calls.length
    await vi.advanceTimersByTimeAsync(6000)
    expect(apiRequest).toHaveBeenCalledTimes(calls)
  })

  it('labels explicit subject holdout and displays its actual training and development membership', async () => {
    const latest = state({ panel: { evaluation_mode: 'subject_holdout', train_subjects: ['S001', 'S002'], development_subjects: ['S003'],
      folds: [{ id: 'fold-01', train_subjects: ['S001', 'S002'], development_subjects: ['S003'] }] } })
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : latest)
    const { wrapper } = await open('/searches?id=search-1')
    const panel = wrapper.get('[aria-label="评估面板"]')
    expect(panel.text()).toContain('被试留出评估')
    expect(panel.text()).toContain('训练被试 2')
    expect(panel.text()).toContain('开发被试 1')
    expect(panel.findAll('tbody tr')).toHaveLength(1)
    expect(panel.text()).not.toContain('每名被试作为开发被试一次')
  })

  it('renders hypotheses and measured prediction checks as readable content, preserving unavailable values and tiny tolerances', async () => {
    const signal = { kind: 'signal' as const, metric: 'diagnostics.subjects.S003.covariance_condition', direction: 'decrease' as const, tolerance: 1e-9, explanation: '降低协方差病态程度' }
    const utility = { kind: 'utility' as const, metric: 'macro_ba', direction: 'increase' as const, tolerance: .001, explanation: '改善开发被试分类' }
    const latest = state({ actions: [{ index: 1, action: 'propose_candidate', status: 'completed', candidate_id: 'c2', base_candidate_id: 'c1',
      request: { hypothesis: { explanation: '对齐可能降低被试间尺度差异', competing_explanation: '变化可能来自频带而非对齐',
        observations: [{ candidate_id: 'c1', metric: signal.metric }], predictions: [signal, utility], weakened_by: '条件数未改善会削弱尺度差异解释' } },
      result: { prediction_checks: { checks: [
        { ...signal, status: 'contradicted', before: 12, after: 15, difference: 3 },
        { ...utility, status: 'matched', before: .7, after: .75, difference: .05 },
        { ...signal, direction: 'unchanged', status: 'unavailable', before: null, after: null, difference: null },
      ], interpretation: '符合提前预测不构成生理原因确认。' } } }] })
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : latest)
    const { wrapper } = await open('/searches?id=search-1')
    await button(wrapper, '轮次时间线').trigger('click')
    const hypothesis = wrapper.get('[aria-label="机制假设"]')
    expect(hypothesis.text()).toContain('对齐可能降低被试间尺度差异')
    expect(hypothesis.text()).toContain('变化可能来自频带而非对齐')
    expect(hypothesis.text()).toContain('宽频平均参考 · S003 · 协方差条件数')
    expect(hypothesis.text()).toContain('信号预测')
    expect(hypothesis.text()).toContain('效用预测')
    expect(hypothesis.text()).toContain('条件数未改善会削弱尺度差异解释')
    const checks = wrapper.get('[aria-label="实测预测核验"]')
    expect(checks.text()).toContain('与预测不符')
    expect(checks.text()).toContain('符合预测')
    expect(checks.text()).toContain('无法核验')
    expect(checks.text()).toContain('1.000e-9')
    expect(checks.findAll('tbody tr')[0]!.findAll('td').slice(2, 5).map(cell => cell.text())).toEqual(['12', '15', '3'])
    expect(checks.findAll('tbody tr')[2]!.findAll('td').slice(2, 5).map(cell => cell.text())).toEqual(['—', '—', '—'])
    expect(checks.text()).toContain('不构成生理原因确认')
    expect(wrapper.get('.timeline').findAll('pre')).toHaveLength(0)
  })

  it('displays numeric signal diagnostics, secondary scores, development intervals and dimensionless gate-off adaptation', async () => {
    const latest = state({ candidates: [{ id: 'c1', status: 'evaluated', parameters: { adaptation: 'conditional_alignment', alignment_threshold: 10 },
      receipt: { macro_ba: .75, secondary_macro_ba: .6, mean_delta: .05, paired_subject_ci: { low: -.02, high: .1, n_subjects: 2 },
        subjects: { S003: { ba: .75, delta: .05, predicted_trials: 40, eligible_trials: 40 } }, secondary_subjects: { S003: .6 },
        diagnostics: { subjects: { S003: { covariance_condition: 8, covariance_condition_before: 8, covariance_condition_after: 8, mean_channel_variance_before: 1.5e-12, mean_channel_variance_after: 1, effective_rank_before: 1, effective_rank_after: 2, channel_variance: [1e-12, 2e-12], channel_flat_fraction: [0, .25] } }, summary: { mean_condition_before: 8, mean_condition_after: 8, mean_variance_before: 1.5e-12, mean_variance_after: 1, gate_fraction: 0, mean_effective_rank: 1, mean_anisotropy: 2 } },
        representation: { policy: { adaptation: 'conditional_alignment', alignment_threshold: 10 }, unit: 'dimensionless', transductive: true, gate_subject_count: 1, gate_passed_subject_count: 0, gate_fraction: 0,
          channels: ['C3', 'C4'], covariance_regularization: .1, fit_scope: 'subject_whole_batch_label_free', records: {},
          subjects: { S003: { applied_adaptation: 'scale_only', gate_passed: false, fallback_reason: '未达到条件阈值', covariance_anisotropy: 8, gate_metric_value: 2, fit_trials: 40, transform_path: null, transform_sha256: null, unit: 'dimensionless' } } } } }] })
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : latest)
    const { wrapper } = await open('/searches?id=search-1')
    await button(wrapper, '候选比较').trigger('click')
    expect(wrapper.get('tr.selected').text()).toContain('60.0%')
    expect(wrapper.get('tr.selected').text()).toContain('描述性区间 -2.0 pp ～ +10.0 pp')
    expect(wrapper.get('tr.selected').text()).toContain('2 名配对被试 · 开发比较')
    await button(wrapper, '开发被试').trigger('click')
    const diagnostics = wrapper.get('[aria-label="信号诊断"]')
    expect(diagnostics.text()).toContain('S003')
    expect(diagnostics.text()).toContain('8 → 8')
    expect(diagnostics.text()).toContain('1.50e-12 → 1.00e+0')
    expect(diagnostics.text()).toContain('C3 · 方差 1.00e-12 · 平坦比例 0.0%')
    expect(diagnostics.text()).toContain('C4 · 方差 2.00e-12 · 平坦比例 25.0%')
    const adaptation = wrapper.get('[aria-label="逐被试适配"]')
    expect(adaptation.text()).toContain('保持空间结构，仅统一尺度')
    expect(adaptation.text()).toContain('Q90/Q10，达到阈值 10 时触发')
    expect(adaptation.get('[aria-label="条件触发比例"]').text()).toContain('0.0% · 0 / 1 名被试')
    expect(adaptation.findAll('tbody td').slice(2, 5).map(cell => cell.text())).toEqual(['8', '2', '否'])
    const summary = diagnostics.get('[aria-label="诊断总体均值"]')
    expect(summary.text()).toContain('平均条件数 8 → 8')
    expect(summary.text()).toContain('平均通道方差 1.50e-12 → 1.00e+0')
    expect(summary.text()).toContain('平均有效秩（适配前） 1')
    expect(summary.text()).toContain('平均谱 Q90/Q10 2')
    expect(summary.text()).toContain('条件触发比例 0.0%')
    expect(diagnostics.findAll('tbody td')[3]!.text()).toBe('1 → 2')
    expect(adaptation.text()).toContain('无量纲')
    expect(adaptation.text()).toContain('未达到条件阈值')
    expect(adaptation.text()).not.toContain('none · 不对齐')
    expect(wrapper.get('[aria-label="开发被试明细"]').text()).toContain('60.0%')
  })

  it.each(['none', 'euclidean_alignment', 'conditional_alignment'] as const)('distinguishes unavailable or inapplicable gate metrics for %s', async adaptation => {
    const latest = state({ candidates: [{ id: 'c1', status: 'evaluated', receipt: {
      representation: { policy: { adaptation, alignment_threshold: 10 }, unit: adaptation === 'none' ? 'V' : 'dimensionless', transductive: adaptation !== 'none',
        channels: ['C3'], covariance_regularization: .1, fit_scope: 'subject_whole_batch_label_free', records: {},
        ...(adaptation === 'conditional_alignment' ? {} : { gate_subject_count: 0, gate_passed_subject_count: 0, gate_fraction: null }),
        subjects: { S003: { applied_adaptation: adaptation === 'none' ? 'none' : 'euclidean_alignment', gate_passed: true, fallback_reason: null,
          covariance_anisotropy: 123, fit_trials: 40, transform_path: null, transform_sha256: null, unit: adaptation === 'none' ? 'V' : 'dimensionless' } } },
    } }] })
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : latest)
    const { wrapper } = await open('/searches?id=search-1')
    await button(wrapper, '开发被试').trigger('click')
    const panel = wrapper.get('[aria-label="逐被试适配"]')
    const fraction = panel.get('[aria-label="条件触发比例"]')
    expect(fraction.text()).toContain(adaptation === 'conditional_alignment' ? '— · — / —' : '不适用')
    expect(fraction.text()).not.toContain('0.0%')
    expect(panel.findAll('tbody td')[2]!.text()).toBe('123')
    expect(panel.findAll('tbody td')[3]!.text()).toBe('—')
    expect(wrapper.find('[aria-label="诊断总体均值"]').exists()).toBe(false)
  })

  it.each([5, 109])('keeps five folds compact for %i subjects and expands complete lists independently across polling', async total => {
    const subjects = Array.from({ length: total }, (_, index) => `S${String(index + 1).padStart(3, '0')}`)
    const folds = Array.from({ length: 5 }, (_, index) => ({ id: `fold-0${index + 1}`,
      train_subjects: subjects.filter((_, subjectIndex) => subjectIndex % 5 !== index),
      development_subjects: subjects.filter((_, subjectIndex) => subjectIndex % 5 === index),
    }))
    const latest = state({ status: 'running', panel: { evaluation_mode: 'group_cross_validation', train_subjects: [], development_subjects: subjects, folds } })
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : structuredClone(latest))
    const { wrapper } = await open('/searches?id=search-1')
    const table = wrapper.get('table[aria-label="评估折次"]')
    expect(table.findAll('tbody tr')).toHaveLength(5)
    expect(table.findAll('details')).toHaveLength(10)
    expect(table.findAll('details[open]')).toHaveLength(0)
    const first = table.findAll('tbody tr')[0]!
    const [train, development] = first.findAll('details')
    expect(first.findAll('summary').map(summary => summary.text())).toEqual(total === 109 ? ['87 人', '22 人'] : ['4 人', '1 人'])
    await train!.get('summary').trigger('click')
    expect(train!.attributes('open')).toBeDefined()
    expect(train!.findAll('li').map(item => item.text())).toEqual(folds[0]!.train_subjects)
    expect(table.findAll('details[open]')).toHaveLength(1)
    await development!.get('summary').trigger('click')
    expect(development!.attributes('open')).toBeDefined()
    expect(development!.findAll('li').map(item => item.text())).toEqual(folds[0]!.development_subjects)
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(table.findAll('details[open]')).toHaveLength(2)
    await train!.get('summary').trigger('click')
    expect(train!.attributes('open')).toBeUndefined()
    expect(development!.attributes('open')).toBeDefined()
    expect(apiRequest.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  })

  it('accepts backend subject maps and panel summaries and hides successful model-decision wrappers', async () => {
    const latest = state({ status: 'stopped', stop_reason: 'candidate_budget_exhausted',
      request: { ...state().request, strategy: 'one_shot', budget: { max_candidates: 48, max_proposals: 128, max_evidence_reads: 32, max_seconds: 86400, max_memory_mb: null, max_disk_mb: null } },
      panel: { trial_count: 200, eligible_count: 180, train_subjects: ['S001', 'S002'], development_subjects: ['S003'], records: {}, output_contract: { sfreq: 160 }, panel_hash: 'hash' },
      candidates: [{ id: 'c1', status: 'evaluated', receipt: { subjects: { S003: { ba: .75, delta: .03, eligible_trials: 40 } }, coverage: { original: 45, eligible: 40, predicted: 40, missing: 0, train: { original: 80, eligible: 75 }, development: { original: 45, eligible: 40, predicted: 40 } } } }],
      actions: [{ index: 0, action: 'model_decision', status: 'completed', reason: '不重复展示的包装记录', result: { decision: { action: 'propose_candidate' } } },
        { index: 1, action: 'propose_candidate', status: 'completed', reason: '开发评估后提出候选', result: { candidate_id: 'c1' } },
        { index: 2, action: 'model_decision', status: 'failed', error: 'LLM 超时' }],
    })
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : latest)
    const { wrapper } = await open('/searches?id=search-1')
    expect(wrapper.text()).toContain('一次性提案对照')
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
    await wrapper.get('input[aria-label="候选数"]').setValue(257)
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[role="alert"]').text()).toContain('不能超过 256')
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

  it.each([
    ['candidate_invalid', '候选无效'], ['data_unevaluable', '数据不可评价'],
  ])('renders %s receipts with unknown coverage and diagnostic warnings', async (status, translated) => {
    const latest = state({ selected_candidate_id: null, candidates: [{ id: 'c1', status,
      receipt: { status, coverage: null, macro_ba: null, mean_delta: null,
        diagnostics: { floor_fraction: null, converged: null, warnings: ['共同面板不可评价，未生成覆盖计数'] } } }],
    })
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : latest)
    const { wrapper } = await open('/searches?id=search-1')
    await button(wrapper, '候选比较').trigger('click')
    expect(wrapper.get('tbody').text()).toContain(translated)
    expect(wrapper.get('tbody').text()).toContain('— / —')
    await button(wrapper, '开发被试').trigger('click')
    expect(wrapper.get('.diagnostics').text()).toContain('预测（开发） —')
    expect(wrapper.get('.diagnostics').text()).not.toContain('预测（开发） 0')
    expect(wrapper.text()).toContain('诊断警告（1）')
    expect(wrapper.text()).toContain('共同面板不可评价，未生成覆盖计数')
  })

  it('keeps core files visible, collapses candidate/engine groups, and makes every permanent artifact reachable through bounded pages', async () => {
    const files = [
      { name: 'search.json', description: '当前搜索状态' },
      { name: 'files.json', description: '全部文件索引' },
      { name: 'candidates/c1/receipt.json', description: '宽频评价回执' },
      { name: 'candidates/c1/originalpredictions.tsv', description: '逐事件原始预测' },
      { name: 'candidates/c2/method.json', description: '窄频处理方法' },
      { name: 'engine/objects/input/hash.json', description: '冻结输入对象' },
      { name: 'engine/environment.json', description: '执行环境' },
      { name: 'engine/runs/job-2/S001/data-epo.fif', description: '分段信号' },
      ...Array.from({ length: 109 }, (_, index) => ({
        name: `engine/runs/job-1/S${String(index + 1).padStart(3, '0')}/signal_V.npy`, description: `被试 ${index + 1} 的信号数组`,
      })),
    ].map(file => ({ ...file, url: `/api/searches/search-1/artifacts/${file.name}?download=true` }))
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : state({ artifacts: files }))
    const { wrapper } = await open('/searches?id=search-1')
    await button(wrapper, '报告 / 文件').trigger('click')
    expect(wrapper.get('.artifact-toolbar').text()).toContain(`${files.length} / ${files.length} 个文件`)
    expect(wrapper.findAll('.artifact-list a').map(link => link.text())).toEqual(['search.json', 'files.json'])
    expect(wrapper.get('[data-group="candidates/c1"]').attributes('open')).toBeUndefined()
    expect(wrapper.get('[data-group="engine/runs/job-1"]').attributes('open')).toBeUndefined()
    expect(wrapper.get('[data-group="engine/runs/job-1"] summary').text()).toContain('数值执行 · 宽频平均参考')
    expect(wrapper.get('[data-group="engine/objects"] summary').text()).toContain('对象快照')
    const seen = new Set<string>()
    for (const group of wrapper.findAll('.artifact-group')) {
      if (group.attributes('open') === undefined) await group.get('summary').trigger('click')
      while (true) {
        const links = group.findAll('.artifact-list a')
        expect(links.length).toBeLessThanOrEqual(30)
        links.forEach(link => {
          seen.add(link.text())
          expect(link.attributes('href')).toBe(`https://api.example.test/api/searches/search-1/artifacts/${link.text()}?download=true`)
          expect(link.element.parentElement?.querySelector('.artifact-description')?.textContent).toBe(files.find(file => file.name === link.text())!.description)
        })
        const next = group.findAll('button').find(item => item.text() === '下一页')
        if (!next || next.attributes('disabled') !== undefined) break
        await next.trigger('click')
      }
    }
    expect([...seen].sort()).toEqual(files.map(file => file.name).sort())
    const engine = wrapper.get('[data-group="engine/runs/job-1"]')
    expect(engine.findAll('.artifact-list a')).toHaveLength(19)
    expect(engine.get('.artifact-pagination').text()).toContain('第 4 / 4 页')
    expect(apiRequest.mock.calls.map(([path]) => path).sort()).toEqual(['/api/searches', '/api/searches/search-1?include_artifacts=true', '/api/searches/search-1?include_artifacts=true'])
  })

  it('filters files by name or description and resets the group page when filtering', async () => {
    const files = Array.from({ length: 65 }, (_, index) => ({
      name: `engine/runs/job-1/S${index}/signal_V.npy`, description: index === 64 ? '特殊诊断结果' : '信号数组',
    }))
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : state({ artifacts: files }))
    const { wrapper } = await open('/searches?id=search-1')
    await button(wrapper, '报告 / 文件').trigger('click')
    await wrapper.get('.artifact-group summary').trigger('click')
    await button(wrapper, '下一页').trigger('click')
    expect(wrapper.get('.artifact-pagination').text()).toContain('第 2 / 3 页')
    await wrapper.get('input[aria-label="查找搜索文件"]').setValue('特殊诊断')
    expect(wrapper.findAll('.artifact-list a')).toHaveLength(1)
    expect(wrapper.get('.artifact-list a').text()).toContain('/S64/')
    expect(wrapper.get('.artifact-toolbar').text()).toContain('1 / 65 个文件')
    await wrapper.get('input[aria-label="查找搜索文件"]').setValue('not-a-file')
    expect(wrapper.text()).toContain('没有匹配的文件')
    await wrapper.get('input[aria-label="查找搜索文件"]').setValue('')
    expect(wrapper.get('.artifact-pagination').text()).toContain('第 1 / 3 页')
    expect(wrapper.findAll('.artifact-list a')).toHaveLength(30)
    await wrapper.get('input[aria-label="查找搜索文件"]').setValue('/S42/')
    expect(wrapper.get('.artifact-list a').text()).toContain('/S42/')
    expect(apiRequest).toHaveBeenCalledTimes(3)
  })

  it('preserves expanded file groups and pages during polling, but resets them when switching searches', async () => {
    const files = Array.from({ length: 65 }, (_, index) => ({ name: `engine/runs/job-1/S${index}/signal_V.npy` }))
    let latest = state({ status: 'running', artifacts: files })
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : latest)
    const { wrapper, router } = await open('/searches?id=search-1')
    await button(wrapper, '报告 / 文件').trigger('click')
    await wrapper.get('.artifact-group summary').trigger('click')
    await button(wrapper, '下一页').trigger('click')
    latest = { ...latest, artifacts: [...files, { name: 'engine/runs/job-1/S65/signal_V.npy' }, { name: 'candidates/c2/receipt.json' }] }
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(wrapper.get('.artifact-pagination').text()).toContain('共 65 个')
    await button(wrapper, '刷新文件').trigger('click'); await flushPromises()
    expect(wrapper.get('[data-group="engine/runs/job-1"]').attributes('open')).toBeDefined()
    expect(wrapper.get('.artifact-pagination').text()).toContain('第 2 / 3 页 · 共 66 个')
    expect(wrapper.get('[data-group="candidates/c2"]').attributes('open')).toBeUndefined()
    expect(wrapper.findAll('.artifact-list a')).toHaveLength(30)
    latest = state({ id: 'search-2', artifacts: files })
    await router.push('/searches?id=search-2'); await flushPromises()
    await button(wrapper, '报告 / 文件').trigger('click')
    expect(wrapper.get('.artifact-group').attributes('open')).toBeUndefined()
    await wrapper.get('.artifact-group summary').trigger('click')
    expect(wrapper.get('.artifact-pagination').text()).toContain('第 1 / 3 页')
  })

  it('uses lightweight polling in every tab, retains file counts, and refreshes all artifacts on entry or manual refresh', async () => {
    let fullArtifacts = [{ name: 'search.json' }]
    apiRequest.mockImplementation(async (path: string) => {
      if (path === '/api/searches') return []
      if (path.startsWith('/api/searches/search-2?')) return state({ id: 'search-2', artifacts: [] })
      return state({ status: 'running', artifacts: path.endsWith('include_artifacts=true') ? fullArtifacts : [] })
    })
    const { wrapper, router } = await open('/searches?id=search-1')
    expect(apiRequest).toHaveBeenLastCalledWith('/api/searches')
    expect(apiRequest).toHaveBeenCalledWith('/api/searches/search-1?include_artifacts=true')
    fullArtifacts = [...fullArtifacts, { name: 'selection.json' }]
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(apiRequest).toHaveBeenLastCalledWith('/api/searches/search-1?include_artifacts=false')
    expect(button(wrapper, '报告 / 文件').text()).toBe('报告 / 文件1')
    await button(wrapper, '报告 / 文件').trigger('click'); await flushPromises()
    expect(apiRequest).toHaveBeenLastCalledWith('/api/searches/search-1?include_artifacts=true')
    expect(wrapper.findAll('.artifact-list a')).toHaveLength(2)
    fullArtifacts = [...fullArtifacts, { name: 'protocol.json' }]
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(apiRequest).toHaveBeenLastCalledWith('/api/searches/search-1?include_artifacts=false')
    expect(wrapper.findAll('.artifact-list a')).toHaveLength(2)
    await button(wrapper, '刷新文件').trigger('click'); await flushPromises()
    expect(apiRequest).toHaveBeenLastCalledWith('/api/searches/search-1?include_artifacts=true')
    expect(wrapper.findAll('.artifact-list a')).toHaveLength(3)
    await button(wrapper, '候选比较').trigger('click')
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(apiRequest).toHaveBeenLastCalledWith('/api/searches/search-1?include_artifacts=false')
    expect(button(wrapper, '报告 / 文件').text()).toBe('报告 / 文件3')
    await router.push('/searches?id=search-2'); await flushPromises()
    expect(button(wrapper, '报告 / 文件').text()).toBe('报告 / 文件0')
  })

  it('ignores an older lightweight poll after a full artifact refresh finishes', async () => {
    const oldPoll = deferred<SearchState>()
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : state({ status: 'running', artifacts: [{ name: 'search.json' }] }))
    const { wrapper } = await open('/searches?id=search-1')
    apiRequest.mockReturnValueOnce(oldPoll.promise)
    await vi.advanceTimersByTimeAsync(2000)
    apiRequest.mockResolvedValueOnce(state({ status: 'running', message: '最新完整文件状态', artifacts: [{ name: 'search.json' }, { name: 'selection.json' }] }))
    await button(wrapper, '报告 / 文件').trigger('click'); await flushPromises()
    oldPoll.resolve(state({ status: 'running', message: '旧轮询状态', artifacts: [] })); await flushPromises()
    expect(wrapper.text()).toContain('最新完整文件状态')
    expect(wrapper.text()).not.toContain('旧轮询状态')
    expect(wrapper.findAll('.artifact-list a')).toHaveLength(2)
  })

  it('refreshes files once when a candidate finishes, while unchanged file-tab polling stays lightweight', async () => {
    let candidateStatus = 'running'
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : state({
      status: 'running', candidates: [{ id: 'c1', status: candidateStatus }],
      artifacts: path.endsWith('include_artifacts=true') ? [{ name: 'search.json' }, ...(candidateStatus === 'evaluated' ? [{ name: 'candidates/c1/receipt.json' }] : [])] : [],
    }))
    const fullCalls = () => apiRequest.mock.calls.filter(([path]) => path.endsWith('include_artifacts=true')).length
    const { wrapper } = await open('/searches?id=search-1')
    await button(wrapper, '报告 / 文件').trigger('click'); await flushPromises()
    expect(fullCalls()).toBe(2)
    await vi.advanceTimersByTimeAsync(6000); await flushPromises()
    expect(fullCalls()).toBe(2)
    candidateStatus = 'evaluated'
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(fullCalls()).toBe(3)
    expect(wrapper.find('[data-group="candidates/c1"]').exists()).toBe(true)
    await vi.advanceTimersByTimeAsync(8000); await flushPromises()
    expect(fullCalls()).toBe(3)
    expect(apiRequest).toHaveBeenLastCalledWith('/api/searches/search-1?include_artifacts=false')
  })

  it('waits for both late terminal artifacts and stops automatic checks once the report and index arrive', async () => {
    let status: SearchState['status'] = 'running'
    let files = [{ name: 'search.json' }]
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : state({ status,
      artifacts: path.endsWith('include_artifacts=true') ? [...files] : [],
    }))
    const fullCalls = () => apiRequest.mock.calls.filter(([path]) => path.endsWith('include_artifacts=true')).length
    const { wrapper } = await open('/searches?id=search-1')
    await button(wrapper, '报告 / 文件').trigger('click'); await flushPromises()
    status = 'completed'
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(fullCalls()).toBe(3)
    expect(wrapper.get('h1').text()).toContain('已完成')
    expect(wrapper.get('section[aria-label="报告与文件"]').text()).toContain('正在整理产物')
    files = [...files, { name: 'report.html' }]
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(wrapper.find('iframe').exists()).toBe(true)
    expect(wrapper.get('section[aria-label="报告与文件"]').text()).toContain('正在整理产物')
    files = [...files, { name: 'files.json' }]
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(wrapper.get('iframe').attributes('src')).toContain('/report.html?download=false')
    expect(wrapper.findAll('.artifact-list a').map(link => link.text())).toContain('files.json')
    expect(wrapper.get('section[aria-label="报告与文件"]').text()).not.toContain('正在整理产物')
    expect(fullCalls()).toBe(5)
    const total = apiRequest.mock.calls.length
    await vi.advanceTimersByTimeAsync(30000)
    expect(apiRequest).toHaveBeenCalledTimes(total)
  })

  it.each(['missing', 'errors'])('bounds late artifact checks to ten attempts (%s), then permits manual recovery', async outcome => {
    let fullCalls = 0, ready = false
    apiRequest.mockImplementation(async (path: string) => {
      if (path === '/api/searches') return []
      if (path.endsWith('include_artifacts=true')) {
        fullCalls++
        if (!ready && outcome === 'errors' && fullCalls > 2) throw new Error('暂时无法扫描文件')
      }
      return state({ artifacts: ready ? [{ name: 'report.html' }, { name: 'files.json' }] : [] })
    })
    const { wrapper } = await open('/searches?id=search-1')
    expect(fullCalls).toBe(1)
    await vi.advanceTimersByTimeAsync(10000)
    expect(fullCalls).toBe(1)
    await button(wrapper, '报告 / 文件').trigger('click'); await flushPromises()
    expect(fullCalls).toBe(2)
    expect(wrapper.get('section[aria-label="报告与文件"]').text()).toContain('正在整理产物')
    await vi.advanceTimersByTimeAsync(20000); await flushPromises()
    expect(fullCalls).toBe(12)
    expect(wrapper.text()).toContain('自动检查已达 10 次')
    expect(button(wrapper, '刷新文件').attributes('disabled')).toBeUndefined()
    const total = apiRequest.mock.calls.length
    await vi.advanceTimersByTimeAsync(60000)
    expect(apiRequest).toHaveBeenCalledTimes(total)
    ready = true
    await button(wrapper, '刷新文件').trigger('click'); await flushPromises()
    expect(fullCalls).toBe(13)
    expect(wrapper.find('iframe').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('自动检查已达')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    await vi.advanceTimersByTimeAsync(6000)
    expect(fullCalls).toBe(13)
  })

  it('cancels terminal artifact retries when leaving the file tab and on unmount', async () => {
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : state({ artifacts: [] }))
    const { wrapper } = await open('/searches?id=search-1')
    await button(wrapper, '报告 / 文件').trigger('click'); await flushPromises()
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(wrapper.text()).toContain('自动检查 1 / 10 次')
    await button(wrapper, '候选比较').trigger('click')
    const calls = apiRequest.mock.calls.length
    await vi.advanceTimersByTimeAsync(60000)
    expect(apiRequest).toHaveBeenCalledTimes(calls)
    await button(wrapper, '报告 / 文件').trigger('click'); await flushPromises()
    expect(apiRequest).toHaveBeenCalledTimes(calls + 1)
    expect(wrapper.text()).toContain('自动检查 1 / 10 次')
    wrappers.splice(wrappers.indexOf(wrapper), 1); wrapper.unmount()
    await vi.advanceTimersByTimeAsync(6000)
    expect(apiRequest).toHaveBeenCalledTimes(calls + 1)
  })

  it('does not scan files for completion events in other tabs, and loads the final files on entry', async () => {
    let finished = false
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : state({
      status: finished ? 'completed' : 'running', candidates: [{ id: 'c1', status: finished ? 'evaluated' : 'running' }],
      artifacts: finished && path.endsWith('include_artifacts=true') ? [{ name: 'report.html' }, { name: 'files.json' }] : [],
    }))
    const { wrapper } = await open('/searches?id=search-1')
    finished = true
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(wrapper.get('h1').text()).toContain('已完成')
    expect(apiRequest.mock.calls.filter(([path]) => path.endsWith('include_artifacts=true'))).toHaveLength(1)
    const total = apiRequest.mock.calls.length
    await vi.advanceTimersByTimeAsync(10000)
    expect(apiRequest).toHaveBeenCalledTimes(total)
    await button(wrapper, '报告 / 文件').trigger('click'); await flushPromises()
    expect(wrapper.find('iframe').exists()).toBe(true)
    expect(apiRequest.mock.calls.filter(([path]) => path.endsWith('include_artifacts=true'))).toHaveLength(2)
  })

  it('does not overlap full file scans while a manual refresh is pending', async () => {
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : state({ status: 'running' }))
    const { wrapper } = await open('/searches?id=search-1')
    await button(wrapper, '报告 / 文件').trigger('click'); await flushPromises()
    const scan = deferred<SearchState>()
    apiRequest.mockReturnValueOnce(scan.promise)
    await button(wrapper, '刷新文件').trigger('click')
    expect(button(wrapper, '正在刷新文件').attributes('disabled')).toBeDefined()
    const total = apiRequest.mock.calls.length
    await vi.advanceTimersByTimeAsync(10000)
    expect(apiRequest).toHaveBeenCalledTimes(total)
    scan.resolve(state({ status: 'running' })); await flushPromises()
    await vi.advanceTimersByTimeAsync(2000)
    expect(apiRequest).toHaveBeenLastCalledWith('/api/searches/search-1?include_artifacts=false')
  })

  it('advances the active elapsed display from the deadline and uses only the final backend elapsed after stopping', async () => {
    const deadline = Date.now() / 1000 - 200 + 3600
    let status: SearchState['status'] = 'running', elapsed = 125
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : state({ status, deadline,
      usage: { elapsed_seconds: elapsed }, artifacts: [],
    }))
    const { wrapper } = await open('/searches?id=search-1')
    const meter = () => wrapper.get('[role="progressbar"][aria-label="耗时（秒）"]').attributes('aria-valuetext')
    expect(meter()).toBe('200 / 3,600')
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(meter()).toBe('202 / 3,600')
    expect(apiRequest).toHaveBeenLastCalledWith('/api/searches/search-1?include_artifacts=false')
    elapsed = 300
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(meter()).toBe('300 / 3,600')
    status = 'stopped'; elapsed = 190
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(meter()).toBe('190 / 3,600')
    await vi.advanceTimersByTimeAsync(10000)
    expect(meter()).toBe('190 / 3,600')
    expect(apiRequest.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  })

  it('falls back to backend elapsed without a deadline and labels a running one-shot initial schedule', async () => {
    let planning = true
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : state({
      status: 'running', request: { ...state().request, strategy: 'one_shot', budget: { max_candidates: 48, max_proposals: 128, max_evidence_reads: 32, max_seconds: 86400, max_memory_mb: null, max_disk_mb: null } }, phase: 'freeze_panel',
      usage: { elapsed_seconds: 12.5 }, actions: [{ index: 0, action: 'initial_schedule', status: planning ? 'running' : 'completed' }],
    }))
    const { wrapper } = await open('/searches?id=search-1')
    const phase = () => wrapper.get('[aria-label="进度与预算"] [role="status"]').text()
    expect(phase()).toContain('制定初始计划')
    expect(phase()).not.toContain('冻结开发面板')
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(wrapper.get('[role="progressbar"][aria-label="耗时（秒）"]').attributes('aria-valuetext')).toBe('12.5 / 86,400')
    planning = false
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(phase()).toContain('冻结开发面板')
  })
})

describe('search entry and artifact links', () => {
  beforeEach(() => {
    apiRequest.mockReset()
    HTMLDialogElement.prototype.showModal = function() { this.setAttribute('open', '') }
    HTMLDialogElement.prototype.close = function() { this.removeAttribute('open') }
  })
  afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

  it.each([true, false])('shows automatic search preparation after data collection (%s)', async collected => {
    const workflow = { schema_version: '1', engine: 'diagnostic-policy-search-v2', id: 'source-1', status: 'completed', created_at: '2026-09-09T08:00:00Z', updated_at: '2026-09-09T08:00:00Z',
      request: { source_root: 'E:/data' }, stages: [], events: [], artifacts: [], error: null,
      outputs: { data_delivery: { shape: [90, 64, 321] }, ...(collected ? { data_collection: { path: 'collection' } } : {}) } }
    apiRequest.mockImplementation(async (path: string) => path.endsWith('/sources') ? { allowed_roots: [] } : path === '/api/workflows' ? [workflow] : workflow)
    const { wrapper } = await open('/workflows?id=source-1', WorkflowsView)
    const entry = wrapper.find('[aria-label="预算搜索入口"]')
    expect(entry.exists()).toBe(collected)
    if (collected) {
      expect(entry.find('a').exists()).toBe(false)
      expect(entry.text()).toContain('等待自动启动搜索')
    }
    expect(wrapper.text()).toContain('方法与分组信息以保存的交付记录为准')
    expect(wrapper.text()).not.toContain('随机选择')
  })

  it.each(['running', 'completed'])('opens the linked search for a %s workflow without creating another search', async status => {
    const workflow = { schema_version: '1', engine: 'diagnostic-policy-search-v2', id: 'source-1', search_id: 'linked-search', status, created_at: '2026-09-09T08:00:00Z', updated_at: '2026-09-09T08:00:00Z',
      request: { source_root: 'E:/data' }, stages: [], events: [], artifacts: [], error: null,
      outputs: { data_preprocessing: { search_id: 'other-search' }, data_evaluation: { selection_policy: 'development_score', quality_evaluated: true,
        search_id: 'other-search', score: .735, evaluation_scope: 'development', selected_method_ref: { id: 'selected-method', sha256: 'hash' } } } }
    apiRequest.mockImplementation(async (path: string) => path.endsWith('/sources') ? { allowed_roots: [] } : path === '/api/workflows' ? [workflow] : workflow)
    const { wrapper, router } = await open('/workflows?id=source-1', WorkflowsView)
    const entry = wrapper.get('[aria-label="预算搜索入口"]')
    expect(entry.get('a').attributes('href')).toBe('/searches?id=linked-search')
    expect(entry.text()).toContain('开发 BA 73.5%')
    expect(entry.text()).toContain('selected-method')
    await entry.get('a').trigger('click'); await flushPromises()
    expect(router.currentRoute.value.query).toEqual({ id: 'linked-search' })
    expect(apiRequest.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
    expect(wrapper.text()).not.toContain('随机选择')
  })

  it('uses the preprocessing search reference when the workflow reference is not yet present', async () => {
    const workflow = { schema_version: '1', engine: 'diagnostic-policy-search-v2', id: 'source-1', status: 'completed', created_at: '2026-09-09T08:00:00Z', updated_at: '2026-09-09T08:00:00Z',
      request: { source_root: 'E:/data' }, stages: [], events: [], artifacts: [], error: null,
      outputs: { data_preprocessing: { search_id: 'preprocessing-search' } } }
    apiRequest.mockImplementation(async (path: string) => path.endsWith('/sources') ? { allowed_roots: [] } : path === '/api/workflows' ? [workflow] : workflow)
    const { wrapper } = await open('/workflows?id=source-1', WorkflowsView)
    expect(wrapper.get('[aria-label="预算搜索入口"] a').attributes('href')).toBe('/searches?id=preprocessing-search')
    expect(apiRequest.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  })

  it('preserves artifact query parameters, handles API bases, and excludes executable links', () => {
    expect(searchArtifactUrl('id/1', { name: 'report.html', url: 'https://files.test/report.html?v=3&download=false#page=2' })).toBe('https://files.test/report.html?v=3&download=true#page=2')
    expect(searchArtifactUrl('id/1', { name: '子目录/文件.json' })).toContain(`/api/searches/id%2F1/artifacts/${encodeURIComponent('子目录')}/${encodeURIComponent('文件.json')}?download=true`)
    expect(searchArtifactUrl('id/1', { name: 'bad.html', url: 'javascript:alert(1)' })).toBe('')
  })
  it.each([
    [{ version: '3', assessment: { version: 2 } }, 'EEGNet 三种子训练效用', '历史 v1'],
    [{ version: '3', assessment: { version: 1 } }, '历史 v1 三模型训练效用', 'EEGNet'],
  ])('labels saved utility protocols before candidate assessments arrive', async (protocol, expected, excluded) => {
    apiRequest.mockImplementation(async (path: string) => path === '/api/searches' ? [] : state({ protocol: protocol as any, candidates: [] }))
    const { wrapper } = await open('/searches?id=search-1')
    expect(wrapper.text()).toContain(expected)
    expect(wrapper.text()).not.toContain(excluded)
  })

})
