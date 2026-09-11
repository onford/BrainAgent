import { describe, expect, it } from 'vitest'
import { installReportPagination } from './reportPagination'
import { nextTick } from 'vue'
import { setLocale } from '../i18n'

describe('report pagination', () => {
  it('switches toolbar language without changing the page or report rows', async () => {
    const doc = document.implementation.createHTMLDocument()
    doc.body.innerHTML = '<main><div class="table"><table><tbody>' + Array.from({length:45}, (_,i) => `<tr><td>被试 ${i}</td></tr>`).join('') + '</tbody></table></div></main>'
    const cleanup = installReportPagination(doc)
    doc.querySelectorAll<HTMLButtonElement>('button')[1]!.click()
    const visible = () => [...doc.querySelectorAll<HTMLTableRowElement>('tr')].filter(row => !row.hidden).map(row => row.textContent)
    const before = visible()
    setLocale('en'); await nextTick()
    expect(doc.querySelector('input')!.placeholder).toBe('Search Records…')
    expect(doc.querySelector('.report-pagination')!.textContent).toContain('Page 2 / 3')
    expect(visible()).toEqual(before)
    cleanup()
    setLocale('zh'); await nextTick()
    expect(doc.querySelector('.report-pagination')).toBeNull()
  })
  it('searches every row, resets pages, and restores the document on cleanup', () => {
    const doc = document.implementation.createHTMLDocument()
    doc.body.innerHTML = '<main><div class="table"><table><tbody>' + Array.from({length:109},(_,i)=>`<tr><td>S${String(i+1).padStart(3,'0')}</td></tr>`).join('') + '</tbody></table></div></main>'
    const cleanup = installReportPagination(doc)
    const visible = () => Array.from(doc.querySelectorAll<HTMLTableRowElement>('tr')).filter(row=>!row.hidden)
    expect(visible()).toHaveLength(20)
    doc.querySelectorAll<HTMLButtonElement>('button')[1]!.click()
    expect(visible()[0]!.textContent).toBe('S021')
    const input = doc.querySelector('input')!
    input.value = 'S109'; input.dispatchEvent(new Event('input'))
    expect(visible()).toHaveLength(1)
    expect(visible()[0]!.textContent).toBe('S109')
    input.value = 'missing'; input.dispatchEvent(new Event('input'))
    expect(visible()).toHaveLength(0)
    cleanup()
    expect(visible()).toHaveLength(109)
    expect(doc.querySelector('.report-pagination')).toBeNull()
  })
})
