// Vorlage nexui 0.1.0
/**
 * The ui kit is in the app unchanged: every file of `src/vendor/nexui/` has the checksum its MANIFEST.json names (line
 * ends counted as LF), none is missing, none was added. Copied once by `bauplaene/ui/tools/sync.py`; then the app's file.
 * A change to the kit is made in bauplaene and copied again, never here.
 */
import { describe, expect, it } from 'vitest'

type Fs = { readFileSync: (file: string) => Uint8Array; readdirSync: (folder: string) => string[]; statSync: (path: string) => { isDirectory: () => boolean } }
type Crypto = { createHash: (name: string) => { update: (data: Uint8Array) => { digest: (encoding: string) => string } } }
// Loaded by name at run time: the app's TypeScript knows no node types.
const fsName = 'node:fs'
const cryptoName = 'node:crypto'
const fs = (await import(/* @vite-ignore */ fsName)) as Fs
const crypto = (await import(/* @vite-ignore */ cryptoName)) as Crypto

/** vitest runs in the app's frontend/ folder. */
const FOLDER = 'src/vendor/nexui'
const MANIFEST = `${FOLDER}/MANIFEST.json`

function digest(path: string): string {
  const raw = fs.readFileSync(path)
  const lf: number[] = []
  raw.forEach((byte, index) => {
    if (!(byte === 13 && raw[index + 1] === 10)) lf.push(byte)
  })
  return 'sha256-' + crypto.createHash('sha256').update(Uint8Array.from(lf)).digest('base64')
}

function files(folder: string): string[] {
  return fs.readdirSync(folder).flatMap((name) => {
    const path = `${folder}/${name}`
    return fs.statSync(path).isDirectory() ? files(path) : [path]
  })
}

describe('the ui kit', () => {
  it('is in the app exactly as bauplaene/ui made it', () => {
    const manifest = JSON.parse(new TextDecoder().decode(fs.readFileSync(MANIFEST))) as { module: string; version: string; files: Record<string, string> }
    expect(manifest.module).toBe('ui')
    const named = Object.keys(manifest.files).map((path) => path.replace(/^frontend\//, ''))
    for (const [path, expected] of Object.entries(manifest.files)) {
      expect(digest(path.replace(/^frontend\//, '')), path).toBe(expected)
    }
    expect(files(FOLDER).filter((path) => path !== MANIFEST).sort()).toEqual(named.sort())
  })
})
