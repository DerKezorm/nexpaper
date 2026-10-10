/** What the camera does with a photo: corners in order, the perspective, the straightened page, the looks, the PDF. */
import { applyLook, area, fitWithin, homography, inset, makePdf, order, pageSize, plausible, project, scale, scanName, steady, tighten, warp, type Pixels, type Quad } from './scan'

function blank(width: number, height: number, value = 0): Pixels {
  const data = new Uint8ClampedArray(width * height * 4)
  for (let i = 0; i < data.length; i += 4) {
    data[i] = data[i + 1] = data[i + 2] = value
    data[i + 3] = 255
  }
  return { data, width, height }
}

function at(pixels: Pixels, x: number, y: number): number {
  return pixels.data[(y * pixels.width + x) * 4]
}

describe('the corners', () => {
  it('come in the frame order whatever order they came in', () => {
    const quad: Quad = [[10, 12], [90, 8], [95, 140], [5, 130]]
    for (const shuffled of [[quad[2], quad[0], quad[3], quad[1]], [quad[3], quad[2], quad[1], quad[0]], [quad[1], quad[3], quad[0], quad[2]]]) {
      expect(order(shuffled)).toEqual(quad)
    }
  })

  it('are a sheet only when convex and large enough', () => {
    const sheet: Quad = [[10, 10], [90, 10], [90, 130], [10, 130]]
    expect(plausible(sheet, 100, 140)).toBe(true)
    expect(area(sheet)).toBe(80 * 120)
    expect(plausible([[10, 10], [20, 10], [20, 20], [10, 20]], 100, 140)).toBe(false)
    expect(plausible([[10, 10], [90, 130], [90, 10], [10, 130]], 100, 140)).toBe(false)
    expect(plausible([[10, 10], [90, 10], [50, 50], [10, 130]], 100, 140)).toBe(false)
    expect(plausible([[10, 10], [90, 10], [90, Number.NaN], [10, 130]], 100, 140)).toBe(false)
  })

  it('hold still when no corner moved more than a little', () => {
    const sheet: Quad = [[10, 10], [90, 10], [90, 130], [10, 130]]
    expect(steady(sheet, scale(sheet, 1.01), 100, 140)).toBe(true)
    expect(steady(sheet, [[30, 10], [90, 10], [90, 130], [10, 130]], 100, 140)).toBe(false)
    expect(steady(null, sheet, 100, 140)).toBe(false)
  })

  it('move a little towards the middle before the page is cut out', () => {
    expect(tighten([[0, 0], [100, 0], [100, 100], [0, 100]], 0.05)).toEqual([[5, 5], [95, 5], [95, 95], [5, 95]])
  })

  it('start a little inside the picture when nothing was found', () => {
    expect(inset(1000, 2000)).toEqual([[80, 160], [920, 160], [920, 1840], [80, 1840]])
  })
})

describe('the sizes', () => {
  it('are cut down to the long side, never blown up', () => {
    expect(fitWithin(4000, 3000, 2000)).toEqual([2000, 1500])
    expect(fitWithin(300, 400, 2000)).toEqual([300, 400])
  })

  it('of a page follow the longer of each pair of sides', () => {
    expect(pageSize([[0, 0], [100, 10], [110, 200], [0, 180]])).toEqual([Math.round(Math.hypot(110, 20)), Math.round(Math.hypot(10, 190))])
    const [width, height] = pageSize([[0, 0], [5000, 0], [5000, 7000], [0, 7000]])
    expect(Math.max(width, height)).toBe(3508)
  })
})

