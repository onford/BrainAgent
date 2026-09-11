/** Verify the standalone artifact without a server or network access. */
import { readFile, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { gunzipSync } from 'node:zlib'
import { strict as assert } from 'node:assert'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { JSDOM, ResourceLoader, VirtualConsole } from 'jsdom'

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const filename = path.resolve(process.argv[2] || path.join(project, 'exports/BrainAgent-最新运行结果-离线.html'))
const html = await readFile(filename, 'utf8')
const receipt = JSON.parse(await readFile(filename.replace(/\.html$/, '.manifest.json'), 'utf8'))
assert.equal(createHash('sha256').update(html).digest('hex'), receipt.outputSha256)
const encoded = html.match(/<script id="snapshot-data" type="application\/octet-stream">([\s\S]*?)<\/script>/)[1]
const snapshot = JSON.parse(gunzipSync(Buffer.from(encoded, 'base64')).toString('utf8'))
assert.equal(snapshot.workflow.id, receipt.workflowId)
assert.equal(snapshot.workflow.artifacts.length, receipt.artifactCount)
assert.equal(snapshot.workflow.events.length, receipt.eventCount)
for (const file of receipt.embeddedFiles) {
  assert.equal(createHash('sha256').update(snapshot.embedded[file.name].content).digest('hex'), file.sha256, file.name)
}

const network = [], errors = [], blobs = new Map()
class NoNetwork extends ResourceLoader {
  fetch(url) { network.push(url); return null }
}
const consoleOutput = new VirtualConsole()
consoleOutput.on('jsdomError', error => errors.push(error.message))
consoleOutput.on('error', (...values) => errors.push(values.map(String).join(' ')))
const dom = new JSDOM(html, {
  url:'file:///offline-copy/BrainAgent.html', runScripts:'dangerously',
  resources:new NoNetwork(), pretendToBeVisual:true, virtualConsole:consoleOutput,
  beforeParse(window) {
    window.Blob = Blob; window.Response = Response; window.DecompressionStream = DecompressionStream
    window.fetch = (...args) => { network.push(String(args[0])); throw new Error('Network disabled') }
    window.URL.createObjectURL = blob => { const url = 'blob:offline-' + blobs.size; blobs.set(url,blob); return url }
    window.URL.revokeObjectURL = url => blobs.delete(url)
    window.HTMLElement.prototype.scrollIntoView = function () {}
    window.HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open','') }
    window.HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  },
})
const {document, MouseEvent, Event} = dom.window
const tick = () => new Promise(resolve => setTimeout(resolve, 25))
async function until(predicate) {
  const limit = Date.now() + 30000
  while (!predicate()) { assert.ok(Date.now() < limit, 'Offline UI initialization timed out'); await tick() }
}
async function click(element) {
  assert.ok(element, 'Expected control to exist')
  element.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true})); await tick()
}
const byText = (selector, text) => [...document.querySelectorAll(selector)].find(node => node.textContent.includes(text))
await until(() => document.querySelector('.dataset-heading h1'))
assert.equal(document.querySelector('.dataset-heading h1').textContent, snapshot.workflow.outputs.data_survey.profile.name)
assert.equal(document.querySelectorAll('.stages > li.completed').length, 6)
assert.ok(document.querySelector('.new-run').disabled)
assert.ok(document.querySelector('.run-picker select').disabled)
assert.ok(byText('.content-toolbar button', '预算预处理搜索').disabled)
assert.equal(document.querySelector('.run-picker option').textContent.slice(0,11), '09/09 16:31')

