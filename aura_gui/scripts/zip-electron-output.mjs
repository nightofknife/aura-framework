import { createWriteStream } from 'node:fs'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { ZipArchive } from 'archiver'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const guiRoot = path.resolve(__dirname, '..')

function argValue(name, fallback = '') {
  const index = process.argv.indexOf(name)
  if (index < 0 || index + 1 >= process.argv.length) return fallback
  return process.argv[index + 1]
}

const version = argValue('--version', '0.1.0')
const input = path.resolve(guiRoot, argValue('--input', 'release/win-unpacked'))
const output = path.resolve(guiRoot, argValue('--output', `release/AuraGUI-win-x64-${version}.zip`))

await fs.access(input)
await fs.mkdir(path.dirname(output), { recursive: true })

const archive = new ZipArchive({ zlib: { level: 9 } })
const stream = createWriteStream(output)

const completed = new Promise((resolve, reject) => {
  stream.on('close', resolve)
  archive.on('error', reject)
})

archive.pipe(stream)
archive.directory(input, false)
await archive.finalize()
await completed

console.log(JSON.stringify({ status: 'success', path: output, bytes: archive.pointer() }, null, 2))
