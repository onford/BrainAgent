<script setup lang="ts">
import { t } from '../../i18n'
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { groupReports, reportHeadings, type ReaderReport, type ReportHeading } from '../../utils/reportNavigation'
import { installReportPagination } from '../../utils/reportPagination'

type Report = ReaderReport
const props = defineProps<{ reports: Report[]; workflowId: string; fileUrl: (name: string, download?: boolean) => string; focused: boolean }>()
const emit = defineEmits<{ focus: []; exitFocus: [] }>()
const selected = ref('')
const query = ref(''), navigationMode = ref('reports'), navigationOpen = ref(false)
const groups = computed(() => groupReports(props.reports, query.value))
const ordered = computed(() => groupReports(props.reports).flatMap(group => group.reports))
const report = computed(() => props.reports.find(r => r.name === selected.value) ?? ordered.value[0])
const activeHeading = ref(-1)
const sectionCount = computed(() => headings.value.filter(h => h.level === 2).length)
const frame = ref<HTMLIFrameElement>()
const headings = shallowRef<ReportHeading[]>([])
const loading = ref(true)
const loadError = ref(false)
let detach: (() => void) | undefined
const positions = new Map<string, number>()
watch(ordered, available => {
  if (!available.some(item => item.name === selected.value)) selected.value = available[0]?.name ?? ''
}, { immediate: true })
function choose(name: string) {
  if (report.value) {
    try { positions.set(report.value.name, frame.value?.contentDocument?.scrollingElement?.scrollTop ?? 0) } catch { /* External navigation cannot expose scroll position. */ }
  }
  selected.value = name
  navigationOpen.value = false
}

watch(() => props.workflowId, () => { selected.value = ordered.value[0]?.name ?? ''; query.value = ''; navigationMode.value = 'reports'; headings.value = []; positions.clear(); activeHeading.value = -1 })
watch([() => props.workflowId, () => report.value?.name], () => { loading.value = true; loadError.value = false; headings.value = []; activeHeading.value = -1; detach?.() })
function loaded() {
  loading.value = false
  detach?.()
  try {
    const doc = frame.value?.contentDocument
    if (!doc?.querySelector('main, h1')) { loadError.value = true; return }
    // Presentation only: the downloaded, versioned HTML stays unchanged.
    const style = doc.createElement('style')
    style.textContent = 'body{background:#fff!important}main{padding:24px 30px!important;max-width:none!important}main>nav,main>p:first-child,main>h1{display:none!important}h2{scroll-margin-top:24px}table{font-size:14px}a{overflow-wrap:anywhere}@media(max-width:600px){main{padding:18px!important}}'
    doc.head.append(style)
    style.textContent += '.report-pagination{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:12px 0;font-size:12px;color:#617368}.report-pagination input{padding:8px 10px;border:1px solid #d4dfd8;border-radius:6px;flex:1;min-width:120px}.report-pagination button{padding:6px 10px;background:#f3f7f4;border:1px solid #d4dfd8;border-radius:5px;color:#365c45;cursor:pointer}.report-pagination button:disabled{opacity:.4;cursor:default}[hidden]{display:none!important}@media print{.report-pagination{display:none}tr[hidden],.subject-group[hidden]{display:revert!important}}'
    const removePagination = installReportPagination(doc)
    if (doc.scrollingElement && report.value) doc.scrollingElement.scrollTop = positions.get(report.value.name) ?? 0
    headings.value = reportHeadings(doc)
    const updatePosition = () => {
      let index = -1
      headings.value.forEach((heading, i) => {
        // Collapsed details and paginated content are not reading positions.
        if (heading.element.getClientRects().length && heading.element.getBoundingClientRect().top <= 80) index = i
      })
      activeHeading.value = index
    }
    doc.addEventListener('scroll', updatePosition, { passive: true })
    updatePosition()
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      const detail = doc.querySelector<HTMLDetailsElement>('.observation-record[open]')
      if (detail) { detail.open = false; detail.querySelector<HTMLElement>('summary')?.focus(); event.preventDefault() }
      else emit('exitFocus')
    }
    doc.addEventListener('keydown', escape)
    detach = () => { doc.removeEventListener('keydown', escape); doc.removeEventListener('scroll', updatePosition); removePagination(); style.remove() }
  } catch { loadError.value = true }
}
function jump(index: number) {
  const heading = headings.value[index]
  if (!heading) return
  let parent = heading.element.parentElement
  while (parent) {
    if (parent.tagName === 'DETAILS') (parent as HTMLDetailsElement).open = true
    parent = parent.parentElement
  }
  heading.element.scrollIntoView({ behavior: 'instant', block: 'start' })
  heading.element.setAttribute('tabindex', '-1')
  heading.element.focus({ preventScroll: true })
  activeHeading.value = index
  navigationOpen.value = false
}
onBeforeUnmount(() => detach?.())
</script>

