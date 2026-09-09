import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ReportReader from './ReportReader.vue'

describe('ReportReader', () => {
  it('builds chapter navigation from the report and restores its reading position', async () => {
    const wrapper = mount(ReportReader, {props:{workflowId:'run',focused:false,fileUrl:(name:string)=>`/${name}`,reports:[
      {name:'one.html',title:'第一篇',description:'范围'}, {name:'two.html',title:'第二篇',description:'文献'},
    ]}})
    function attachDocument() {
      const doc = document.implementation.createHTMLDocument('report')
      doc.body.innerHTML='<main><h1>原始标题</h1><h2>统计范围</h2><p>保留的正文</p></main>'
      Object.defineProperty(doc,'scrollingElement',{value:doc.documentElement})
      Object.defineProperty(wrapper.get('iframe').element,'contentDocument',{value:doc,configurable:true})
      return doc
    }
    const first = attachDocument()
    const scroll = vi.fn()
    first.querySelector('h2')!.scrollIntoView = scroll
    await wrapper.get('iframe').trigger('load')
    await wrapper.get('.outline button').trigger('click')
    expect(scroll).toHaveBeenCalled()
    first.documentElement.scrollTop = 640
    await wrapper.findAll('nav[aria-label="选择报告"] button')[1]!.trigger('click')
    const second = attachDocument()
    await wrapper.get('iframe').trigger('load')
    expect(second.documentElement.scrollTop).toBe(0)
    await wrapper.findAll('nav[aria-label="选择报告"] button')[0]!.trigger('click')
    const restored = attachDocument()
    await wrapper.get('iframe').trigger('load')
    expect(restored.documentElement.scrollTop).toBe(640)
    expect(restored.body.textContent).toContain('保留的正文')
    restored.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))
    expect(wrapper.emitted('exitFocus')).toHaveLength(1)
    const remove = vi.spyOn(restored,'removeEventListener')
    wrapper.unmount()
    expect(remove).toHaveBeenCalledWith('keydown',expect.any(Function))
  })

  it('shows a fallback for unavailable HTML and resets selection between workflows', async () => {
    const props = {workflowId:'one',focused:false,fileUrl:(name:string)=>`/${name}`,reports:[{name:'a',title:'甲',description:''},{name:'b',title:'乙',description:''}]}
    const wrapper = mount(ReportReader,{props})
    await wrapper.findAll('nav[aria-label="选择报告"] button')[1]!.trigger('click')
    Object.defineProperty(wrapper.get('iframe').element,'contentDocument',{value:null})
    await wrapper.get('iframe').trigger('load')
    expect(wrapper.get('[role="alert"]').text()).toContain('暂时无法')
    await wrapper.setProps({workflowId:'two'})
    await flushPromises()
    expect(wrapper.get('iframe').attributes('src')).toBe('/a')
    wrapper.unmount()
  })
})