describe('the perspective', () => {
  it('takes the four corners where they belong, and the middle with them', () => {
    const from: Quad = [[30, 20], [270, 40], [250, 380], [20, 360]]
    const to: Quad = [[0, 0], [210, 0], [210, 297], [0, 297]]
    const matrix = homography(from, to)
    from.forEach((point, index) => {
      const [x, y] = project(matrix, point)
      expect(x).toBeCloseTo(to[index][0], 6)
      expect(y).toBeCloseTo(to[index][1], 6)
    })
  })

  it('refuses corners that lie on one line', () => {
    expect(() => homography([[0, 0], [1, 1], [2, 2], [3, 3]], [[0, 0], [1, 0], [1, 1], [0, 1]])).toThrow()
  })

  it('straightens a sheet lying askew into an upright page', () => {
    // A white sheet with a black square in its upper left quarter, drawn askew on a dark desk.
    const width = 200
    const height = 200
    const photo = blank(width, height, 30)
    const sheet: Quad = [[40, 30], [170, 50], [160, 180], [30, 165]]
    const toPage = homography(sheet, [[0, 0], [100, 0], [100, 100], [0, 100]])
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const [u, v] = project(toPage, [x + 0.5, y + 0.5])
        if (u < 0 || u > 100 || v < 0 || v > 100) continue
        const value = u < 50 && v < 50 ? 0 : 255
        const i = (y * width + x) * 4
        photo.data[i] = photo.data[i + 1] = photo.data[i + 2] = value
      }
    }
    const page = warp(photo, sheet, 100, 100)
    expect([page.width, page.height]).toEqual([100, 100])
    expect(at(page, 20, 20)).toBeLessThan(40)
    expect(at(page, 80, 20)).toBeGreaterThan(215)
    expect(at(page, 20, 80)).toBeGreaterThan(215)
    expect(at(page, 80, 80)).toBeGreaterThan(215)
    expect(page.data[3]).toBe(255)
  })
})

describe('the looks', () => {
  it('keep colour, stretch greyscale, and make black and white of a shadowed page', () => {
    const colour = blank(4, 1)
    colour.data.set([200, 10, 10, 255], 0)
    expect(Array.from(applyLook(colour, 'color').data.slice(0, 3))).toEqual([200, 10, 10])
    const grey = blank(10, 1)
    for (let x = 0; x < 10; x++) grey.data.fill(100 + x * 5, x * 4, x * 4 + 3)
    applyLook(grey, 'gray')
    expect(at(grey, 0, 0)).toBe(0)
    expect(at(grey, 9, 0)).toBe(255)
    // Black text on paper that grows darker to the right: the text stays black, the paper turns white everywhere.
    const shadow = blank(64, 64)
    for (let y = 0; y < 64; y++)
      for (let x = 0; x < 64; x++) {
        const paper = 230 - x * 2
        const text = y >= 30 && y < 34 && x % 8 < 4
        shadow.data.fill(text ? paper - 120 : paper, (y * 64 + x) * 4, (y * 64 + x) * 4 + 3)
      }
    applyLook(shadow, 'bw')
    expect(at(shadow, 2, 10)).toBe(255)
    expect(at(shadow, 60, 10)).toBe(255)
    expect(at(shadow, 1, 31)).toBe(0)
    expect(at(shadow, 57, 31)).toBe(0)
  })
})

describe('the PDF', () => {
  const jpeg = (fill: number) => new Uint8Array([0xff, 0xd8, 0xff, 0xe0, fill, fill, 0xff, 0xd9])

  it('holds every page as its JPEG, and its table points at every object', () => {
    const pdf = makePdf([{ jpeg: jpeg(1), width: 2480, height: 3508 }, { jpeg: jpeg(2), width: 3000, height: 2000 }])
    const text = new TextDecoder('latin1').decode(pdf)
    expect(text.startsWith('%PDF-1.4\n')).toBe(true)
    expect(text.trimEnd().endsWith('%%EOF')).toBe(true)
    expect(text).toContain('/Count 2')
    expect(text).toContain('/MediaBox [0 0 595.28 842.03]')
    expect(text).toContain('/MediaBox [0 0 595.28 396.85]')
    expect((text.match(/\/Filter \/DCTDecode/g) ?? []).length).toBe(2)
    const start = Number(/startxref\n(\d+)/.exec(text)![1])
    expect(text.slice(start, start + 4)).toBe('xref')
    const offsets = [...text.slice(start).matchAll(/^(\d{10}) 00000 n $/gm)].map((match) => Number(match[1]))
    expect(offsets).toHaveLength(8)
    offsets.forEach((offset, index) => expect(text.slice(offset, offset + `${index + 1} 0 obj`.length)).toBe(`${index + 1} 0 obj`))
    // The JPEG is inside as it came, byte for byte.
    const bytes = Array.from(pdf)
    const first = bytes.findIndex((_, i) => bytes[i] === 0xff && bytes[i + 1] === 0xd8 && bytes[i + 4] === 1)
    expect(bytes.slice(first, first + 8)).toEqual(Array.from(jpeg(1)))
  })

  it('needs a page', () => {
    expect(() => makePdf([])).toThrow()
  })

  it('is named after the moment it was taken', () => {
    expect(scanName(new Date(2026, 9, 9, 14, 5))).toBe('Scan 2026-10-09 14-05.pdf')
  })
})
