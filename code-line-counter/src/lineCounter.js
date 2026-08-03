export const THRESHOLD = 1000

const EXTENSION_RULES = {
  '.js': 'slash', '.jsx': 'slash', '.ts': 'slash', '.tsx': 'slash',
  '.mjs': 'slash', '.cjs': 'slash', '.java': 'slash', '.go': 'slash',
  '.rs': 'slash', '.c': 'slash', '.h': 'slash', '.cc': 'slash',
  '.cpp': 'slash', '.cxx': 'slash', '.hpp': 'slash', '.cs': 'slash',
  '.php': 'slash', '.swift': 'slash', '.kt': 'slash', '.kts': 'slash',
  '.css': 'slash', '.scss': 'slash', '.less': 'slash',
  '.py': 'hash', '.pyw': 'hash', '.rb': 'hash', '.sh': 'hash',
  '.bash': 'hash', '.zsh': 'hash', '.ps1': 'hash',
  '.sql': 'dash',
  '.html': 'html', '.htm': 'html', '.vue': 'html', '.svelte': 'html',
}

export const SUPPORTED_EXTENSIONS = Object.keys(EXTENSION_RULES)

export const IGNORED_DIRECTORIES = new Set([
  '.git', '.hg', '.svn', 'node_modules', 'dist', 'build', 'coverage',
  'target', 'vendor', '.next', '.nuxt', 'out', 'bin', 'obj',
  '.venv', 'venv', '__pycache__', '.pytest_cache', '.cache',
])

function getRule(extension) {
  const style = EXTENSION_RULES[extension.toLowerCase()]
  if (style === 'hash') return { line: ['#'], block: [['/*', '*/']] }
  if (style === 'dash') return { line: ['--'], block: [['/*', '*/']] }
  if (style === 'html') {
    return { line: ['//'], block: [['<!--', '-->'], ['/*', '*/']] }
  }
  return { line: ['//'], block: [['/*', '*/']] }
}

function startsWithAny(text, index, tokens) {
  return tokens.find(token => text.startsWith(token, index)) || null
}

function stripComments(text, extension) {
  const rules = getRule(extension)
  let output = ''
  let quote = null
  let blockEnd = null
  let lineComment = false
  let escaped = false

  for (let index = 0; index < text.length; index += 1) {
    const character = text[index]

    if (lineComment) {
      if (character === '\n') {
        lineComment = false
        output += '\n'
      }
      continue
    }

    if (blockEnd) {
      if (text.startsWith(blockEnd, index)) {
        index += blockEnd.length - 1
        blockEnd = null
        output += ' '
      } else if (character === '\n') {
        output += '\n'
      }
      continue
    }

    if (quote) {
      output += character
      if (escaped) {
        escaped = false
      } else if (character === '\\') {
        escaped = true
      } else if (text.startsWith(quote, index)) {
        if (quote.length > 1) {
          output += text.slice(index + 1, index + quote.length)
          index += quote.length - 1
        }
        quote = null
      }
      continue
    }

    const blockStart = rules.block.find(([start]) => text.startsWith(start, index))
    if (blockStart) {
      blockEnd = blockStart[1]
      index += blockStart[0].length - 1
      output += ' '
      continue
    }

    const lineStart = startsWithAny(text, index, rules.line)
    if (lineStart) {
      lineComment = true
      index += lineStart.length - 1
      output += ' '
      continue
    }

    if ((extension === '.py' || extension === '.pyw') &&
        (text.startsWith('"""', index) || text.startsWith("'''", index))) {
      quote = text.slice(index, index + 3)
      output += quote
      index += 2
      continue
    }

    if (character === '"' || character === "'" || character === '`') {
      quote = character
    }
    output += character
  }

  return output
}

export function getExtension(filePath) {
  const filename = filePath.split(/[\\/]/).pop() || ''
  const dotIndex = filename.lastIndexOf('.')
  return dotIndex > 0 ? filename.slice(dotIndex).toLowerCase() : ''
}

export function isSupportedExtension(extensionOrPath) {
  const extension = extensionOrPath.startsWith('.')
    ? extensionOrPath.toLowerCase()
    : getExtension(extensionOrPath)
  return Boolean(EXTENSION_RULES[extension])
}

export function isIgnoredPath(relativePath) {
  return relativePath.split(/[\\/]/).some(part => IGNORED_DIRECTORIES.has(part.toLowerCase()))
}

export function countCodeLines(text, extensionOrPath) {
  const extension = extensionOrPath.startsWith('.')
    ? extensionOrPath.toLowerCase()
    : getExtension(extensionOrPath)
  const normalized = String(text ?? '').replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n')
  const lines = normalized.length === 0
    ? []
    : normalized.split('\n').slice(normalized.endsWith('\n') ? 0 : undefined)
  const effectiveLines = normalized.endsWith('\n') ? lines.slice(0, -1) : lines
  const cleaned = stripComments(normalized, extension)
  const cleanedLines = cleaned.split('\n')
  const rawLines = normalized.length === 0 ? [] : normalized.split('\n')
  const physicalLines = normalized.endsWith('\n') ? rawLines.slice(0, -1) : rawLines

  let codeLines = 0
  let blankLines = 0
  let commentLines = 0
  physicalLines.forEach((line, index) => {
    const cleanLine = (cleanedLines[index] || '').trim()
    if (!line.trim()) blankLines += 1
    else if (!cleanLine) commentLines += 1
    else codeLines += 1
  })

  return {
    totalLines: effectiveLines.length,
    codeLines,
    blankLines,
    commentLines,
  }
}

export function createFileResult(path, text) {
  const extension = getExtension(path)
  return { path, extension, ...countCodeLines(text, extension) }
}