<template>
  <section class="report-reader" :aria-label="t('Report reader')">
    <button class="directory-toggle" :aria-expanded="navigationOpen" @click="navigationOpen = !navigationOpen">{{ navigationOpen ? t('Hide navigation') : t('Reports and sections') }} <span>{{ report?.title || t('No reports yet') }}</span></button>
    <aside class="report-navigation" :class="{ 'is-open': navigationOpen }" :aria-label="t('Report navigation')">
      <div class="nav-header"><strong>{{ t('Report navigation') }}</strong><span>{{ t('{0} reports', { 0: reports.length }) }}</span></div>
      <div class="navigation-modes" :aria-label="t('Navigation view')">
        <button :aria-pressed="navigationMode === 'reports'" @click="navigationMode = 'reports'">{{ t('All reports') }}</button>
        <button :aria-pressed="navigationMode === 'chapters'" @click="navigationMode = 'chapters'">{{ t('Current report sections') }}<span>{{ headings.length }}</span></button>
      </div>
      <div v-show="navigationMode === 'reports'">
        <label class="report-search"><span>{{ t('Find a report') }}</span><input v-model="query" type="search" :placeholder="t('Title, topic, or purpose')" /></label>
        <nav :aria-label="t('Choose a report')">
          <section v-for="group in groups" :key="group.id" class="report-group">
            <h3>{{ group.title }} <span>{{ group.reports.length }}</span></h3><p class="group-purpose">{{ group.purpose }}</p>
            <button v-for="item in group.reports" :key="item.name" :data-report-name="item.name" :aria-pressed="report?.name === item.name" @click="choose(item.name)">
              <span class="report-title">{{ item.title }}</span><small>{{ item.hint }}</small><span v-if="report?.name === item.name" class="reading-mark">{{ t('Reading') }}</span>
            </button>
          </section>
        </nav>
        <p v-if="!groups.length" class="nav-empty">{{ reports.length ? t('No matching reports. Try another keyword.') : t('Generated reports appear here by topic.') }}</p>
      </div>
      <nav v-show="navigationMode === 'chapters'" class="outline" :aria-label="t('Report sections')">
        <p class="chapter-caption">{{ report?.title }}</p>
        <p v-if="!headings.length" class="nav-empty">{{ loading && report ? t('Loading sections…') : t('This report has no navigable sections.') }}</p>
        <button v-for="(heading,index) in headings" :key="index" :class="{ subheading: heading.level === 3 }" :aria-current="activeHeading === index ? 'location' : undefined" @click="jump(index)">{{ heading.title }}</button>
      </nav>
    </aside>
    <div v-if="report" class="document">
      <header class="document-toolbar"><div><h2>{{report.title}}</h2><p>{{report.description}}</p><small class="source-language">{{ t('Saved content is shown in its original language.') }}</small><small class="document-location" v-if="headings.length">{{ t('{0} main sections', { 0: sectionCount }) }}<span v-if="activeHeading >= 0"> · {{ headings[activeHeading]?.title }}</span></small></div><div class="reader-actions">
        <button @click="emit('focus')">{{focused?t('Exit focus mode'):t('Focus mode')}}</button>
        <a :href="fileUrl(report.name,false)" target="_blank" rel="noopener">{{ t('New window ↗') }}</a>
        <a :href="fileUrl(report.name)">{{ t('Download') }}</a>
      </div></header>
      <p v-if="loading" class="reader-notice" role="status">{{ t('Loading report…') }}</p>
      <p v-if="loadError" class="reader-notice" role="alert">{{ t('This report cannot be previewed here. Open it in a new window or download it.') }}</p>
      <iframe :key="workflowId+report.name" ref="frame" :src="fileUrl(report.name,false)" :title="report.title" sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-downloads" @load="loaded" />
    </div>
    <div v-else class="reader-empty"><span class="empty-icon">▤</span><h2>{{ t('Reports appear here after data research completes') }}</h2><p>{{ t('Progress appears above. Execution logs record current actions and processing details.') }}</p></div>
  </section>
</template>

