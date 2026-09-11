import { watch } from 'vue'
import { locale, t } from '../i18n'
/** Add searchable pages to large tables and subject lists in the report reader. */
export function installReportPagination(doc: Document) {
  const cleanups: (() => void)[] = []
  const collections: { host: HTMLElement; items: HTMLElement[]; label: string }[] = []
  doc.querySelectorAll<HTMLElement>('main > .table').forEach(host => {
    collections.push({host, items: Array.from(host.querySelectorAll<HTMLElement>('tbody > tr')), get label() { return t('Records') }})
  })
  doc.querySelectorAll<HTMLElement>('.subject-list').forEach(host => {
    collections.push({host, items: Array.from(host.querySelectorAll<HTMLElement>(':scope > .subject-group')), get label() { return t('Subjects') }})
  })
  for (const collection of collections) {
    const {host,items} = collection
    if (items.length <= 20) continue
    let page = 0
    const toolbar = doc.createElement('div')
    toolbar.className = 'report-pagination'
    const input = doc.createElement('input')
    input.type = 'search'
    const previous = doc.createElement('button'), next = doc.createElement('button'), status = doc.createElement('span')
    status.setAttribute('aria-live','polite')
    const texts = items.map(item => (item.dataset.search ?? item.textContent ?? '').toLowerCase())
    const render = (resetScroll = true) => {
      const label = collection.label
      input.placeholder = t('Search {0}…', { 0: label })
      input.setAttribute('aria-label', t('Search {0}', { 0: label }))
      previous.textContent = t('Previous page'); next.textContent = t('Next page')
      const query = input.value.trim().toLowerCase()
      const matched = items.filter((_, index) => texts[index]!.includes(query))
      const pages = Math.max(1, Math.ceil(matched.length/20))
      page = Math.min(page,pages-1)
      const visible = new Set(matched.slice(page*20,(page+1)*20))
      items.forEach(item => { item.hidden = !visible.has(item) })
      previous.disabled = page === 0; next.disabled = page >= pages-1
      status.textContent = t('{0} / {1} {2} · Page {3} / {4}', { 0: matched.length, 1: items.length, 2: label, 3: page+1, 4: pages })
      if (resetScroll) host.scrollTop = 0
    }
    input.oninput = () => {page=0;render()}
    previous.onclick = () => {page--;render()}; next.onclick = () => {page++;render()}
    toolbar.append(input,status,previous,next); host.before(toolbar); render()
    const stopLocaleWatch = watch(locale, () => render(false))
    cleanups.push(() => {stopLocaleWatch();input.oninput=null;previous.onclick=null;next.onclick=null;toolbar.remove();items.forEach(item=>{item.hidden=false})})
  }
  return () => cleanups.forEach(cleanup=>cleanup())
}
