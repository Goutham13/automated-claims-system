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

// The Cloudflare adapter build outputs dist/server/index.js which exports a fetch handler.
// Both the default export (an object with .fetch) and a named fetch export are supported.
const mod = await import('./dist/server/index.js')
const serverEntry = mod.default ?? mod
const fetchHandler = typeof serverEntry === 'function'
  ? serverEntry
  : serverEntry.fetch?.bind(serverEntry)

if (!fetchHandler) {
  console.error('Could not find fetch handler in dist/server/index.js. Exports:', Object.keys(mod))
  process.exit(1)
}

// The Cloudflare worker wrangler.json uses assets.directory = "../client",
// meaning dist/client/ is served at the root path (e.g. /assets/foo.js).
async function tryServeStatic(pathname) {
  try {
    const fullPath = join(DIST_CLIENT, pathname)
    const content = await readFile(fullPath)
    return { content, type: CONTENT_TYPES[extname(pathname)] || 'application/octet-stream' }
  } catch {
    return null
  }
}

const STATIC_RE = /\.(js|mjs|css|png|jpg|jpeg|svg|ico|woff2?|ttf|webp|gif|map)$/i

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`)

  // Serve static files for asset-like paths before hitting the SSR handler
  if (STATIC_RE.test(url.pathname)) {
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

  // Forward to TanStack Start SSR handler (Web Fetch API)
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
