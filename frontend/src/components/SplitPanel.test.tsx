/**
 * Splitting a batch scan against test data: the separators the server found, cutting and joining between pages, a page taken
 * for a separator by mistake, splitting (the separators are dropped), and keeping it as one document.
 */
import { changeLanguage } from '../i18n'
import { Page, Server } from '../test/harness'
import { SplitPanel } from './SplitPanel'

const server = new Server()
const page = new Page()
const say = vi.fn()
const onSplit = vi.fn()
const onKeep = vi.fn()

const stack = { id: 5, title: 'Stapelscan vom Drucker', pages: 6, current_version: 1, source: 'folder' }
const proposal = { version: 1, checked: true, blank_pages: [2, 5], parts: [[1], [3, 4], [6]], duplex: false, dismissed: false, suggested: true }

function open(document = stack) {
  return page.show(<SplitPanel document={document} onSplit={onSplit} onKeep={onKeep} say={say} />)
}
const parts = () => [...document.querySelectorAll('[data-testid="split-panel"] ol li')].map((li) => li.textContent)
const go = () => [...document.querySelectorAll('button')].find((b) => b.textContent?.trim().startsWith('In '))

beforeEach(async () => {
  await changeLanguage('de', false)
  for (const fn of [say, onSplit, onKeep]) fn.mockClear()
  server.answers = {
    'GET /api/v1/documents/5/separators': proposal,
    'POST /api/v1/documents/5/split': { items: [{ id: 11 }, { id: 12 }, { id: 13 }] },
    'DELETE /api/v1/documents/5/separators': 204,
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('splitting a batch scan', () => {
  it('says what was found and proposes the parts', async () => {
    await open()
    expect(page.text).toContain('Stapelscan aufteilen?')
    expect(page.text).toContain('6 Seiten aus dem Eingangsordner. nexpaper hat 2 leere Trennblätter gefunden und schlägt 3 Dokumente vor. Ein Klick zwischen zwei Seiten schneidet dort oder fügt wieder zusammen.')
    expect(parts()).toEqual(['1Stapelscan vom Drucker (1)Seite 1', '2Stapelscan vom Drucker (2)Seiten 3, 4', '3Stapelscan vom Drucker (3)Seite 6'])
    expect(page.text.match(/Trennblatt/g)?.length).toBe(2)
    expect(go()!.textContent).toContain('In 3 Dokumente aufteilen')
  })

  it('splits as shown: each part its pages, the separators dropped', async () => {
    await open()
    await page.click(go())
    expect(server.called('POST', '/api/v1/documents/5/split')!.body).toEqual({
      base_version: 1,
      parts: [{ pages: [{ page: 1, turn: 0 }] }, { pages: [{ page: 3, turn: 0 }, { page: 4, turn: 0 }] }, { pages: [{ page: 6, turn: 0 }] }],
    })
    expect(say).toHaveBeenCalledWith('In 3 Dokumente aufgeteilt. Die Trennblätter sind weg.')
    expect(onSplit).toHaveBeenCalledWith([{ id: 11 }, { id: 12 }, { id: 13 }])
  })

  it('cuts between two pages and joins them again', async () => {
    await open()
    await page.click(page.button('Hier schneiden'))
    expect(parts()).toHaveLength(4)
    expect(parts()[1]).toContain('Seite 3')
    await page.click(page.button('Wieder zusammenfügen'))
    expect(parts()).toHaveLength(3)
  })

  it('keeps a page that was taken for a separator', async () => {
    await open()
    await page.click(page.button('Seite 5 behalten, kein Trennblatt'))
    expect(parts()[1]).toContain('Seiten 3, 4, 5')
    expect(page.text.match(/Trennblatt/g)?.length).toBe(1)
  })

  it('keeps it as one document', async () => {
    await open()
    await page.click(page.button('Als ein Dokument behalten'))
    expect(server.changes()).toEqual(['DELETE /api/v1/documents/5/separators'])
    expect(say).toHaveBeenCalledWith('Bleibt ein Dokument.')
    expect(onKeep).toHaveBeenCalled()
  })

  it('without separators every cut is the person\'s own, and one part cannot be split', async () => {
    server.answers['GET /api/v1/documents/5/separators'] = { ...proposal, checked: false, blank_pages: [], parts: [], suggested: false }
    await open({ ...stack, pages: 3, source: 'upload' })
    expect(page.text).toContain('nexpaper hat keine leeren Trennblätter gefunden.')
    expect(go()!.disabled).toBe(true)
    await page.click(page.button('Hier schneiden'))
    await page.click(go())
    expect(say).toHaveBeenCalledWith('In 2 Dokumente aufgeteilt.')
  })

  it('shows what the server refused', async () => {
    server.fails = { 'POST /api/v1/documents/5/split': { status: 409, code: 'version_changed' } }
    await open()
    await page.click(go())
    expect(page.text).toContain('Das Dokument hat sich inzwischen geändert.')
    expect(onSplit).not.toHaveBeenCalled()
  })
})
