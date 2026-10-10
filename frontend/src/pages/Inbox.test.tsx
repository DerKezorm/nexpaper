/**
 * The inbox against a stand-in of the server: what waits there (being read first, then the newest; nothing the person
 * may only read), one document with every field and where each proposal came from, filing it (only what changed, the
 * vault by moving, then the next one), Ctrl+Enter, the hint that it looks like one the person has, a file that could
 * not be read with "try again", where it came from, and the hint for a long document.
 */
import { act } from 'react'
import { Route, Routes, useLocation } from 'react-router-dom'

import { changeLanguage } from '../i18n'
import { forgetPictures } from '../lib/pictures'
import { INBOX_CHANGED } from '../lib/say'
import { INBOX, Page, Server, inboxOf, plain } from '../test/harness'
import { until } from '../test/wait'
import { InboxPage } from './InboxPage'

// The notice of a missing file speaks to the operator and to everybody else differently: the signed-in person is needed.
const auth = { me: { id: 1, name: 'jule', role: 'operator' } }
vi.mock('../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()

const invoice = { id: 1, key: 'invoice', name: 'Rechnung', hue: 28, position: 0 }
const health = { id: 2, key: 'health', name: 'Gesundheit', hue: 340, position: 1 }
function doc(id: number, title: string, added: string, extra: Record<string, unknown> = {}) {
  return {
    id, vault_id: 9, owner: { id: 1, name: 'jule', display_name: 'Jule' }, title, sender: { id: 5, name: 'Elektro Brandt GmbH' }, kind: invoice,
    date: '2026-10-06', amount: 22491, currency: 'EUR', tags: ['handwerker'], dates: [{ kind: 'due', date: '2026-10-20' }], pages: 1, source: 'mail',
    status: 'inbox', added_at: added, trashed_at: null, trash_ends_at: null, change_seq: id, current_version: 1, my_right: 'manage', via_share: false,
    can_share: true, notes: 0, process_error: '', duplicate: null, suggest: {}, ...extra,
  }
}
const heating = doc(11, 'Rechnung Heizungswartung', '2026-10-08T07:42:00Z', { suggest: { title: 'einvoice', vault: 'rule', tags: 'last_time' } })
const teeth = doc(12, 'Zahnreinigung Lea', '2026-10-08T07:15:00Z', { kind: health, sender: { id: 6, name: 'Zahnarztpraxis Dr. Sommer' }, pages: 2, source: 'camera' })
const reading = doc(13, 'Scan', '2026-10-08T08:00:00Z', { status: 'processing', pages: 0, sender: null })

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>
}
function show(at: string) {
  return page.show(
    <>
      <Routes>
        <Route path="eingang" element={<InboxPage />} />
        <Route path="eingang/:id" element={<InboxPage />} />
        <Route path="dokument/:id" element={<p>document page</p>} />
      </Routes>
      <Where />
    </>,
    at,
  )
}
const where = () => plain(page.box.querySelector('[data-testid="where"]')!.textContent)

