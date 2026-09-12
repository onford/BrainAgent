import { existsSync, readdirSync, readFileSync, writeFileSync, mkdirSync, copyFileSync } from 'node:fs'
import { resolve, relative, extname } from 'node:path'

// Leave ordinary Vite builds usable without a Sites registration.
if (existsSync('.openai/hosting.json')) {
  const root = resolve('dist')
  const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png',
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.woff2': 'font/woff2', '.ico': 'image/x-icon' }
  const assets = {}
  function collect(directory) {
    for (const item of readdirSync(directory, { withFileTypes: true })) {
      if (['server', '.openai'].includes(item.name)) continue
      const file = resolve(directory, item.name)
      if (item.isDirectory()) collect(file)
      else if (item.isFile()) assets['/' + relative(root, file).replaceAll('\\', '/')] = {
        type: mime[extname(file)] || 'application/octet-stream', body: readFileSync(file).toString('base64'),
      }
    }
  }
  collect(root)
  if (!assets['/index.html']) throw new Error('Build is missing index.html')
  mkdirSync('dist/server', { recursive: true })
  mkdirSync('dist/.openai', { recursive: true })
  copyFileSync('sites/worker.mjs', 'dist/server/worker.js')
  writeFileSync('dist/server/index.js', `import { createWorker } from './worker.js'\nexport default createWorker(${JSON.stringify(assets)})\n`)
  copyFileSync('.openai/hosting.json', 'dist/.openai/hosting.json')
  console.log(`Sites Worker built with ${Object.keys(assets).length} assets.`)
}
