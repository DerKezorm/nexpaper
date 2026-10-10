/**
 * What the camera does with a photo of a page, apart from any screen so that it can be tested: straightening the sheet
 * between its four corners (a perspective warp, computed here, no library), the looks (colour, greyscale, black and
 * white), and the PDF the pages become. The edges themselves are found by OpenCV in a worker (`public/scanner/worker.js`).
 *
 * Memory is the limit on a phone: a photo is cut down to `MAX_SHOT` pixels on its long side before anything else, and
 * a page to `MAX_PAGE`; a page is kept only as its JPEG.
 */

/** A point in pixels of the picture it belongs to. */
export type Pt = [number, number]
/** The corners of a sheet, in the order the frame draws them: top left, top right, bottom right, bottom left. */
export type Quad = [Pt, Pt, Pt, Pt]
export type Look = 'color' | 'gray' | 'bw'
export type Pixels = { data: Uint8ClampedArray; width: number; height: number }

/** The long side of a photo, in pixels, before it is straightened (about 8 megapixels at 4:3). */
export const MAX_SHOT = 3264
/** The long side of a straightened page: a little over 300 dots per inch on A4. */
export const MAX_PAGE = 3508
/** The long side of the frames the edge finder looks at. */
export const MAX_PROBE = 480

/** `[width, height]` scaled down (never up) so that the long side is at most `max`. */
export function fitWithin(width: number, height: number, max: number): [number, number] {
  const scale = Math.min(1, max / Math.max(width, height))
  return [Math.max(1, Math.round(width * scale)), Math.max(1, Math.round(height * scale))]
}

function distance(a: Pt, b: Pt): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1])
}

/** Four points in the frame's order, whatever order they came in: by their angle around the middle, top left first. */
export function order(points: Pt[]): Quad {
  const cx = points.reduce((sum, p) => sum + p[0], 0) / points.length
  const cy = points.reduce((sum, p) => sum + p[1], 0) / points.length
  const sorted = [...points].sort((a, b) => Math.atan2(a[1] - cy, a[0] - cx) - Math.atan2(b[1] - cy, b[0] - cx))
  // Clockwise on screen from the smallest angle; the top left is the one with the smallest x + y.
  let first = 0
  sorted.forEach((p, index) => {
    if (p[0] + p[1] < sorted[first][0] + sorted[first][1]) first = index
  })
  return [0, 1, 2, 3].map((step) => sorted[(first + step) % 4]) as Quad
}

/** The area of a quadrilateral (shoelace), positive for the frame's clockwise order. */
export function area(quad: Quad): number {
  let sum = 0
  for (let i = 0; i < 4; i++) {
    const [x1, y1] = quad[i]
    const [x2, y2] = quad[(i + 1) % 4]
    sum += x1 * y2 - x2 * y1
  }
  return sum / 2
}

/** A sheet worth taking: convex, and covering at least `minShare` of the picture. */
export function plausible(quad: Quad, width: number, height: number, minShare = 0.15): boolean {
  if (quad.some(([x, y]) => !Number.isFinite(x) || !Number.isFinite(y))) return false
  let sign = 0
  for (let i = 0; i < 4; i++) {
    const [ax, ay] = quad[i]
    const [bx, by] = quad[(i + 1) % 4]
    const [cx, cy] = quad[(i + 2) % 4]
    const cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
    if (cross === 0) return false
    if (sign === 0) sign = Math.sign(cross)
    else if (Math.sign(cross) !== sign) return false
  }
  return Math.abs(area(quad)) >= minShare * width * height
}

/** Whether a sheet stands still: no corner moved more than `share` of the picture's diagonal. */
export function steady(before: Quad | null, now: Quad | null, width: number, height: number, share = 0.03): boolean {
  if (!before || !now) return false
  const limit = share * Math.hypot(width, height)
  return now.every((point, index) => distance(point, before[index]) <= limit)
}

/** The corners scaled from one picture's pixels to another's. */
export function scale(quad: Quad, factorX: number, factorY = factorX): Quad {
  return quad.map(([x, y]) => [x * factorX, y * factorY]) as Quad
}

/** Corners a little inside the edges: where the frame starts when nothing was found. */
export function inset(width: number, height: number, share = 0.08): Quad {
  const dx = width * share
  const dy = height * share
  return [[dx, dy], [width - dx, dy], [width - dx, height - dy], [dx, height - dy]]
}

/** The corners moved a little towards the middle: the edge of the sheet (and the desk just past it) stays out of the
 * page. */
export function tighten(quad: Quad, share = 0.008): Quad {
  const cx = quad.reduce((sum, p) => sum + p[0], 0) / 4
  const cy = quad.reduce((sum, p) => sum + p[1], 0) / 4
  return quad.map(([x, y]) => [x + (cx - x) * share * 2, y + (cy - y) * share * 2]) as Quad
}

