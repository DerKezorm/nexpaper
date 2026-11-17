/**
 * The archive on a wide screen (issue #7): a click in the table opens the document beside it (`?open=<id>`), the list
 * stays as it is; j and k go down and up (over the end of a page too), Esc and the cross close it, a change in the
 * document asks the list again. Below the width, or with Ctrl, a click opens the document's own page as before.
 */
import { act } from 'react'
import { useLocation } from 'react-router-dom'

import type { Me } from '../api/client'
import { changeLanguage } from '../i18n'
import { forgetPictures } from '../lib/pictures'
import { Page, Server, plain } from '../test/harness'
import { until } from '../test/wait'
import { ArchivePage } from './ArchivePage'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: '', language: 'de', email_confirmed: false,
  email_pending: '', oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.0.1',
  whats_new_seen: '0.0.1', session_stage: 'full', profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true, deadlines: true },
}
const auth = { status: 'signedIn', me: me as Me | null, setMe: vi.fn((next: Me) => (auth.me = next)), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()

const kind = { id: 1, key: 'invoice', name: 'Rechnung', hue: 28, position: 0 }
function doc(id: number, title: string, date: string) {
  return {
    id, vault_id: 9, owner: { id: 1, name: 'jule', display_name: 'Jule' }, title, sender: { id: 5, name: 'Stadtwerke Lindenau' }, kind, date, amount: 8640,
    currency: 'EUR', tags: [], dates: [], pages: 1, source: 'upload', status: 'filed', added_at: `${date}T08:00:00Z`, trashed_at: null,
    trash_ends_at: null, change_seq: id, current_version: 1, my_right: 'manage', via_share: false, can_share: true, notes: 0, process_error: '',
    duplicate: null,
  }
}
const docs = [doc(1, 'Abschlag Strom Oktober', '2026-10-01'), doc(2, 'Kfz-Versicherung', '2026-09-28'), doc(3, 'Waschmaschine', '2025-03-14'), doc(4, 'Grundsteuer', '2025-02-10')]
const hit = (d: ReturnType<typeof doc>) => ({ document: d, title_marks: [], sender_marks: [], excerpt: null })
const result = (items: unknown[], total = items.length) => ({ items, total, next: null, understood: {} })
const table = (rest = 'limit=50&sort=-date&page=1') => `GET /api/v1/search?q=&status=filed&${rest}`
const ALL = table()
const vaults = [{ id: 9, name: 'Haushalt', icon: 'home', personal_of: null, my_right: 'edit', documents: 4, size: 1, members: [] }]

/** A window of the given width for the media query of `lib/wide.ts`. */
function windowOf(width: number) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: Number(/min-width:\s*(\d+)px/.exec(query)?.[1] ?? 0) <= width,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }))
}

function Where() {
  const location = useLocation()
  return <p data-testid="where">{location.pathname + location.search}</p>
}
const show = (at: string) =>
  page.show(
    <>
      <ArchivePage slots={{}} />
      <Where />
    </>,
    at,
  )
const where = () => plain(page.box.querySelector('[data-testid="where"]')!.textContent)
const link = (id: number) => page.box.querySelector<HTMLAnchorElement>(`[data-doc="${id}"] a`)
const pane = () => page.box.querySelector<HTMLElement>('[data-testid="document-pane"]')
const paneTitle = () => pane()?.querySelector<HTMLInputElement>('input[aria-label="Titel"]')?.value
async function press(key: string, on: EventTarget = window) {
  await act(async () => {
    on.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
  })
  await until(() => true)
}

