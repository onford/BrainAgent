import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ReportReader from './ReportReader.vue'
import { nextTick } from 'vue'
import { setLocale } from '../../i18n'

describe('ReportReader', () => {
  it('keeps the report document and reading position when localized titles change', async () => {
    const wrapper = mount(ReportReader, { props: { workflowId: 'run', focused: false, fileUrl: name => `/${name}`, reports: [
      { name: 'report/report.html', title: '处理报告', description: '说明' },
    ] } })
    const frame = wrapper.get('iframe').element
    const doc = document.implementation.createHTMLDocument()
    doc.body.innerHTML = '<main><h2>原始章节</h2><p>原始正文 63.27%</p></main>'
    Object.defineProperty(doc, 'scrollingElement', { value: doc.documentElement })
    Object.defineProperty(frame, 'contentDocument', { value: doc })
    await wrapper.get('iframe').trigger('load')
    doc.documentElement.scrollTop = 320
    setLocale('en')
    await wrapper.setProps({ reports: [{ name: 'report/report.html', title: 'Processing report', description: 'Description' }] })
    await nextTick()
    expect(wrapper.get('iframe').element).toBe(frame)
    expect(doc.documentElement.scrollTop).toBe(320)
    expect(doc.querySelector('main')!.textContent).toBe('原始章节原始正文 63.27%')
    expect(wrapper.text()).toContain('Report navigation')
    expect(wrapper.text()).not.toContain('Loading report…')
    expect(wrapper.get('.outline').text()).toContain('原始章节')
    wrapper.unmount()
  })
  it('keeps the current reading when a result report is generated later', async () => {
    const basic = { name: 'survey/reports/dataset-basic.html', title: '基本信息', description: '范围' }
    const wrapper = mount(ReportReader, { props: { workflowId: 'run', focused: false, fileUrl: name => `/${name}`, reports: [basic] } })
    await wrapper.setProps({ reports: [basic, { name: 'report/report.html', title: '处理结果', description: '过程' }] })
    expect(wrapper.get('iframe').attributes('src')).toBe('/survey/reports/dataset-basic.html')
    wrapper.unmount()
  })
  it('filters the directory without replacing the open report and reveals a nested chapter', async () => {
    const wrapper = mount(ReportReader, { props: { workflowId: 'run', focused: false, fileUrl: name => `/${name}`, reports: [
      { name: 'report/report.html', title: '处理结果', description: '过程' },
      { name: 'survey/reports/statistics.html', title: '统计', description: '被试规模' },
    ] } })
    expect(wrapper.get('iframe').attributes('src')).toBe('/report/report.html')
    await wrapper.get('input[type="search"]').setValue('统计')
    expect(wrapper.findAll('nav[aria-label="选择报告"] button')).toHaveLength(1)
    expect(wrapper.get('iframe').attributes('src')).toBe('/report/report.html')
    const doc = document.implementation.createHTMLDocument()
    doc.body.innerHTML = '<main><h2>概览</h2><details><summary>条件</summary><h3>限制</h3></details></main>'
    Object.defineProperty(wrapper.get('iframe').element, 'contentDocument', { value: doc })
    const scroll = vi.fn()
    doc.querySelector('h3')!.scrollIntoView = scroll
    await wrapper.get('iframe').trigger('load')
    await wrapper.get('.outline .subheading').trigger('click')
    expect(doc.querySelector('details')!.open).toBe(true)
    expect(scroll).toHaveBeenCalledOnce()
    expect(wrapper.get('.outline .subheading').attributes('aria-current')).toBe('location')
    wrapper.unmount()
  })
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
    restored.body.insertAdjacentHTML('beforeend','<details class="observation-record" open><summary>记录详情</summary><p>原始文件头</p></details>')
    restored.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))
    expect(restored.querySelector('details')!.open).toBe(false)
    expect(wrapper.emitted('exitFocus')).toBeUndefined()
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
