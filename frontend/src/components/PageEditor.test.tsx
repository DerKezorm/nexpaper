/**
 * The page editor against test data: the pages of the current version, turning, moving, deleting, saving as a new version
 * (with the version it was made for), nothing to save, a change in the meantime, and "Ab hier eigenes Dokument".
 */
import { act } from 'react'

import { changeLanguage } from '../i18n'
import { Page, Server } from '../test/harness'
import { PageEditor } from './PageEditor'

const server = new Server()
const page = new Page()
const say = vi.fn()
const onDone = vi.fn()
const onSplit = vi.fn()

function open(pages = 3) {
  return page.show(<PageEditor document={{ id: 5, pages, current_version: 2 }} onDone={onDone} onSplit={onSplit} say={say} />)
}

const pictures = () => [...document.querySelectorAll<HTMLElement>('[data-testid="page-editor"] [data-src]')]

beforeEach(async () => {
  await changeLanguage('de', false)
  say.mockClear()
  onDone.mockClear()
  onSplit.mockClear()
  server.answers = { 'POST /api/v1/documents/5/pages': { id: 5, pages: 2, current_version: 3 } }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('the page editor', () => {
  it('shows the pages of the current version and says what it does', async () => {
    await open()
    expect(page.text).toContain('Seite antippen, dann drehen, verschieben oder löschen. Gespeichert wird als neue Fassung, das Original bleibt.')
    expect(pictures().map((img) => img.getAttribute('data-src'))).toEqual([
      '/api/v1/documents/5/versions/2/pages/1?size=small',
      '/api/v1/documents/5/versions/2/pages/2?size=small',
      '/api/v1/documents/5/versions/2/pages/3?size=small',
    ])
    expect(page.button('Nach vorn')!.disabled).toBe(true)
  })

  it('turns, moves and deletes, and saves the pages in their new order for the version it was made for', async () => {
    await open()
    await page.click(page.button('Rechts drehen'))
    expect(pictures()[0].style.transform).toBe('rotate(90deg) scale(0.707)')
    await page.click(page.button('Nach hinten'))
    await page.click(page.button('Seite 3 wählen'))
    await page.click(page.button('Links drehen'))
    await page.click(page.button('Links drehen'))
    await page.click(page.button('Seite 1 wählen'))
    await page.click(page.button('Seite löschen'))
    await page.click(page.button('Speichern'))
    expect(server.called('POST', '/api/v1/documents/5/pages')!.body).toEqual({
      base_version: 2,
      pages: [{ page: 1, turn: 90 }, { page: 3, turn: 180 }],
    })
    expect(say).toHaveBeenCalledWith('Gespeichert als neue Fassung. Das Original bleibt erhalten.')
    expect(onDone).toHaveBeenCalledWith({ id: 5, pages: 2, current_version: 3 })
  })

  it('saves nothing when nothing changed, and cancels', async () => {
    await open()
    await page.click(page.button('Rechts drehen'))
    await page.click(page.button('Links drehen'))
    await page.click(page.button('Speichern'))
    expect(server.changes()).toEqual([])
    expect(onDone).toHaveBeenCalledWith(null)
    await page.click(page.button('Abbrechen'))
    expect(onDone).toHaveBeenCalledTimes(2)
  })

  it('says so when the document changed in the meantime, and keeps what was done', async () => {
    server.fails = { 'POST /api/v1/documents/5/pages': { status: 409, code: 'version_changed', values: { current_version: 3 } } }
    await open()
    await page.click(page.button('Seite löschen'))
    await page.click(page.button('Speichern'))
    expect(page.text).toContain('Das Dokument hat sich inzwischen geändert. Sieh es dir noch einmal an.')
    expect(onDone).not.toHaveBeenCalled()
    expect(pictures()).toHaveLength(2)
  })

  it('offers to start again from the current version after a change in the meantime', async () => {
    server.fails = { 'POST /api/v1/documents/5/pages': { status: 409, code: 'version_changed', values: { current_version: 3 } } }
    server.answers['GET /api/v1/documents/5'] = { id: 5, pages: 2, current_version: 3 }
    await open()
    await page.click(page.button('Rechts drehen'))
    await page.click(page.button('Speichern'))
    await page.click(page.button('Neu laden'))
    expect(pictures().map((img) => img.getAttribute('data-src'))).toEqual([
      '/api/v1/documents/5/versions/3/pages/1?size=small',
      '/api/v1/documents/5/versions/3/pages/2?size=small',
    ])
    expect(page.button('Neu laden')).toBeUndefined()
    server.fails = {}
    await page.click(page.button('Seite löschen'))
    await page.click(page.button('Speichern'))
    expect(server.calls.filter((c) => c.method === 'POST').at(-1)!.body).toEqual({ base_version: 3, pages: [{ page: 2, turn: 0 }] })
  })

  it('sends one request for two quick clicks on Speichern', async () => {
    let answer: (value: Response) => void = () => undefined
    const fetcher = vi.fn((_url: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') === 'GET') return Promise.resolve(new Response('{}', { status: 200 }))
      return new Promise<Response>((resolve) => (answer = resolve))
    })
    vi.stubGlobal('fetch', fetcher)
    await open()
    await page.click(page.button('Seite löschen'))
    const save = page.button('Speichern')!
    await act(async () => {
      save.click()
      save.click()
    })
    const posts = fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')
    expect(posts).toHaveLength(1)
    await act(async () => answer(new Response(JSON.stringify({ id: 5, pages: 2, current_version: 3 }), { status: 200, headers: { 'Content-Type': 'application/json' } })))
  })

  it('makes a document of its own from the page chosen on, after asking once', async () => {
    server.answers['POST /api/v1/documents/5/split'] = { items: [{ id: 8 }, { id: 9 }] }
    await open()
    expect(page.button('Ab hier eigenes Dokument')!.disabled).toBe(true)
    await page.click(page.button('Seite 3 wählen'))
    await page.click(page.button('Ab hier eigenes Dokument'))
    expect(page.text).toContain('Ab Seite 3 wird ein eigenes Dokument.')
    expect(server.changes()).toEqual([])
    await page.click(page.button('Aufteilen'))
    expect(server.called('POST', '/api/v1/documents/5/split')!.body).toEqual({
      base_version: 2,
      parts: [{ pages: [{ page: 1, turn: 0 }, { page: 2, turn: 0 }] }, { pages: [{ page: 3, turn: 0 }] }],
    })
    expect(onSplit).toHaveBeenCalledWith([{ id: 8 }, { id: 9 }])
  })

  it('never deletes the last page', async () => {
    await open(1)
    expect(page.button('Seite löschen')!.disabled).toBe(true)
  })

  it('speaks English too', async () => {
    await changeLanguage('en', false)
    await open()
    expect(page.button('Turn right')).toBeTruthy()
    expect(page.text).toContain('It is saved as a new version; the original stays.')
  })
})
