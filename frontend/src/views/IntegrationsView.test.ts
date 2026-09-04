import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import IntegrationsView from './IntegrationsView.vue'

const { fetchIntegrations, saveIntegration } = vi.hoisted(() => ({
  fetchIntegrations: vi.fn(),
  saveIntegration: vi.fn(),
}))

vi.mock('../api/integrations', () => ({
  fetchIntegrations,
  saveIntegration,
  validateIntegration: vi.fn(),
  deleteIntegration: vi.fn(),
}))

const github = {
  id: 'github',
  name: 'GitHub',
  description: 'Search repositories',
  category: 'code',
  credential_requirement: 'optional',
  credential_schema: [
    {
      key: 'token',
      label: 'Personal access token',
      type: 'secret',
      required: false,
      options: [],
      configured: true,
      value: null,
      masked_value: '********',
    },
  ],
  cost_policy: { tier: 'free', summary: 'Free API', requires_user_approval: false },
  configured: true,
  enabled: true,
  status: 'unvalidated',
  last_validated_at: null,
  last_validation_error: null,
} as const

describe('IntegrationsView', () => {
  beforeEach(() => {
    fetchIntegrations.mockReset().mockResolvedValue([github])
    saveIntegration.mockReset().mockResolvedValue(github)
  })

  it('renders server-defined secret fields without exposing their value', async () => {
    const wrapper = mount(IntegrationsView, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    const input = wrapper.get('input[type="password"]')
    expect(input.attributes('placeholder')).toBe('********')
    expect((input.element as HTMLInputElement).value).toBe('')
    expect(wrapper.text()).not.toContain('top-secret-token')
  })

  it('sends only a newly entered secret when saving', async () => {
    const wrapper = mount(IntegrationsView, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()
    await wrapper.get('input[type="password"]').setValue('replacement-token')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(saveIntegration).toHaveBeenCalledWith('github', {
      enabled: true,
      credentials: { token: 'replacement-token' },
      remove_credentials: [],
    })
  })
})
