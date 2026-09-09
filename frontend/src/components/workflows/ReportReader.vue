<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'

type Report = { name: string; title: string; description: string }
const props = defineProps<{ reports: Report[]; workflowId: string; fileUrl: (name: string, download?: boolean) => string; focused: boolean }>()
const emit = defineEmits<{ focus: []; exitFocus: [] }>()
const selected = ref('')
const report = computed(() => props.reports.find(r => r.name === selected.value) ?? props.reports[0])
const frame = ref<HTMLIFrameElement>()
const headings = shallowRef<{ title: string; element: HTMLElement }[]>([])
const loading = ref(true)
const loadError = ref(false)
let detach: (() => void) | undefined
const positions = new Map<string, number>()
function choose(name: string) {
  if (report.value) {
    try { positions.set(report.value.name, frame.value?.contentDocument?.scrollingElement?.scrollTop ?? 0) } catch { /* External navigation cannot expose scroll position. */ }
  }
  selected.value = name
}

watch(() => props.workflowId, () => { selected.value = ''; headings.value = []; positions.clear() })
watch(() => report.value?.name, () => { loading.value = true; loadError.value = false; headings.value = []; detach?.() })
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
    if (doc.scrollingElement && report.value) doc.scrollingElement.scrollTop = positions.get(report.value.name) ?? 0
    headings.value = Array.from(doc.querySelectorAll<HTMLElement>('h2')).map(element => ({ title: element.textContent ?? '', element }))
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') emit('exitFocus') }
    doc.addEventListener('keydown', escape)
    detach = () => doc.removeEventListener('keydown', escape)
  } catch { loadError.value = true }
}
onBeforeUnmount(() => detach?.())
</script>

<template>
  <section class="report-reader" aria-label="报告阅读区">
    <aside class="report-navigation">
      <p class="nav-caption">报告目录 <span>{{reports.length}}</span></p>
      <nav aria-label="选择报告">
        <button v-for="(item,index) in reports" :key="item.name" :aria-pressed="report?.name===item.name" :title="item.description" @click="choose(item.name)">
          <span class="report-number">{{String(index+1).padStart(2,'0')}}</span><span>{{item.title}}</span>
        </button>
      </nav>
      <nav v-if="headings.length" class="outline" aria-label="报告章节">
        <p class="nav-caption">本篇章节</p>
        <button v-for="(heading,index) in headings" :key="index" @click="heading.element.scrollIntoView({behavior:'instant',block:'start'})">{{heading.title}}</button>
      </nav>
    </aside>
    <div v-if="report" class="document">
      <header class="document-toolbar"><div><h2>{{report.title}}</h2><p>{{report.description}}</p></div><div class="reader-actions">
        <button @click="emit('focus')">{{focused?'退出专注':'专注阅读'}}</button>
        <a :href="fileUrl(report.name,false)" target="_blank" rel="noopener">新窗口 ↗</a>
        <a :href="fileUrl(report.name)">下载</a>
      </div></header>
      <p v-if="loading" class="reader-notice" role="status">正在载入报告…</p>
      <p v-if="loadError" class="reader-notice" role="alert">报告暂时无法在此预览，请使用“新窗口”或下载查看。</p>
      <iframe :key="workflowId+report.name" ref="frame" :src="fileUrl(report.name,false)" :title="report.title" sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-downloads" @load="loaded" />
    </div>
    <div v-else class="reader-empty"><span class="empty-icon">▤</span><h2>报告将在调研完成后出现在这里</h2><p>上方可以查看进度，执行日志中保留当前操作与处理记录。</p></div>
  </section>
</template>

<style scoped>
.report-reader{display:grid;grid-template-columns:210px minmax(0,1fr);height:100%;min-height:0}.report-navigation{background:#f7f9f8;border-right:1px solid #e4eae6;padding:20px 12px;overflow-y:auto}.nav-caption{font-size:11px;font-weight:650;color:#73837a;letter-spacing:.08em;padding:0 10px;margin:0 0 12px;display:flex;justify-content:space-between}nav button{display:flex;gap:10px;align-items:baseline;width:100%;border:0;background:transparent;text-align:left;font:inherit;font-size:13px;line-height:1.5;color:#4e6157;padding:11px 10px;margin:2px 0;border-radius:7px;cursor:pointer}nav button:hover{background:#eaf0ec}nav button[aria-pressed=true]{background:#e1eee6;color:#1b5b3e;font-weight:650}.report-number{font-size:10px;opacity:.65;font-variant-numeric:tabular-nums}.outline{border-top:1px solid #dfe7e2;padding-top:22px;margin-top:22px}.outline button{font-size:12px;border-left:2px solid #dde6e0;border-radius:0;padding:6px 12px;margin-left:10px;width:calc(100% - 10px)}.document{display:flex;flex-direction:column;min-width:0;min-height:0;background:white}.document-toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:18px 24px;border-bottom:1px solid #e7ece9;flex-shrink:0}.document-toolbar h2{font-size:16px;margin:0 0 3px;color:#233e30}.document-toolbar p{font-size:12px;color:#7b8780;margin:0}.reader-actions{display:flex;gap:14px;align-items:center;flex-shrink:0;font-size:12px}.reader-actions button{font:inherit;border:1px solid #d6e2da;background:white;color:#315d45;border-radius:6px;padding:6px 10px;cursor:pointer}a{color:#35684e;text-decoration:none}a:hover{text-decoration:underline}iframe{width:100%;flex:1;min-height:0;border:0}.reader-notice{font-size:13px;padding:8px 24px;margin:0;background:#f3f7f4;color:#557462}.reader-empty{display:flex;align-items:center;justify-content:center;flex-direction:column;padding:30px;text-align:center;color:#718278}.reader-empty h2{font-size:18px;color:#34513e}.reader-empty p{font-size:13px}.empty-icon{font-size:32px;color:#89a693}:is(button,a):focus-visible{outline:2px solid #438a64;outline-offset:3px}@media(max-width:900px){.report-reader{grid-template-columns:175px minmax(0,1fr)}.document-toolbar{padding:12px 16px;flex-wrap:wrap}.document-toolbar p{display:none}.report-navigation{padding:16px 7px}}@media(max-width:600px){.report-reader{display:flex;flex-direction:column}.report-navigation{padding:8px;border-right:0;border-bottom:1px solid #e4eae6;overflow-x:auto;overflow-y:hidden;flex-shrink:0}.report-navigation>.nav-caption,.outline{display:none}.report-navigation>nav{display:flex;width:max-content}.report-navigation button{width:auto;padding:8px 12px;white-space:nowrap}.report-number{display:none}.document{flex:1}.document-toolbar{gap:7px}.document-toolbar h2{font-size:14px}.reader-actions{gap:12px}.reader-empty{flex:1}}
</style>
