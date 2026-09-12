import test from 'node:test'
import assert from 'node:assert/strict'
import { createWorker } from './worker.mjs'

const assets = { '/index.html': { body: btoa('<title>Brain Agent</title>'), type: 'text/html' } }
test('public routes serve the application without a login redirect', async () => {
  const worker = createWorker(assets)
  for (const path of ['/', '/workflows', '/searches', '/settings/integrations']) {
    const response = await worker.fetch(new Request(`https://site.example${path}`), {})
    assert.equal(response.status, 200)
    assert.match(await response.text(), /Brain Agent/)
    assert.equal(response.headers.get('Location'), null)
  }
  assert.equal((await worker.fetch(new Request('https://site.example/missing.js'), {})).status, 404)
})
test('missing backend returns an honest unavailable response', async () => {
  const response = await createWorker(assets).fetch(new Request('https://site.example/api/sessions'), {})
  assert.equal(response.status, 503)
  assert.match((await response.json()).detail, /后端尚未连接/)
})
test('proxy preserves streaming, uses trusted owner and does not forward visitor secrets', async () => {
  const stream = new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode('data: {}\n\n')); c.close() } })
  const worker = createWorker(assets, async (url, init) => {
    assert.equal(url.href, 'https://backend.example/api/chat/stream?q=1')
    assert.equal(init.headers.get('X-Brain-Agent-Owner-ID'), 'sites-public')
    assert.equal(init.headers.get('Authorization'), 'Bearer server-token')
    assert.equal(init.headers.get('cookie'), null)
    assert.equal(init.redirect, 'manual')
    return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } })
  })
  const response = await worker.fetch(new Request('https://site.example/api/chat/stream?q=1', {
    headers: { 'X-Brain-Agent-Owner-ID': 'local-development-user', Authorization: 'attacker', Cookie: 'secret' },
  }), { BRAIN_AGENT_BACKEND_URL: 'https://backend.example', BRAIN_AGENT_BACKEND_TOKEN: 'server-token' })
  assert.equal(response.body, stream)
  assert.equal(response.headers.get('Content-Type'), 'text/event-stream')
  assert.equal(await response.text(), 'data: {}\n\n')
})
test('invalid backend and network failures stay inside the site', async () => {
  const worker = createWorker(assets, async () => { throw new Error('private upstream details') })
  const request = new Request('https://site.example/api/sessions')
  assert.equal((await worker.fetch(request, { BRAIN_AGENT_BACKEND_URL: 'http://localhost:8000' })).status, 503)
  const response = await worker.fetch(request, { BRAIN_AGENT_BACKEND_URL: 'https://backend.example' })
  assert.equal(response.status, 502)
  assert.doesNotMatch(await response.text(), /private upstream/)
})

test('WebSocket transport reconstructs an SSE response across the local tunnel', async () => {
  class Socket extends EventTarget {
    binaryType = 'blob'
    accept() { assert.equal(this.binaryType, 'arraybuffer') }
    close() {}
    send(body) {
      assert.equal(JSON.parse(body).message, 'hello')
      queueMicrotask(() => {
        for (const data of [JSON.stringify({ type: 'headers', status: 200, contentType: 'text/event-stream' }),
          new TextEncoder().encode('data: {"type":"done"}\n\n').buffer, JSON.stringify({ type: 'end' })]) {
          this.dispatchEvent(new MessageEvent('message', { data }))
        }
      })
    }
  }
  const worker = createWorker(assets, async (url, init) => {
    assert.equal(url.href, 'https://backend.example/_bridge/chat')
    assert.equal(init.headers.get('Upgrade'), 'websocket')
    assert.equal(init.headers.get('Authorization'), 'Bearer server-token')
    return { webSocket: new Socket() }
  })
  const response = await worker.fetch(new Request('https://site.example/api/chat/stream', {
    method: 'POST', body: JSON.stringify({ message: 'hello' }),
  }), { BRAIN_AGENT_BACKEND_URL: 'https://backend.example', BRAIN_AGENT_BACKEND_TOKEN: 'server-token', BRAIN_AGENT_STREAM_BRIDGE: 'websocket' })
  assert.equal(response.status, 200)
  assert.equal(response.headers.get('Content-Type'), 'text/event-stream')
  assert.equal(await response.text(), 'data: {"type":"done"}\n\n')
})
