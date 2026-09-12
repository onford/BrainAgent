import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import PreprocessingCard from './PreprocessingCard.vue'
import { apiRequest } from '../api/client'

vi.mock('../api/client', () => ({ apiRequest: vi.fn(), apiUrl: (path: string) => path }))
const request = vi.mocked(apiRequest)
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

describe('PreprocessingCard', () => {
  it('requires a reason and confirms exactly the observed record and hashes', async () => {
    const pending = { record_key: 'r1', record_id: 'sub-01', step_id: 'mark', input_sha256: 'a'.repeat(64), model_sha256: null, parameters: { bads: ['C3'] }, reason: 'review' }
    request.mockResolvedValueOnce({ job_id: 'job', status: 'waiting_decision', completed: 0, total: 1, records: [] }).mockResolvedValueOnce([pending]).mockResolvedValueOnce({ plan_ref: { id: 'new', sha256: 'new' }, plan: { records: [{}], screening: [] } }).mockResolvedValueOnce(null)
    const wrapper = mount(PreprocessingCard, { props: { output: { job_id: 'job' } } })
    await flushPromises()
    const button = wrapper.findAll('button').find(b => b.text().includes('确认所列决定'))!
    expect(button.attributes('disabled')).toBeDefined()
    await wrapper.get('input').setValue('Reviewed electrode diagnostic')
    await button.trigger('click'); await flushPromises()
    expect(request).toHaveBeenCalledWith('/api/preprocessing/jobs/job/decisions', { method: 'POST', body: JSON.stringify({ confirmations: [{ record_key: 'r1', step_id: 'mark', input_sha256: pending.input_sha256, model_sha256: null, reason: 'Reviewed electrode diagnostic' }] }) })
    expect(wrapper.text()).toContain('等待决定')
    wrapper.unmount()
  })
  it('submits a plan, polls after chat ends, and stops on completion', async () => {
    vi.useFakeTimers()
    request.mockResolvedValueOnce(null).mockResolvedValueOnce({ job_id: 'job', status: 'queued', completed: 0, total: 2, records: [] }).mockResolvedValueOnce({ job_id: 'job', status: 'completed', completed: 2, total: 2, records: [] })
    const wrapper = mount(PreprocessingCard, { props: { output: { plan_ref: { id: 'plan', sha256: 'plan' }, record_count: 2, execution_status: 'planned' } } })
    await flushPromises()
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('等待处理')
    expect(wrapper.text()).not.toContain('处理完成')
    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()
    expect(wrapper.text()).toContain('已完成 2 / 2')
    await vi.advanceTimersByTimeAsync(6000)
    expect(request).toHaveBeenCalledTimes(3)
    wrapper.unmount()
  })

  it('restores a submitted plan and exposes per-record failures and retry', async () => {
    const partial = { job_id: 'job', status: 'partial', completed: 1, total: 2, records: [{ key: 'r', method_id: 'abcdef01', record_id: 'sub-02', status: 'failed', attempt: 1, error: 'No usable epochs', result: null }] }
    request.mockResolvedValueOnce(partial).mockResolvedValueOnce(partial).mockResolvedValueOnce({ ...partial, status: 'queued' })
    const wrapper = mount(PreprocessingCard, { props: { output: { plan_ref: { id: 'plan', sha256: 'plan' } } } })
    await flushPromises()
    expect(wrapper.text()).toContain('No usable epochs')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(request).toHaveBeenLastCalledWith('/api/preprocessing/jobs/job/retry', { method: 'POST' })
    wrapper.unmount()
  })

  it('cleans up polling on unmount', async () => {
    vi.useFakeTimers()
    request.mockResolvedValue({ job_id: 'job', status: 'running', completed: 0, total: 1, records: [] })
    const wrapper = mount(PreprocessingCard, { props: { output: { job_id: 'job' } } })
    await flushPromises()
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(request).toHaveBeenCalledTimes(1)
  })
})
