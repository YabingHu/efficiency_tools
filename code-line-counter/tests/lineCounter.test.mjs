import test from 'node:test'
import assert from 'node:assert/strict'
import {
  countCodeLines,
  createFileResult,
  isIgnoredPath,
  isSupportedExtension,
} from '../src/lineCounter.js'

test('counts code, blank, and comment lines in JavaScript', () => {
  const result = countCodeLines('\uFEFFconst url = "https://example.com"; // keep this\r\n\r\n// comment\r\n/* block\r\n * comment\r\n */\r\nconsole.log(url)\r\n', '.js')
  assert.deepEqual(result, { totalLines: 7, codeLines: 2, blankLines: 1, commentLines: 4 })
})

test('does not interpret comment markers inside strings', () => {
  const result = countCodeLines('const value = "// not a comment";\nconst other = `/* still code */`;\n', '.js')
  assert.equal(result.codeLines, 2)
  assert.equal(result.commentLines, 0)
})

test('supports hash comments and keeps Python docstrings as strings', () => {
  const result = countCodeLines('"""module docs"""\n# comment\nvalue = "# value"\n', '.py')
  assert.equal(result.totalLines, 3)
  assert.equal(result.codeLines, 2)
  assert.equal(result.commentLines, 1)
})

test('supports SQL and HTML block comments', () => {
  assert.equal(countCodeLines('-- query\nSELECT 1;\n', '.sql').codeLines, 1)
  assert.equal(countCodeLines('<!-- note -->\n<div>content</div>\n', '.html').codeLines, 1)
})

test('handles empty files and extension/path helpers', () => {
  assert.deepEqual(countCodeLines('', '.ts'), { totalLines: 0, codeLines: 0, blankLines: 0, commentLines: 0 })
  assert.equal(createFileResult('src/App.tsx', 'export default 1;').extension, '.tsx')
  assert.equal(isSupportedExtension('src/App.tsx'), true)
  assert.equal(isSupportedExtension('photo.png'), false)
  assert.equal(isIgnoredPath('src/node_modules/pkg/index.js'), true)
  assert.equal(isIgnoredPath('src/components/App.jsx'), false)
})
