import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import InvasiveWorkflowsView from './InvasiveWorkflowsView.vue'

const { request, replace } = vi.hoisted(() => ({ request: vi.fn(), replace: vi.fn() }))
vi.mock('../api/client', () => ({ apiRequest: request, apiUrl: (path: string) => path }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ replace }),
  RouterLink: { template: '<a><slot /></a>' },
}))

const ref = (char: string) => ({ id: char.repeat(64), sha256: char.repeat(64) })
const snapshot = {
  dataset_id: 'falcon-session', session_id: 'session-1', subject_id: 'MonkeyL', standard: 'NWB', standard_version: '2.8.0', modality: 'intracortical_array', inspected_values: 64,
  source: { path: '/data/falcon.nwb', size_bytes: 1024, modified_ns: 1, sha256: null }, warnings: [], processing_history: ['behavior'], timebases: [],
  collections: [{ id: 'units', path: '/units', modality: 'ecephys', representation: 'threshold_crossings', entity_axis: 'threshold_channel', shape: [215241, 64], dtype: 'float64', physical_units: 'seconds', upstream_processed: true, metadata: {} }],
}
const plan = {
  task: '生成用于行为解码的 T×N 神经活动矩阵', modality: 'intracortical_array', input_representation: 'threshold_crossings', strategy: 'consume_released_derivative', executable: true, method_profile: null,
  qc: {}, transform: { bin_size_s: .02, representation: 'both', run_baseline: true }, warnings: [], literature_evidence_refs: [], code_evidence_refs: [],
  steps: [{ id: 'unit_qc', stage: 'qc', operation: 'unit_quality_control', status: 'run', reason: '检查 firing rate 和稳定性', parameters: {}, evidence_needed: [] }],
}
const result = {
  status: 'completed', created_at: '2026-09-14T08:00:00Z', report: '/output/report.md', unit_retention_ratio: 1, warnings: [],
  final_shapes: { neural_matrix: [6481, 64], aligned_target: [6481, 16], trial_aligned: [10, 141, 64] },
  alignment: { target: { count: 6671, neural_coverage_overlap_ratio: .9998 }, evaluation_mask: { covered_fraction: .9997 } },
  validation: { unit_count_input: 64, unit_count_retained: 64, unit_retention_ratio: 1, signal_distribution: { mean: .1, standard_deviation: .3 }, baseline: { status: 'completed', model: 'ridge', alpha: 1, split: 'nwb_eval_mask', train_rows: 5200, test_rows: 1279, r2: [.64, .45, -.08], interpretation: 'Diagnostic only.' } },
}
const detail = { result_ref: ref('c'), result, plan_ref: ref('b'), plan, snapshot_ref: ref('a'), snapshot, artifacts: [{ name: 'report.md', bytes: 800, sha256: 'd' }, { name: 'neural-matrix.npy', bytes: 1000, sha256: 'e' }, { name: 'qc-decisions.json', bytes: 300, sha256: 'f' }] }
const summary = { result_ref: ref('c'), status: 'completed', created_at: result.created_at, dataset_id: snapshot.dataset_id, session_id: snapshot.session_id, subject_id: snapshot.subject_id, modality: snapshot.modality, task: plan.task, strategy: plan.strategy, final_shapes: result.final_shapes, unit_retention_ratio: 1 }

describe('InvasiveWorkflowsView', () => {
  beforeEach(() => {
    request.mockReset(); replace.mockReset().mockResolvedValue(undefined)
    HTMLDialogElement.prototype.showModal = function() { this.setAttribute('open', '') }
    HTMLDialogElement.prototype.close = function() { this.removeAttribute('open') }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify([{ unit_id: 1, retained: true, reasons: [] }]), { status: 200, headers: { 'Content-Type': 'application/json' } })))
  })

  it('restores a saved run and presents process, evidence, metrics, and files', async () => {
    request.mockImplementation(async (path: string) => path.endsWith('/sources') ? { allowed_roots: ['/data'] } : path === '/api/preprocessing/invasive/results' ? [summary] : detail)
    const wrapper = mount(InvasiveWorkflowsView)
    await flushPromises()

    expect(wrapper.text()).toContain('falcon-session')
    expect(wrapper.text()).toContain('6481 × 64')
    expect(wrapper.text()).toContain('2 / 3 R² > 0')
    expect(wrapper.findAll('.stages li')).toHaveLength(7)
    await wrapper.findAll('.tabs button').find(button => button.text().includes('数据调研'))!.trigger('click')
    expect(wrapper.text()).toContain('/units')
    await wrapper.findAll('.tabs button').find(button => button.text().includes('结果与可视化'))!.trigger('click')
    expect(wrapper.text()).toContain('nwb_eval_mask')
    await wrapper.findAll('.tabs button').find(button => button.text().includes('文件'))!.trigger('click')
    expect(wrapper.text()).toContain('neural-matrix.npy')
    wrapper.unmount()
  })

  it('runs inspect, plan, and execution from the new-run form', async () => {
    let completed = false
    request.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path.endsWith('/sources')) return { allowed_roots: ['/data'] }
      if (path === '/api/preprocessing/invasive/results') return completed ? [summary] : []
      if (path.includes('/detail')) return detail
      if (path.endsWith('/inspect') && init?.method === 'POST') return { snapshot_ref: ref('a'), snapshot }
      if (path.endsWith('/plans') && init?.method === 'POST') return { plan_ref: ref('b'), plan }
      if (path.endsWith('/runs') && init?.method === 'POST') { completed = true; return { result_ref: ref('c'), result } }
      throw new Error(`unexpected request ${path}`)
    })
    const wrapper = mount(InvasiveWorkflowsView)
    await flushPromises()
    await wrapper.get('.initial .primary').trigger('click')
    await wrapper.get('input[placeholder="/absolute/path/session.nwb"]').setValue('/data/falcon.nwb')
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()

    const posts = request.mock.calls.filter(([, init]) => init?.method === 'POST')
    expect(posts.map(([path]) => path)).toEqual([
      '/api/preprocessing/invasive/inspect',
      '/api/preprocessing/invasive/plans',
      '/api/preprocessing/invasive/runs',
    ])
    expect(JSON.parse(posts[1]![1].body)).toMatchObject({ task: plan.task, transform: { bin_size_s: .02, run_baseline: true } })
    expect(wrapper.text()).toContain('falcon-session')
    expect(replace).toHaveBeenCalledWith({ path: '/invasive', query: { id: ref('c').id } })
    wrapper.unmount()
  })
})
