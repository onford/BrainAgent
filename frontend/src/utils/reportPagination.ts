/** Add searchable pages to large tables and subject lists in the report reader. */
export function installReportPagination(doc: Document) {
  const cleanups: (() => void)[] = []
  const collections: { host: HTMLElement; items: HTMLElement[]; label: string }[] = []
  doc.querySelectorAll<HTMLElement>('main > .table').forEach(host => {
    collections.push({host, items: Array.from(host.querySelectorAll<HTMLElement>('tbody > tr')), label:'记录'})
  })
  doc.querySelectorAll<HTMLElement>('.subject-list').forEach(host => {
    collections.push({host, items: Array.from(host.querySelectorAll<HTMLElement>(':scope > .subject-group')), label:'被试'})
  })
  for (const {host,items,label} of collections) {
    if (items.length <= 20) continue
    let page = 0
    const toolbar = doc.createElement('div')
    toolbar.className = 'report-pagination'
    const input = doc.createElement('input')
    input.type = 'search'; input.placeholder = `搜索${label}…`; input.setAttribute('aria-label',`搜索${label}`)
    const previous = doc.createElement('button'), next = doc.createElement('button'), status = doc.createElement('span')
    previous.textContent = '上一页'; next.textContent = '下一页'; status.setAttribute('aria-live','polite')
    const texts = items.map(item => (item.dataset.search ?? item.textContent ?? '').toLowerCase())
    const render = () => {
      const query = input.value.trim().toLowerCase()
      const matched = items.filter((_, index) => texts[index]!.includes(query))
      const pages = Math.max(1, Math.ceil(matched.length/20))
      page = Math.min(page,pages-1)
      const visible = new Set(matched.slice(page*20,(page+1)*20))
      items.forEach(item => { item.hidden = !visible.has(item) })
      previous.disabled = page === 0; next.disabled = page >= pages-1
      status.textContent = `${matched.length} / ${items.length} ${label} · ${page+1} / ${pages} 页`
      host.scrollTop = 0
    }
    input.oninput = () => {page=0;render()}
    previous.onclick = () => {page--;render()}; next.onclick = () => {page++;render()}
    toolbar.append(input,status,previous,next); host.before(toolbar); render()
    cleanups.push(() => {input.oninput=null;previous.onclick=null;next.onclick=null;toolbar.remove();items.forEach(item=>{item.hidden=false})})
  }
  return () => cleanups.forEach(cleanup=>cleanup())
}