<style scoped>
.report-reader { display: grid; grid-template-columns: 260px minmax(0,1fr); height: 100%; min-height: 0; }
.report-navigation { padding: 20px 14px; overflow-y: auto; background: #f5f8f8; border-right: 1px solid #dce6e3; }
.nav-header { display: flex; justify-content: space-between; align-items: center; margin: 0 8px 16px; color: #29443c; font-size: 14px; }
.nav-header span, .navigation-modes span { font-size: 11px; color: #60776f; }
.navigation-modes { display: flex; gap: 3px; background: #e9efed; border-radius: 8px; padding: 4px; }
.navigation-modes button { flex: 1; border: 0; background: transparent; padding: 8px 3px; border-radius: 5px; font: inherit; font-size: 12px; color: #587166; cursor: pointer; }
.navigation-modes button[aria-pressed=true] { background: white; color: #1e6551; box-shadow: 0 1px 3px #254b3812; }
.report-search { display: block; margin: 16px 4px; font-size: 11px; color: #60776f; }
.report-search input { width: 100%; box-sizing: border-box; margin-top: 6px; padding: 9px 10px; border: 1px solid #ceded7; border-radius: 7px; font: inherit; font-size: 12px; background: #fff; color: #29443c; }
.report-group { margin-top: 22px; }
.report-group h3 { display: flex; justify-content: space-between; margin: 0 8px 4px; font-size: 12px; color: #49685a; }
.report-group h3 span { font-weight: 400; color: #60776f; }
.group-purpose { margin: 0 8px 9px; font-size: 11px; line-height: 1.6; color: #687e74; }
nav button { display: block; width: 100%; text-align: left; border: 1px solid transparent; background: transparent; border-radius: 8px; padding: 11px 12px; margin: 4px 0; font: inherit; font-size: 13px; line-height: 1.6; color: #39564a; cursor: pointer; }
nav button:hover { background: #eaf1ed; }
nav button[aria-pressed=true] { background: #fff; border-color: #abcabd; box-shadow: inset 3px 0 #397e63; }
.report-title { display: block; font-weight: 550; }
nav button small { display: block; font-size: 11px; color: #60776f; margin-top: 3px; }
.reading-mark { display: inline-block; font-size: 10px; color: #267353; margin-top: 6px; }
.chapter-caption { color: #49685a; font-size: 12px; line-height: 1.8; padding: 12px 8px; margin: 8px 0; border-bottom: 1px solid #dce6e3; }
.outline button { border-radius: 0; border-left: 2px solid #dbe5df; padding: 8px 10px; font-size: 12px; }
.outline button.subheading { padding-left: 23px; color: #60776f; font-size: 11px; }
.outline button[aria-current=location] { color: #176046; border-left-color: #397e63; background: #e5f0e9; font-weight: 600; }
.nav-empty { font-size: 12px; color: #60776f; line-height: 1.8; padding: 12px 8px; }
.document { display: flex; flex-direction: column; min-width: 0; min-height: 0; background: white; }
.document-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 24px; border-bottom: 1px solid #e7ece9; flex-shrink: 0; }
.document-toolbar h2 { font-size: 16px; margin: 0 0 5px; color: #233e30; }
.document-toolbar p { font-size: 12px; line-height: 1.7; color: #60776f; margin: 0; }
.document-location { display: block; font-size: 11px; color: #397e63; margin-top: 6px; }
.reader-actions { display: flex; gap: 14px; align-items: center; flex-shrink: 0; font-size: 12px; }
.reader-actions button { font: inherit; border: 1px solid #d6e2da; background: white; color: #315d45; border-radius: 6px; padding: 6px 10px; cursor: pointer; }
a { color: #35684e; text-decoration: none; } a:hover { text-decoration: underline; }
iframe { width: 100%; flex: 1; min-height: 0; border: 0; }
.reader-notice { font-size: 13px; padding: 8px 24px; margin: 0; background: #f3f7f4; color: #557462; }
.reader-empty { display: flex; align-items: center; justify-content: center; flex-direction: column; padding: 30px; text-align: center; color: #60776f; }
.reader-empty h2 { font-size: 18px; color: #34513e; } .reader-empty p { font-size: 13px; } .empty-icon { font-size: 32px; color: #89a693; }
:is(button,a,input):focus-visible { outline: 2px solid #438a64; outline-offset: 3px; }
.directory-toggle { display: none; }
@media(max-width:1000px) { .report-reader { grid-template-columns: 220px minmax(0,1fr); } .document-toolbar { padding: 12px 16px; flex-wrap: wrap; } }
@media(max-width:700px) {
  .report-reader { display: flex; flex-direction: column; }
  .directory-toggle { display: flex; justify-content: space-between; gap: 12px; padding: 12px 16px; border: 0; border-bottom: 1px solid #dce6e3; background: #f5f8f8; font: inherit; font-size: 12px; color: #315d45; cursor: pointer; }
  .directory-toggle span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #60776f; }
  .report-navigation { display: none; padding: 14px; border-right: 0; max-height: 42vh; flex-shrink: 0; border-bottom: 1px solid #dce6e3; }
  .report-navigation.is-open { display: block; }
  .document { flex: 1; } .document-toolbar { gap: 8px; } .document-toolbar h2 { font-size: 14px; }
  .reader-empty { flex: 1; }
}
</style>
