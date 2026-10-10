/**
 * Joining documents against test data: the filed documents of the same vault are offered (newest first, as the search finds
 * them), chosen ones go into the order, the order can change, and the first one is the document that stays.
 */
import { act } from 'react'

import { changeLanguage } from '../i18n'
import { Page, Server } from '../test/harness'
import { MergeDialog } from './MergeDialog'

const server = new Server()
const page = new Page()
const say = vi.fn()
const onMerged = vi.fn()
const onClose = vi.fn()

const doc = (id: number, title: string, pages: number, over: Record<string, unknown> = {}) => ({
  id, title, pages, vault_id: 7, current_version: 1, sender: { id: 1, name: 'Stadtwerke Lindenau' }, date: '2026-03-14', ...over,
})
const SEARCH = '/api/v1/search?q=&vault_id=7&status=filed&limit=16'

function open() {
  return page.show(<MergeDialog document={doc(5, 'Rechnung März', 2)} onClose={onClose} onMerged={onMerged} say={say} />)
}

const order = () => [...document.querySelectorAll('[data-testid="merge-order"] li')].map((li) => li.querySelector('.font-semibold')?.textContent)

beforeEach(async () => {
  await changeLanguage('de', false)
  for (const fn of [say, onMerged, onClose]) fn.mockClear()
  server.answers = {
    [`GET ${SEARCH}`]: { items: [doc(5, 'Rechnung März', 2), doc(6, 'Rechnung März Seite 3', 1, { current_version: 2 }), doc(9, 'Anlage', 3)].map((d) => ({ document: d })) },
    'POST /api/v1/documents/5/merge': { ...doc(5, 'Rechnung März', 3), current_version: 2 },
    'POST /api/v1/documents/6/merge': { ...doc(6, 'Rechnung März Seite 3', 3), current_version: 3 },
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('joining', () => {
  it('offers the other filed documents of the vault and says where their pages go', async () => {
    await open()
    expect(server.calls[0].url).toBe(SEARCH)
    expect(page.text).toContain('Die Seiten der gewählten Dokumente kommen hinten an „Rechnung März“.')
    expect(page.button('Dazunehmen: Rechnung März')).toBeUndefined()
    expect(page.text).toContain('Stadtwerke Lindenau · 14.03.2026 · 1 Seite')
    expect(page.button('Zusammenfügen')).toBeTruthy()
    expect([...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'Zusammenfügen')!.disabled).toBe(true)
  })

  it('joins the chosen ones in the order given, with the version each was seen at', async () => {
    await open()
    await page.click(page.button('Dazunehmen: Anlage'))
    await page.click(page.button('Dazunehmen: Rechnung März Seite 3'))
    expect(order()).toEqual(['Rechnung März', 'Anlage', 'Rechnung März Seite 3'])
    await page.click(page.button('Nach hinten: Anlage'))
    expect(order()).toEqual(['Rechnung März', 'Rechnung März Seite 3', 'Anlage'])
    const go = [...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'Zusammenfügen')
    await page.click(go)
    expect(server.called('POST', '/api/v1/documents/5/merge')!.body).toEqual({
      base_version: 1,
      others: [{ id: 6, base_version: 2 }, { id: 9, base_version: 1 }],
    })
    expect(say).toHaveBeenCalledWith('Zusammengefügt: jetzt 3 Seiten.')
    expect(onMerged).toHaveBeenCalledWith(expect.objectContaining({ id: 5 }))
    expect(onClose).toHaveBeenCalled()
  })

  it('makes another one the first: it keeps its fields and the dialog says so', async () => {
    await open()
    await page.click(page.button('Dazunehmen: Rechnung März Seite 3'))
    await page.click(page.button('Nach vorn: Rechnung März Seite 3'))
    expect(page.text).toContain('kommen hinten an „Rechnung März Seite 3“')
    expect(page.text).toContain('behält die Felder')
    await page.click([...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'Zusammenfügen'))
    expect(server.called('POST', '/api/v1/documents/6/merge')!.body).toEqual({ base_version: 2, others: [{ id: 5, base_version: 1 }] })
  })

  it('takes one out again, and shows what the server refused', async () => {
    server.fails = { 'POST /api/v1/documents/5/merge': { status: 403, code: 'forbidden' } }
    await open()
    await page.click(page.button('Dazunehmen: Anlage'))
    await page.click(page.button('Dazunehmen: Rechnung März Seite 3'))
    await page.click(page.button('Herausnehmen: Anlage'))
    expect(order()).toEqual(['Rechnung März', 'Rechnung März Seite 3'])
    await page.click([...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'Zusammenfügen'))
    expect(page.text).toContain('Dein Recht reicht dafür nicht.')
    expect(onMerged).not.toHaveBeenCalled()
  })

  it('searches what is typed', async () => {
    server.answers['GET /api/v1/search?q=Anlage&vault_id=7&status=filed&limit=16'] = { items: [{ document: doc(9, 'Anlage', 3) }] }
    await open()
    await page.type(document.querySelector<HTMLInputElement>('input[aria-label="Dokument suchen"]'), 'Anlage')
    await act(() => new Promise((resolve) => setTimeout(resolve, 400)))
    expect(server.calls.at(-1)!.url).toBe('/api/v1/search?q=Anlage&vault_id=7&status=filed&limit=16')
    expect(page.button('Dazunehmen: Anlage')).toBeTruthy()
    expect(page.button('Dazunehmen: Rechnung März Seite 3')).toBeUndefined()
  })
})
