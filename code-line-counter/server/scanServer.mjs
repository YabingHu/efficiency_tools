import { createServer } from 'node:http'
import { promises as fs } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  createFileResult,
  getExtension,
  isIgnoredPath,
  isSupportedExtension,
  IGNORED_DIRECTORIES,
  THRESHOLD,
} from '../src/lineCounter.js'

const HOST = '127.0.0.1'
const PORT = Number(process.env.CODE_LINE_COUNTER_PORT || 8787)
const projectRoot = path.resolve(fileURLToPath(new URL('..', import.meta.url)))
const distRoot = path.join(projectRoot, 'dist')

const contentTypes = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.json': 'application/json',
}

function sendJson(response, statusCode, body) {
  const data = JSON.stringify(body)
  response.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(data),
    'Access-Control-Allow-Origin': 'http://127.0.0.1:5174',
    'Access-Control-Allow-Headers': 'Content-Type',
  })
  response.end(data)
}

function isIgnoredDirectory(name) {
  return IGNORED_DIRECTORIES.has(name.toLowerCase())
}

export async function scanDirectory(rootPath) {
  const resolvedRoot = path.resolve(rootPath)
  const rootStat = await fs.stat(resolvedRoot)
  if (!rootStat.isDirectory()) throw new Error('输入路径不是文件夹')

  const files = []
  const errors = []
  let ignoredFileCount = 0

  async function visit(currentPath, relativeDirectory) {
    const entries = await fs.readdir(currentPath, { withFileTypes: true })
    entries.sort((left, right) => left.name.localeCompare(right.name))
    for (const entry of entries) {
      if (entry.isSymbolicLink()) continue
      const relativePath = path.join(relativeDirectory, entry.name)
      if (entry.isDirectory()) {
        if (!isIgnoredDirectory(entry.name)) await visit(path.join(currentPath, entry.name), relativePath)
        continue
      }
      if (!entry.isFile()) continue
      if (isIgnoredPath(relativePath) || !isSupportedExtension(getExtension(entry.name))) {
        ignoredFileCount += 1
        continue
      }
      try {
        const content = await fs.readFile(path.join(currentPath, entry.name), 'utf8')
        files.push(createFileResult(relativePath.replaceAll(path.sep, '/'), content))
      } catch (error) {
        errors.push({ path: relativePath.replaceAll(path.sep, '/'), message: error.message || '文件读取失败' })
      }
    }
  }

  await visit(resolvedRoot, '')
  return {
    rootName: path.basename(resolvedRoot),
    source: 'path',
    threshold: THRESHOLD,
    totalCodeLines: files.reduce((sum, file) => sum + file.codeLines, 0),
    fileCount: files.length,
    ignoredFileCount,
    files,
    errors,
  }
}

async function readBody(request) {
  let body = ''
  for await (const chunk of request) {
    body += chunk
    if (body.length > 20_000) throw new Error('请求内容过大')
  }
  return body
}

async function serveStatic(request, response) {
  const requestPath = new URL(request.url, `http://${HOST}:${PORT}`).pathname
  const relativePath = requestPath === '/' ? 'index.html' : requestPath.replace(/^\/+/, '')
  const target = path.resolve(distRoot, relativePath)
  if (target !== distRoot && !target.startsWith(`${distRoot}${path.sep}`)) {
    response.writeHead(403)
    response.end('Forbidden')
    return
  }
  try {
    const stat = await fs.stat(target)
    const filePath = stat.isDirectory() ? path.join(target, 'index.html') : target
    const content = await fs.readFile(filePath)
    response.writeHead(200, { 'Content-Type': contentTypes[path.extname(filePath)] || 'application/octet-stream' })
    response.end(content)
  } catch {
    response.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' })
    response.end('请先运行 npm run build，再启动本地服务。')
  }
}

export const server = createServer(async (request, response) => {
  if (request.method === 'OPTIONS') {
    response.writeHead(204, {
      'Access-Control-Allow-Origin': 'http://127.0.0.1:5174',
      'Access-Control-Allow-Headers': 'Content-Type',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
    })
    response.end()
    return
  }

  if (request.method === 'POST' && request.url === '/api/scan') {
    try {
      const body = JSON.parse(await readBody(request))
      if (typeof body.path !== 'string' || !body.path.trim()) throw new Error('请输入要扫描的文件夹路径')
      sendJson(response, 200, await scanDirectory(body.path.trim()))
    } catch (error) {
      sendJson(response, 400, { error: error.message || '扫描失败' })
    }
    return
  }

  if (request.method === 'GET') {
    await serveStatic(request, response)
    return
  }
  sendJson(response, 405, { error: '不支持的请求方法' })
})

export function startServer() {
  server.listen(PORT, HOST, () => {
    console.log(`代码行数统计服务已启动：http://${HOST}:${PORT}`)
    console.log('路径扫描只会读取本机文件，不会上传代码内容。')
  })
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  startServer()
}
