/**
 * A document open to the outside (N2b) against test data: the notice for who may change it but not share it, and the
 * question before every change of its pages (page tools, splitting there and in the inbox, joining, a new version, an
 * old version back). Nothing is sent before the click on the button that does it; "Abbrechen" sends nothing.
 */
import { act } from 'react'

import { changeLanguage } from '../i18n'
import { Page, Server } from '../test/harness'
import { MergeDialog } from './MergeDialog'
import { PageEditor } from './PageEditor'
import { ShownOutsideNotice } from './ShownOutside'
import { SplitPanel } from './SplitPanel'
import { UploadVersionDialog, VersionRowActions } from './VersionActions'

const server = new Server()
const page = new Page()
const SENTENCE = 'Dieses Dokument ist über einen Link nach außen sichtbar. Was du änderst, ist es dann auch.'

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = {}
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

/** The question stands, says its sentence, and "Abbrechen" closes it without a request. */
async function cancelled(): Promise<void> {
  expect(page.dialog).toBeTruthy()
  expect(page.dialog!.textContent).toContain('Nach außen sichtbar')
  expect(page.dialog!.textContent).toContain(SENTENCE)
  expect(server.changes()).toEqual([])
  await page.inDialog('Abbrechen')
  expect(document.body.textContent).not.toContain(SENTENCE)
  expect(server.changes()).toEqual([])
}

const byText = (text: string) => [...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === text)

describe('the notice at the document', () => {
  it('tells who may change it but not share it, and names nobody', async () => {
    await page.show(<ShownOutsideNotice document={{ shown_outside: true, can_share: false }} />)
    expect(page.text).toBe('Über einen Link nach außen sichtbar. Wer teilen darf, sieht, an wen.')
  })

  it('stands back for who may share it (they see to whom) and when nothing is open', async () => {
    await page.show(
      <>
        <ShownOutsideNotice document={{ shown_outside: true, can_share: true }} />
        <ShownOutsideNotice document={{ shown_outside: false, can_share: false }} />
        <ShownOutsideNotice document={{ can_share: false }} />
      </>,
    )
    expect(page.text).toBe('')
  })

  it('speaks English too', async () => {
    await changeLanguage('en', false)
    await page.show(<ShownOutsideNotice document={{ shown_outside: true, can_share: false }} />)
    expect(page.text).toBe('Visible to the outside through a link. Whoever may share sees to whom.')
  })
})