beforeEach(async () => {
  forgetPictures()
  await changeLanguage('de', false)
  auth.me = me
  server.answers = {
    'GET /api/v1/vaults': vaults,
    'GET /api/v1/kinds': [kind],
    'GET /api/v1/search/overview?status=filed': { total: 3, senders: [], kinds: [], years: [], tags: [] },
    'GET /api/v1/search?q=&status=filed&limit=6': result(docs.slice(0, 3).map(hit)),
    [ALL]: result(docs.slice(0, 3).map(hit)),
    ...Object.fromEntries(docs.map((d) => [`GET /api/v1/documents/${d.id}`, d])),
    'PATCH /api/v1/documents/2': { ...docs[1], title: 'Kfz-Versicherung 2027' },
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('below the width', () => {
  it('opens the document on its own page, as before', async () => {
    windowOf(1536)
    await show('/?all=1')
    await page.click(link(2))
    expect(where()).toBe('/dokument/2')
    expect(pane()).toBeNull()
  })

  it('ignores an open document in the address', async () => {
    windowOf(1536)
    await show('/?all=1&open=2')
    expect(page.box.querySelector('[data-testid="archive-split"]')).toBeNull()
    expect(pane()).toBeNull()
  })
})

describe('on a wide screen', () => {
  beforeEach(() => windowOf(1920))

  it('keeps the filters of the narrow list to its two columns (issue #7)', async () => {
    await show('/?all=1&open=2')
    await until(() => paneTitle() === 'Kfz-Versicherung', 'the document beside the list')
    await page.click(page.button('Filter'))
    const box = page.box.querySelector<HTMLElement>('[data-testid="archive-filters"]')!
    expect(box.className).toContain('grid-cols-2')
    expect(box.className).not.toMatch(/lg:grid-cols/)
    // A span of the wide grid (seven columns) in a grid of two makes seven columns of two fields' room.
    for (const field of box.children) expect(field.className).not.toMatch(/(?:sm|md|lg|xl):col-span|col-span-(?:[3-9]|full)/)
    expect(box.querySelector('input[aria-label="Absender"]')!.closest('.col-span-2')).toBeTruthy()
  })

  it('opens a document beside the list and marks its row', async () => {
    await show('/?all=1')
    await page.click(link(2))
    expect(where()).toBe('/?all=1&open=2')
    await until(() => paneTitle() === 'Kfz-Versicherung', 'the document beside the list')
    expect(page.box.querySelector('[data-testid="archive-split"]')).toBeTruthy()
    expect(link(2)!.getAttribute('aria-current')).toBe('true')
    expect(link(1)!.getAttribute('aria-current')).toBeNull()
    expect(plain(page.box.querySelector('[data-testid="pane-position"]')!.textContent)).toBe('2 von 3')
    // The list itself was not asked for again: search, filters and page stay.
    expect(server.calls.filter((c) => c.url === ALL.slice(4))).toHaveLength(1)
  })

  it('goes down and up the list with j and k, and closes with Esc', async () => {
    await show('/?all=1&open=1')
    await until(() => paneTitle() === 'Abschlag Strom Oktober', 'the first document')
    await press('j')
    expect(where()).toBe('/?all=1&open=2')
    await until(() => paneTitle() === 'Kfz-Versicherung', 'the second document')
    await press('j')
    expect(where()).toBe('/?all=1&open=3')
    await press('k')
    await press('k')
    expect(where()).toBe('/?all=1&open=1')
    // Before the first there is nothing.
    await press('k')
    expect(where()).toBe('/?all=1&open=1')
    await press('Escape')
    expect(where()).toBe('/?all=1')
    expect(pane()).toBeNull()
    expect(page.box.querySelector('[data-testid="archive-split"]')).toBeNull()
  })

  it('leaves the keys to a field that is typed in', async () => {
    await show('/?all=1&open=1')
    await until(() => pane(), 'the document')
    const field = page.box.querySelector<HTMLInputElement>('input[type="search"]')!
    await press('j', field)
    await press('Escape', field)
    expect(where()).toBe('/?all=1&open=1')
  })

  it('goes on to the next page past the end of this one, and back', async () => {
    // Pages of 25: the 25th document is the last of the first page, the 26th the first of the second.
    const many = Array.from({ length: 26 }, (_, i) => doc(100 + i, `Abrechnung ${i + 1}`, '2025-01-01'))
    for (const d of many) server.answers[`GET /api/v1/documents/${d.id}`] = d
    server.answers[table('limit=25&sort=-date&page=1')] = result(many.slice(0, 25).map(hit), 26)
    server.answers[table('limit=25&sort=-date&page=2')] = result(many.slice(25).map(hit), 26)
    await show('/?all=1&n=25&open=124')
    await until(() => paneTitle() === 'Abrechnung 25', 'the last document of the first page')
    await press('j')
    await until(() => where() === '/?all=1&n=25&open=125&page=2', 'the first document of the next page')
    await until(() => paneTitle() === 'Abrechnung 26', 'the document of the next page')
    expect(plain(page.box.querySelector('[data-testid="pane-position"]')!.textContent)).toBe('26 von 26')
    // At the very end j goes nowhere.
    await press('j')
    expect(where()).toBe('/?all=1&n=25&open=125&page=2')
    await press('k')
    await until(() => where() === '/?all=1&n=25&open=124', 'the last document of the first page again')
  })

  it('closes with the cross', async () => {
    await show('/?all=1&open=2')
    await until(() => pane(), 'the document')
    await page.click(page.button('Schließen', pane()!))
    expect(where()).toBe('/?all=1')
  })

  it('asks the list again when the document changed', async () => {
    await show('/?all=1&open=2')
    await until(() => paneTitle() === 'Kfz-Versicherung', 'the document')
    const before = server.calls.filter((c) => c.url === ALL.slice(4)).length
    const field = pane()!.querySelector<HTMLInputElement>('input[aria-label="Titel"]')!
    await act(async () => field.focus())
    await page.type(field, 'Kfz-Versicherung 2027')
    await act(async () => field.blur())
    await until(() => server.called('PATCH', '/api/v1/documents/2'), 'the new title')
    await until(() => server.calls.filter((c) => c.url === ALL.slice(4)).length > before, 'the list asked again')
  })

  it('opens from the overview into the list of all', async () => {
    await show('/')
    await page.click(link(1))
    expect(where()).toBe('/?all=1&open=1')
    await until(() => paneTitle() === 'Abschlag Strom Oktober', 'the document beside the list')
  })

  it('leaves a click with Ctrl to the browser (a new tab)', async () => {
    await show('/?all=1')
    const clicked = new MouseEvent('click', { bubbles: true, cancelable: true, ctrlKey: true, button: 0 })
    await act(async () => {
      link(2)!.dispatchEvent(clicked)
    })
    expect(where()).toBe('/?all=1')
    expect(pane()).toBeNull()
  })
})
