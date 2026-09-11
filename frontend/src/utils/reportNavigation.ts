import { t } from '../i18n'
export type ReaderReport = { name: string; title: string; description: string }

const sections = [
  { id: 'results', get title() { return t('Processing results') }, get purpose() { return t('Processing and delivery overview') } },
  { id: 'data', get title() { return t('Dataset overview') }, get purpose() { return t('Data scope, cross-checks, and statistics') } },
  { id: 'methods', get title() { return t('Method references') }, get purpose() { return t('Related research and preprocessing evidence') } },
  { id: 'other', get title() { return t('Other reports') }, get purpose() { return t('Supplementary material saved with this workflow') } },
]

const catalog: Record<string, { group: string; hint: string }> = {
  'report/report.html': { group: 'results', get hint() { return t('Processing, evaluation, and delivery') } },
  'survey/reports/dataset-basic.html': { group: 'data', get hint() { return t('Source, license, and task scope') } },
  'survey/reports/data-information.html': { group: 'data', get hint() { return t('Local data, official sources, and paper cross-checks') } },
  'survey/reports/statistics.html': { group: 'data', get hint() { return t('Subjects, channels, and events') } },
  'survey/reports/literature-usage.html': { group: 'methods', get hint() { return t('Dataset analysis and algorithm applications') } },
  'survey/reports/literature-discussion.html': { group: 'methods', get hint() { return t('Data characteristics, issues, and limitations') } },
  'survey/reports/literature-preprocessing.html': { group: 'methods', get hint() { return t('Processing methods and parameter rationale') } },
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
