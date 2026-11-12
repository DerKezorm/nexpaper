/**
 * The page behind a link, for somebody without an account: the document's title and sender, who shared it, until when;
 * the download only where the link allows it; a gentle word for a link that does not work; and no call to anything but
 * the link's own routes.
 */
import { act } from 'react'
import { Route, Routes } from 'react-router-dom'

import { changeLanguage } from '../i18n'
import { forgetPictures } from '../lib/pictures'
import { Page, Server, plain } from '../test/harness'
import { idle, until } from '../test/wait'
import { LinkPage } from './LinkPage'

const server = new Server()
const page = new Page()

const shown = { shared_by: 'Jule', recipient: 'Steuerbüro', title: 'Rechnung Heizungswartung', sender: 'Elektro Brandt GmbH', kind: 'Rechnung', date: '2026-10-06', pages: 2, until: '2026-10-31T10:00:00Z', allow_download: true, has_file: true, viewable: true }

function open(at = '/l/lnk_abc123456789') {
  return page.show(<Routes><Route path="l/:token" element={<LinkPage />} /></Routes>, at)
}

beforeEach(async () => {
  forgetPictures()
  await changeLanguage('de', false)
  server.answers = { 'GET /api/v1/l/lnk_abc123456789': shown }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('the page behind a link', () => {
  it('shows the document, who shared it and until when, and offers the download', async () => {
    await open()
    expect(page.box.querySelector('h1')!.textContent).toBe('Rechnung Heizungswartung')
    expect(page.text).toContain('Elektro Brandt GmbH · 2 Seiten')
    expect(page.text).toContain('Jule hat dir ein Dokument freigegeben')
    expect(page.text).toContain('gilt bis 31.10.2026')
    expect(page.text).toContain('Nur dieses Dokument ist freigegeben. Jule sieht, wann der Link geöffnet wurde')
    const download = page.box.querySelector<HTMLAnchorElement>('a[download]')!
    expect(download.getAttribute('href')).toBe('/api/v1/l/lnk_abc123456789/file')
    expect(page.box.querySelector('a[target="_blank"]')!.getAttribute('href')).toBe('/api/v1/l/lnk_abc123456789/file')
  })

  it('shows the name of who shared it as text, never as markup', async () => {
    server.answers['GET /api/v1/l/lnk_abc123456789'] = { ...shown, shared_by: '<strong>Jule</strong><name>x</name>' }
    await open()
    expect(page.box.querySelector('header strong, header name')).toBeNull()
    expect(page.text).toContain('<strong>Jule</strong><name>x</name> hat dir ein Dokument freigegeben')
  })

  it('asks the server for the link and for nothing else', async () => {
    await open()
    expect(server.calls.map((c) => `${c.method} ${c.url}`)).toEqual(['GET /api/v1/l/lnk_abc123456789'])
  })

  it('without downloading hands out no file at all: no download, no view in the browser, only the word "view only"', async () => {
    server.answers['GET /api/v1/l/lnk_abc123456789'] = { ...shown, allow_download: false, viewable: false }
    await open()
    expect(page.box.querySelector('a[download]')).toBeNull()
    expect(page.box.querySelector('a[target="_blank"]')).toBeNull()
    expect(page.box.querySelector('a[href*="/file"]')).toBeNull()
    expect(page.text).toContain('Nur zum Ansehen freigegeben, ohne Herunterladen.')
    // For the person who got the link: whom to ask (a document without pages to show).
    expect(page.text).toContain('Die Seiten lassen sich hier nicht zeigen.')
  })

  it('shows the pages as pictures of the own route of the link, small first and then sharp where the screen shows more', async () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 900 } as DOMRect)
    server.answers['GET /api/v1/l/lnk_abc123456789'] = { ...shown, has_pages: true, pages: 3 }
    await open()
    await until(() => page.box.querySelectorAll('img').length === 3)
    expect([...page.box.querySelectorAll('img')].map((img) => img.getAttribute('alt'))).toEqual(['Seite 1', 'Seite 2', 'Seite 3'])
    const asked = server.calls.map((c) => c.url).filter((url) => url.includes('/pages/'))
    for (const n of [1, 2, 3]) {
      expect(asked).toContain(`/api/v1/l/lnk_abc123456789/pages/${n}?size=small`)
      expect(asked).toContain(`/api/v1/l/lnk_abc123456789/pages/${n}?size=large`)
      // The small one comes first.
      expect(asked.indexOf(`/api/v1/l/lnk_abc123456789/pages/${n}?size=small`)).toBeLessThan(asked.indexOf(`/api/v1/l/lnk_abc123456789/pages/${n}?size=large`))
    }
    expect(page.text).not.toContain('Die Seiten lassen sich hier nicht zeigen.')
    vi.restoreAllMocks()
  })

  it('asks for no large picture where the small one is sharp enough (a phone)', async () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 358 } as DOMRect)
    server.answers['GET /api/v1/l/lnk_abc123456789'] = { ...shown, has_pages: true, pages: 3 }
    await open()
    await until(() => page.box.querySelectorAll('img').length === 3)
    expect(server.calls.filter((c) => c.url.includes('size=large'))).toEqual([])
    vi.restoreAllMocks()
  })

  it('asks only for the pages that come into view, the first at once', async () => {
    const watched: { element: Element; seen: (entries: { isIntersecting: boolean }[]) => void }[] = []
    vi.stubGlobal('IntersectionObserver', class {
      constructor(private seen: (entries: { isIntersecting: boolean }[]) => void) {}
      observe(element: Element) {
        watched.push({ element, seen: this.seen })
      }
      disconnect() {}
    })
    server.answers['GET /api/v1/l/lnk_abc123456789'] = { ...shown, has_pages: true, pages: 90 }
    await open()
    const pictures = () => server.calls.map((c) => c.url).filter((url) => url.includes('/pages/'))
    expect(pictures()).toEqual(['/api/v1/l/lnk_abc123456789/pages/1?size=small'])
    expect(watched).toHaveLength(89)
    await act(async () => watched[4].seen([{ isIntersecting: true }]))
    await idle()
    expect(pictures()).toContain('/api/v1/l/lnk_abc123456789/pages/6?size=small')
    expect(pictures()).toHaveLength(2)
  })

  it('shows the pages also where the link does not allow downloading, and still hands out no file', async () => {
    server.answers['GET /api/v1/l/lnk_abc123456789'] = { ...shown, has_pages: true, allow_download: false, viewable: false }
    await open()
    await until(() => page.box.querySelectorAll('img').length === 2)
    expect(page.text).toContain('Nur zum Ansehen freigegeben, ohne Herunterladen.')
    expect(page.box.querySelector('a[download]')).toBeNull()
    expect(page.box.querySelector('a[href*="/file"]')).toBeNull()
  })

  it('shows no pictures for a document without pages', async () => {
    server.answers['GET /api/v1/l/lnk_abc123456789'] = { ...shown, has_pages: false, pages: 0 }
    await open()
    expect(page.box.querySelector('img')).toBeNull()
  })

  it('offers "view in the browser" only where the browser can show the file', async () => {
    server.answers['GET /api/v1/l/lnk_abc123456789'] = { ...shown, viewable: false }
    await open()
    expect(page.box.querySelector('a[download]')).toBeTruthy()
    expect(page.box.querySelector('a[target="_blank"]')).toBeNull()
  })

  it('names nobody when the person who shared it has no display name', async () => {
    server.answers['GET /api/v1/l/lnk_abc123456789'] = { ...shown, shared_by: '' }
    await open()
    expect(page.text).toContain('Dir wurde ein Dokument freigegeben')
    expect(page.text).toContain('Wer den Link gemacht hat, sieht')
  })

  it('says the document is still being processed when there is no file yet', async () => {
    server.answers['GET /api/v1/l/lnk_abc123456789'] = { ...shown, has_file: false, viewable: false }
    await open()
    expect(page.text).toContain('Das Dokument wird noch verarbeitet.')
    expect(page.box.querySelector('a[download]')).toBeNull()
    expect(page.box.querySelector('a[target="_blank"]')).toBeNull()
  })

  it('says a link that does not work does not work, and tells nothing about why', async () => {
    server.fails['GET /api/v1/l/lnk_abc123456789'] = { status: 404, code: 'not_found' }
    await open()
    expect(page.text).toContain('Dieser Link gilt nicht mehr')
    expect(page.box.querySelector('h1')).toBeNull()
    // No sentence in the header: nobody shared anything that can be named.
    expect(page.box.querySelector('header')!.textContent).toBe('')
  })

  it('says to wait when the address has made too many wrong tries', async () => {
    server.fails['GET /api/v1/l/lnk_abc123456789'] = { status: 429, code: 'too_many_attempts' }
    await open()
    expect(page.text).toContain('Zu viele Versuche')
    expect(page.box.querySelector('header')!.textContent).toBe('')
  })

  it('speaks English too', async () => {
    await changeLanguage('en', false)
    await open()
    expect(page.text).toContain('Jule has shared a document with you')
    expect(page.text).toContain('Elektro Brandt GmbH · 2 pages')
    expect(page.text).toContain('valid until')
  })
})

