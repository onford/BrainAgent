import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ChatView from './ChatView.vue'

const { deleteSession, fetchSessions, writeText } = vi.hoisted(() => ({
  deleteSession: vi.fn(),
  fetchSessions: vi.fn(),
  writeText: vi.fn(),
}))

vi.mock('../api/sessions', () => ({
  createSession: vi.fn(),
  deleteSession,
  fetchSessions,
}))

vi.mock('../api/chat', () => ({ streamChat: vi.fn() }))

const session = {
  id: 'session-1',
  created_at: '2026-09-04T08:00:00Z',
  updated_at: '2026-09-04T08:00:00Z',
  messages: [
    {
      id: 'user-1',
      role: 'user',
      content: 'Tell me more',
      created_at: '2026-09-04T08:00:00Z',
    },
    {
      id: 'assistant-1',
      role: 'assistant',
      content: '## Result\n\n**EEG** evidence',
      created_at: '2026-09-04T08:00:01Z',
    },
  ],
} as const

describe('ChatView', () => {
  beforeEach(() => {
    fetchSessions.mockReset().mockResolvedValue(structuredClone([session]))
    deleteSession.mockReset().mockResolvedValue(undefined)
    writeText.mockReset().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  it('renders assistant markdown and copies both message roles', async () => {
    const wrapper = mount(ChatView, {
      global: {
        plugins: [createPinia()],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    await flushPromises()

    expect(wrapper.get('.markdown-content').html()).toContain('<h2>Result</h2>')
    expect(wrapper.findAll('.message-copy-button')).toHaveLength(2)
    await wrapper.findAll('.message-copy-button')[1].trigger('click')
    await flushPromises()

    expect(writeText).toHaveBeenCalledWith('## Result\n\n**EEG** evidence')
    expect(wrapper.text()).toContain('已复制')
  })

  it('deletes a confirmed session from the server and sidebar', async () => {
    const wrapper = mount(ChatView, {
      global: {
        plugins: [createPinia()],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    await flushPromises()

    await wrapper.get('.session-delete').trigger('click')
    await flushPromises()

    expect(deleteSession).toHaveBeenCalledWith('session-1')
    expect(wrapper.find('.session-item-shell').exists()).toBe(false)
  })
})