beforeEach(async () => {
  forgetPictures()
  await changeLanguage('de', false)
  server.answers = {
    [INBOX]: inboxOf([reading, heating, teeth]),
    'GET /api/v1/vaults': [
      { id: 7, name: 'Jule', icon: 'user', personal_of: 1, my_right: 'manage', documents: 1, size: 1, members: [] },
      { id: 9, name: 'Ferienwohnung', icon: 'sun', personal_of: null, my_right: 'manage', documents: 1, size: 1, members: [] },
      { id: 10, name: 'Tom', icon: 'user', personal_of: 2, my_right: 'read', documents: 1, size: 1, members: [] },
    ],
    'GET /api/v1/kinds?vault_id=9': [invoice, health],
    'GET /api/v1/kinds': [invoice, health],
    'GET /api/v1/senders': [{ name: 'Elektro Brandt GmbH', items: [{ id: 5, vault_id: 9 }] }],
    'GET /api/v1/documents/11/origin': { source: 'mail', unknown: true, sender: 'rechnung@example.com', subject: 'Ihre Rechnung', folder: '', file: '', at: null },
    'GET /api/v1/documents/11/versions/1/text': { version: 1, state: 'done', pages: ['Rechnung'], ocr_pages: 0, languages: '', long_document_pages: 300 },
    'PATCH /api/v1/documents/11': { ...heating, status: 'filed' },
    'POST /api/v1/documents/11/move': { ...heating, vault_id: 7 },
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('the inbox', () => {
  it('lists what is being read first, then the newest, as the server sorted them', async () => {
    await show('/eingang')
    expect(plain(page.box.querySelector('h1')!.textContent)).toBe('Eingang')
    const items = [...page.box.querySelectorAll('ul[aria-label="Eingang"] li')].map((li) => plain(li.textContent))
    expect(items).toHaveLength(3)
    expect(items[0]).toContain('Wird gelesen …')
    expect(items[1]).toContain('Rechnung Heizungswartung')
    expect(items[2]).toContain('Zahnreinigung Lea')
  })

  it('says when everything is filed', async () => {
    server.answers[INBOX] = inboxOf([])
    await show('/eingang')
    expect(page.text).toContain('Alles abgelegt')
    expect(page.text).toContain('Neues kommt vom Handy, aus dem Postfach, dem Eingangsordner oder über „Hochladen“.')
  })

  it('shows one document with every field, where each proposal came from, and where it came from', async () => {
    await show('/eingang/11')
    await until(() => page.text.includes('Von rechnung@example.com'))
    expect(page.box.querySelector<HTMLInputElement>('input[aria-label="Titel"]')!.value).toBe('Rechnung Heizungswartung')
    expect(page.box.querySelector<HTMLInputElement>('input[aria-label="Absender"]')!.value).toBe('Elektro Brandt GmbH')
    expect(page.box.querySelector<HTMLInputElement>('input[aria-label="Betrag"]')!.value).toBe('224,91')
    expect(page.box.querySelector<HTMLInputElement>('input[aria-label="Fällig am"]')!.value).toBe('2026-10-20')
    expect(plain(page.box.querySelector('[role="radio"][aria-checked="true"]')!.textContent)).toBe('Rechnung')
    for (const why of ['E-Rechnung', 'Regel', 'wie beim letzten Mal']) expect(page.text).toContain(why)
    expect(plain(page.box.querySelector('[data-testid="origin"]')!.textContent)).toContain('Aus dem Postfach')
    expect(plain(page.box.querySelector('[data-testid="origin"]')!.textContent)).toContain('unbekannt')
    expect(page.text).toContain('„Ihre Rechnung“')
    // Only vaults the person may add to; Tom's (read) is not offered.
    expect([...page.select('Tresor')!.options].map((o) => plain(o.textContent))).toEqual(['Jule (persönlich)', 'Ferienwohnung'])
  })

  it('opens the document large over the page, and Escape closes it', async () => {
    await show('/eingang/11')
    await until(() => page.text.includes('Von rechnung@example.com'))
    await page.click(page.button('Groß ansehen'))
    const large = document.querySelector('[role="dialog"][aria-label="Rechnung Heizungswartung"]')
    expect(large).toBeTruthy()
    expect(large!.querySelectorAll('img').length).toBeGreaterThan(0)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await until(() => !document.querySelector('[role="dialog"][aria-label="Rechnung Heizungswartung"]'))
  })

  it('a click on the picture of the page opens the document large, with no tools on the small one', async () => {
    await show('/eingang/11')
    await until(() => page.text.includes('Von rechnung@example.com'))
    expect(document.querySelector('[data-testid="pdf-view"]')).toBeNull()
    await page.click(document.querySelector<HTMLButtonElement>('button.cursor-zoom-in'))
    expect(document.querySelector('[role="dialog"][aria-label="Rechnung Heizungswartung"]')).toBeTruthy()
  })

  it('quotes the subject of a mail in the way of the language', async () => {
    await changeLanguage('en', false)
    await show('/eingang/11')
    await until(() => page.text.includes('From rechnung@example.com'))
    expect(page.text).toContain('“Ihre Rechnung”')
  })

  it('files only what changed, moves it first to another vault, and goes on to the next', async () => {
    await show('/eingang/11')
    await page.type(page.box.querySelector<HTMLInputElement>('input[aria-label="Titel"]'), 'Heizung Oktober')
    const amount = page.box.querySelector<HTMLInputElement>('input[aria-label="Betrag"]')!
    await page.type(amount, '230,00')
    await act(async () => amount.dispatchEvent(new FocusEvent('focusout', { bubbles: true })))
    await page.choose(page.select('Tresor'), '7')
    await page.click(page.button('Ablegen'))
    const changes = server.changes()
    expect(changes).toEqual(['POST /api/v1/documents/11/move', 'PATCH /api/v1/documents/11'])
    expect(server.called('POST', '/api/v1/documents/11/move')!.body).toEqual({ vault_id: 7 })
    expect(server.called('PATCH', '/api/v1/documents/11')!.body).toEqual({ title: 'Heizung Oktober', amount: 23000, status: 'filed' })
    expect(where()).toBe('/eingang/12')
  })

  it('follows the server for the fields the person has not touched, and never files its own stale copy over them', async () => {
    const bare = doc(11, 'Rechnung Heizungswartung', '2026-10-08T07:42:00Z', { sender: null })
    server.answers[INBOX] = inboxOf([bare, teeth])
    await show('/eingang/11')
    const sender = () => page.box.querySelector<HTMLInputElement>('input[aria-label="Absender"]')!
    expect(sender().value).toBe('')
    // The sender is proposed later (the document is in the inbox already): the field shows it, untouched.
    server.answers[INBOX] = inboxOf([heating, teeth])
    await act(async () => window.dispatchEvent(new Event(INBOX_CHANGED)))
    await until(() => sender().value === 'Elektro Brandt GmbH')
    await page.click(page.button('Ablegen'))
    // Nothing of the sender in the call: the person never touched it, so the stale empty copy must not clear it.
    expect(server.called('PATCH', '/api/v1/documents/11')!.body).toEqual({ status: 'filed' })
  })

  it('shows what the server took away, and keeps what the person typed', async () => {
    await show('/eingang/11')
    const sender = () => page.box.querySelector<HTMLInputElement>('input[aria-label="Absender"]')!
    const title = () => page.box.querySelector<HTMLInputElement>('input[aria-label="Titel"]')!
    expect(sender().value).toBe('Elektro Brandt GmbH')
    await page.type(title(), 'Mein Titel')
    server.answers[INBOX] = inboxOf([doc(11, 'Titel vom Server', '2026-10-08T07:42:00Z', { sender: null, date: '2026-11-01' }), teeth])
    await act(async () => window.dispatchEvent(new Event(INBOX_CHANGED)))
    await until(() => sender().value === '')
    expect(page.box.querySelector<HTMLInputElement>('input[aria-label="Datum"]')!.value).toBe('2026-11-01')
    expect(title().value).toBe('Mein Titel')
    await page.click(page.button('Ablegen'))
    expect(server.called('PATCH', '/api/v1/documents/11')!.body).toEqual({ title: 'Mein Titel', status: 'filed' })
  })

  it('files with Ctrl+Enter, from any field', async () => {
    await show('/eingang/11')
    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true })))
    await until(() => server.called('PATCH', '/api/v1/documents/11'))
    expect(server.called('PATCH', '/api/v1/documents/11')!.body).toEqual({ status: 'filed' })
  })

  it('refuses an empty title before asking the server', async () => {
    await show('/eingang/11')
    await page.type(page.box.querySelector<HTMLInputElement>('input[aria-label="Titel"]'), '  ')
    await page.click(page.button('Ablegen'))
    expect(server.changes()).toEqual([])
    expect(page.box.querySelector('[role="alert"]')).toBeTruthy()
  })

  it('says what the server refused and stays', async () => {
    server.fails['PATCH /api/v1/documents/11'] = { status: 403, code: 'forbidden' }
    await show('/eingang/11')
    await page.click(page.button('Ablegen'))
    expect(plain(page.box.querySelector('[role="alert"]')!.textContent)).toBe('Dein Recht reicht dafür nicht.')
    expect(where()).toBe('/eingang/11')
  })

  it('warns when it looks like one the person has, and discarding puts it in the trash', async () => {
    server.answers[INBOX] = inboxOf([{ ...heating, duplicate: { document_id: 4, title: 'Abschlag Strom Oktober', kind: 'similar' } }, teeth])
    server.answers['DELETE /api/v1/documents/11'] = { ...heating, status: 'trash' }
    await show('/eingang/11')
    const box = page.box.querySelector('[data-testid="looks-like"]')!
    expect(plain(box.textContent)).toContain('Fast derselbe Text wie „Abschlag Strom Oktober“')
    await page.click(page.button('Verwerfen'))
    expect(server.changes()).toEqual([])
    await page.inDialog('In den Papierkorb')
    expect(server.changes()).toEqual(['DELETE /api/v1/documents/11'])
    expect(where()).toBe('/eingang/12')
  })

  it('says why a file could not be read and tries again', async () => {
    server.answers[INBOX] = inboxOf([{ ...heating, process_error: 'encrypted', pages: 0 }])
    server.answers['POST /api/v1/documents/11/retry'] = { ...heating, status: 'processing' }
    await show('/eingang/11')
    expect(page.text).toContain('Das PDF ist mit einem Passwort geschützt')
    await page.click(page.button('Erneut versuchen'))
    expect(server.called('POST', '/api/v1/documents/11/retry')).toBeTruthy()
  })

  it('says that a long document takes a while for its text', async () => {
    server.answers[INBOX] = inboxOf([{ ...heating, pages: 420 }])
    server.answers['GET /api/v1/documents/11/versions/1/text'] = { version: 1, state: 'pending', pages: [], ocr_pages: 0, languages: '', long_document_pages: 300 }
    await show('/eingang/11')
    await until(() => page.text.includes('Ein langes Dokument mit 420 Seiten'))
  })

  it('says a document is being read and leaves its fields alone', async () => {
    await show('/eingang/13')
    expect(page.box.querySelector('[data-testid="inbox-reading"]')).toBeTruthy()
    expect(page.button('Ablegen')).toBeUndefined()
  })

  it('opens a document that was filed meanwhile on its own page', async () => {
    server.answers['GET /api/v1/documents/99'] = doc(99, 'Abgelegt', '2026-10-01T00:00:00Z', { status: 'filed' })
    await show('/eingang/99')
    await until(() => where() === '/dokument/99')
  })
})