describe('asking before a change of the pages', () => {
  it('the page editor asks before it saves', async () => {
    server.answers['POST /api/v1/documents/5/pages'] = { id: 5, pages: 2, current_version: 3 }
    const onDone = vi.fn()
    await page.show(<PageEditor document={{ id: 5, pages: 2, current_version: 2, shown_outside: true }} onDone={onDone} />)
    await page.click(page.button('Rechts drehen'))
    await page.click(page.button('Speichern'))
    await cancelled()
    expect(onDone).not.toHaveBeenCalled()
    await page.click(page.button('Speichern'))
    await page.inDialog('Speichern')
    expect(server.changes()).toEqual(['POST /api/v1/documents/5/pages'])
    expect(onDone).toHaveBeenCalledWith({ id: 5, pages: 2, current_version: 3 })
  })

  it('the page editor asks nothing when nothing changed', async () => {
    const onDone = vi.fn()
    await page.show(<PageEditor document={{ id: 5, pages: 2, current_version: 2, shown_outside: true }} onDone={onDone} />)
    await page.click(page.button('Speichern'))
    expect(page.dialog).toBeNull()
    expect(onDone).toHaveBeenCalledWith(null)
  })

  it('the page editor asks before it splits', async () => {
    server.answers['POST /api/v1/documents/5/split'] = { items: [{ id: 8 }, { id: 9 }] }
    const onSplit = vi.fn()
    await page.show(<PageEditor document={{ id: 5, pages: 2, current_version: 2, shown_outside: true }} onDone={vi.fn()} onSplit={onSplit} />)
    await page.click(page.button('Seite 2 wählen'))
    await page.click(page.button('Ab hier eigenes Dokument'))
    await page.click(page.button('Aufteilen'))
    await cancelled()
    await page.click(page.button('Ab hier eigenes Dokument'))
    await page.click(page.button('Aufteilen'))
    await page.inDialog('Aufteilen')
    expect(server.changes()).toEqual(['POST /api/v1/documents/5/split'])
    expect(onSplit).toHaveBeenCalledWith([{ id: 8 }, { id: 9 }])
  })

  it('splitting a batch scan asks, keeping it as one does not', async () => {
    server.answers['GET /api/v1/documents/5/separators'] = { version: 1, checked: true, blank_pages: [2], parts: [[1], [3]], duplex: false, dismissed: false, suggested: true }
    server.answers['POST /api/v1/documents/5/split'] = { items: [{ id: 11 }, { id: 12 }] }
    server.answers['DELETE /api/v1/documents/5/separators'] = 204
    const onSplit = vi.fn()
    const onKeep = vi.fn()
    await page.show(<SplitPanel document={{ id: 5, title: 'Stapel', pages: 3, current_version: 1, source: 'folder', shown_outside: true }} onSplit={onSplit} onKeep={onKeep} />)
    const go = () => [...document.querySelectorAll('button')].find((b) => b.textContent?.trim().startsWith('In '))
    await page.click(go())
    await cancelled()
    await page.click(go())
    await page.inDialog('In 2 Dokumente aufteilen')
    expect(server.changes()).toEqual(['POST /api/v1/documents/5/split'])
    expect(onSplit).toHaveBeenCalled()
    await page.click(page.button('Als ein Dokument behalten'))
    expect(page.dialog).toBeNull()
    expect(onKeep).toHaveBeenCalled()
  })

  it('joining asks when the document that keeps the pages is open', async () => {
    const doc = (id: number, title: string, over: Record<string, unknown> = {}) => ({ id, title, pages: 1, vault_id: 7, current_version: 1, ...over })
    server.answers['GET /api/v1/search?q=&vault_id=7&status=filed&limit=16'] = { items: [{ document: doc(9, 'Anlage') }] }
    server.answers['POST /api/v1/documents/5/merge'] = { ...doc(5, 'Lieferschein'), pages: 2, current_version: 2 }
    const onMerged = vi.fn()
    await page.show(<MergeDialog document={doc(5, 'Lieferschein', { shown_outside: true })} onClose={vi.fn()} onMerged={onMerged} />)
    await page.click(page.button('Dazunehmen: Anlage'))
    await page.click(byText('Zusammenfügen'))
    await cancelled()
    await page.click(byText('Zusammenfügen'))
    await page.inDialog('Zusammenfügen')
    expect(server.changes()).toEqual(['POST /api/v1/documents/5/merge'])
    expect(onMerged).toHaveBeenCalled()
  })

  it('joining asks when an open document is put into one that is open, from either side', async () => {
    const doc = (id: number, title: string, over: Record<string, unknown> = {}) => ({ id, title, pages: 1, vault_id: 7, current_version: 1, ...over })
    server.answers['GET /api/v1/search?q=&vault_id=7&status=filed&limit=16'] = { items: [{ document: doc(9, 'Rechnung', { shown_outside: true }) }] }
    server.answers['POST /api/v1/documents/9/merge'] = { ...doc(9, 'Rechnung'), pages: 2, current_version: 2 }
    // The dialog is opened on a document that is not open; the one that comes first and keeps the pages is.
    await page.show(<MergeDialog document={doc(5, 'Notiz')} onClose={vi.fn()} onMerged={vi.fn()} />)
    await page.click(page.button('Dazunehmen: Rechnung'))
    await page.click(page.button('Nach vorn: Rechnung'))
    await page.click(byText('Zusammenfügen'))
    await cancelled()
    await page.click(byText('Zusammenfügen'))
    await page.inDialog('Zusammenfügen')
    expect(server.changes()).toEqual(['POST /api/v1/documents/9/merge'])
  })

  it('joining into a document that is not open asks nothing', async () => {
    const doc = (id: number, title: string, over: Record<string, unknown> = {}) => ({ id, title, pages: 1, vault_id: 7, current_version: 1, ...over })
    server.answers['GET /api/v1/search?q=&vault_id=7&status=filed&limit=16'] = { items: [{ document: doc(9, 'Anlage') }] }
    server.answers['POST /api/v1/documents/5/merge'] = { ...doc(5, 'Lieferschein'), pages: 2, current_version: 2 }
    await page.show(<MergeDialog document={doc(5, 'Lieferschein', { shown_outside: false })} onClose={vi.fn()} onMerged={vi.fn()} />)
    await page.click(page.button('Dazunehmen: Anlage'))
    await page.click(byText('Zusammenfügen'))
    expect(server.changes()).toEqual(['POST /api/v1/documents/5/merge'])
  })

  it('bringing an old version back asks', async () => {
    server.answers['POST /api/v1/documents/5/versions/1/restore'] = { id: 5, current_version: 4 }
    const onDone = vi.fn()
    await page.show(<VersionRowActions document={{ id: 5, current_version: 3, shown_outside: true }} version={{ n: 1, current: false, state: 'ready' }} canEdit onDone={onDone} />)
    await page.click(page.button('Fassung 1 zurückholen'))
    await cancelled()
    await page.click(page.button('Fassung 1 zurückholen'))
    await page.inDialog('Zurückholen')
    expect(server.changes()).toEqual(['POST /api/v1/documents/5/versions/1/restore'])
    expect(onDone).toHaveBeenCalledWith({ id: 5, current_version: 4 })
  })

  it('a new version asks before it goes up', async () => {
    const sent: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
      if (init?.method === 'POST') sent.push(url)
      return new Response(JSON.stringify({ n: 4, current: false, state: 'processing' }), { status: 202, headers: { 'Content-Type': 'application/json' } })
    }))
    const onUploaded = vi.fn()
    await page.show(<UploadVersionDialog document={{ id: 5, title: 'Vertrag', shown_outside: true }} onClose={vi.fn()} onUploaded={onUploaded} />)
    const input = document.querySelector<HTMLInputElement>('[data-testid="version-file"]')!
    await act(async () => {
      Object.defineProperty(input, 'files', { value: [new File(['%PDF-1.4'], 'besser.pdf', { type: 'application/pdf' })] })
      input.dispatchEvent(new Event('change', { bubbles: true }))
    })
    const upload = () => [...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'Neue Fassung hochladen' && !b.closest('[role="dialog"] [role="dialog"]'))
    await page.click(upload())
    expect(page.dialog!.textContent).toContain(SENTENCE)
    expect(sent).toEqual([])
    await page.inDialog('Abbrechen')
    expect(sent).toEqual([])
    await page.click(upload())
    await page.inDialog('Neue Fassung hochladen')
    expect(sent).toEqual(['/api/v1/documents/5/versions'])
    expect(onUploaded).toHaveBeenCalled()
  })

  it('asks in English too', async () => {
    await changeLanguage('en', false)
    server.answers['POST /api/v1/documents/5/versions/1/restore'] = { id: 5, current_version: 4 }
    await page.show(<VersionRowActions document={{ id: 5, current_version: 3, shown_outside: true }} version={{ n: 1, current: false, state: 'ready' }} canEdit onDone={vi.fn()} />)
    await page.click(document.querySelector<HTMLButtonElement>('button[aria-label]'))
    expect(page.dialog!.textContent).toContain('Visible to the outside')
    expect(page.dialog!.textContent).toContain('This document is visible to the outside through a link. What you change will be too.')
    expect(server.changes()).toEqual([])
  })
})
