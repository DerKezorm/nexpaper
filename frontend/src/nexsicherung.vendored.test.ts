// Vorlage nexsicherung 1.0.0
/**
 * The page of the module sicherung is in the app unchanged: every file of `src/vendor/nexsicherung/` has the checksum
 * the module's MANIFEST.json names (line ends counted as LF), none is missing, none was added. Copied once by
 * `bauplaene/sicherung/tools/sync.py`; then the app's file. A change is made in bauplaene and copied again, never here.
 */
import { describe, expect, it } from 'vitest'

type Fs = { readFileSync: (file: string) => Uint8Array; readdirSync: (folder: string) => string[]; statSync: (path: string) => { isDirectory: () => boolean } }
type Crypto = { createHash: (name: string) => { update: (data: Uint8Array) => { digest: (encoding: string) => string } } }
// Loaded by name at run time: the app's TypeScript knows no node types.
const fsName = 'node:fs'
const cryptoName = 'node:crypto'
const fs = (await import(/* @vite-ignore */ fsName)) as Fs
const crypto = (await import(/* @vite-ignore */ cryptoName)) as Crypto

/** vitest runs in the app's frontend/ folder; the manifest lies beside the package in the backend. */
const FOLDER = 'src/vendor/nexsicherung'
const MANIFEST = '../backend/app/vendor/nexsicherung/MANIFEST.json'

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

describe('the page of the module sicherung', () => {
  it('is in the app exactly as bauplaene/sicherung made it', () => {
    const manifest = JSON.parse(new TextDecoder().decode(fs.readFileSync(MANIFEST))) as { module: string; files: Record<string, string> }
    expect(manifest.module).toBe('sicherung')
    const named = Object.keys(manifest.files)
      .filter((path) => path.startsWith(`frontend/${FOLDER}/`))
      .map((path) => path.replace(/^frontend\//, ''))
    expect(named.length).toBeGreaterThan(4)
    for (const path of named) expect(digest(path), path).toBe(manifest.files[`frontend/${path}`])
    expect(files(FOLDER).sort()).toEqual(named.sort())
  })
})