describe('a batch scan in the inbox (the page tools)', () => {
  it('has the scissors in the list and the proposal to split in place of the details, and splits', async () => {
    const stack = doc(15, 'Stapelscan vom Drucker', '2026-10-08T10:00:00Z', { pages: 3, source: 'folder', split_suggested: true, sender: null })
    server.answers[INBOX] = inboxOf([stack, heating])
    server.answers['GET /api/v1/documents/15/separators'] = { version: 1, checked: true, blank_pages: [2], parts: [[1], [3]], duplex: false, dismissed: false, suggested: true }
    server.answers['POST /api/v1/documents/15/split'] = { items: [{ id: 21 }, { id: 22 }] }
    await show('/eingang/15')
    await until(() => page.text.includes('Stapelscan aufteilen?'))
    expect(page.box.querySelector('[aria-label="Aufteilen vorgeschlagen"]')).toBeTruthy()
    expect(page.text).toContain('nexpaper hat ein leeres Trennblatt gefunden und schlägt 2 Dokumente vor.')
    const first = doc(21, 'Stapelscan vom Drucker (1)', '2026-10-08T10:01:00Z', { pages: 1, source: 'folder', sender: null })
    server.answers[INBOX] = inboxOf([first, heating])
    server.answers['GET /api/v1/documents/21'] = first
    await page.click([...page.box.querySelectorAll('button')].find((b) => plain(b.textContent)?.includes('In 2 Dokumente aufteilen')))
    expect(server.called('POST', '/api/v1/documents/15/split')!.body).toEqual({ base_version: 1, parts: [{ pages: [{ page: 1, turn: 0 }] }, { pages: [{ page: 3, turn: 0 }] }] })
    await until(() => where() === '/eingang/21')
  })
})

