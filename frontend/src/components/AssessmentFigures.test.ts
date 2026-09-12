import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AssessmentPlot from './AssessmentPlot.vue'
import AssessmentHeatmap from './AssessmentHeatmap.vue'
import { serializeSvg } from '../utils/assessmentPlots'
import { axisDomain, colorDomain, seriesStyle } from '../utils/figureStyle'
const lineProps = { title:'PSD', caption:'No interpolation', xLabel:'Hz', yLabel:'dB', series:[{id:'PSD',name:'PSD',points:[{x:0,y:1},{x:1,y:null},{x:2,y:3}]}] }
const spec = (w: ReturnType<typeof mount>) => JSON.parse(w.find('metadata').text())
const svgText = (w: ReturnType<typeof mount>) => serializeSvg(w.find('svg').element as unknown as SVGSVGElement)
describe('reproducible scientific figures', () => {
  it('exports identically across time, remounts and surrounding DOM changes', () => {
    vi.useFakeTimers()
    try {
      const a=mount(AssessmentPlot,{props:lineProps}), initial=svgText(a)
      vi.setSystemTime(new Date('2040-01-01')); document.body.style.fontSize='40px'
      const b=mount(AssessmentPlot,{props:lineProps})
      expect(svgText(b)).toBe(initial); expect(initial).toContain('width="183mm"')
      expect(initial).toContain('series-legend'); expect(initial).not.toContain('data-v-')
      expect(new DOMParser().parseFromString(initial,'image/svg+xml').querySelector('parsererror')).toBeNull()
      expect(spec(a).rendering.smoothing).toBe('none'); a.unmount(); b.unmount()
    } finally {vi.useRealTimers(); document.body.style.fontSize=''}
  })
  it('keeps missing endpoints on the x axis and breaks curves at gaps', async () => {
    const w=mount(AssessmentPlot,{props:lineProps}), x=spec(w).rendering.xDomain
    expect(w.find('.data-line').attributes('d').match(/M/g)).toHaveLength(2)
    await w.setProps({series:[{id:'PSD',name:'PSD',points:[{x:0,y:1},{x:1,y:2},{x:2,y:null}]}]})
    expect(spec(w).rendering.xDomain).toEqual(x); expect(w.findAll('.data-marker')).toHaveLength(2)
  })
  it('assigns styles by identity and uses subject IDs as categorical ticks', async () => {
    const series=['eegnet','csp_lda'].map(id=>({id,name:id,connect:false,points:[{x:1,y:.6,label:'S001'},{x:2,y:null,label:'S002'}]}))
    const w=mount(AssessmentPlot,{props:{...lineProps,series,categorical:true,yDomain:[0,1]}}), styles=spec(w).rendering.styles
    expect(spec(w).rendering.xTicks).toEqual([{value:1,label:'S001'},{value:2,label:'S002'}])
    await w.setProps({series:[...series].reverse()}); expect(spec(w).rendering.styles).toEqual([...styles].reverse())
    expect(seriesStyle('eegnet').marker).not.toBe(seriesStyle('csp_lda').marker)
  })
  it('handles large traces, constants, and missing-only data', () => {
    expect(axisDomain(Array.from({length:200000},(_,i)=>i))).toEqual([0,200000])
    for(const v of [0,1e-9,-5]) {const [lo,hi]=colorDomain([v,v]);expect(lo).toBeLessThan(v);expect(hi).toBeGreaterThan(v)}
    const w=mount(AssessmentPlot,{props:{...lineProps,series:[{name:'empty',points:[{x:0,y:null}]}]}})
    expect(w.find('svg').exists()).toBe(false)
  })
  it('keeps reconstruction-style scatter labels from becoming categorical coordinates', () => {
    const w=mount(AssessmentPlot,{props:{...lineProps,series:[{name:'cases',connect:false,points:[{x:1,y:2,label:'case A'},{x:2,y:3,label:'case B'}]}]}})
    expect(spec(w).rendering.xTicks.every((v:{label:string})=>!v.label.includes('case'))).toBe(true)
  })
  it('keeps cell geometry, viewBox and scale on sparse last pages and restores the same SVG', async () => {
    const rows=Array.from({length:25},(_,i)=>'E'+i),columns=Array.from({length:65},(_,i)=>i+' Hz')
    const values=rows.map((_,r)=>columns.map((_,c)=>r+c===88?100:r===0&&c===0?null:0))
    const w=mount(AssessmentHeatmap,{props:{title:'Map',rows,columns,values,unit:'%',caption:'All pages',diverging:true}})
    const initial=svgText(w),cell=w.find('.heatmap-cell').attributes('width'),box=w.find('svg').attributes('viewBox')
    expect(spec(w).rendering.colorLimits).toEqual([-100,100]);expect(w.find('.colorbar').exists()).toBe(true)
    const next=()=>w.findAll('button').filter(b=>b.text().includes('下一'))
    await next()[0]!.trigger('click');await next()[1]!.trigger('click')
    expect(w.find('.heatmap-cell').attributes('width')).toBe(cell);expect(w.find('svg').attributes('viewBox')).toBe(box)
    expect(spec(w).rendering.colorLimits).toEqual([-100,100]);expect(spec(w).rendering.rowIndices).toEqual([24]);expect(spec(w).rendering.columnIndices).toEqual([64])
    const prev=()=>w.findAll('button').filter(b=>b.text().includes('上一'))
    await prev()[0]!.trigger('click');await prev()[1]!.trigger('click');const result=svgText(w); const mismatch=[...initial].findIndex((ch,i)=>ch!==result[i]); expect(result.slice(Math.max(0,mismatch-80),mismatch+160)).toBe(initial.slice(Math.max(0,mismatch-80),mismatch+160)); expect(result === initial).toBe(true)
  })
  it('distinguishes zero from missing and shares an explicit scale across panels', () => {
    const props={title:'ERDS',rows:['8 Hz'],columns:['0','1','2'],values:[[null,0,20]],unit:'%',caption:'matched',diverging:true,colorLimits:[-100,100] as [number,number]}
    const a=mount(AssessmentHeatmap,{props}),b=mount(AssessmentHeatmap,{props:{...props,values:[[-100,0,100]]}})
    expect(a.findAll('.heatmap-cell')[0]!.attributes('fill')).not.toBe(a.findAll('.heatmap-cell')[1]!.attributes('fill'))
    expect(a.findAll('.heatmap-cell')[1]!.attributes('fill')).toBe(b.findAll('.heatmap-cell')[1]!.attributes('fill'))
    expect(spec(a).rendering.colorLimits).toEqual(spec(b).rendering.colorLimits)
  })
  it('shows both time edges in a complete TFR without interpolating masked samples', () => {
    const rows = ['8 Hz', '10 Hz'], columns = Array.from({length:81}, (_,i) => `${i / 40} s`)
    const values = rows.map(() => columns.map((_,i) => i < 5 || i > 75 ? null : i))
    const w = mount(AssessmentHeatmap, { props: { title:'TFR', rows, columns, values, unit:'%', caption:'full interval', fullMatrix:true, reverseRows:true, diverging:true } })
    expect(spec(w).rendering.columnIndices).toHaveLength(81)
    expect(spec(w).rendering.rowIndices).toEqual([1,0])
    expect(w.findAll('.heatmap-cell')).toHaveLength(162)
    expect(w.find('.pagination').text()).toBe('')
    expect(w.findAll('.heatmap-cell')[0]!.attributes('fill')).toBe(w.findAll('.heatmap-cell')[80]!.attributes('fill'))
  })
})
