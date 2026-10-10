/**
 * The page behind a link to an export, for somebody without an account: who shared it, for whom, how many documents,
 * the ZIP once it is packed, a word while it is packed, a gentle word for a link that does not work, and no call to
 * anything but the link's own routes.
 */
import { act } from 'react'
import { Route, Routes } from 'react-router-dom'

import { changeLanguage } from '../i18n'
import { Page, Server } from '../test/harness'
import { ExportLinkPage } from './ExportLinkPage'

const server = new Server()
const page = new Page()

// Made at run time: a token written out here would look like a secret to the scanners.
const TOKEN = 'lnx_' + Array.from({ length: 12 }, () => Math.floor(Math.random() * 16).toString(16)).join('')
const shown = { shared_by: 'Jule', recipient: 'Steuerbüro Lindenau', state: 'ready', documents: 341, size: 1_900_000_000, until: '2026-11-09T10:00:00Z', date_from: '2026-01-01', date_to: '2026-12-31' }

function open(at = `/x/${TOKEN}`) {
  return page.show(<Routes><Route path="x/:token" element={<ExportLinkPage />} /></Routes>, at)
}

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = { [`GET /api/v1/x/${TOKEN}`]: shown }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('the page behind a link to an export', () => {
  it('shows who shared it, for whom, how much, until when, and offers the ZIP', async () => {
    await open()
    expect(page.box.querySelector('h1')!.textContent).toBe('Export für Steuerbüro Lindenau')
    expect(page.text).toContain('Jule gibt dir einen Export')
    expect(page.text.replace(/\u00a0/g, ' ')).toContain('341 Dokumente · 1,9 GB')
    expect(page.text).toContain('Zeitraum 01.01.2026 bis 31.12.2026')
    expect(page.text).toContain('gilt bis 09.11.2026')
    const download = page.box.querySelector<HTMLAnchorElement>('a[download]')!
    expect(download.getAttribute('href')).toBe(`/api/v1/x/${TOKEN}/file`)
    expect(download.textContent).toContain('ZIP herunterladen')
    expect(page.text).toContain('Nur dieser Export ist freigegeben. Jule sieht, wann der Link geöffnet wurde')
    expect(server.calls.map((c) => c.url)).toEqual([`/api/v1/x/${TOKEN}`])
  })

  it('says that the ZIP is still being packed and offers nothing yet', async () => {
    server.answers[`GET /api/v1/x/${TOKEN}`] = { ...shown, state: 'packing', documents: 0, size: 0 }
    await open()
    expect(page.text).toContain('Das ZIP wird noch gepackt. Schau in ein paar Minuten noch einmal vorbei.')
    expect(page.box.querySelector('a[download]')).toBeNull()
  })

  it('asks again while the ZIP is packed and stops once it is ready', async () => {
    // The page's own waits (15 s) are kept here and run by hand; every other timer runs as always.
    const waiting: (() => void)[] = []
    const real = window.setTimeout
    const spy = vi.spyOn(window, 'setTimeout').mockImplementation(((handler: () => void, delay?: number) => {
      if (delay === 15_000) {
        waiting.push(handler)
        return 0
      }
      return real(handler, delay)
    }) as typeof window.setTimeout)
    try {
      server.answers[`GET /api/v1/x/${TOKEN}`] = { ...shown, state: 'packing', documents: 0, size: 0 }
      await open()
      expect(server.calls).toHaveLength(1)
      expect(waiting).toHaveLength(1)
      server.answers[`GET /api/v1/x/${TOKEN}`] = shown
      await act(async () => waiting.shift()!())
      await page.click(document.body)
      expect(server.calls).toHaveLength(2)
      expect(page.text).toContain('ZIP herunterladen')
      expect(waiting).toHaveLength(0)
    } finally {
      spy.mockRestore()
    }
  })

  it('has a gentle word for a link that does not work', async () => {
    server.fails[`GET /api/v1/x/${TOKEN}`] = { status: 404, code: 'not_found' }
    await open()
    expect(page.text).toContain('Dieser Link gilt nicht mehr')
    expect(page.box.querySelector('a[download]')).toBeNull()
  })

  it('speaks English', async () => {
    await changeLanguage('en', false)
    await open()
    expect(page.text).toContain('Jule gives you an export')
    expect(page.text).toContain('Download ZIP')
  })
})