describe('the check of the files in the inbox', () => {
  it('puts a sign on the list entry and a notice on the document whose file is missing', async () => {
    const lost = doc(31, 'Zählerstand', '2026-10-09T10:00:00Z', { files_state: 'missing' })
    server.answers[INBOX] = inboxOf([lost, heating])
    server.answers['GET /api/v1/documents/31'] = lost
    await show('/eingang/31')
    await until(() => page.box.querySelector('[data-testid="file-notice"]') !== null)
    expect(page.box.querySelectorAll('[data-testid="file-sign"]')).toHaveLength(1)
    expect(plain(page.box.querySelector('[data-testid="file-notice"]')!.textContent)).toContain('fehlt auf dem Server')
    expect(page.box.querySelector('[data-testid="file-notice"]')!.textContent).toContain('Dieses Dokument jetzt neu prüfen')
  })

  it('has the operator ask for this document again, and reloads the inbox when the server answered', async () => {
    const lost = doc(32, 'Zählerstand', '2026-10-09T10:00:00Z', { files_state: 'missing' })
    server.answers[INBOX] = inboxOf([lost])
    server.answers['GET /api/v1/documents/32'] = lost
    server.answers['POST /api/v1/storage/files/documents/32/check'] = { files_state: '' }
    await show('/eingang/32')
    await until(() => page.box.querySelector('[data-testid="file-notice"]') !== null)
    await page.click(page.button('Dieses Dokument jetzt neu prüfen'))
    expect(server.called('POST', '/api/v1/storage/files/documents/32/check')).toBeTruthy()
  })
})

