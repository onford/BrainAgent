import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import PreprocessingUnitsView from './PreprocessingUnitsView.vue'
import { apiRequest } from '../api/client'
vi.mock('../api/client', () => ({ apiRequest: vi.fn(), apiUrl: (p: string) => p }))
afterEach(() => vi.clearAllMocks())

it('shows unverified and missing dependencies separately and preserves conditional profiles', async () => {
  const row = { identity: 'EEG-WICA/wica_apply/variant=ordinary', unit_id: 'EEG-WICA', op: 'wica_apply', profile: 'variant=ordinary', input_kind: 'raw', effect: 'preserve', fit: false, model_kind: 'ica', decision: true, profile_parameters: { variant: 'ordinary' }, parameters: { required: ['variant'], properties: { variant: { type: 'string' }, eye_weights: { type: ['array', 'null'], default: null } } }, status: { collected: true, adapted: false, compiled: false, executed: false, numerically_verified: false, real_data_verified: false, current_input_applicable: null, dependency_missing: [{ name: 'asset' }] }, source_fields: {}, verification: {} }
  vi.mocked(apiRequest).mockResolvedValueOnce({ rows: [row] }).mockResolvedValueOnce({ operators: [] })
  const wrapper = mount(PreprocessingUnitsView, { global: { stubs: { RouterLink: true } } })
  await flushPromises(); expect(wrapper.text()).toContain('0 项数值验证通过'); expect(wrapper.text()).toContain('依赖缺失')
  await wrapper.get('.catalog button').trigger('click')
  const value = JSON.parse((wrapper.get('textarea').element as HTMLTextAreaElement).value)
  expect(value.params.variant).toBe('ordinary'); expect(value.params).not.toHaveProperty('eye_weights'); expect(value.decision.status).toBe('pending')
  wrapper.unmount()
})
