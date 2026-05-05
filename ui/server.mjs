import { createServer } from 'node:http'
import { Readable } from 'node:stream'
import { readFile } from 'node:fs/promises'
import { join, extname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = fileURLToPath(new URL('.', import.meta.url))
const DIST_CLIENT = join(__dirname, 'dist/client')

const CONTENT_TYPES = {
  '.js': 'application/javascript; charset=utf-8',
  '.mjs': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.json': 'application/json',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.woff': 'font/woff',
  '.ttf': 'font/ttf',
  '.txt': 'text/plain',
}

const { default: serverEntry } = await import('./dist/server/index.js')
const fetchHandler = typeof serverEntry === 'function' ? serverEntry : serverEntry.fetch.bind(serverEntry)

async function tryServeStatic(pathname) {
  // Strip /_build prefix → maps to dist/client/
  const rel = pathname.startsWith('/_build/') ? pathname.slice(7) : pathname
  try {
    const fullPath = join(DIST_CLIENT, rel)
    const content = await readFile(fullPath)
    return { content, type: CONTENT_TYPES[extname(rel)] || 'application/octet-stream' }
  } catch {
    return null
  }
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`)

  // Serve static assets directly
  if (url.pathname.startsWith('/_build/') || url.pathname.match(/\.(js|mjs|css|png|jpg|svg|ico|woff2?|ttf)$/)) {
    const file = await tryServeStatic(url.pathname)
    if (file) {
      res.writeHead(200, {
        'Content-Type': file.type,
        'Cache-Control': 'public, max-age=31536000, immutable',
      })
      res.end(file.content)
      return
    }
  }

  // Forward to TanStack Start SSR handler
  const proto = req.headers['x-forwarded-proto'] || 'http'
  const fullUrl = `${proto}://${req.headers.host || 'localhost'}${req.url}`
  const headers = new Headers()
  for (const [k, v] of Object.entries(req.headers)) {
    if (Array.isArray(v)) v.forEach(val => headers.append(k, val))
    else if (v != null) headers.set(k, v)
  }

  const hasBody = req.method !== 'GET' && req.method !== 'HEAD'
  const reqInit = { method: req.method, headers }
  if (hasBody) {
    reqInit.body = Readable.toWeb(req)
    reqInit.duplex = 'half'
  }

  let response
  try {
    response = await fetchHandler(new Request(fullUrl, reqInit))
  } catch (err) {
    console.error('SSR error:', err)
    res.writeHead(500)
    res.end('Internal Server Error')
    return
  }

  res.statusCode = response.status
  for (const [k, v] of response.headers) res.setHeader(k, v)

  if (response.body) {
    Readable.fromWeb(response.body).pipe(res)
  } else {
    res.end()
  }
})

const PORT = parseInt(process.env.PORT || '8080', 10)
server.listen(PORT, () => console.log(`UI server listening on :${PORT}`))