describe('the inbox of the vaults', () => {
  it('has one filter by vault with the numbers, and asks the server for the vault chosen', async () => {
    server.answers['GET /api/v1/inbox?vault_id=9&sort=new&limit=50'] = inboxOf([heating, teeth])
    await show('/eingang')
    const chips = [...page.box.querySelectorAll('[role="group"] button')].map((b) => plain(b.textContent).trim().replace(/\s+/g, ' '))
    expect(chips).toEqual(['Alle 3', 'Mein Tresor 0', 'Ferienwohnung 3'])
    await page.click([...page.box.querySelectorAll<HTMLElement>('[role="group"] button')].find((b) => plain(b.textContent).includes('Ferienwohnung')))
    expect(server.called('GET', '/api/v1/inbox?vault_id=9&sort=new&limit=50')).toBeTruthy()
    expect(page.box.querySelector<HTMLElement>('[aria-pressed="true"]')!.textContent).toContain('Ferienwohnung')
    // Only the vaults the person may file in are chips: Tom's (read) is not one.
    expect(chips.join()).not.toContain('Tom')
  })

  it('says in each entry which vault it waits in and who brought it, and explains the inbox', async () => {
    server.answers[INBOX] = inboxOf([heating, { ...teeth, owner: { id: 3, name: 'lea', display_name: 'Lea' }, vault_id: 7 }])
    await show('/eingang')
    const shields = [...page.box.querySelectorAll('[data-testid="inbox-shield"]')].map((p) => plain(p.textContent))
    expect(shields).toEqual(['Ferienwohnungvon dir', 'Mein Tresorvon Lea'])
    expect(page.text).toContain('Jeder Tresor hat seinen eigenen Eingang.')
  })

  it('searches after a pause in typing and narrows by source, all in the address', async () => {
    await show('/eingang')
    await page.type(page.box.querySelector<HTMLInputElement>('input[type="search"]'), 'zahn')
    await until(() => server.called('GET', '/api/v1/inbox?q=zahn&sort=new&limit=50'))
    await page.choose(page.box.querySelector<HTMLSelectElement>('select[aria-label="Sortierung"]'), 'date')
    expect(server.called('GET', '/api/v1/inbox?q=zahn&sort=date&limit=50')).toBeTruthy()
    await page.click(page.button('Filter'))
    await page.choose(page.select('Quelle'), 'mail')
    expect(server.called('GET', '/api/v1/inbox?q=zahn&source=mail&sort=date&limit=50')).toBeTruthy()
  })

  it('loads the next page below the ones shown, and says how many of how many', async () => {
    server.answers[INBOX] = { ...inboxOf([heating, teeth]), total: 120 }
    server.answers['GET /api/v1/inbox?sort=new&limit=50&offset=2'] = { ...inboxOf([doc(40, 'Spät', '2026-10-01T07:00:00Z')]), total: 120 }
    await show('/eingang')
    expect(plain(page.box.querySelector('[data-testid="inbox-shown"]')!.textContent)).toBe('2 von 120')
    await page.click(page.button('Mehr laden'))
    expect(server.called('GET', '/api/v1/inbox?sort=new&limit=50&offset=2')).toBeTruthy()
    expect(plain(page.box.querySelector('[data-testid="inbox-shown"]')!.textContent)).toBe('3 von 120')
    expect(page.text).toContain('Spät')
  })

  it('steps through the list with j and k, but not while typing in a field', async () => {
    await show('/eingang/11')
    const press = (key: string, target: EventTarget = window) => act(async () => void target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true })))
    await press('j')
    expect(where()).toBe('/eingang/12')
    await press('k')
    expect(where()).toBe('/eingang/11')
    const title = page.box.querySelector<HTMLInputElement>('input[aria-label="Titel"]')!
    await press('j', title)
    expect(where()).toBe('/eingang/11')
  })
})

