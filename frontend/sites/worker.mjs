const jsonError = (detail, status) => Response.json({ detail }, {
  status, headers: { 'Cache-Control': 'no-store' },
})

async function bridgedChat(request, upstream, headers, fetchUpstream) {
  const bridgeUrl = new URL('/_bridge/chat', upstream)
  const bridgeHeaders = new Headers(headers)
  bridgeHeaders.set('Upgrade', 'websocket')
  const response = await fetchUpstream(bridgeUrl, { headers: bridgeHeaders, redirect: 'manual' })
  const socket = response.webSocket
  if (!socket) throw new Error('Streaming bridge is unavailable')
  socket.binaryType = 'arraybuffer'
  let controller, complete = false, ready = false, resolveHeaders, rejectHeaders
  const metadata = new Promise((resolve, reject) => { resolveHeaders = resolve; rejectHeaders = reject })
  const close = () => { try { socket.close(1000, 'Finished') } catch {} }
  const fail = () => {
    if (complete) return
    complete = true
    clearTimeout(timeout)
    if (ready) controller.error(new Error('后端连接中断，请重试。'))
    else rejectHeaders(new Error('Streaming bridge failed'))
    close()
  }
  const stream = new ReadableStream({ start(c) { controller = c }, cancel() { complete = true; close() } })
  const timeout = setTimeout(fail, 30000)
  socket.addEventListener('message', event => {
    if (complete) return
    try {
      if (typeof event.data !== 'string') {
        if (!ready) throw new Error('Missing response headers')
        controller.enqueue(new Uint8Array(event.data))
        return
      }
      const message = JSON.parse(event.data)
      if (message.type === 'headers' && !ready) {
        ready = true
        clearTimeout(timeout)
        resolveHeaders(message)
      } else if (message.type === 'end' && ready) {
        complete = true
        controller.close()
        close()
      } else { fail() }
    } catch { fail() }
  })
  socket.addEventListener('error', fail)
  socket.addEventListener('close', () => { if (!complete) fail() })
  request.signal.addEventListener('abort', fail, { once: true })
  socket.accept()
  socket.send(await request.text())
  const info = await metadata
  return new Response(stream, { status: info.status, headers: {
    'Content-Type': info.contentType, 'Cache-Control': 'no-store',
  } })
}

export function createWorker(assets, fetchUpstream = fetch) {
  return {
    async fetch(request, env) {
      const url = new URL(request.url)
      if (url.pathname === '/health' || url.pathname === '/api' || url.pathname.startsWith('/api/')) {
        if (!env.BRAIN_AGENT_BACKEND_URL) {
          return jsonError('Agent 后端尚未连接，请先配置后端服务地址。', 503)
        }
        let upstream
        try {
          upstream = new URL(env.BRAIN_AGENT_BACKEND_URL)
          if (upstream.protocol !== 'https:' || upstream.username || upstream.password ||
              upstream.pathname !== '/' || upstream.search || upstream.hash) throw new Error('Invalid origin')
        } catch {
          return jsonError('Agent 后端服务地址配置无效。', 503)
        }
        upstream.pathname = url.pathname
        upstream.search = url.search
        // The public site uses one server-selected owner. Visitors cannot impersonate local owners.
        const headers = new Headers()
        for (const name of ['accept', 'content-type', 'range', 'if-none-match', 'if-modified-since']) {
          if (request.headers.has(name)) headers.set(name, request.headers.get(name))
        }
        headers.set('X-Brain-Agent-Owner-ID', env.BRAIN_AGENT_OWNER_ID || 'sites-public')
        if (env.BRAIN_AGENT_BACKEND_TOKEN) headers.set('Authorization', `Bearer ${env.BRAIN_AGENT_BACKEND_TOKEN}`)
        try {
          if (env.BRAIN_AGENT_STREAM_BRIDGE === 'websocket' && url.pathname === '/api/chat/stream' && request.method === 'POST') {
            return await bridgedChat(request, upstream, headers, fetchUpstream)
          }
          const response = await fetchUpstream(upstream, {
            method: request.method, headers,
            body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.body,
            redirect: 'manual', signal: request.signal,
          })
          // Preserve streaming and downloads without buffering entire responses in the Worker.
          const outgoing = new Headers(response.headers)
          outgoing.delete('set-cookie')
          outgoing.delete('access-control-allow-origin')
          outgoing.set('Cache-Control', 'no-store')
          if (response.status >= 300 && response.status < 400 && outgoing.has('location')) {
            const location = new URL(outgoing.get('location'), upstream)
            if (location.origin !== upstream.origin) return jsonError('后端返回了不受支持的跳转。', 502)
            outgoing.set('location', location.pathname + location.search + location.hash)
          }
          return new Response(response.body, { status: response.status, headers: outgoing })
        } catch {
          return jsonError('暂时无法连接 Agent 后端，请检查后端服务是否运行。', 502)
        }
      }
      if (!['GET', 'HEAD'].includes(request.method)) return new Response('Method not allowed', { status: 405 })
      const routes = ['/', '/agents', '/workflows', '/searches', '/settings/integrations']
      const asset = Object.hasOwn(assets, url.pathname) ? assets[url.pathname]
        : routes.includes(url.pathname.replace(/\/$/, '') || '/') ? assets['/index.html'] : null
      if (!asset) return new Response('Not found', { status: 404 })
      return new Response(request.method === 'HEAD' ? null : Uint8Array.from(atob(asset.body), c => c.charCodeAt(0)), {
        headers: {
          'Content-Type': asset.type,
          'Cache-Control': url.pathname.startsWith('/assets/') ? 'public, max-age=31536000, immutable' : 'no-cache',
          'X-Content-Type-Options': 'nosniff',
          'Referrer-Policy': 'same-origin',
        },
      })
    },
  }
}
