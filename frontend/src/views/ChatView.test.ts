import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ChatView from './ChatView.vue'
import { useChatStore } from '../stores/chat'
import * as markdown from '../utils/markdown'
import { nextTick } from 'vue'

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

  it('coalesces scrolling and preserves the position while reading earlier messages', async () => {
    const frames: FrameRequestCallback[] = []
    const requestFrame = vi.spyOn(window, 'requestAnimationFrame').mockImplementation(callback => { frames.push(callback); return 17 })
    const cancelFrame = vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => undefined)
    const pinia = createPinia()
    const wrapper = mount(ChatView, { global: { plugins: [pinia], stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    try {
      await flushPromises()
      expect(frames).toHaveLength(1)
      frames.shift()!(0)
      const scroller = wrapper.get('.conversation-scroll')
      Object.defineProperties(scroller.element, { scrollHeight: { value: 2000 }, clientHeight: { value: 500 } })
      scroller.element.scrollTop = 300
      await scroller.trigger('scroll')
      const message = useChatStore(pinia).activeMessages[1]!
      message.content += '\nUpdate while reading'
      await nextTick()
      expect(frames).toHaveLength(0)
      expect(scroller.element.scrollTop).toBe(300)
      scroller.element.scrollTop = 1500
      await scroller.trigger('scroll')
      message.content += '\nFirst update'
      await nextTick()
      message.content += '\nSecond update'
      await nextTick()
      expect(frames).toHaveLength(1)
      wrapper.unmount()
      expect(cancelFrame).toHaveBeenCalledWith(17)
    } finally { wrapper.unmount(); requestFrame.mockRestore(); cancelFrame.mockRestore() }
  })

  it('does not reparse history when typing, copying, or receiving activity updates', async () => {
    const messages = Array.from({ length: 120 }, (_, index) => ({ ...session.messages[1], id: `assistant-${index}` }))
    fetchSessions.mockResolvedValue([{ ...session, messages }])
    const render = vi.spyOn(markdown, 'renderMarkdown')
    const pinia = createPinia()
    const wrapper = mount(ChatView, { global: { plugins: [pinia], stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    try {
      await flushPromises()
      expect(render).toHaveBeenCalledTimes(120)
      render.mockClear()
      await wrapper.get('textarea').setValue('new question')
      await wrapper.findAll('.message-copy-button')[0]!.trigger('click')
      await flushPromises()
      const store = useChatStore(pinia)
      store.activeMessages[119]!.activities = [{ id: 'event', event_type: 'thought', agent_name: null, message: 'planning', timestamp: '' }]
      await nextTick()
      expect(render).not.toHaveBeenCalled()
      store.activeMessages[119]!.content = '**Updated result**'
      await nextTick()
      expect(render).toHaveBeenCalledOnce()
      expect(wrapper.findAll('.markdown-content')[119]!.html()).toContain('<strong>Updated result</strong>')
    } finally { wrapper.unmount(); render.mockRestore() }
  })

  it('only mounts completed activity details when expanded', async () => {
    fetchSessions.mockResolvedValue([{ ...session, messages: [{ ...session.messages[1], activities: Array.from({ length: 500 }, (_, index) => ({ id: `event-${index}`, event_type: 'thought', message: `step-${index}`, timestamp: '' })) }] }])
    const wrapper = mount(ChatView, { global: { plugins: [createPinia()], stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
    try {
      await flushPromises()
      expect(wrapper.findAll('.activity-item')).toHaveLength(0)
      const details = wrapper.get('details')
      ;(details.element as HTMLDetailsElement).open = true
      await details.trigger('toggle')
      expect(wrapper.findAll('.activity-item')).toHaveLength(500)
    } finally { wrapper.unmount() }
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
    wrapper.unmount()
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
    wrapper.unmount()
  })
})