describe('what comes through a share of the document alone', () => {
  it('has a group of its own that names no vault, and asks for it with shared=true', async () => {
    const lent = doc(30, 'Geliehen', '2026-10-08T06:00:00Z', { vault_id: 99, my_right: 'edit', via_share: true })
    server.answers[INBOX] = { items: [heating, lent], total: 2, counts: { '9': 1 }, shared: 1, all: 2, reading: 0 }
    server.answers['GET /api/v1/inbox?shared=true&sort=new&limit=50'] = { items: [lent], total: 1, counts: { '9': 1 }, shared: 1, all: 2, reading: 0 }
    await show('/eingang')
    const chips = [...page.box.querySelectorAll('[role="group"] button')].map((b) => plain(b.textContent))
    expect(chips).toContain('Einzeln mit dir geteilt (1)')
    expect(chips.join()).not.toContain('99')
    await page.click(page.button('Einzeln mit dir geteilt (1)'))
    expect(server.called('GET', '/api/v1/inbox?shared=true&sort=new&limit=50')).toBeTruthy()
    expect(page.box.querySelectorAll('ul[aria-label="Eingang"] li')).toHaveLength(1)
  })

  it('shows no such group when nothing comes that way', async () => {
    await show('/eingang')
    expect([...page.box.querySelectorAll('[role="group"] button')].map((b) => plain(b.textContent)).join()).not.toContain('geteilt')
  })
})

describe('the sender field in the inbox', () => {
  it('searches the senders with a magnifying glass and the word "Suchen"', async () => {
    await show('/eingang/11')
    const button = page.button('Absender suchen')!
    expect(plain(button.textContent)).toBe('Suchen')
  })
})

