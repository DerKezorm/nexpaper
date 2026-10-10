/**
 * The archive against a stand-in of the server: documents by month as a list or tiles, the search with the marks the
 * server names (never HTML), the help, the chips and filters in the address and in the request, more while scrolling
 * (the cursor), the brake of the search, the field that waits for a pause and stops the request before, the export
 * only where a part for it is plugged in, and a sender deleted after the number of its documents was confirmed.
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
const FIRST = 'GET /api/v1/search?q=&status=filed&limit=50'
const SHARED = 'GET /api/v1/documents?status=filed&via_share=true&limit=1'
const vaults = [
  { id: 7, name: 'Jule', icon: 'user', personal_of: 1, my_right: 'manage', documents: 3, size: 1, members: [] },
  { id: 9, name: 'Haushalt', icon: 'home', personal_of: null, my_right: 'edit', documents: 1654, size: 1, members: [] },
]

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
    [FIRST]: {
      items: [hit(doc(1, 'Abschlag Strom Oktober', '2026-10-01')), hit(doc(2, 'Kfz-Versicherung', '2026-09-28', { notes: 1, sender: { id: 6, name: 'Hansa' } })), hit(doc(3, 'Waschmaschine', '2025-03-14', { amount: null }))],
      total: 3, next: null, understood: {},
    },
    'PUT /api/v1/me/preferences': { ...me.profile, view: 'grid' },
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('the archive', () => {
  it('shows what was filed, by month, with the count of what the person sees', async () => {
    await show()
    expect(plain(page.box.querySelector('h1')!.textContent)).toBe('Archiv')
    expect(page.text).toContain('3 Dokumente in 2 Tresoren, die du sehen kannst')
    expect([...page.box.querySelectorAll('section h2')].map((h) => plain(h.textContent))).toEqual(['Oktober 2026', 'September 2026', 'März 2025'])
    const rows = [...page.box.querySelectorAll('section li')]
    expect(plain(rows[0].textContent)).toContain('Abschlag Strom Oktober')
    expect(plain(rows[0].textContent)).toContain('Stadtwerke Lindenau · 01.10.2026')
    expect(plain(rows[0].textContent)).toContain('86,40')
    expect(rows[0].querySelector('a')!.getAttribute('href')).toBe('/dokument/1')
    expect(rows[1].querySelector('[aria-label="mit Notiz"]')).toBeTruthy()
    // No export without the part of block B9, and no "shared with me" without such documents.
    expect(page.button('Exportieren')).toBeUndefined()
    expect(page.button('Mit mir geteilt')).toBeUndefined()
  })

  it('has no small link to the trash at the foot: the trash is in the menu', async () => {
    await show()
    expect(page.box.querySelector('a[href="/papierkorb"]')).toBeNull()
    expect(page.text).not.toContain('Papierkorb')
  })

  it('shows tiles where the person chose them', async () => {
    auth.me = { ...me, profile: { ...me.profile, view: 'grid' } }
    await show()
    expect(page.box.querySelectorAll('ul.grid li')).toHaveLength(3)
    expect(page.box.querySelector('[role="radio"][aria-checked="true"]')!.getAttribute('aria-label')).toBe('Kacheln')
  })

  it('switches to tiles and keeps that choice with the account', async () => {
    await show()
    await page.click(page.button('Kacheln'))
    expect(server.called('PUT', '/api/v1/me/preferences')!.body).toEqual({ view: 'grid' })
    expect(auth.setMe).toHaveBeenCalledWith(expect.objectContaining({ profile: expect.objectContaining({ view: 'grid' }) }))
  })

  it('searches what is in the address and marks the places the server names', async () => {
    server.answers['GET /api/v1/search?q=werke&status=filed&limit=50'] = {
      items: [hit(doc(1, 'Abschlag Strom Oktober', '2026-10-01'), { sender_marks: [[5, 10]], excerpt: { text: 'Die Stadtwerke <b>Lindenau</b> buchen ab.', marks: [[9, 14]], source: 'text' } })],
      total: 1, next: null, understood: {},
    }
    await show('/?q=werke')
    await until(() => page.box.querySelector('mark'))
    expect([...page.box.querySelectorAll('mark')].map((m) => plain(m.textContent))).toEqual(['werke', 'werke'])
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
    await until(() => server.called('GET', '/api/v1/search?q=strom&status=filed&limit=50'))
    const asked = server.calls.filter((c) => c.url.startsWith('/api/v1/search?q=s'))
    expect(asked.map((c) => c.url)).toEqual(['/api/v1/search?q=strom&status=filed&limit=50'])
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
      if (url.startsWith('/api/v1/search?q=') && url.includes('limit=50')) {
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
    await act(async () => page.root.render(<MemoryRouter initialEntries={['/']}><ArchivePage /></MemoryRouter>))
    await until(() => signals.length === 1)
    await act(async () => page.root.render(<MemoryRouter initialEntries={['/']}><p>elsewhere</p></MemoryRouter>))
    await until(() => signals[0].aborted)
  })

  it('stops loading more when the search changes meanwhile', async () => {
    server.answers[FIRST] = { items: [hit(doc(1, 'Neu', '2026-10-01'))], total: 2, next: 'CURSOR1', understood: {} }
    await show()
    const signals: AbortSignal[] = []
    const answer = (url: string) => new Response(JSON.stringify(server.answers[`GET ${url}`] ?? { items: [], total: 0, next: null, understood: {} }), { status: 200 })
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes('cursor=CURSOR1')) {
        signals.push(init!.signal!)
        return new Promise<Response>((_resolve, reject) => init!.signal!.addEventListener('abort', () => reject(new DOMException('stop', 'AbortError'))))
      }
      return answer(url)
    }))
    await act(async () => page.button('Mehr laden')!.click())
    await until(() => signals.length === 1)
    await act(async () => page.button('Haushalt')!.click())
    await until(() => signals[0].aborted)
  })

  it('marks what the person shared with people or by a link, apart from what was shared with them', async () => {
    server.answers[FIRST] = {
      items: [
        hit(doc(1, 'Geteilt', '2026-10-01', { share_count: 2, link_count: 0 })),
        hit(doc(2, 'Mit Link', '2026-10-01', { share_count: 0, link_count: 1 })),
        hit(doc(3, 'Von Lea', '2026-10-01', { via_share: true, can_share: false, share_count: null, link_count: null, my_right: 'read' })),
      ],
      total: 3, next: null, understood: {},
    }
    await show()
    const rows = [...page.box.querySelectorAll('section li')]
    const marks = (row: Element) => [...row.querySelectorAll('[aria-label]')].map((m) => m.getAttribute('aria-label'))
    expect(marks(rows[0])).toEqual(['mit Personen geteilt'])
    expect(marks(rows[1])).toEqual(['Link nach außen'])
    expect(marks(rows[2])).toEqual([])
    expect(plain(rows[2].textContent)).toContain('mit mir geteilt')
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
    expect(codes).toEqual(['stadtwerke 2026', '"please transfer"', 'kind:invoice', 'sender:hansa', 'tag:car', 'amount:>100'])
  })

  it('counts only what was filed in the heading, and only for the whole archive', async () => {
    await show('/?vault=9')
    expect(plain(page.box.querySelector('[data-testid="archive-count"]')!.textContent)).toBe('')
    await page.click(page.button('Alle Tresore'))
    expect(plain(page.box.querySelector('[data-testid="archive-count"]')!.textContent)).toBe('3 Dokumente in 2 Tresoren, die du sehen kannst')
  })

  it('learns from the list of documents, not from a search, whether something was shared one by one', async () => {
    await show()
    expect(server.calls.filter((c) => c.url.startsWith('/api/v1/search'))).toHaveLength(1)
  })

  it('keeps a title that turns its text around apart from the sentence around it', async () => {
    const turned = `strom ${String.fromCharCode(0x202e)}txt.exe${String.fromCharCode(0x202c)} Rechnung`
    server.answers[FIRST] = { items: [hit(doc(1, turned, '2026-10-01'))], total: 1, next: null, understood: {} }
    await show()
    const title = page.box.querySelector('section li .font-semibold bdi')!
    expect(title.textContent).toBe(turned)
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
    expect(server.called('GET', '/api/v1/search?q=betrag%3A%3E100&status=filed&limit=50')).toBeTruthy()
  })

  it('narrows by vault, kind, sender, tag, owner and time, in the address and in the request', async () => {
    await show()
    await page.click(page.button('Haushalt'))
    expect(where()).toBe('/?vault=9')
    expect(server.called('GET', '/api/v1/search?q=&status=filed&vault_id=9&limit=50')).toBeTruthy()
    await page.click(page.button('Filter'))
    await page.choose(page.select('Art'), '1')
    // The sender is chosen in the field of its own: typing shows the fitting names, a click takes one.
    const sender = page.box.querySelector<HTMLInputElement>('input[aria-label="Absender"]')!
    await act(async () => sender.focus())
    await page.type(sender, 'stadtw')
    await page.click(page.box.querySelector<HTMLElement>('[role="option"]'))
    await page.choose(page.select('Tag'), 'strom')
    await page.choose(page.select('Gehört'), '2')
    expect(server.called('GET', '/api/v1/search?q=&status=filed&vault_id=9&kind_id=1&sender=Stadtwerke+Lindenau&tag=strom&owner_id=2&limit=50')).toBeTruthy()
    expect(page.button('Filter (4)')).toBeTruthy()
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
    expect(server.called('GET', '/api/v1/search?q=&status=filed&kind_id=8&limit=50')).toBeTruthy()
    // An address that carries the number of the namesake shows the same entry.
    expect(page.select('Art')!.value).toBe('8')
  })

  it('shows "shared with me" only when something was shared one by one, and asks the server for exactly that', async () => {
    server.answers[SHARED] = { items: [doc(30, 'Klassenfahrt', '2026-09-05', { via_share: true, my_right: 'read' })], next: null }
    await show()
    await page.click(page.button('Mit mir geteilt'))
    expect(server.called('GET', '/api/v1/search?q=&status=filed&via_share=true&limit=50')).toBeTruthy()
  })

  it('loads the next page with the cursor of the one before', async () => {
    server.answers[FIRST] = { items: [hit(doc(1, 'Neu', '2026-10-01'))], total: 2, next: 'CURSOR1', understood: {} }
    server.answers['GET /api/v1/search?q=&status=filed&limit=50&cursor=CURSOR1'] = { items: [hit(doc(2, 'Alt', '2020-01-02'))], total: 2, next: null, understood: {} }
    await show()
    await page.click(page.button('Mehr laden'))
    expect(page.text).toContain('Alt')
    expect([...page.box.querySelectorAll('section h2')].map((h) => plain(h.textContent))).toEqual(['Oktober 2026', 'Januar 2020'])
    expect(page.button('Mehr laden')).toBeUndefined()
  })

  it('says it kindly when the search is braked, and tries again by itself', async () => {
    server.fails[FIRST] = { status: 429, code: 'search_too_often', values: { retry_after: 1 } }
    await show()
    expect(plain(page.box.querySelector('[role="alert"]')!.textContent)).toBe('Zu viele Suchen auf einmal. Warte einen Moment.')
    delete server.fails[FIRST]
    await until(() => !page.box.querySelector('[role="alert"]') && page.text.includes('Abschlag Strom Oktober'))
  })

  it('names the errors of the search language', async () => {
    server.fails['GET /api/v1/search?q=betrag%3A%3Eviel&status=filed&limit=50'] = { status: 422, code: 'invalid_amount' }
    await show('/?q=betrag:>viel')
    expect(page.text).toContain('Schreib einen Betrag wie betrag:>100 oder betrag:<12,50.')
  })

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

  it('hands the export the number and the sum of what it shows, and says what the export said', async () => {
    const seen: { count: number; sum: number }[] = []
    const ExportDialog = (props: { count: number; sum: number; say?: (text: string) => void; onClose: () => void }) => {
      seen.push(props)
      return (
        <button type="button" onClick={() => { props.say?.('Das ZIP wird gepackt.'); props.onClose() }}>
          fertig
        </button>
      )
    }
    await show('/', { ExportDialog })
    await page.click(page.button('Exportieren'))
    expect(seen.at(-1)).toMatchObject({ count: 3, sum: 8640 * 2 })
    await page.click(page.button('fertig'))
    expect(page.text).toContain('Das ZIP wird gepackt.')
    expect(page.button('fertig')).toBeUndefined()
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

  it('has no tools to rename or delete a sender any more: the filter points to the order page', async () => {
    await show('/?sender=Stadtwerke+Lindenau')
    await page.click(page.button('Filter (1)'))
    expect(page.button('Löschen')).toBeUndefined()
    expect(page.button('Umbenennen')).toBeUndefined()
    const link = [...page.box.querySelectorAll('a')].find((a) => a.getAttribute('href') === '/ordnung')
    expect(link?.textContent).toContain('Ordnung')
  })
})

describe('the check of the files in the archive', () => {
  const broken = hit(doc(4, 'Mietvertrag', '2024-01-15', { files_state: 'missing' }))
  const changed = hit(doc(5, 'Zeugnis', '2023-07-01', { files_state: 'changed' }))

  it('puts a warning sign on a list row whose file is missing or changed, and on no other', async () => {
    server.answers[FIRST] = { items: [hit(doc(1, 'Abschlag Strom Oktober', '2026-10-01')), broken, changed], total: 3, next: null, understood: {} }
    await show()
    const rows = [...page.box.querySelectorAll('section li')]
    expect(rows[0].querySelector('[data-testid="file-sign"]')).toBeNull()
    expect(rows[1].querySelector('[data-testid="file-sign"]')?.getAttribute('aria-label')).toBe('Datei fehlt')
    expect(rows[2].querySelector('[data-testid="file-sign"]')?.getAttribute('aria-label')).toBe('Datei verändert')
  })

  it('puts it on a tile too', async () => {
    auth.me = { ...me, profile: { ...me.profile, view: 'grid' } }
    server.answers[FIRST] = { items: [hit(doc(1, 'Abschlag Strom Oktober', '2026-10-01')), broken], total: 2, next: null, understood: {} }
    await show()
    const tiles = [...page.box.querySelectorAll('ul.grid li')]
    expect(tiles[0].querySelector('[data-testid="file-sign"]')).toBeNull()
    expect(tiles[1].querySelector('[data-testid="file-sign"]')?.getAttribute('aria-label')).toBe('Datei fehlt')
  })
})