describe('what goes with it (N2)', () => {
  const also = [
    { id: 41, title: 'Lieferschein Oktober', kind: 'Lieferschein', date: '2026-10-02', pages: 1, has_file: true, viewable: true, has_pages: true },
    { id: 42, title: 'Auftragsbestätigung', kind: null, date: null, pages: 2, has_file: true, viewable: false, has_pages: false },
  ]
  const entry = (title: string) => [...page.box.querySelectorAll<HTMLButtonElement>('section button')].find((b) => b.textContent?.includes(title))

  it('lists the further documents under the document, with kind, date and pages', async () => {
    server.answers['GET /api/v1/l/lnk_abc123456789'] = { ...shown, also }
    await open()
    expect(page.text).toContain('Gehört dazu')
    expect(page.text).toContain('Lieferschein Oktober')
    expect(page.text).toContain('Lieferschein · 02.10.2026 · 1 Seite')
    expect(page.text).toContain('Auftragsbestätigung')
    expect(page.text).toContain('Nur diese 3 Dokumente sind freigegeben. Jule sieht, wann der Link geöffnet wurde')
    // The head says how many, as the foot does.
    expect(plain(page.box.querySelector('header')!.textContent)).toBe('Jule hat dir 3 Dokumente freigegeben gilt bis 31.10.2026')
  })

  it('counts in the head also without a name', async () => {
    server.answers['GET /api/v1/l/lnk_abc123456789'] = { ...shown, shared_by: '', also: also.slice(0, 1) }
    await open()
    expect(page.text).toContain('Dir wurden 2 Dokumente freigegeben')
  })

  it('opens one in the same page under the link’s own paths, and goes back to the first', async () => {
    server.answers['GET /api/v1/l/lnk_abc123456789'] = { ...shown, has_pages: false, also }
    await open()
    await page.click(entry('Lieferschein Oktober'))
    expect(page.box.querySelector('h1')!.textContent).toBe('Lieferschein Oktober')
    expect(page.box.querySelector<HTMLAnchorElement>('a[download]')!.getAttribute('href')).toBe('/api/v1/l/lnk_abc123456789/also/41/file')
    await until(() => page.box.querySelectorAll('img').length === 1)
    const pictures = server.calls.map((c) => c.url).filter((url) => url.includes('/pages/'))
    expect(pictures.length).toBeGreaterThan(0)
    expect(pictures.every((url) => url.startsWith('/api/v1/l/lnk_abc123456789/also/41/pages/'))).toBe(true)
    // Only the link's own routes: never a document's number of its own.
    expect(server.calls.every((c) => c.url.startsWith('/api/v1/l/lnk_abc123456789'))).toBe(true)
    await page.click(document.querySelector<HTMLButtonElement>('[data-testid="link-back"]'))
    expect(page.box.querySelector('h1')!.textContent).toBe('Rechnung Heizungswartung')
    expect(page.box.querySelector<HTMLAnchorElement>('a[download]')!.getAttribute('href')).toBe('/api/v1/l/lnk_abc123456789/file')
  })

  it('without downloading hands out no file of the further documents either', async () => {
    server.answers['GET /api/v1/l/lnk_abc123456789'] = { ...shown, allow_download: false, viewable: false, also: also.map((a) => ({ ...a, viewable: false })) }
    await open()
    await page.click(entry('Auftragsbestätigung'))
    expect(page.box.querySelector('h1')!.textContent).toBe('Auftragsbestätigung')
    expect(page.box.querySelector('a[href*="/file"]')).toBeNull()
    expect(page.text).toContain('Nur zum Ansehen freigegeben, ohne Herunterladen.')
  })

  it('shows no list and the old footer for a link with one document', async () => {
    server.answers['GET /api/v1/l/lnk_abc123456789'] = { ...shown, also: [] }
    await open()
    expect(page.text).not.toContain('Gehört dazu')
    expect(page.text).toContain('Nur dieses Dokument ist freigegeben.')
  })

  it('speaks English too', async () => {
    await changeLanguage('en', false)
    server.answers['GET /api/v1/l/lnk_abc123456789'] = { ...shown, also }
    await open()
    expect(page.text).toContain('Goes with it')
    expect(page.text).toContain('Only these 3 documents are shared.')
    expect(page.text).toContain('Jule has shared 3 documents with you')
  })
})
