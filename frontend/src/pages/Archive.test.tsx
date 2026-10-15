/**
 * The archive against a stand-in of the server: the overview (the newest, by sender, kind, year and tag) as the way in,
 * the table with numbered pages and sortable columns, the search with the marks the server names (never HTML), the
 * help, the chips and filters in the address and in the request, the brake of the search, the field that waits for a
 * pause and stops the request before, and the export only where a part for it is plugged in.
 */
import { act } from 'react'
import { useLocation } from 'react-router-dom'

import type { Me, SearchHit } from '../api/client'
import { changeLanguage } from '../i18n'
import { forgetPictures } from '../lib/pictures'
import { Page, Server, plain } from '../test/harness'
import { idle, until } from '../test/wait'
import { ArchivePage } from './ArchivePage'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: '', language: 'de', email_confirmed: false,
  email_pending: '', oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.0.1',
  whats_new_seen: '0.0.1', session_stage: 'full', profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true },
}
const auth = { status: 'signedIn', me: me as Me | null, setMe: vi.fn((next: Me) => (auth.me = next)), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()

const kind = { id: 1, key: 'invoice', name: 'Rechnung', hue: 28, position: 0 }
function doc(id: number, title: string, date: string, extra: Record<string, unknown> = {}) {
  return {
    id, vault_id: 9, owner: { id: 1, name: 'jule', display_name: 'Jule' }, title, sender: { id: 5, name: 'Stadtwerke Lindenau' }, kind, date, amount: 8640,
    currency: 'EUR', tags: ['strom'], dates: [], pages: 1, source: 'upload', status: 'filed', added_at: `${date}T08:00:00Z`, trashed_at: null,
    trash_ends_at: null, change_seq: id, current_version: 1, my_right: 'manage', via_share: false, can_share: true, notes: 0, process_error: '',
    duplicate: null, ...extra,
  }
}
function hit(document: ReturnType<typeof doc>, extra: Partial<SearchHit> = {}) {
  return { document, title_marks: [], sender_marks: [], excerpt: null, ...extra }
}
const result = (items: unknown[], total = items.length) => ({ items, total, next: null, understood: {} })
const three = () => [hit(doc(1, 'Abschlag Strom Oktober', '2026-10-01')), hit(doc(2, 'Kfz-Versicherung', '2026-09-28', { notes: 1, sender: { id: 6, name: 'Hansa' } })), hit(doc(3, 'Waschmaschine', '2025-03-14', { amount: null }))]

const WHOLE = 'GET /api/v1/search/overview?status=filed'
const NEWEST = 'GET /api/v1/search?q=&status=filed&limit=6'
/** A page of the table: the search, the filters after the status, then size, order and page. */
const table = (q = '', filters = '', rest = 'limit=50&sort=-date&page=1') => `GET /api/v1/search?q=${q}&status=filed${filters}&${rest}`
const ALL = table()
const SHARED = 'GET /api/v1/documents?status=filed&via_share=true&limit=1'
const vaults = [
  { id: 7, name: 'Jule', icon: 'user', personal_of: 1, my_right: 'manage', documents: 3, size: 1, members: [] },
  { id: 9, name: 'Haushalt', icon: 'home', personal_of: null, my_right: 'edit', documents: 1654, size: 1, members: [] },
]
const overview = {
  total: 3,
  senders: [{ name: 'Stadtwerke Lindenau', count: 2 }, { name: 'Hansa', count: 1 }],
  kinds: [{ kind, count: 3 }],
  years: [{ year: 2026, count: 2 }, { year: 2025, count: 1 }],
  tags: [{ name: 'strom', count: 3 }, { name: 'auto', count: 1 }],
}

function Where() {
  const location = useLocation()
  return <p data-testid="where">{location.pathname + location.search}</p>
}
function show(at = '/', slots = {}) {
  return page.show(
    <>
      <ArchivePage slots={slots} />
      <Where />
    </>,
    at,
  )
}
const where = () => plain(page.box.querySelector('[data-testid="where"]')!.textContent)
const rows = () => [...page.box.querySelectorAll('[data-testid="row"]')]
const section = (label: string) => page.box.querySelector<HTMLElement>(`section[aria-label="${label}"]`)!
const pick = (label: string, name: string) => [...section(label).querySelectorAll<HTMLButtonElement>('li button')].find((b) => plain(b.textContent)?.startsWith(name))

beforeEach(async () => {
  forgetPictures()
  await changeLanguage('de', false)
  auth.me = me
  server.answers = {
    'GET /api/v1/vaults': vaults,
    'GET /api/v1/kinds': [kind],
    'GET /api/v1/people': [{ id: 1, name: 'jule', display_name: 'Jule' }, { id: 2, name: 'tom', display_name: 'Tom' }],
    'GET /api/v1/senders': [{ name: 'Stadtwerke Lindenau', items: [{ id: 5, vault_id: 9 }] }],
    'GET /api/v1/tags': [{ name: 'strom', items: [{ id: 6, vault_id: 9 }] }],
    [SHARED]: { items: [], next: null },
    [WHOLE]: overview,
    [NEWEST]: result(three()),
    [ALL]: result(three()),
    'PUT /api/v1/me/preferences': { ...me.profile, view: 'grid' },
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('the overview of the archive', () => {
  it('shows the newest documents and how the archive spreads, with the count of what the person sees', async () => {
    await show()
    expect(plain(page.box.querySelector('h1')!.textContent)).toBe('Archiv')
    expect(page.text).toContain('3 Dokumente in 2 Tresoren, die du sehen kannst')
    expect(page.text).toContain('Neueste Dokumente')
    expect(rows().map((row) => plain(row.querySelector('.font-semibold')!.textContent))).toEqual(['Abschlag Strom Oktober', 'Kfz-Versicherung', 'Waschmaschine'])
    expect(rows()[0].querySelector('a')!.getAttribute('href')).toBe('/dokument/1')
    expect(rows()[1].querySelector('[aria-label="mit Notiz"]')).toBeTruthy()
    // The newest have no heading and no months; the counts of the cards.
    expect(page.box.querySelector('[data-testid="month"]')).toBeNull()
    expect(plain(pick('Nach Absender', 'Stadtwerke Lindenau')!.textContent)).toBe('Stadtwerke Lindenau2')
    expect(plain(pick('Nach Art', 'Rechnung')!.textContent)).toBe('Rechnung3')
    expect(plain(section('Nach Jahr').textContent)).toBe('Nach Jahr2026220251')
    expect(plain(section('Häufige Tags').textContent)).toContain('strom 3')
    // No pages, no tiles, no table here; no export without its part, no "shared with me" without such documents.
    expect(page.box.querySelector('[data-testid="pager"]')).toBeNull()
    expect(page.button('Kacheln')).toBeUndefined()
    expect(page.button('Exportieren')).toBeUndefined()
    expect(page.button('Mit mir geteilt')).toBeUndefined()
    expect(server.calls.filter((c) => c.url.startsWith('/api/v1/search?')).map((c) => c.url)).toEqual([NEWEST.slice(4)])
  })

  it('opens the table with everything, newest first, page by page', async () => {
    await show()
    await page.click(page.button('Alle 3 anzeigen'))
    expect(where()).toBe('/?all=1')
    expect(server.called('GET', ALL.slice(4))).toBeTruthy()
    expect([...page.box.querySelectorAll('[data-testid="month"]')].map((m) => plain(m.textContent))).toEqual(['Oktober 2026', 'September 2026', 'März 2025'])
    expect(plain(page.box.querySelector('[data-testid="hit-count"]')!.textContent)).toBe('3 Dokumente')
    expect(plain(page.box.querySelector('[data-testid="pager"]')!.textContent)).toContain('1 bis 3 von 3')
    // Back to the overview, and the back button of the browser too.
    await page.click(page.button('Übersicht'))
    expect(where()).toBe('/')
    expect(page.box.querySelector('[data-testid="overview"]')).toBeTruthy()
  })

  it('opens the table of a sender, a kind, a year or a tag of the overview', async () => {
    server.answers[table('', '&sender=Stadtwerke+Lindenau')] = result(three().slice(0, 1), 2)
    await show()
    await page.click(pick('Nach Absender', 'Stadtwerke Lindenau'))
    expect(where()).toBe('/?sender=Stadtwerke+Lindenau')
    expect(server.called('GET', table('', '&sender=Stadtwerke+Lindenau').slice(4))).toBeTruthy()
    // What narrows the table, removable on its own.
    expect(plain(page.box.querySelector('[data-testid="pill"]')!.textContent)).toBe('AbsenderStadtwerke Lindenau')
    await page.click(page.button('Absender entfernen'))
    expect(where()).toBe('/')
    await page.click(pick('Nach Jahr', '2025'))
    expect(server.called('GET', table('', '&date_from=2025-01-01&date_to=2025-12-31').slice(4))).toBeTruthy()
    await page.click(page.button('Übersicht'))
    await page.click(pick('Nach Art', 'Rechnung'))
    expect(server.called('GET', table('', '&kind_id=1').slice(4))).toBeTruthy()
    await page.click(page.button('Übersicht'))
    await page.click([...section('Häufige Tags').querySelectorAll('button')].find((b) => plain(b.textContent) === 'auto 1'))
    expect(where()).toBe('/?tag=auto')
  })

  it('lists every sender in a dialog, to find one by typing and to sort by name', async () => {
    const many = Array.from({ length: 12 }, (_, i) => ({ name: `Absender ${String.fromCharCode(65 + i)}`, count: 12 - i }))
    server.answers[WHOLE] = { ...overview, senders: many }
    await show()
    expect(section('Nach Absender').querySelectorAll('li')).toHaveLength(7)
    await page.click(page.button('Alle 12 Absender'))
    const names = () => [...page.dialog!.querySelectorAll('[data-testid="all-senders"] bdi')].map((b) => b.textContent)
    expect(names()).toHaveLength(12)
    await page.choose(page.select('Reihenfolge'), 'name')
    expect(names()[0]).toBe('Absender A')
    await page.type(page.dialog!.querySelector<HTMLInputElement>('input'), 'absender k')
    expect(names()).toEqual(['Absender K'])
    await page.click(page.dialog!.querySelector<HTMLButtonElement>('[data-testid="all-senders"] button'))
    expect(page.dialog).toBeNull()
    expect(where()).toBe('/?sender=Absender+K')
  })

  it('shows the overview of one vault, and of what was shared one by one', async () => {
    server.answers[SHARED] = { items: [doc(30, 'Klassenfahrt', '2026-09-05', { via_share: true, my_right: 'read' })], next: null }
    server.answers['GET /api/v1/search/overview?status=filed&vault_id=9'] = { ...overview, total: 1, senders: [{ name: 'Hansa', count: 1 }] }
    server.answers['GET /api/v1/search/overview?status=filed&via_share=true'] = { ...overview, total: 1 }
    await show()
    await page.click(page.button('Haushalt'))
    expect(where()).toBe('/?vault=9')
    expect(server.called('GET', '/api/v1/search?q=&status=filed&vault_id=9&limit=6')).toBeTruthy()
    expect(plain(section('Nach Absender').textContent)).toContain('Hansa1')
    // The heading still counts the whole archive.
    expect(plain(page.box.querySelector('[data-testid="archive-count"]')!.textContent)).toBe('3 Dokumente in 2 Tresoren, die du sehen kannst')
    await page.click(page.button('Mit mir geteilt'))
    expect(server.called('GET', '/api/v1/search/overview?status=filed&via_share=true')).toBeTruthy()
    expect(server.called('GET', '/api/v1/search?q=&status=filed&via_share=true&limit=6')).toBeTruthy()
  })

  it('says so when the archive is empty', async () => {
    server.answers[WHOLE] = { total: 0, senders: [], kinds: [], years: [], tags: [] }
    server.answers[NEWEST] = result([])
    await show()
    expect(page.text).toContain('Noch nichts im Archiv')
  })

  it('has no small link to the trash at the foot: the trash is in the menu', async () => {
    await show()
    expect(page.box.querySelector('a[href="/papierkorb"]')).toBeNull()
    expect(page.text).not.toContain('Papierkorb')
  })

  it('learns from the list of documents, not from a search, whether something was shared one by one', async () => {
    await show()
    expect(server.calls.filter((c) => c.url.includes('via_share=true')).map((c) => c.url)).toEqual([SHARED.slice(4)])
  })
})

describe('the table of the archive', () => {
  it('goes from page to page, with the page in the address and in the request', async () => {
    const first = Array.from({ length: 50 }, (_, i) => hit(doc(100 + i, `Brief ${i}`, '2026-05-01')))
    server.answers[ALL] = result(first, 120)
    server.answers[table('', '', 'limit=50&sort=-date&page=2')] = result([hit(doc(200, 'Seite zwei', '2026-01-01'))], 120)
    server.answers[table('', '', 'limit=50&sort=-date&page=3')] = result([hit(doc(300, 'Seite drei', '2025-01-01'))], 120)
    await show('/?all=1')
    expect(rows()).toHaveLength(50)
    const pager = () => page.box.querySelector('[data-testid="pager"]')!
    expect(plain(pager().textContent)).toContain('1 bis 50 von 120')
    expect([...pager().querySelectorAll('nav button[aria-label^="Seite"]')].map((b) => b.textContent)).toEqual(['1', '2', '3'])
    expect(page.button('Vorige Seite')!.disabled).toBe(true)
    await page.click(page.button('Seite 2'))
    expect(where()).toBe('/?all=1&page=2')
    expect(page.text).toContain('Seite zwei')
    expect(plain(pager().textContent)).toContain('51 bis 51 von 120')
    expect(page.button('Seite 2')!.getAttribute('aria-current')).toBe('page')
    await page.click(page.button('Nächste Seite'))
    expect(where()).toBe('/?all=1&page=3')
    expect(page.button('Nächste Seite')!.disabled).toBe(true)
    // Another choice starts on the first page again.
    await page.click(page.button('Haushalt'))
    expect(where()).toBe('/?all=1&vault=9')
  })

  it('takes 25 or 100 a page, and starts on the first', async () => {
    server.answers[table('', '', 'limit=25&sort=-date&page=1')] = result(three(), 3)
    server.answers[table('', '', 'limit=50&sort=-date&page=2')] = result(three(), 60)
    await show('/?all=1&page=2')
    await page.choose(page.select('je Seite'), '25')
    expect(where()).toBe('/?all=1&n=25')
    expect(server.called('GET', table('', '', 'limit=25&sort=-date&page=1').slice(4))).toBeTruthy()
  })

  it('goes to the last page when the one in the address is past the end', async () => {
    server.answers[table('', '', 'limit=50&sort=-date&page=9')] = result([], 60)
    server.answers[table('', '', 'limit=50&sort=-date&page=2')] = result([hit(doc(9, 'Das letzte', '2020-01-01'))], 60)
    await show('/?all=1&page=9')
    await until(() => page.text.includes('Das letzte'))
    expect(where()).toBe('/?all=1&page=2')
  })

  it('sorts by a column, the other way round on a second click, and only months when sorted by date', async () => {
    server.answers[table('', '', 'limit=50&sort=-amount&page=1')] = result(three())
    server.answers[table('', '', 'limit=50&sort=amount&page=1')] = result(three())
    server.answers[table('', '', 'limit=50&sort=title&page=1')] = result(three())
    server.answers[table('', '', 'limit=50&sort=-date&page=2')] = result(three(), 60)
    await show('/?all=1&page=2')
    expect(page.box.querySelectorAll('[data-testid="month"]').length).toBeGreaterThan(0)
    await page.click(page.button('Sortieren nach Betrag'))
    expect(where()).toBe('/?all=1&sort=-amount')
    expect(page.box.querySelector('[data-testid="month"]')).toBeNull()
    expect(page.button('Sortieren nach Betrag')!.getAttribute('aria-pressed')).toBe('true')
    await page.click(page.button('Sortieren nach Betrag'))
    expect(where()).toBe('/?all=1&sort=amount')
    await page.click(page.button('Sortieren nach Titel'))
    expect(server.called('GET', table('', '', 'limit=50&sort=title&page=1').slice(4))).toBeTruthy()
    // The newest first again: the order leaves the address.
    await page.click(page.button('Sortieren nach Datum'))
    expect(where()).toBe('/?all=1')
  })

  it('shows tiles where the person chose them, page by page too', async () => {
    auth.me = { ...me, profile: { ...me.profile, view: 'grid' } }
    await show('/?all=1')
    expect(page.box.querySelectorAll('ul.grid li')).toHaveLength(3)
    expect(page.box.querySelector('[role="radio"][aria-checked="true"]')!.getAttribute('aria-label')).toBe('Kacheln')
    expect(page.box.querySelector('[data-testid="pager"]')).toBeTruthy()
  })

  it('switches to tiles and keeps that choice with the account', async () => {
    await show('/?all=1')
    await page.click(page.button('Kacheln'))
    expect(server.called('PUT', '/api/v1/me/preferences')!.body).toEqual({ view: 'grid' })
    expect(auth.setMe).toHaveBeenCalledWith(expect.objectContaining({ profile: expect.objectContaining({ view: 'grid' }) }))
  })

  it('marks what the person shared with people or by a link, apart from what was shared with them', async () => {
    server.answers[ALL] = result([
      hit(doc(1, 'Geteilt', '2026-10-01', { share_count: 2, link_count: 0 })),
      hit(doc(2, 'Mit Link', '2026-10-01', { share_count: 0, link_count: 1 })),
      hit(doc(3, 'Von Lea', '2026-10-01', { via_share: true, can_share: false, share_count: null, link_count: null, my_right: 'read' })),
    ])
    await show('/?all=1')
    const marks = (row: Element) => [...row.querySelectorAll('[aria-label]')].map((m) => m.getAttribute('aria-label'))
    expect(marks(rows()[0])).toEqual(['mit Personen geteilt'])
    expect(marks(rows()[1])).toEqual(['Link nach außen'])
    expect(marks(rows()[2])).toEqual([])
    expect(plain(rows()[2].textContent)).toContain('mit mir geteilt')
  })

  it('keeps a title that turns its text around apart from the sentence around it', async () => {
    const turned = `strom ${String.fromCharCode(0x202e)}txt.exe${String.fromCharCode(0x202c)} Rechnung`
    server.answers[ALL] = result([hit(doc(1, turned, '2026-10-01'))])
    await show('/?all=1')
    expect(rows()[0].querySelector('.font-semibold bdi')!.textContent).toBe(turned)
  })

  it('says it kindly when the search is braked, and tries again by itself', async () => {
    server.fails[ALL] = { status: 429, code: 'search_too_often', values: { retry_after: 1 } }
    await show('/?all=1')
    expect(plain(page.box.querySelector('[role="alert"]')!.textContent)).toBe('Zu viele Suchen auf einmal. Warte einen Moment.')
    delete server.fails[ALL]
    await until(() => !page.box.querySelector('[role="alert"]') && page.text.includes('Abschlag Strom Oktober'))
  })
})

describe('the search of the archive', () => {
  it('searches what is in the address and marks the places the server names', async () => {
    server.answers[table('werke')] = result([hit(doc(1, 'Abschlag Strom Oktober', '2026-10-01'), { sender_marks: [[5, 10]], excerpt: { text: 'Die Stadtwerke <b>Lindenau</b> buchen ab.', marks: [[9, 14]], source: 'text' } })])
    await show('/?q=werke')
    await until(() => page.box.querySelector('mark'))
    expect([...page.box.querySelectorAll('mark')].map((m) => plain(m.textContent))).toEqual(['werke', 'werke', 'werke'])
    expect(plain(page.box.querySelector('[data-testid="excerpt"]')!.textContent)).toBe('Die Stadtwerke <b>Lindenau</b> buchen ab.')
    expect(page.box.querySelector('[data-testid="excerpt"] b')).toBeNull()
    expect(plain(page.box.querySelector('[data-testid="hit-count"]')!.textContent)).toContain('Ein Treffer für „werke“')
  })

  it('waits for a pause in typing and asks once, with the search in the address', async () => {
    await show()
    const field = page.box.querySelector<HTMLInputElement>('input[type="search"]')!
    await page.type(field, 's')
    await page.type(field, 'st')
    await page.type(field, 'strom')
    await until(() => server.called('GET', table('strom').slice(4)))
    const asked = server.calls.filter((c) => c.url.startsWith('/api/v1/search?q=s'))
    expect(asked.map((c) => c.url)).toEqual([table('strom').slice(4)])
    expect(where()).toBe('/?q=strom')
  })

  it('stops the request before when the search changes', async () => {
    const signals: AbortSignal[] = []
    const answering = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.startsWith('/api/v1/search?q=a')) {
        signals.push(init!.signal!)
        return new Promise<Response>((_resolve, reject) => init!.signal!.addEventListener('abort', () => reject(new DOMException('stop', 'AbortError'))))
      }
      return new Response(JSON.stringify(server.answers[`GET ${url}`] ?? []), { status: 200 })
    })
    await show()
    vi.stubGlobal('fetch', answering)
    const field = page.box.querySelector<HTMLInputElement>('input[type="search"]')!
    await page.type(field, 'alt')
    await until(() => signals.length === 1)
    expect(signals[0].aborted).toBe(false)
    await act(async () => page.box.querySelector<HTMLButtonElement>('button[aria-label="Suche leeren"]')!.click())
    await until(() => signals[0].aborted)
  })

  it('stops a request when the person leaves the page', async () => {
    const signals: AbortSignal[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.startsWith('/api/v1/search?q=') && url.includes('page=1')) {
        signals.push(init!.signal!)
        return new Promise<Response>((_resolve, reject) => init!.signal!.addEventListener('abort', () => reject(new DOMException('stop', 'AbortError'))))
      }
      return new Response(JSON.stringify(server.answers[`GET ${url}`] ?? []), { status: 200 })
    }))
    page.box = document.createElement('div')
    document.body.appendChild(page.box)
    const { createRoot } = await import('react-dom/client')
    const { MemoryRouter } = await import('react-router-dom')
    page.root = createRoot(page.box)
    await act(async () => page.root.render(<MemoryRouter initialEntries={['/?all=1']}><ArchivePage /></MemoryRouter>))
    await until(() => signals.length === 1)
    await act(async () => page.root.render(<MemoryRouter initialEntries={['/']}><p>elsewhere</p></MemoryRouter>))
    await until(() => signals[0].aborted)
  })

  it('keeps the help open while the focus moves into it with Tab, and an example works with the keyboard', async () => {
    await show()
    const field = page.box.querySelector<HTMLInputElement>('input[type="search"]')!
    await act(async () => field.focus())
    await until(() => page.box.querySelector('[data-testid="search-help"]'))
    const first = page.box.querySelector<HTMLButtonElement>('[data-testid="search-help"] button')!
    // Tab from the field to the first example: the focus stays in the group, the help stays.
    await act(async () => field.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: first })))
    await act(async () => first.focus())
    expect(page.box.querySelector('[data-testid="search-help"]')).toBeTruthy()
    // A pointer pressing an example does not take the focus away first.
    const press = new MouseEvent('mousedown', { bubbles: true, cancelable: true })
    first.dispatchEvent(press)
    expect(press.defaultPrevented).toBe(true)
    // Enter on a button is its click: the example is searched, and the focus goes back to the field.
    await act(async () => first.click())
    await idle()
    expect(where()).toBe('/?q=stadtwerke+2026')
    expect(document.activeElement).toBe(field)
  })

  it('closes the help when the focus leaves the field and its help', async () => {
    await show()
    const field = page.box.querySelector<HTMLInputElement>('input[type="search"]')!
    await act(async () => field.focus())
    await until(() => page.box.querySelector('[data-testid="search-help"]'))
    await act(async () => field.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: document.body })))
    expect(page.box.querySelector('[data-testid="search-help"]')).toBeNull()
  })

  it('teaches the words of the search in the language of the page', async () => {
    await changeLanguage('en', false)
    await show()
    const field = page.box.querySelector<HTMLInputElement>('input[type="search"]')!
    await act(async () => field.focus())
    await until(() => page.box.querySelector('[data-testid="search-help"]'))
    const codes = [...page.box.querySelectorAll('[data-testid="search-help"] code')].map((c) => c.textContent)
    expect(codes).toEqual(['stadtwerke 2026', '"please transfer"', 'kind:invoice', 'sender:hansa', 'tag:car', 'amount:>100', 'deadline:open', 'deadline:<30', 'keep:expired'])
  })

  it('offers the help of the search on an empty field, and an example searches at once', async () => {
    await show()
    const field = page.box.querySelector<HTMLInputElement>('input[type="search"]')!
    await act(async () => field.focus())
    await act(async () => field.dispatchEvent(new FocusEvent('focus', { bubbles: true })))
    await until(() => page.box.querySelector('[data-testid="search-help"]'))
    expect(page.text).toContain('So geht die Suche')
    expect(page.text).toContain('Teile von Wörtern gehen auch')
    const example = [...page.box.querySelectorAll('[data-testid="search-help"] button')].find((b) => plain(b.textContent)?.includes('betrag:>100'))!
    await act(async () => (example as HTMLButtonElement).click())
    await idle()
    expect(where()).toBe('/?q=betrag%3A%3E100')
    expect(server.called('GET', table('betrag%3A%3E100').slice(4))).toBeTruthy()
  })

  it('a new search starts on the first page', async () => {
    await show('/?q=alt&page=3')
    const field = page.box.querySelector<HTMLInputElement>('input[type="search"]')!
    await page.type(field, 'neu')
    await until(() => where() === '/?q=neu')
  })

  it('narrows by vault, kind, sender, tag, owner and year, in the address and in the request', async () => {
    server.answers['GET /api/v1/search/overview?status=filed&vault_id=9'] = overview
    await show()
    await page.click(page.button('Haushalt'))
    expect(where()).toBe('/?vault=9')
    await page.click(page.button('Filter'))
    await page.choose(page.select('Art'), '1')
    // The sender is chosen in the field of its own: typing shows the fitting names, a click takes one.
    const sender = page.box.querySelector<HTMLInputElement>('input[aria-label="Absender"]')!
    await act(async () => sender.focus())
    await page.type(sender, 'stadtw')
    await page.click(page.box.querySelector<HTMLElement>('[role="option"]'))
    await page.choose(page.select('Tag'), 'strom')
    await page.choose(page.select('Gehört'), '2')
    await page.choose(page.select('Jahr'), '2025')
    expect(server.called('GET', table('', '&vault_id=9&kind_id=1&sender=Stadtwerke+Lindenau&tag=strom&owner_id=2&date_from=2025-01-01&date_to=2025-12-31').slice(4))).toBeTruthy()
    expect(page.button('Filter (5)')).toBeTruthy()
    await page.click(page.button('Filter zurücksetzen'))
    expect(where()).toBe('/?vault=9')
  })

  it('lists a kind once when two vaults have it, and filters by the first of them', async () => {
    server.answers['GET /api/v1/kinds'] = [kind, { id: 8, key: '', name: 'Mietvertrag', hue: 120, position: 0, vault_id: 9 }, { id: 9, key: '', name: 'MIETVERTRAG', hue: 30, position: 0, vault_id: 7 }]
    await show()
    await page.click(page.button('Filter'))
    const options = [...page.select('Art')!.querySelectorAll('option')].map((o) => [o.value, plain(o.textContent)])
    expect(options).toEqual([['', 'Alle'], ['1', 'Rechnung'], ['8', 'Mietvertrag']])
    await page.choose(page.select('Art'), '8')
    expect(server.called('GET', table('', '&kind_id=8').slice(4))).toBeTruthy()
    // An address that carries the number of the namesake shows the same entry.
    expect(page.select('Art')!.value).toBe('8')
  })

  it('names the errors of the search language', async () => {
    server.fails[table('betrag%3A%3Eviel')] = { status: 422, code: 'invalid_amount' }
    await show('/?q=betrag:>viel')
    expect(page.text).toContain('Schreib einen Betrag wie betrag:>100 oder betrag:<12,50.')
  })

  it('has no tools to rename or delete a sender any more: the filter points to the order page', async () => {
    await show('/?sender=Stadtwerke+Lindenau')
    await page.click(page.button('Filter (1)'))
    expect(page.button('Löschen')).toBeUndefined()
    expect(page.button('Umbenennen')).toBeUndefined()
    const link = [...page.box.querySelectorAll('a')].find((a) => a.getAttribute('href') === '/ordnung')
    expect(link?.textContent).toContain('Ordnung')
  })
})