// srcdoc has no implementation in jsdom. Verify each complete source string;
// materialize only the first document to exercise the real reader's load hook.
const reportButtons = [...document.querySelectorAll('nav[aria-label="选择报告"] button')]
assert.equal(reportButtons.length, receipt.reportCount)
const reportNames = ['survey/reports/dataset-basic.html','survey/reports/data-information.html','survey/reports/statistics.html','survey/reports/literature-usage.html','survey/reports/literature-discussion.html','survey/reports/literature-preprocessing.html','report/report.html']
for (let index = 0; index < reportButtons.length; index++) {
  await click(reportButtons[index])
  const frame = document.querySelector('.report-reader iframe')
  assert.equal(frame.getAttribute('srcdoc'), snapshot.embedded[reportNames[index]].content)
  assert.equal(frame.getAttribute('src'), null)
  if (index === 0) {
    frame.contentDocument.open(); frame.contentDocument.write(frame.getAttribute('srcdoc')); frame.contentDocument.close()
    frame.dispatchEvent(new Event('load')); await tick()
    assert.ok(document.querySelectorAll('nav[aria-label="报告章节"] button').length > 0)
    assert.equal(document.querySelector('.reader-notice[role="alert"]'), null)
  }
}
await click(byText('.reader-actions button', '专注阅读'))
assert.ok(document.querySelector('.workflow-page.focused'))
await click(byText('.reader-actions button', '退出专注'))
assert.equal(document.querySelector('.workflow-page.focused'),null)

await click(byText('.workspace-tabs button', '执行日志'))
assert.equal(document.querySelectorAll('.event-list li').length, receipt.eventCount)
const logSearch = document.querySelector('input[aria-label="搜索执行记录"]')
logSearch.value = 'offline-no-such-event'; logSearch.dispatchEvent(new Event('input',{bubbles:true})); await tick()
assert.ok(document.querySelector('.event-list').textContent.includes('没有匹配'))
logSearch.value = ''; logSearch.dispatchEvent(new Event('input',{bubbles:true})); await tick()
assert.equal(document.querySelectorAll('.event-list li').length, receipt.eventCount)

await click(byText('.workspace-tabs button','记录文件'))
assert.ok(document.querySelector('.file-content header').textContent.includes(String(receipt.artifactCount)))
const fileSearch = document.querySelector('input[aria-label="查找文件"]')
fileSearch.value = 'training-data.zip'; fileSearch.dispatchEvent(new Event('input',{bubbles:true})); await tick()
assert.ok(document.querySelector('.file-content header').textContent.includes('1 个文件'))
await click(byText('.file-list a','training-data.zip'))
assert.ok(document.querySelector('#offline-record-dialog').open)
assert.ok(document.querySelector('#offline-record-meta').textContent.includes('302028170'))
document.querySelector('#offline-record-dialog').close()

await click(byText('.workspace-tabs button','训练数据'))
assert.deepEqual([...document.querySelectorAll('.stats strong')].map(node => Number(node.textContent)), receipt.shape)
await click(document.querySelector('.stages button'))
assert.ok(document.querySelector('.stage-dialog').open)
await click(byText('.stage-dialog button', '查看本阶段文件'))
assert.equal(document.querySelector('.stage-dialog').open,false)
assert.ok(byText('.files-panel nav button[aria-pressed="true"]','数据调研'))
await click(byText('.workspace-tabs button','报告阅读'))
await click(reportButtons[0])
await tick()
assert.deepEqual(network,[], 'The standalone HTML attempted a network request')
assert.deepEqual(errors,[], 'The standalone HTML emitted an error')
const result = {workflowId:receipt.workflowId, passed:true, networkRequests:network.length, errors,
  checked:['gzip payload and embedded source hashes','file URL startup','original layout and six completed modules','execution controls disabled','all seven complete report srcdocs','report outline','focus mode','361 logs and filtering','24,812 artifact entries and filtering','large-file metadata','training shape','stage dialog and module filter'],
  limitations:['jsdom does not perform visual rendering or implement native srcdoc navigation; complete iframe content and the first report load hook were checked.']}
await writeFile(filename.replace(/\.html$/, '.verification.json'), JSON.stringify(result,null,2)+'\n')
console.log(JSON.stringify(result,null,2))
dom.window.close()
