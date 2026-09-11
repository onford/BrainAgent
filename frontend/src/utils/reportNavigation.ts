export type ReaderReport = { name: string; title: string; description: string }

const sections = [
  { id: 'results', title: '处理结果', purpose: '了解处理过程与交付内容' },
  { id: 'data', title: '数据认识', purpose: '确认数据范围、核对结果与统计' },
  { id: 'methods', title: '方法依据', purpose: '查阅相关研究与预处理依据' },
  { id: 'other', title: '其他报告', purpose: '本流程保存的补充材料' },
]

const catalog: Record<string, { group: string; hint: string }> = {
  'report/report.html': { group: 'results', hint: '处理过程、评价与交付' },
  'survey/reports/dataset-basic.html': { group: 'data', hint: '来源、许可与任务范围' },
  'survey/reports/data-information.html': { group: 'data', hint: '本地、官网与论文核对' },
  'survey/reports/statistics.html': { group: 'data', hint: '被试、通道与事件规模' },
  'survey/reports/literature-usage.html': { group: 'methods', hint: '数据集的分析与算法应用' },
  'survey/reports/literature-discussion.html': { group: 'methods', hint: '数据特点、问题与限制' },
  'survey/reports/literature-preprocessing.html': { group: 'methods', hint: '处理方法与参数依据' },
}

export function groupReports(reports: ReaderReport[], query = '') {
  const search = query.trim().toLowerCase()
  return sections.map(section => ({ ...section, reports: reports
    .filter(report => (catalog[report.name]?.group ?? 'other') === section.id)
    .map(report => ({ ...report, hint: catalog[report.name]?.hint ?? report.description }))
    .filter(report => `${report.title} ${report.description} ${report.hint} ${section.title}`.toLowerCase().includes(search)),
  })).filter(section => section.reports.length)
}

export type ReportHeading = { title: string; level: number; element: HTMLElement }
export function reportHeadings(doc: Document): ReportHeading[] {
  return Array.from(doc.querySelectorAll<HTMLElement>('main h2, main h3'))
    .filter(element => !element.closest('nav, table, .subject-list, .observation-record, [hidden]'))
    .map(element => ({ title: element.textContent?.trim() ?? '', level: Number(element.tagName.slice(1)), element }))
    .filter(heading => heading.title)
}