describe('the export of the archive', () => {
  it('shows the export only where its part is plugged in, with the filters as they are', async () => {
    const seen: unknown[] = []
    const ExportDialog = (props: { q: string; filters: unknown }) => {
      seen.push(props)
      return <p>export dialog</p>
    }
    await show('/?q=strom&vault=9', { ExportDialog })
    await page.click(page.button('Exportieren'))
    expect(page.text).toContain('export dialog')
    expect(seen[0]).toMatchObject({ q: 'strom', filters: { status: 'filed', vault_id: 9 } })
  })

  it('hands the export the number and the sum of what the table shows, and says what the export said', async () => {
    const seen: { count: number; sum: number }[] = []
    const ExportDialog = (props: { count: number; sum: number; say?: (text: string) => void; onClose: () => void }) => {
      seen.push(props)
      return (
        <button type="button" onClick={() => { props.say?.('Das ZIP wird gepackt.'); props.onClose() }}>
          fertig
        </button>
      )
    }
    await show('/?all=1', { ExportDialog })
    await page.click(page.button('Exportieren'))
    expect(seen.at(-1)).toMatchObject({ count: 3, sum: 8640 * 2 })
    await page.click(page.button('fertig'))
    expect(page.text).toContain('Das ZIP wird gepackt.')
    expect(page.button('fertig')).toBeUndefined()
  })

  it('hands it the number of the whole archive from the overview', async () => {
    const seen: { count: number }[] = []
    const ExportDialog = (props: { count: number }) => {
      seen.push(props)
      return <p>export dialog</p>
    }
    await show('/', { ExportDialog })
    await page.click(page.button('Exportieren'))
    expect(seen.at(-1)).toMatchObject({ count: 3 })
  })

  it('opens the export when the notice of a finished one leads here, and forgets it in the address', async () => {
    const ExportDialog = () => <p>export dialog</p>
    await show('/?export=1', { ExportDialog })
    expect(page.text).toContain('export dialog')
    expect(where()).toBe('/')
    page.close()
    await show('/?export=1')
    expect(page.text).not.toContain('export dialog')
  })
})