/** The size of the straightened page: as long as the longer of each pair of opposite sides, at most `max`. */
export function pageSize(quad: Quad, max = MAX_PAGE): [number, number] {
  const width = Math.max(distance(quad[0], quad[1]), distance(quad[3], quad[2]))
  const height = Math.max(distance(quad[0], quad[3]), distance(quad[1], quad[2]))
  return fitWithin(Math.max(1, width), Math.max(1, height), max)
}

/**
 * The perspective that takes the four points `from` to the four points `to`: the 3×3 matrix (row by row, the last entry
 * 1) of the plane projection, from the eight equations the corners give.
 */
export function homography(from: Quad, to: Quad): number[] {
  const rows: number[][] = []
  for (let i = 0; i < 4; i++) {
    const [x, y] = from[i]
    const [u, v] = to[i]
    rows.push([x, y, 1, 0, 0, 0, -u * x, -u * y, u])
    rows.push([0, 0, 0, x, y, 1, -v * x, -v * y, v])
  }
  // Gauss-Jordan with the largest pivot of each column.
  for (let col = 0; col < 8; col++) {
    let pivot = col
    for (let row = col + 1; row < 8; row++) if (Math.abs(rows[row][col]) > Math.abs(rows[pivot][col])) pivot = row
    if (Math.abs(rows[pivot][col]) < 1e-12) throw new Error('degenerate')
    ;[rows[col], rows[pivot]] = [rows[pivot], rows[col]]
    const lead = rows[col][col]
    for (let k = col; k < 9; k++) rows[col][k] /= lead
    for (let row = 0; row < 8; row++) {
      if (row === col) continue
      const factor = rows[row][col]
      if (factor === 0) continue
      for (let k = col; k < 9; k++) rows[row][k] -= factor * rows[col][k]
    }
  }
  return [...rows.map((row) => row[8]), 1]
}

/** Where the matrix takes a point. */
export function project(matrix: number[], [x, y]: Pt): Pt {
  const w = matrix[6] * x + matrix[7] * y + matrix[8]
  return [(matrix[0] * x + matrix[1] * y + matrix[2]) / w, (matrix[3] * x + matrix[4] * y + matrix[5]) / w]
}

/** The sheet between `quad` straightened into a picture of `width` × `height`, sampled between the four nearest pixels. */
export function warp(source: Pixels, quad: Quad, width: number, height: number): Pixels {
  const target: Quad = [[0, 0], [width, 0], [width, height], [0, height]]
  // From each pixel of the page back to the photo.
  const m = homography(target, quad)
  const out = new Uint8ClampedArray(width * height * 4)
  const { data, width: sw, height: sh } = source
  const maxX = sw - 1
  const maxY = sh - 1
  let at = 0
  for (let y = 0; y < height; y++) {
    const py = y + 0.5
    for (let x = 0; x < width; x++) {
      const px = x + 0.5
      const w = m[6] * px + m[7] * py + m[8]
      let sx = (m[0] * px + m[1] * py + m[2]) / w - 0.5
      let sy = (m[3] * px + m[4] * py + m[5]) / w - 0.5
      sx = sx < 0 ? 0 : sx > maxX ? maxX : sx
      sy = sy < 0 ? 0 : sy > maxY ? maxY : sy
      const x0 = sx | 0
      const y0 = sy | 0
      const x1 = x0 < maxX ? x0 + 1 : x0
      const y1 = y0 < maxY ? y0 + 1 : y0
      const fx = sx - x0
      const fy = sy - y0
      const a = (y0 * sw + x0) * 4
      const b = (y0 * sw + x1) * 4
      const c = (y1 * sw + x0) * 4
      const d = (y1 * sw + x1) * 4
      for (let k = 0; k < 3; k++) {
        const top = data[a + k] + (data[b + k] - data[a + k]) * fx
        const bottom = data[c + k] + (data[d + k] - data[c + k]) * fx
        out[at + k] = top + (bottom - top) * fy
      }
      out[at + 3] = 255
      at += 4
    }
  }
  return { data: out, width, height }
}

/** The look of a page, in place: colour stays as it is; greyscale is stretched to full contrast; black and white compares
 * each pixel with the mean of its neighbourhood (shadows across the sheet do not turn it black). */
