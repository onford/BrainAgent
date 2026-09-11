import { expect, it } from 'vitest'
import { groupReports, reportHeadings } from './reportNavigation'

it('prioritizes saved results and groups available reports without inventing missing reports', () => {
  const reports = ['survey/reports/statistics.html', 'report/report.html', 'extra.html', 'survey/reports/literature-usage.html'].map(name => ({ name, title: name, description: '说明' }))
  const groups = groupReports(reports)
  expect(groups.map(g => g.id)).toEqual(['results', 'data', 'methods', 'other'])
  expect(groups.flatMap(g => g.reports)).toHaveLength(4)
  expect(groupReports(reports, '方法依据').map(g => g.id)).toEqual(['methods'])
  expect(groupReports(reports, 'missing')).toEqual([])
})

it('keeps section hierarchy while excluding repeated record and hidden headings', () => {
  const doc = document.implementation.createHTMLDocument()
  doc.body.innerHTML = '<main><nav><h2>导航</h2></nav><h2>范围</h2><h3>人群</h3><details><summary>更多</summary><h3>边界</h3></details><div class="subject-list"><h3>重复被试</h3></div><div hidden><h2>隐藏内容</h2></div></main>'
  expect(reportHeadings(doc).map(h => [h.title, h.level])).toEqual([['范围', 2], ['人群', 3], ['边界', 3]])
})
