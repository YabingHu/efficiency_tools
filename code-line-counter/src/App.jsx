import { useMemo, useRef, useState } from 'react'
import {
  createFileResult,
  getExtension,
  isIgnoredPath,
  isSupportedExtension,
  THRESHOLD,
} from './lineCounter.js'

const numberFormatter = new Intl.NumberFormat('zh-CN')

function formatNumber(value) {
  return numberFormatter.format(value)
}

function languageFor(extension) {
  const names = {
    '.js': 'JavaScript', '.jsx': 'JSX', '.ts': 'TypeScript', '.tsx': 'TSX',
    '.py': 'Python', '.java': 'Java', '.go': 'Go', '.rs': 'Rust',
    '.c': 'C', '.h': 'C/C++', '.cpp': 'C++', '.cs': 'C#', '.php': 'PHP',
    '.rb': 'Ruby', '.swift': 'Swift', '.kt': 'Kotlin', '.css': 'CSS',
    '.scss': 'SCSS', '.html': 'HTML', '.vue': 'Vue', '.svelte': 'Svelte',
    '.sql': 'SQL', '.sh': 'Shell', '.ps1': 'PowerShell',
  }
  return names[extension] || extension.slice(1).toUpperCase()
}

function emptyResult() {
  return null
}

function summarizeFiles(files, rootName, source, ignoredFileCount = 0, errors = []) {
  const sortedFiles = [...files].sort((a, b) => a.path.localeCompare(b.path))
  return {
    rootName,
    source,
    threshold: THRESHOLD,
    totalCodeLines: sortedFiles.reduce((sum, file) => sum + file.codeLines, 0),
    fileCount: sortedFiles.length,
    ignoredFileCount,
    files: sortedFiles,
    errors,
  }
}

async function scanBrowserFiles(fileList) {
  const files = Array.from(fileList)
  const firstPath = files[0]?.webkitRelativePath || files[0]?.name || ''
  const rootName = firstPath.split('/')[0] || '所选文件夹'
  const results = []
  const errors = []
  let ignoredFileCount = 0

  await Promise.all(files.map(async file => {
    const relativePath = file.webkitRelativePath
      ? file.webkitRelativePath.split('/').slice(1).join('/')
      : file.name
    if (isIgnoredPath(relativePath) || !isSupportedExtension(file.name)) {
      ignoredFileCount += 1
      return
    }
    try {
      results.push(createFileResult(relativePath, await file.text()))
    } catch (error) {
      errors.push({ path: relativePath, message: error.message || '文件读取失败' })
    }
  }))

  return summarizeFiles(results, rootName, 'folder-picker', ignoredFileCount, errors)
}

function sortFiles(files, field, direction) {
  return [...files].sort((a, b) => {
    const left = a[field]
    const right = b[field]
    const comparison = typeof left === 'number'
      ? left - right
      : String(left).localeCompare(String(right))
    return comparison * direction
  })
}