export function applyLook(pixels: Pixels, look: Look): Pixels {
  if (look === 'color') return pixels
  const { data, width, height } = pixels
  const gray = new Uint8ClampedArray(width * height)
  for (let i = 0, j = 0; j < gray.length; i += 4, j++) gray[j] = (data[i] * 299 + data[i + 1] * 587 + data[i + 2] * 114) / 1000
  if (look === 'gray') {
    // The darkest and brightest 1 % set the range.
    const counts = new Uint32Array(256)
    for (const value of gray) counts[value]++
    const cut = gray.length * 0.01
    let low = 0
    let high = 255
    for (let sum = 0; low < 255 && sum + counts[low] <= cut; low++) sum += counts[low]
    for (let sum = 0; high > 0 && sum + counts[high] <= cut; high--) sum += counts[high]
    const span = Math.max(1, high - low)
    for (let i = 0, j = 0; j < gray.length; i += 4, j++) {
      const value = ((gray[j] - low) * 255) / span
      data[i] = data[i + 1] = data[i + 2] = value
    }
    return pixels
  }
  // Black and white (Bradley): darker than the mean around it by more than `t`.
  const integral = new Float64Array((width + 1) * (height + 1))
  for (let y = 0; y < height; y++) {
    let row = 0
    for (let x = 0; x < width; x++) {
      row += gray[y * width + x]
      integral[(y + 1) * (width + 1) + x + 1] = integral[y * (width + 1) + x + 1] + row
    }
  }
  const half = Math.max(7, Math.round(Math.max(width, height) / 32))
  const t = 0.15
  for (let y = 0; y < height; y++) {
    const y0 = Math.max(0, y - half)
    const y1 = Math.min(height, y + half + 1)
    for (let x = 0; x < width; x++) {
      const x0 = Math.max(0, x - half)
      const x1 = Math.min(width, x + half + 1)
      const sum = integral[y1 * (width + 1) + x1] - integral[y0 * (width + 1) + x1] - integral[y1 * (width + 1) + x0] + integral[y0 * (width + 1) + x0]
      const count = (x1 - x0) * (y1 - y0)
      const value = gray[y * width + x] * count < sum * (1 - t) ? 0 : 255
      const i = (y * width + x) * 4
      data[i] = data[i + 1] = data[i + 2] = value
    }
  }
  return pixels
}

/** One page of the PDF: a JPEG and its size in pixels. */
export type PdfPage = { jpeg: Uint8Array; width: number; height: number }

/**
 * A PDF of the pages, each a JPEG shown as it is (nothing re-encoded): the page is 210 mm wide and as tall as the photo's
 * proportions say, so an A4 sheet becomes an A4 page.
 */
export function makePdf(pages: PdfPage[]): Uint8Array {
  if (pages.length === 0) throw new Error('no pages')
  const encoder = new TextEncoder()
  const parts: Uint8Array[] = []
  const offsets: number[] = []
  let length = 0
  const add = (piece: Uint8Array | string) => {
    const bytes = typeof piece === 'string' ? encoder.encode(piece) : piece
    parts.push(bytes)
    length += bytes.length
  }
  const object = (number: number, body: string, stream?: Uint8Array) => {
    offsets[number] = length
    add(`${number} 0 obj\n${body}\n`)
    if (stream) {
      add('stream\n')
      add(stream)
      add('\nendstream\n')
    }
    add('endobj\n')
  }
  add('%PDF-1.4\n')
  add(new Uint8Array([0x25, 0xe2, 0xe3, 0xcf, 0xd3, 0x0a]))
  const kids = pages.map((_, index) => `${3 + index * 3} 0 R`).join(' ')
  object(1, '<< /Type /Catalog /Pages 2 0 R >>')
  object(2, `<< /Type /Pages /Kids [${kids}] /Count ${pages.length} >>`)
  pages.forEach((page, index) => {
    const first = 3 + index * 3
    const width = 595.28
    const height = Math.round(((width * page.height) / page.width) * 100) / 100
    const draw = encoder.encode(`q ${width} 0 0 ${height} 0 0 cm /Im0 Do Q`)
    object(first, `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${width} ${height}] /Resources << /XObject << /Im0 ${first + 2} 0 R >> >> /Contents ${first + 1} 0 R >>`)
    object(first + 1, `<< /Length ${draw.length} >>`, draw)
    object(first + 2, `<< /Type /XObject /Subtype /Image /Width ${page.width} /Height ${page.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${page.jpeg.length} >>`, page.jpeg)
  })
  const count = 3 + pages.length * 3
  const xref = length
  let table = `xref\n0 ${count}\n0000000000 65535 f \n`
  for (let number = 1; number < count; number++) table += `${String(offsets[number]).padStart(10, '0')} 00000 n \n`
  add(table)
  add(`trailer\n<< /Size ${count} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`)
  const out = new Uint8Array(length)
  let at = 0
  for (const part of parts) {
    out.set(part, at)
    at += part.length
  }
  return out
}

/** The name of a scan: "Scan 2026-10-09 14-30.pdf", in the person's local time. */
export function scanName(moment: Date): string {
  const two = (value: number) => String(value).padStart(2, '0')
  return `Scan ${moment.getFullYear()}-${two(moment.getMonth() + 1)}-${two(moment.getDate())} ${two(moment.getHours())}-${two(moment.getMinutes())}.pdf`
}