describe('the check of the files in the archive', () => {
  const broken = hit(doc(4, 'Mietvertrag', '2024-01-15', { files_state: 'missing' }))
  const changed = hit(doc(5, 'Zeugnis', '2023-07-01', { files_state: 'changed' }))

  it('puts a warning sign on a row whose file is missing or changed, and on no other', async () => {
    server.answers[ALL] = result([hit(doc(1, 'Abschlag Strom Oktober', '2026-10-01')), broken, changed])
    await show('/?all=1')
    expect(rows()[0].querySelector('[data-testid="file-sign"]')).toBeNull()
    expect(rows()[1].querySelector('[data-testid="file-sign"]')?.getAttribute('aria-label')).toBe('Datei fehlt')
    expect(rows()[2].querySelector('[data-testid="file-sign"]')?.getAttribute('aria-label')).toBe('Datei verändert')
  })

  it('puts it on a tile too', async () => {
    auth.me = { ...me, profile: { ...me.profile, view: 'grid' } }
    server.answers[ALL] = result([hit(doc(1, 'Abschlag Strom Oktober', '2026-10-01')), broken])
    await show('/?all=1')
    const tiles = [...page.box.querySelectorAll('ul.grid li')]
    expect(tiles[0].querySelector('[data-testid="file-sign"]')).toBeNull()
    expect(tiles[1].querySelector('[data-testid="file-sign"]')?.getAttribute('aria-label')).toBe('Datei fehlt')
  })
})