export default function App() {
  const folderInputRef = useRef(null)
  const [path, setPath] = useState('')
  const [result, setResult] = useState(emptyResult)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [sortField, setSortField] = useState('codeLines')
  const [sortDirection, setSortDirection] = useState(-1)

  const visibleFiles = useMemo(() => {
    if (!result) return []
    const query = search.trim().toLowerCase()
    const filtered = query
      ? result.files.filter(file => file.path.toLowerCase().includes(query))
      : result.files
    return sortFiles(filtered, sortField, sortDirection)
  }, [result, search, sortField, sortDirection])

  const handleFolderChange = async event => {
    const selectedFiles = event.target.files
    if (!selectedFiles?.length) return
    setLoading(true)
    setError('')
    try {
      setResult(await scanBrowserFiles(selectedFiles))
    } catch (scanError) {
      setError(scanError.message || '文件夹扫描失败')
    } finally {
      setLoading(false)
      event.target.value = ''
    }
  }

  const scanPath = async event => {
    event.preventDefault()
    if (!path.trim()) {
      setError('请输入要扫描的文件夹路径')
      return
    }
    setLoading(true)
    setError('')
    try {
      const response = await fetch('/api/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: path.trim() }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.error || '路径扫描失败')
      setResult(payload)
    } catch (scanError) {
      setError(scanError.message || '路径扫描失败，请确认本地扫描服务已启动')
    } finally {
      setLoading(false)
    }
  }

  const changeSort = field => {
    if (sortField === field) setSortDirection(direction => direction * -1)
    else {
      setSortField(field)
      setSortDirection(field === 'path' ? 1 : -1)
    }
  }

  const sortIndicator = field => sortField === field ? (sortDirection === 1 ? '↑' : '↓') : ''

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark"><span /><span /><span /></div>
          <div>
            <div className="brand-name">代码行数统计</div>
            <div className="brand-subtitle">Code Line Counter</div>
          </div>
        </div>
        <div className="rule-note"><span className="rule-dot" /> 公司参考规则：单次 1000 行</div>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow">LOCAL CODE INSPECTOR</p>
          <h1>看看你的代码规模，<em>一目了然。</em></h1>
          <p className="hero-copy">选择一个项目文件夹，统计真正的有效代码行。空行、注释和常见依赖目录会自动排除。</p>
        </div>
        <div className="hero-orbit" aria-hidden="true">
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <div className="orbit-core">{'{ }'}</div>
        </div>
      </section>

      <section className="scan-panel">
        <div className="panel-heading">
          <div>
            <h2>开始一次扫描</h2>
            <p>数据只在本机处理，不会上传代码内容。</p>
          </div>
          <button className="folder-button" type="button" onClick={() => folderInputRef.current?.click()}>
            <span className="folder-icon">⌁</span> 选择文件夹
          </button>
          <input
            ref={folderInputRef}
            className="visually-hidden"
            type="file"
            webkitdirectory="true"
            directory="true"
            multiple
            onChange={handleFolderChange}
          />
        </div>
        <form className="path-form" onSubmit={scanPath}>
          <div className="path-input-wrap">
            <span className="path-icon">⌂</span>
            <input
              value={path}
              onChange={event => setPath(event.target.value)}
              placeholder="或输入文件夹路径，例如 D:\\Projects\\my-app"
              aria-label="文件夹路径"
            />
          </div>
          <button className="scan-button" type="submit" disabled={loading}>
            {loading ? <><span className="spinner" /> 扫描中</> : <>开始扫描 <span>→</span></>}
          </button>
        </form>
        <div className="scan-hint"><span>✦</span> 支持常见代码文件 · 自动忽略 node_modules、.git、dist 等目录</div>
      </section>

      {error && <div className="alert error-alert"><span>!</span>{error}</div>}

      {result ? (
        <section className="results-section">
          <div className="results-heading">
            <div>
              <p className="eyebrow">SCAN RESULT</p>
              <h2>{result.rootName}</h2>
              <p className="result-meta">{result.source === 'path' ? '本地路径扫描' : '浏览器文件夹选择'} · {result.files.length ? '已完成' : '没有找到可统计的代码文件'}</p>
            </div>
            <div className="result-actions">
              <span className="reference-badge">参考上限 {formatNumber(result.threshold)} 行</span>
              <button className="reset-button" onClick={() => { setResult(null); setSearch('') }}>清空结果</button>
            </div>
          </div>

          <div className="metrics-grid">
            <article className="metric-card primary-metric">
              <div className="metric-label">有效代码行</div>
              <div className="metric-value">{formatNumber(result.totalCodeLines)}</div>
              <div className="metric-foot">排除空行与纯注释行</div>
            </article>
            <article className="metric-card">
              <div className="metric-label">代码文件</div>
              <div className="metric-value">{formatNumber(result.fileCount)}</div>
              <div className="metric-foot">支持的代码扩展名</div>
            </article>
            <article className="metric-card">
              <div className="metric-label">空行 / 注释行</div>
              <div className="metric-value small-value">
                {formatNumber(result.files.reduce((sum, file) => sum + file.blankLines, 0))}
                <span>/</span>
                {formatNumber(result.files.reduce((sum, file) => sum + file.commentLines, 0))}
              </div>
              <div className="metric-foot">未计入有效代码</div>
            </article>
            <article className="metric-card">
              <div className="metric-label">已忽略文件</div>
              <div className="metric-value">{formatNumber(result.ignoredFileCount)}</div>
              <div className="metric-foot">不纳入统计的文件</div>
            </article>
          </div>

          {result.errors.length > 0 && (
            <div className="alert warning-alert"><span>!</span>有 {result.errors.length} 个文件读取失败，详情见扫描结果底部。</div>
          )}

          <div className="files-panel">
            <div className="files-toolbar">
              <div><h3>文件明细</h3><span>{visibleFiles.length} 个结果</span></div>
              <label className="search-box"><span>⌕</span><input value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索文件名..." /></label>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th><button onClick={() => changeSort('path')}>文件 <span>{sortIndicator('path')}</span></button></th>
                    <th>语言</th>
                    <th><button onClick={() => changeSort('codeLines')}>有效代码 <span>{sortIndicator('codeLines')}</span></button></th>
                    <th><button onClick={() => changeSort('totalLines')}>总行数 <span>{sortIndicator('totalLines')}</span></button></th>
                    <th>空行</th>
                    <th>注释</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleFiles.map(file => (
                    <tr key={file.path}>
                      <td><span className="file-glyph">{getExtension(file.path).slice(1, 3).toUpperCase()}</span><span className="file-path" title={file.path}>{file.path}</span></td>
                      <td><span className="language-pill">{languageFor(file.extension)}</span></td>
                      <td className="number-cell emphasis">{formatNumber(file.codeLines)}</td>
                      <td className="number-cell">{formatNumber(file.totalLines)}</td>
                      <td className="number-cell muted-number">{formatNumber(file.blankLines)}</td>
                      <td className="number-cell muted-number">{formatNumber(file.commentLines)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {visibleFiles.length === 0 && <div className="empty-state">没有匹配的文件</div>}
            </div>
          </div>

          {result.errors.length > 0 && (
            <div className="errors-list"><strong>读取失败的文件</strong>{result.errors.map(item => <div key={item.path}>{item.path}：{item.message}</div>)}</div>
          )}
        </section>
      ) : (
        <section className="empty-dashboard">
          <div className="empty-icon">⌘</div>
          <h2>还没有扫描结果</h2>
          <p>选择项目文件夹或输入本地路径，开始查看代码规模。</p>
        </section>
      )}

      <footer>代码内容只在本机读取和计算 · 目录总量仅作规模参考，不直接代表一次提交大小</footer>
    </main>
  )
}
