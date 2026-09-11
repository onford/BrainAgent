/** Export one saved workflow with the existing Vue UI into a standalone HTML. */
import { readFile, writeFile, mkdir, stat } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'
import { gzipSync } from 'node:zlib'
import { build } from 'vite'
import vue from '@vitejs/plugin-vue'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const project = path.dirname(frontend)
const base = process.env.SNAPSHOT_API_URL || 'http://127.0.0.1:8000'
const workflowRoot = process.env.SNAPSHOT_WORKFLOW_ROOT || path.join(project, 'backend/workspace/training-workflow/workflows')
const output = path.resolve(process.argv[3] || path.join(project, 'exports/BrainAgent-最新运行结果-离线.html'))
async function get(route) {
  const response = await fetch(`${base}${route}`)
  if (!response.ok) throw new Error(`${route}: ${response.status}`)
  return response.json()
}
const jobs = await get('/api/workflows')
const id = process.argv[2] || jobs[0]?.id
if (!/^[a-f0-9]{32}$/.test(id || '')) throw new Error('A saved workflow ID is required.')
const workflow = await get(`/api/workflows/${id}`)
const root = path.resolve(workflowRoot, id)
const embedded = {}
// The reader includes all original reports. Also retain small top-level records
// for offline reading/download; numerical arrays stay in the original workspace.
for (const artifact of workflow.artifacts) {
  const parts = artifact.name.split('/')
  const report = artifact.name.endsWith('.html')
  const record = parts.length <= 2 && /\.(json|tsv|csv|txt|md|py)$/.test(artifact.name) && artifact.bytes <= 3 * 1024 ** 2
  if (!report && !record) continue
  const filename = path.resolve(root, ...parts)
  if (!filename.startsWith(root + path.sep)) throw new Error(`Invalid artifact path: ${artifact.name}`)
  const bytes = await readFile(filename)
  if (bytes.length !== artifact.bytes) throw new Error(`Artifact changed during export: ${artifact.name}`)
  const sha256 = createHash('sha256').update(bytes).digest('hex')
  if (artifact.sha256 && sha256 !== artifact.sha256) throw new Error(`Artifact hash mismatch: ${artifact.name}`)
  const content = bytes.toString('utf8')
  if (report && /<(?:script|iframe|object|embed)\b|\son\w+\s*=|(?:src|poster)\s*=\s*["'](?!data:)[^"']+/i.test(content)) {
    throw new Error(`Report requires a resource review before offline export: ${artifact.name}`)
  }
  embedded[artifact.name] = { content, sha256, type: report ? 'text/html;charset=utf-8' : 'text/plain;charset=utf-8' }
}
const snapshot = { workflow, embedded, capturedAt: new Date().toISOString() }
const data = gzipSync(Buffer.from(JSON.stringify(snapshot)), { level: 9 }).toString('base64')

const runtime = `
export let snapshot;
const urls = new Map();
export async function initialize() {
  const bytes = Uint8Array.from(atob(document.getElementById('snapshot-data').textContent.trim()), c => c.charCodeAt(0));
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  snapshot = JSON.parse(await new Response(stream).text());
}
export const apiUrl = path => path;
export async function apiRequest(path, init = {}) {
  if (init.method && init.method !== 'GET') throw new Error('此文件只展示已保存的运行结果。');
  if (path === '/api/workflows/sources') return {allowed_roots: [snapshot.workflow.request.source_root]};
  if (path === '/api/workflows') return [snapshot.workflow];
  if (path === '/api/workflows/' + snapshot.workflow.id) return snapshot.workflow;
  throw new Error('离线快照未包含此内容。');
}
export function artifactText(name) { return snapshot.embedded[name]?.content || ''; }
export function artifactUrl(name) {
  if (!snapshot.embedded[name]) return '#offline-record=' + encodeURIComponent(name);
  if (!urls.has(name)) {
    const item = snapshot.embedded[name];
    urls.set(name, URL.createObjectURL(new Blob([item.content], {type:item.type})));
  }
  return urls.get(name);
}
export function openRecord(name) {
  const file = snapshot.workflow.artifacts.find(item => item.name === name);
  document.getElementById('offline-record-name').textContent = name;
  document.getElementById('offline-record-meta').textContent = file ? JSON.stringify({name:file.name, bytes:file.bytes, sha256:file.sha256}, null, 2) : name;
  document.getElementById('offline-record-dialog').showModal();
}
export function installOfflineLinks() {
  document.addEventListener('click', event => {
    const link = event.target.closest?.('a');
    if (!link) return;
    const href = link.getAttribute('href') || '';
    if (href.startsWith('#offline-record=')) {
      event.preventDefault();
      const name = decodeURIComponent(href.slice('#offline-record='.length));
      openRecord(name);
    } else if (href.startsWith('blob:') && link.target !== '_blank') {
      const match = [...urls].find(([,url]) => url === href);
      if (match) link.download = match[0].split('/').at(-1);
    }
  });
}
`

const entry = `
import { createApp } from 'vue';
import { createRouter, createMemoryHistory } from 'vue-router';
import WorkflowsView from ${JSON.stringify(path.join(frontend, 'src/views/WorkflowsView.vue').replaceAll('\\', '/'))};
import ${JSON.stringify(path.join(frontend, 'src/style.css').replaceAll('\\', '/'))};
import { initialize, installOfflineLinks, snapshot } from 'virtual:offline-runtime';
(async () => {
  try {
    await initialize();
    const router = createRouter({history:createMemoryHistory(), routes:[{path:'/workflows',component:WorkflowsView}]});
    await router.push({path:'/workflows',query:{id:snapshot.workflow.id}});
    await router.isReady();
    createApp(WorkflowsView).use(router).mount('#app');
    installOfflineLinks();
    document.documentElement.dataset.snapshotReady = 'true';
  } catch (error) {
    document.getElementById('app').textContent = '无法打开离线快照。请使用近期版本的 Edge、Chrome、Firefox 或 Safari。' + error.message;
    console.error(error);
  }
})();
`

function replace(source, before, after) {
  if (!source.includes(before)) throw new Error(`The UI changed; update the offline adapter: ${before.slice(0, 100)}`)
  return source.replace(before, after)
}
const result = await build({
  configFile: false,
  root: frontend,
  logLevel: 'warn',
  define: { 'process.env.NODE_ENV': '"production"' },
  plugins: [{
    name: 'offline-snapshot', enforce: 'pre',
    resolveId(id) {
      if (id.endsWith('virtual:offline-entry')) return '\0virtual:offline-entry'
      if (id === 'virtual:offline-runtime') return '\0virtual:offline-runtime'
    },
    load(id) {
      if (id === '\0virtual:offline-entry') return entry
      if (id === '\0virtual:offline-runtime') return runtime
    },
    transform(source, id) {
      const normalized = id.replaceAll('\\', '/').split('?')[0]
      if (normalized.endsWith('/src/api/client.ts')) return `export {apiUrl, apiRequest} from 'virtual:offline-runtime'`
      if (normalized.endsWith('/src/views/WorkflowsView.vue') && !id.includes('?')) {
        source = replace(source, "import { apiRequest, apiUrl } from '../api/client'", "import { apiRequest } from '../api/client'\nimport { artifactUrl } from 'virtual:offline-runtime'")
        const start = source.indexOf('function fileUrl(')
        const end = source.indexOf('\n}', start)
        if (start < 0 || end < 0) throw new Error('Cannot locate the original artifact URL helper.')
        source = source.slice(0, start) + 'function fileUrl(name: string, download = true) { return artifactUrl(name) }' + source.slice(end + 2)
        source = replace(source, "if(active.value) timer=setTimeout(()=>void refresh(id),2000)", '// This saved state never polls the backend.')
        source = replace(source, "toLocaleString('zh-CN',{month:", "toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:")
        source = replace(source, '<RouterLink to="/" aria-label="返回对话">←</RouterLink>', '<span class="offline-back" aria-label="离线展示">←</span>')
        source = replace(source, '<span class="brand-caption">数据工作区</span>', '<span class="brand-caption">数据工作区 · 离线展示</span>')
        source = replace(source, '<select :value="selectedId"', '<select disabled :value="selectedId"')
        source = replace(source, '<button class="primary new-run" @click="createDialog?.showModal()">', '<button class="primary new-run" disabled title="离线展示，不能新建流程">')
        source = replace(source, '<RouterLink v-if="searchId" class="primary" :to="{path:\'/searches\',query:{id:searchId}}">查看策略搜索 →</RouterLink>', '<button v-if="searchId" class="primary" disabled title="策略搜索详情需在在线工作区查看">查看策略搜索 →</button>')
        source = source.replaceAll(':disabled="busy" @click="retry"', 'disabled title="离线展示"')
        return source
      }
      if (normalized.endsWith('/components/workflows/ReportReader.vue') && !id.includes('?')) {
        source = replace(source, "import { installReportPagination }", "import { artifactText, artifactUrl, openRecord } from 'virtual:offline-runtime'\nimport { installReportPagination }")
        source = replace(source, ':src="fileUrl(report.name,false)"', ':srcdoc="artifactText(report.name)"')
        source = replace(source, 'loading.value = false', 'loading.value = false; loadError.value = false')
        // Reports have a CSP and script-free body. Keep their reference links
        // available in a new tab without navigating away from the saved report.
        source = replace(source, 'doc.head.append(style)', `doc.head.append(style)
    doc.querySelectorAll<HTMLAnchorElement>('a[href]').forEach(link => {
      const href = link.getAttribute('href') || ''
      if (/^https?:/.test(href)) { link.target = '_blank'; link.rel = 'noopener noreferrer' }
      else if (href && !href.startsWith('#') && report.value) {
        const name = decodeURIComponent(new URL(href, 'https://offline.invalid/' + report.value.name).pathname.slice(1))
        if (props.reports.some(item => item.name === name)) {
          link.href = '#report'; link.onclick = event => { event.preventDefault(); choose(name) }
        } else {
          const url = artifactUrl(name)
          if (url.startsWith('#offline-record=')) { link.href = '#record'; link.onclick = event => { event.preventDefault(); openRecord(name) } }
          else { link.href = url; link.download = name.split('/').at(-1) || name }
        }
      }
    })`)
        return source
      }
    },
  }, vue()],
  build: {
    write: false, minify: true, target: 'es2022', cssCodeSplit: false,
    lib: { entry: 'virtual:offline-entry', name: 'BrainAgentSnapshot', formats: ['iife'] },
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
})
const outputs = (Array.isArray(result) ? result : [result]).flatMap(item => item.output)
const js = outputs.filter(item => item.type === 'chunk').map(item => item.code).join('\n')
const css = outputs.filter(item => item.type === 'asset' && item.fileName.endsWith('.css')).map(item => String(item.source)).join('\n')
if (!js || !css) throw new Error('The export must contain both compiled UI and stylesheet.')
const capturedAt = snapshot.capturedAt
const html = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; frame-src 'self' about: blob:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
<meta name="description" content="Brain Agent 已保存运行 ${id} 的离线展示，包含原始报告、执行日志和文件清单。">
<title>Brain Agent · 最新运行结果 · 离线展示</title>
<style>${css}
.workflow-page button:disabled{cursor:default}.offline-back{font-size:18px;color:#8c9c91;margin-right:8px}
#offline-record-dialog{font:14px/1.6 system-ui,sans-serif;border:1px solid #d9e4dc;border-radius:16px;padding:28px;width:min(640px,90vw);color:#314d3b}
#offline-record-dialog::backdrop{background:#19342455}#offline-record-dialog h2{font-size:17px;overflow-wrap:anywhere}#offline-record-dialog pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;background:#f3f7f4;padding:16px;border-radius:8px}#offline-record-dialog button{background:#285e43;color:#fff;border:0;border-radius:7px;padding:8px 18px;cursor:pointer}
</style></head><body>
<!-- Frozen workflow: ${id}; captured: ${capturedAt}; original updated_at: ${workflow.updated_at}. -->
<div id="app"><p style="padding:32px;color:#315b3e;background:#f2f5f3">正在打开已保存的运行结果…</p></div>
<dialog id="offline-record-dialog"><h2 id="offline-record-name"></h2><p>此文件保留在原始运行目录中。离线展示包含完整文件清单；大体积信号、训练数组及逐记录中间文件未嵌入。</p><pre id="offline-record-meta"></pre><form method="dialog"><button>关闭</button></form></dialog>
<noscript>请启用浏览器 JavaScript 以切换报告、查看日志。页面不连接网络或运行 Agent。</noscript>
<script id="snapshot-data" type="application/octet-stream">${data}</script>
<script>${js.replaceAll('</script', '<\\/script')}</script></body></html>`
await mkdir(path.dirname(output), {recursive:true})
await writeFile(output, html, 'utf8')
const receipt = {
  workflowId:id, createdAt:workflow.created_at, updatedAt:workflow.updated_at, capturedAt,
  status:workflow.status, stages:workflow.stages, shape:workflow.outputs.data_delivery?.shape,
  reportCount:workflow.artifacts.filter(item => item.name.startsWith('survey/reports/') && item.name.endsWith('.html')).length + Number(!!embedded['report/report.html']),
  eventCount:workflow.events.length, artifactCount:workflow.artifacts.length,
  embeddedCount:Object.keys(embedded).length,
  embeddedFiles:Object.entries(embedded).map(([name,item]) => ({name,sha256:item.sha256})),
  output, outputBytes:(await stat(output)).size, outputSha256:createHash('sha256').update(html).digest('hex'),
}
await writeFile(output.replace(/\.html$/, '.manifest.json'), JSON.stringify(receipt,null,2)+'\n')
console.log(JSON.stringify({...receipt, embeddedFiles:undefined, stages:undefined},null,2))
