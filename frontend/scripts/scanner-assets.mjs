// OpenCV.js for the camera's edge finder (`public/scanner/worker.js`), copied from node_modules into public/scanner
// before the dev server or a build starts. 13 MB that change only with the package, so they are not kept in the
// repository; nexpaper serves them itself (no CDN), and only the camera page loads them.
import { copyFileSync, existsSync, mkdirSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const from = join(here, '..', 'node_modules', '@techstark', 'opencv-js')
const to = join(here, '..', 'public', 'scanner')
mkdirSync(to, { recursive: true })
for (const [source, target] of [
  [join(from, 'dist', 'opencv.js'), join(to, 'opencv.js')],
  [join(from, 'LICENSE'), join(to, 'opencv.LICENSE.txt')],
]) {
  if (!existsSync(source)) {
    console.error(`missing ${source}: run npm ci first`)
    process.exit(1)
  }
  if (existsSync(target) && statSync(target).size === statSync(source).size && statSync(target).mtimeMs >= statSync(source).mtimeMs) continue
  copyFileSync(source, target)
}
