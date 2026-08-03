import test, { afterEach } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { scanDirectory } from '../server/scanServer.mjs'

const temporaryDirectories = []

afterEach(async () => {
  await Promise.all(temporaryDirectories.splice(0).map(directory => rm(directory, { recursive: true, force: true })))
})

test('scans recursively, ignores dependency directories, and skips non-code files', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'code-line-counter-'))
  temporaryDirectories.push(root)
  await mkdir(path.join(root, 'src'), { recursive: true })
  await mkdir(path.join(root, 'node_modules', 'package'), { recursive: true })
  await writeFile(path.join(root, 'src', 'main.js'), 'const answer = 42;\n// ignored\n')
  await writeFile(path.join(root, 'README.md'), '# documentation\n')
  await writeFile(path.join(root, 'node_modules', 'package', 'index.js'), 'const dependency = true;\n')

  const result = await scanDirectory(root)
  assert.equal(result.source, 'path')
  assert.equal(result.fileCount, 1)
  assert.equal(result.totalCodeLines, 1)
  assert.equal(result.ignoredFileCount, 1)
  assert.deepEqual(result.files[0], {
    path: 'src/main.js',
    extension: '.js',
    totalLines: 2,
    codeLines: 1,
    blankLines: 0,
    commentLines: 1,
  })
})

test('rejects a missing path', async () => {
  await assert.rejects(() => scanDirectory(path.join(os.tmpdir(), 'code-line-counter-does-not-exist')), /ENOENT/)
})
