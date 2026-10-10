import { ACCEPT, ACCEPT_PHOTOS } from './formats'

describe('what a file dialog offers', () => {
  it('names the kinds the server takes and not every picture', () => {
    const list = ACCEPT.split(',')
    for (const taken of ['application/pdf', 'image/jpeg', 'image/png', 'image/tiff', 'image/heic', 'image/webp', 'image/avif', 'application/xml', '.pdf', '.webp', '.avif', '.heic', '.xml']) {
      expect(list).toContain(taken)
    }
    expect(list).not.toContain('image/*')
    expect(list.some((entry) => entry === 'image/gif' || entry === '.gif' || entry === '.bmp' || entry === '.svg')).toBe(false)
  })

  it('offers the library of photos only pictures, and the same pictures', () => {
    const photos = ACCEPT_PHOTOS.split(',')
    expect(photos.every((entry) => entry.startsWith('image/'))).toBe(true)
    expect(photos).toEqual(expect.arrayContaining(['image/jpeg', 'image/heic', 'image/webp', 'image/avif']))
    for (const entry of photos) expect(ACCEPT.split(',')).toContain(entry)
  })
})
