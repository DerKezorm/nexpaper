/**
 * "Gehört zu" against test data: the section on the document page (entries, removing without a question, empty, read
 * only, proposals with their reason), the dialog (proposals first, the search only with documents the person may
 * change), the line on a card of the inbox, and the lines of the history.
 */
import type { TFunction } from 'i18next'

import type { DocumentEvent } from '../api/client'
import i18n, { changeLanguage } from '../i18n'
import { eventWhat } from '../lib/events'
import { Page, Server, plain } from '../test/harness'
import { until } from '../test/wait'
import { RelatedDialog, RelatedHint, RelatedSection } from './Related'

const server = new Server()
const page = new Page()

const kind = { id: 3, key: 'delivery_note', name: 'Lieferschein', hue: 200, position: 2 }
const delivery = { id: 8, title: 'Lieferschein Oktober', kind, sender: { id: 1, name: 'Stadtwerke Lindenau' }, date: '2026-11-03', status: 'filed', can_unlink: true, linked_at: '2026-11-04T08:00:00Z' }
const reminder = { id: 9, title: 'Mahnung', kind: null, sender: { id: 1, name: 'Stadtwerke Lindenau' }, date: null, status: 'inbox', can_unlink: false, linked_at: null }
const proposal = { id: 12, title: 'Auftragsbestätigung', kind: null, sender: { id: 1, name: 'Stadtwerke Lindenau' }, date: '2026-10-28', status: 'filed', via: 'order' }
const doc = { id: 5, title: 'Rechnung Oktober', status: 'filed' as const }

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = {
    'GET /api/v1/documents/5/related': [delivery, reminder],
    'GET /api/v1/documents/5/related/suggestions': [proposal],
    'DELETE /api/v1/documents/5/related/8': [reminder],
    'PUT /api/v1/documents/5/related/12': [delivery, reminder, { ...proposal, can_unlink: true, linked_at: null }],
    'POST /api/v1/documents/5/related/12/dismiss': [],
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('the section on the document page', () => {
  it('lists what goes with it, each with its kind, title, sender and date, opening the document', async () => {
    await page.show(<RelatedSection document={doc} canEdit />)
    expect(page.text).toContain('Gehört zu')
    const items = [...document.querySelectorAll('[data-testid="related-item"]')]
    expect(items.map((item) => plain(item.textContent))).toEqual([
      'LieferscheinLieferschein OktoberStadtwerke Lindenau · 03.11.2026Lösen',
      'MahnungStadtwerke Lindenau',
    ])
    expect(items[0].querySelector('a')!.getAttribute('href')).toBe('/dokument/8')
    // A document waiting in the inbox opens there.
    expect(items[1].querySelector('a')!.getAttribute('href')).toBe('/eingang/9')
  })

  it('removes a pair at once, without asking: nothing is lost, it can be set again', async () => {
    const changed = vi.fn()
    await page.show(<RelatedSection document={doc} canEdit onChange={changed} />)
    await page.click(page.button('Verknüpfung mit „Lieferschein Oktober“ lösen'))
    expect(page.dialog).toBeNull()
    expect(server.changes()).toEqual(['DELETE /api/v1/documents/5/related/8'])
    expect(changed).toHaveBeenCalled()
  })

  it('offers no removing where the person may not change the other one', async () => {
    await page.show(<RelatedSection document={doc} canEdit />)
    expect(page.button('Verknüpfung mit „Mahnung“ lösen')).toBeUndefined()
  })

  it('shows the proposals with a dashed edge and their reason, to connect or to turn down', async () => {
    await page.show(<RelatedSection document={doc} canEdit />)
    const box = document.querySelector('[data-testid="related-proposal"]')!
    expect(box.className).toContain('border-dashed')
    expect(plain(box.textContent)).toContain('Gleiche Bestellnummer')
    await page.click(page.button('„Auftragsbestätigung“ passt nicht'))
    expect(server.changes()).toEqual(['POST /api/v1/documents/5/related/12/dismiss'])
    await page.click(page.button('Mit „Auftragsbestätigung“ verknüpfen'))
    expect(server.changes()).toEqual(['POST /api/v1/documents/5/related/12/dismiss', 'PUT /api/v1/documents/5/related/12'])
  })

  it('says so when nothing goes with it, and offers the button', async () => {
    server.answers['GET /api/v1/documents/5/related'] = []
    server.answers['GET /api/v1/documents/5/related/suggestions'] = []
    await page.show(<RelatedSection document={doc} canEdit />)
    expect(page.text).toContain('Noch nichts verknüpft. Gehört etwas dazu')
    await page.click(page.button('Verknüpfen'))
    expect(page.dialog).not.toBeNull()
  })

  it('has no button and asks for no proposals for someone who may only read', async () => {
    server.answers['GET /api/v1/documents/5/related'] = []
    await page.show(<RelatedSection document={doc} canEdit={false} />)
    expect(page.text).toContain('Noch nichts verknüpft.')
    expect(page.text).not.toContain('Gehört etwas dazu')
    expect(page.button('Verknüpfen')).toBeUndefined()
    expect(server.calls.map((c) => c.url)).toEqual(['/api/v1/documents/5/related'])
  })
})

describe('the dialog', () => {
  it('shows the proposals first and searches only among what the person may change, never the document itself', async () => {
    const editable = { id: 21, title: 'Lieferschein Zwei', kind: null, sender: null, date: null, status: 'filed', my_right: 'edit' }
    const readOnly = { ...editable, id: 22, title: 'Nur lesen', my_right: 'read' }
    const itself = { ...editable, id: 5, title: 'Rechnung Oktober' }
    server.answers['GET /api/v1/search?q=lieferschein&limit=20'] = { items: [editable, readOnly, itself].map((d) => ({ document: d })), total: 3, next: null }
    server.answers['PUT /api/v1/documents/5/related/21'] = []
    const linked = vi.fn()
    await page.show(<RelatedDialog document={doc} linked={new Set([8])} onClose={vi.fn()} onLinked={linked} />)
    expect(page.dialog!.textContent).toContain('Vorschläge')
    expect(page.dialog!.textContent).toContain('Gleiche Bestellnummer')
    await page.type(page.dialog!.querySelector('input'), 'lieferschein')
    await until(() => page.dialog!.textContent?.includes('Lieferschein Zwei'), 'the hits')
    expect(page.dialog!.textContent).not.toContain('Nur lesen')
    expect(plain(page.dialog!.textContent)).not.toMatch(/Treffer.*Rechnung Oktober/)
    await page.click(page.button('Mit „Lieferschein Zwei“ verknüpfen'))
    expect(server.changes()).toEqual(['PUT /api/v1/documents/5/related/21'])
    expect(linked).toHaveBeenCalled()
  })
})

describe('the line on a card of the inbox', () => {
  it('names the first proposal by kind, sender and date, to connect or to turn down', async () => {
    const done = vi.fn()
    const first = { ...proposal, id: 8, title: 'Lieferschein Oktober', kind, date: '2026-11-03', via: 'delivery' as const }
    server.answers['PUT /api/v1/documents/5/related/8'] = []
    await page.show(<RelatedHint documentId={5} proposals={[first, { ...proposal }] as never} onDone={done} />)
    expect(page.text).toBe('Passt zu: Lieferschein, Stadtwerke Lindenau, 03.11.2026VerknüpfenPasst nicht')
    await page.click(page.button('Mit „Lieferschein Oktober“ verknüpfen'))
    expect(server.changes()).toEqual(['PUT /api/v1/documents/5/related/8'])
    expect(done).toHaveBeenCalled()
  })

  it('is said in English too', async () => {
    await changeLanguage('en', false)
    await page.show(<RelatedHint documentId={5} proposals={[{ ...proposal }] as never} onDone={vi.fn()} />)
    expect(page.text).toBe("Goes with: Auftragsbestätigung, Stadtwerke Lindenau, 10/28/2026ConnectDoesn't fit")
  })
})

describe('the history', () => {
  const context = { people: new Map(), vaults: new Map(), sourceText: (s: string) => s }
  const line = (action: string, detail: Record<string, unknown>) =>
    plain(eventWhat({ id: 1, at: '2026-11-04T08:00:00Z', action, by: null, by_link: '', detail } as DocumentEvent, i18n.t.bind(i18n) as TFunction, context))

  it('names the other document only when the server gave its title', () => {
    expect(line('related_set', { document: 8, title: 'Lieferschein Oktober' })).toBe('hat es mit Lieferschein Oktober verknüpft')
    expect(line('related_set', { document: null })).toBe('hat es mit einem anderen Dokument verknüpft')
    expect(line('related_unset', { document: 8, title: 'Lieferschein Oktober' })).toBe('hat die Verknüpfung mit Lieferschein Oktober gelöst')
    expect(line('related_unset', { document: null })).toBe('hat die Verknüpfung mit einem anderen Dokument gelöst')
    expect(line('related_set', { document: 8, title: 'Mahnung', by: 'merge' })).toBe('hat es beim Zusammenfügen mit Mahnung verknüpft')
  })
})
