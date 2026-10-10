// The edge finder of the camera page: where the sheet of paper is in a frame of the camera.
//
// It runs apart from the page, in this worker, and is loaded only when the camera opens: OpenCV.js (WebAssembly, served
// by nexpaper itself) and jscanify (MIT, vendored next to it). OpenCV's bindings make functions at run time, so this
// script alone arrives with a policy that allows that (``SCANNER_CSP`` in the backend's middleware); the page keeps its
// strict one. The worker sees pixels and answers with four corners: no page, no cookie, no request of its own.
//
// Messages in: {type: 'find', id, width, height, pixels: ArrayBuffer (RGBA)}. Out: {type: 'ready'}, {type: 'failed'},
// {type: 'found', id, corners: [[x, y] x 4] | null} in the pixels of the frame, in any order (the page orders them).

/* global cv, jscanify, importScripts */

let ready = null
let scanner = null

function load() {
  if (ready) return ready
  ready = new Promise((resolve, reject) => {
    try {
      importScripts('/scanner/opencv.js', '/scanner/jscanify.js')
    } catch (error) {
      reject(error)
      return
    }
    const done = (module) => {
      if (module && module.Mat) self.cv = module
      scanner = new jscanify()
      resolve()
    }
    const found = self.cv
    if (!found) reject(new Error('OpenCV did not load'))
    else if (found.Mat) done(found)
    else if (typeof found.then === 'function') {
      // Newer builds hand out a promise of the module (and older ones a module that is its own "then").
      found.then((module) => {
        if (module && typeof module.then === 'function') delete module.then
        done(module || found)
      }, reject)
    } else found.onRuntimeInitialized = () => done(found)
  })
  return ready
}

function find(width, height, pixels) {
  const image = cv.matFromImageData({ data: new Uint8ClampedArray(pixels), width, height })
  let contour = null
  try {
    contour = scanner.findPaperContour(image)
    if (!contour) return null
    const corners = scanner.getCornerPoints(contour)
    const points = [corners.topLeftCorner, corners.topRightCorner, corners.bottomRightCorner, corners.bottomLeftCorner]
    if (points.some((point) => !point)) return null
    return points.map((point) => [point.x, point.y])
  } finally {
    image.delete()
    if (contour) contour.delete()
  }
}

self.onmessage = async (event) => {
  const message = event.data || {}
  if (message.type === 'load') {
    try {
      await load()
      self.postMessage({ type: 'ready' })
    } catch {
      self.postMessage({ type: 'failed' })
    }
    return
  }
  if (message.type !== 'find') return
  try {
    await load()
    const width = Math.min(4096, Math.max(1, message.width | 0))
    const height = Math.min(4096, Math.max(1, message.height | 0))
    if (!(message.pixels instanceof ArrayBuffer) || message.pixels.byteLength !== width * height * 4) throw new Error('size')
    self.postMessage({ type: 'found', id: message.id, corners: find(width, height, message.pixels) })
  } catch {
    self.postMessage({ type: 'found', id: message.id, corners: null })
  }
}