describe('filing many at once', () => {
  const start = async () => page.click(page.button('Auswählen'))
  const pick = async (title: string) => {
    if (!page.box.querySelector('input[aria-label$=" auswählen"]')) await start()
    await page.click(page.box.querySelector<HTMLElement>(`input[aria-label="${title} auswählen"]`))
  }
  const press = (key: string) => act(async () => void window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true })))

  it('selects, offers the fields for all of them, and files with one call', async () => {
    server.answers['POST /api/v1/inbox/file'] = { filed: [11, 12], failed: [] }
    await show('/eingang')
    await pick('Rechnung Heizungswartung')
    await pick('Zahnreinigung Lea')
    const bar = page.box.querySelector('[role="region"]')!
    expect(plain(bar.textContent)).toContain('2 ausgewählt')
    await page.choose(bar.querySelector<HTMLSelectElement>('select[aria-label="Art"]'), '2')
    const tag = bar.querySelector<HTMLInputElement>('input[aria-label="Tag dazu"]')!
    await page.type(tag, 'Steuer')
    // Going to the button takes the focus from the field, which settles the word (nothing like it exists).
    await act(async () => void tag.dispatchEvent(new FocusEvent('focusout', { bubbles: true })))
    expect(plain(bar.textContent)).toContain('Steuer')
    expect(server.changes()).toEqual([])
    await page.click(page.button('2 ablegen'))
    expect(server.called('POST', '/api/v1/inbox/file')!.body).toEqual({ ids: [11, 12], kind_id: 2, add_tags: ['Steuer'] })
    expect(server.changes()).toEqual(['POST /api/v1/inbox/file'])
  })

  it('does not offer to select what is still being read', async () => {
    await show('/eingang')
    await start()
    expect(page.box.querySelector<HTMLInputElement>('input[aria-label="Scan auswählen"]')!.disabled).toBe(true)
  })

  it('shows no boxes until "Auswählen" is pressed, and "Fertig" puts them and the selection away', async () => {
    await show('/eingang')
    expect(page.box.querySelectorAll('input[type="checkbox"]')).toHaveLength(0)
    expect(page.box.querySelector('[role="region"]')).toBeNull()
    await start()
    expect(page.box.querySelectorAll('input[type="checkbox"]')).toHaveLength(4)
    await pick('Zahnreinigung Lea')
    expect(plain(page.box.querySelector('[role="region"]')!.textContent)).toContain('1 ausgewählt')
    await page.click(page.button('Fertig'))
    expect(page.box.querySelectorAll('input[type="checkbox"]')).toHaveLength(0)
    expect(page.box.querySelector('[role="region"]')).toBeNull()
    await start()
    expect(page.box.querySelector<HTMLInputElement>('input[aria-label="Zahnreinigung Lea auswählen"]')!.checked).toBe(false)
  })

  it('switches the selection on with the key x and selects the open document; a document still being read stays unselected', async () => {
    await show('/eingang/12')
    await press('x')
    expect(page.box.querySelector<HTMLInputElement>('input[aria-label="Zahnreinigung Lea auswählen"]')!.checked).toBe(true)
    expect(plain(page.box.querySelector('[role="region"]')!.textContent)).toContain('1 ausgewählt')
    await press('x')
    expect(page.box.querySelector('[role="region"]')).toBeNull()
    page.close()
    await show('/eingang/13')
    await press('x')
    expect(page.box.querySelectorAll('input[type="checkbox"]')).toHaveLength(0)
    expect(page.box.querySelector('[role="region"]')).toBeNull()
  })

  it('empties the selection when the filter changes, and stays in the selecting state', async () => {
    server.answers['GET /api/v1/inbox?sort=old&limit=50'] = inboxOf([reading, teeth, heating])
    await show('/eingang')
    await pick('Rechnung Heizungswartung')
    expect(page.box.querySelector('[role="region"]')).not.toBeNull()
    await page.choose(page.box.querySelector<HTMLSelectElement>('select[aria-label="Sortierung"]'), 'old')
    expect(page.box.querySelector('[role="region"]')).toBeNull()
    expect(page.box.querySelector<HTMLInputElement>('input[aria-label="Rechnung Heizungswartung auswählen"]')!.checked).toBe(false)
  })

  it('names the documents that could not be filed, with the reason, and keeps them selected', async () => {
    server.answers['POST /api/v1/inbox/file'] = { filed: [12], failed: [{ id: 11, code: 'forbidden' }] }
    await show('/eingang')
    await pick('Rechnung Heizungswartung')
    await pick('Zahnreinigung Lea')
    await page.click(page.button('2 ablegen'))
    const bar = page.box.querySelector('[role="region"]')!
    expect(plain(bar.textContent)).toContain('1 Dokument ließ sich nicht ablegen')
    expect(plain(bar.textContent)).toContain('Rechnung Heizungswartung: Dein Recht reicht dafür nicht.')
    expect(plain(bar.textContent)).toContain('1 ausgewählt')
  })

  it('selects every loaded one with the box above the list, and clears the selection', async () => {
    await show('/eingang')
    await page.click(page.button('Auswählen'))
    await page.click(page.box.querySelector<HTMLElement>('input[aria-label^="Alle"]'))
    expect(plain(page.box.querySelector('[role="region"]')!.textContent)).toContain('2 ausgewählt')
    await page.click(page.button('Auswahl aufheben'))
    expect(page.box.querySelector('[role="region"]')).toBeNull()
  })
})
