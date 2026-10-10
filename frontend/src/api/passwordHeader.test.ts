/** The password of a backup upload travels in a header; umlauts must arrive as they were typed. */
import { passwordHeader } from './client'

describe('the password header', () => {
  it('is base64 of the UTF-8, so umlauts and symbols survive', () => {
    for (const password of ['plain-password-12', 'Grüße aus Köln 2026', 'emoji 🎨 pass']) {
      const decoded = new TextDecoder().decode(Uint8Array.from(atob(passwordHeader(password)), (c) => c.charCodeAt(0)))
      expect(decoded).toBe(password)
    }
  })

  it('carries only header-safe characters', () => {
    expect(passwordHeader('Grüße')).toMatch(/^[A-Za-z0-9+/=]+$/)
  })
})
