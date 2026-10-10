// The files pdf.js may ask for while it reads a PDF (character maps, the 14 standard fonts, image decoders), copied
// from the package to public/pdfjs/ before Vite builds. The PDF frame never fetches them itself: the page does, by
// name, and hands them over (src/lib/pdfFrame.ts). Not in the repository; made anew on every build.
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const from = join(here, '..', 'node_modules', 'pdfjs-dist')
const to = join(here, '..', 'public', 'pdfjs')
rmSync(to, { recursive: true, force: true })
mkdirSync(to, { recursive: true })
for (const folder of ['cmaps', 'standard_fonts', 'wasm']) {
  cpSync(join(from, folder), join(to, folder), { recursive: true })
}
cpSync(join(from, 'LICENSE'), join(to, 'LICENSE'))
if (readdirSync(join(to, 'cmaps')).length < 100 || !existsSync(join(to, 'wasm', 'openjpeg.wasm'))) throw new Error('pdf.js files missing')
console.log(`pdf.js files: ${readdirSync(join(to, 'cmaps')).length} character maps, fonts, decoders`)
