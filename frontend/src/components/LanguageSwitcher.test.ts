import { defineComponent, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LanguageSwitcher from './LanguageSwitcher.vue'
import SearchParameters from './SearchParameters.vue'
import { setLocale } from '../i18n'

describe('Language switcher', () => {
  it('updates parameter labels in place without resetting open sections or input', async () => {
    setLocale('en')
    const wrapper = mount(defineComponent({
      components: { LanguageSwitcher, SearchParameters },
      template: `<LanguageSwitcher /><input value="用户输入 EEG" /><SearchParameters :expanded="true" :protocol="{utility_protocol:{eegnet:{training:{max_epochs:100,patience:15}}}}" />`,
    }))
    const details = wrapper.get('details').element
    expect(wrapper.text()).toContain('Maximum epochs')
    expect(wrapper.text()).toContain('Early-stopping patience')
    await wrapper.get('input').setValue('My unchanged draft')
    await wrapper.get('button[lang="zh-CN"]').trigger('click')
    expect(wrapper.get('details').element).toBe(details)
    expect((details as HTMLDetailsElement).open).toBe(true)
    expect(wrapper.text()).toContain('训练轮数上限')
    expect(wrapper.get('input').element.value).toBe('My unchanged draft')
    await wrapper.get('button[lang="en"]').trigger('click')
    await nextTick()
    expect(wrapper.text()).toContain('Maximum epochs')
    expect(wrapper.get('button[lang="en"]').attributes('aria-pressed')).toBe('true')
    wrapper.unmount()
  })
})
