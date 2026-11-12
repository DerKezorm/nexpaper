/**
 * The archive's table with what A1 adds, against a stand-in of the server: "Merken" with a suggested name and "Gemerkt
 * als", the chips of the saved searches on the phone, the sums of the whole result under the table, and "Auswählen"
 * with the bar (tag, kind, vault, trash), its questions (nothing goes without a yes) and the line that says what
 * happened.
 */
import { act } from 'react'

import type { Me, SearchHit } from '../api/client'
import { changeLanguage } from '../i18n'
import { forgetPictures } from '../lib/pictures'
import { forgetSaved } from '../lib/saved'
import { Page, Server, plain } from '../test/harness'
import { idle } from '../test/wait'
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
function doc(id: number, title: string, extra: Record<string, unknown> = {}) {
  return {
    id, vault_id: 9, owner: { id: 1, name: 'jule', display_name: 'Jule' }, title, sender: { id: 5, name: 'Stadtwerke Lindenau' }, kind, date: '2026-10-01', amount: 8640,
    currency: 'EUR', tags: ['strom'], dates: [], pages: 1, source: 'upload', status: 'filed', added_at: '2026-10-01T08:00:00Z', trashed_at: null,
    trash_ends_at: null, change_seq: id, current_version: 1, my_right: 'manage', via_share: false, can_share: true, notes: 0, process_error: '',
    duplicate: null, ...extra,
  }
}
const hit = (document: ReturnType<typeof doc>): SearchHit => ({ document, title_marks: [], sender_marks: [], excerpt: null }) as unknown as SearchHit
const result = (items: unknown[], total = items.length) => ({ items, total, next: null, understood: {} })
const three = () => [
  hit(doc(1, 'Abschlag Strom Oktober')),
  hit(doc(2, 'Kfz-Versicherung', { my_right: 'read', dates: [{ kind: 'keep_until', date: '2099-12-31', manual: true }] })),
  hit(doc(3, 'Waschmaschine', { amount: null })),
]

const WHOLE = 'GET /api/v1/search/overview?status=filed'
const NEWEST = 'GET /api/v1/search?q=&status=filed&limit=6'
const table = (q = '', filters = '', rest = 'limit=50&sort=-date&page=1') => `GET /api/v1/search?q=${q}&status=filed${filters}&${rest}`
const ALL = table('', '', 'limit=50&sort=-date&page=1')
const SAVED = 'GET /api/v1/saved-searches'
const vaults = [
  { id: 7, name: 'Jule', icon: 'user', personal_of: 1, my_right: 'manage', documents: 3, size: 1, members: [{ user_id: 1, name: 'jule', display_name: 'Jule', right: 'manage' }] },
  { id: 9, name: 'Haushalt', icon: 'home', personal_of: null, my_right: 'edit', documents: 1654, size: 1, members: [{ user_id: 1, name: 'jule', display_name: 'Jule', right: 'manage' }, { user_id: 2, name: 'tom', display_name: 'Tom', right: 'edit' }] },
]
const overview = { total: 3, senders: [{ name: 'Stadtwerke Lindenau', count: 3 }], kinds: [{ kind, count: 3 }], years: [{ year: 2026, count: 3 }], tags: [{ name: 'strom', count: 3 }] }

function show(at = '/') {
  return page.show(<ArchivePage slots={{}} />, at)
}
const dialogButton = (text: string) => [...document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')].find((b) => b.textContent?.trim() === text)
async function type(field: HTMLInputElement | HTMLSelectElement, value: string) {
  await act(async () => {
    const proto = field instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(field, value)
    field.dispatchEvent(new Event(field instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }))
  })
  await idle()
}

beforeEach(async () => {
  forgetPictures()
  forgetSaved()
  await changeLanguage('de', false)
  auth.me = me
  server.answers = {
    'GET /api/v1/vaults': vaults,
    'GET /api/v1/kinds': [kind, { ...kind, id: 4, name: 'Nebenkosten', vault_id: 9 }],
    'GET /api/v1/people': [{ id: 1, name: 'jule', display_name: 'Jule' }],
    'GET /api/v1/senders': [],
    'GET /api/v1/tags': [{ name: 'strom', items: [{ id: 6, vault_id: 9 }] }],
    'GET /api/v1/documents?status=filed&via_share=true&limit=1': { items: [], next: null },
    [WHOLE]: overview,
    [NEWEST]: result(three()),
    [ALL]: result(three()),
    [SAVED]: [],
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('Merken', () => {
  it('keeps the search with a suggested name and says where it went', async () => {
    const KIND = table('strom', '&kind_id=1')
    server.answers[KIND] = result(three())
    server.answers['POST /api/v1/saved-searches'] = { id: 5, name: '„strom“ · Rechnung', query: 'kind=1&q=strom', position: 0, count: null, state: 'ok', deadlines_off: false }
    await show('/?q=strom&kind=1&page=2')
    await page.click(page.button('Merken'))
    const name = document.querySelector<HTMLInputElement>('[role="dialog"] input')!
    expect(name.value).toBe('„strom“ · Rechnung')
    expect(page.text).toContain('Gemerkt wird die Suche mit ihren Filtern, nicht das Ergebnis')
    server.answers[SAVED] = [{ id: 5, name: '„strom“ · Rechnung', query: 'kind=1&q=strom', position: 0, count: 3, state: 'ok', deadlines_off: false }]
    await page.click(dialogButton('Merken'))
    // The page is not kept, the rest sorted.
    expect(server.called('POST', '/api/v1/saved-searches')?.body).toEqual({ name: '„strom“ · Rechnung', query: 'kind=1&q=strom' })
    expect(plain(page.box.querySelector('[data-testid="kept-as"]')?.textContent).trim()).toBe('Gemerkt als „„strom“ · Rechnung“')
    expect(page.button('Merken')).toBeUndefined()
  })

  it('says when there are thirty already, and the server refusing is shown', async () => {
    server.answers[SAVED] = Array.from({ length: 30 }, (_, n) => ({ id: n + 1, name: `S${n}`, query: `q=w${n}`, position: n, count: 0, state: 'ok', deadlines_off: false }))
    server.answers[table('', '', 'limit=50&sort=-date&page=1').replace('status=filed', 'status=filed&tag=strom')] = result(three())
    await show('/?tag=strom')
    await page.click(page.button('Merken'))
    expect(page.text).toContain('Du hast schon 30 gemerkte Suchen. Lösch erst eine in der Seitenleiste.')
    expect(dialogButton('Merken')?.disabled).toBe(true)
  })

  it('shows the chips of the saved searches on the phone, with their numbers or the hint', async () => {
    server.answers[SAVED] = [
      { id: 1, name: 'Strom', query: 'q=strom', position: 0, count: 1234, state: 'ok', deadlines_off: false },
      { id: 2, name: 'Alter Tresor', query: 'vault=99', position: 1, count: null, state: 'no_access', deadlines_off: false },
    ]
    await show('/')
    const chips = [...page.box.querySelectorAll<HTMLAnchorElement>('[data-testid="saved-chips"] a')]
    expect(chips.map((a) => plain(a.textContent).trim())).toEqual(['Strom1.234', 'Alter Tresor'])
    expect(chips[0].getAttribute('href')).toBe('/?q=strom')
    expect(chips[1].getAttribute('title')).toBe('Den Tresor dieser Suche siehst du nicht.')
    expect(page.box.querySelector('[data-testid="saved-chips"]')?.className).toContain('lg:hidden')
  })

  it('says that the filter "Frist" does not count for someone who switched deadlines off', async () => {
    auth.me = { ...me, profile: { ...me.profile, deadlines: false } }
    server.answers[table('', '', 'limit=50&sort=-date&page=1')] = result(three())
    await show('/?deadline=open&all=1')
    expect(plain(page.box.querySelector('[data-testid="deadlines-off"]')?.textContent)).toBe('Fristen sind für dich ausgeschaltet. Der Filter „Frist“ zählt hier nicht.')
  })
})

describe('Auswählen', () => {
  const ALL_TABLE = '/?all=1'
  const boxes = () => [...page.box.querySelectorAll<HTMLInputElement>('[data-testid="row"] input[type="checkbox"]')]
  const bulkCalls = () => server.calls.filter((c) => c.method === 'POST' && c.url === '/api/v1/documents/bulk')

  it('shows the boxes only after "Auswählen", with the words of the inbox, and "Fertig" lets go', async () => {
    await show(ALL_TABLE)
    expect(boxes()).toHaveLength(0)
    await page.click(page.button('Auswählen'))
    expect(boxes()).toHaveLength(3)
    const all = page.box.querySelector<HTMLInputElement>('input[aria-label="Alle 3 geladenen auswählen"]')!
    await act(async () => all.click())
    await idle()
    expect(plain(page.box.querySelector('[data-testid="bulk-bar"]')?.textContent)).toContain('3 ausgewählt')
    await page.click(page.button('Auswahl aufheben'))
    expect(page.box.querySelector('[data-testid="bulk-bar"]')).toBeNull()
    await act(async () => boxes()[0].click())
    await idle()
    expect(plain(page.box.querySelector('[data-testid="bulk-bar"]')?.textContent)).toContain('1 ausgewählt')
    await page.click(page.button('Fertig'))
    expect(boxes()).toHaveLength(0)
  })

  it('adds a tag to all of them and says honestly what happened', async () => {
    server.answers['POST /api/v1/documents/bulk'] = { changed: [1, 3], skipped: [{ id: 2, reason: 'forbidden' }], reasons: { forbidden: 1 } }
    await show(ALL_TABLE)
    await page.click(page.button('Auswählen'))
    await act(async () => page.box.querySelector<HTMLInputElement>('input[aria-label="Alle 3 geladenen auswählen"]')!.click())
    await idle()
    await page.click(page.button('Tag dazu'))
    expect(page.text).toContain('Tag zu 3 Dokumenten dazu')
    await type(document.querySelector<HTMLInputElement>('[role="dialog"] input')!, ' steuer2026 ')
    await page.click(dialogButton('Übernehmen'))
    expect(bulkCalls().map((c) => c.body)).toEqual([{ ids: [1, 2, 3], action: 'add_tag', tag: 'steuer2026' }])
    expect(page.text).toContain('2 geändert, 1 nicht (nur Lesen).')
  })

  it('names every reason when there are several', async () => {
    server.answers['POST /api/v1/documents/bulk'] = { changed: [1], skipped: [{ id: 2, reason: 'forbidden' }, { id: 3, reason: 'kind_elsewhere' }], reasons: { forbidden: 1, kind_elsewhere: 1 } }
    await show(ALL_TABLE)
    await page.click(page.button('Auswählen'))
    await act(async () => page.box.querySelector<HTMLInputElement>('input[aria-label="Alle 3 geladenen auswählen"]')!.click())
    await idle()
    await page.click(page.button('Art'))
    await type(document.querySelector<HTMLSelectElement>('[role="dialog"] select')!, '4')
    await page.click(dialogButton('Übernehmen'))
    expect(bulkCalls()[0].body).toEqual({ ids: [1, 2, 3], action: 'kind', kind_id: 4 })
    expect(page.text).toContain('1 geändert, 2 nicht (1 nur Lesen, 1 Art eines anderen Tresors).')
  })

  it('asks before the trash, names the 30 days and the documents still to be kept, and sends nothing without a yes', async () => {
    server.answers['POST /api/v1/documents/bulk'] = { changed: [1, 2, 3], skipped: [], reasons: {} }
    await show(ALL_TABLE)
    await page.click(page.button('Auswählen'))
    await act(async () => page.box.querySelector<HTMLInputElement>('input[aria-label="Alle 3 geladenen auswählen"]')!.click())
    await idle()
    await page.click(page.button('In den Papierkorb'))
    expect(page.text).toContain('3 Dokumente in den Papierkorb?')
    expect(page.text).toContain('30 Tage im Papierkorb')
    expect(plain(document.querySelector('[data-testid="bulk-keep-running"]')?.textContent)).toBe('1 davon liegt noch vor Ablauf seiner Aufbewahrung.')
    expect(bulkCalls()).toHaveLength(0)
    await page.click(dialogButton('Abbrechen'))
    expect(bulkCalls()).toHaveLength(0)
    await page.click(page.button('In den Papierkorb'))
    await page.click(dialogButton('Trotzdem in den Papierkorb'))
    expect(bulkCalls().map((c) => c.body)).toEqual([{ ids: [1, 2, 3], action: 'trash' }])
    expect(page.text).toContain('3 geändert.')
  })

  it('asks before moving and says who sees them afterwards', async () => {
    server.answers['POST /api/v1/documents/bulk'] = { changed: [1], skipped: [], reasons: {} }
    await show(ALL_TABLE)
    await page.click(page.button('Auswählen'))
    await act(async () => boxes()[0].click())
    await idle()
    await page.click(page.button('Tresor'))
    await type(document.querySelector<HTMLSelectElement>('[role="dialog"] select')!, '9')
    await page.click(dialogButton('Weiter'))
    expect(page.text).toContain('1 Dokument nach „Haushalt“ verschieben?')
    expect(plain(document.querySelector('[data-testid="bulk-move-who"]')?.textContent)).toBe('Danach sehen sie alle mit Zugang zu „Haushalt“: Jule, Tom.')
    expect(bulkCalls()).toHaveLength(0)
    await page.click(dialogButton('Verschieben'))
    expect(bulkCalls().map((c) => c.body)).toEqual([{ ids: [1], action: 'move', vault_id: 9 }])
  })

  it('leaves the filter "Darf weg" as it was: no "Auswählen" there', async () => {
    server.answers['GET /api/v1/keeping?limit=1'] = { items: [], total: 3 }
    server.answers[table('', '&keep=expired')] = result(three())
    await show('/?keep=expired')
    expect(page.box.querySelector('[data-testid="keep-bar"]')).not.toBeNull()
    expect(page.button('Auswählen')).toBeUndefined()
    expect(page.box.querySelector('[data-testid="bulk-bar"]')).toBeNull()
  })
})

describe('the sums under the table', () => {
  const SUM = 'GET /api/v1/search/sum?q=&status=filed'
  const line = () => plain(page.box.querySelector('[data-testid="sum"]')?.textContent).replace(/\s/g, ' ')

  it('sums the whole result after the page, per currency, with the number without an amount', async () => {
    server.answers[SUM] = { total: 23, sums: [{ currency: 'EUR', cents: 184012 }], without: 3 }
    await show('/?all=1')
    expect(line()).toBe('23 Dokumente · zusammen 1.840,12 € · 3 ohne Betrag')
    // The page first, then the sums.
    const urls = server.calls.map((c) => c.url)
    expect(urls.indexOf('/api/v1/search/sum?q=&status=filed')).toBeGreaterThan(urls.indexOf('/api/v1/search?q=&status=filed&limit=50&sort=-date&page=1'))
  })

  it('puts several currencies side by side, the euro first, and converts nothing', async () => {
    server.answers[SUM] = { total: 5, sums: [{ currency: 'CHF', cents: 20000 }, { currency: 'EUR', cents: 17345 }, { currency: 'USD', cents: 999 }], without: 0 }
    await show('/?all=1')
    expect(line()).toMatch(/^5 Dokumente · zusammen 200,00\sCHF, 173,45\s€, 9,99\s\$$/)
  })

  it('without any amount it is only the number', async () => {
    server.answers[SUM] = { total: 2, sums: [], without: 2 }
    await show('/?all=1')
    expect(line()).toBe('2 Dokumente')
  })

  it('stands under "Darf weg" too, and goes in English as well', async () => {
    await changeLanguage('en', false)
    server.answers['GET /api/v1/keeping?limit=1'] = { items: [], total: 3 }
    server.answers[table('', '&keep=expired')] = result(three())
    server.answers['GET /api/v1/search/sum?q=&status=filed&keep=expired'] = { total: 3, sums: [{ currency: 'EUR', cents: 17280 }], without: 1 }
    await show('/?keep=expired')
    expect(line()).toBe('3 documents · together €172.80 · 1 without an amount')
  })

  it('shows nothing when the sums do not come (the page stays as it is)', async () => {
    server.fails[SUM] = { status: 429, code: 'search_too_often' }
    await show('/?all=1')
    expect(page.box.querySelector('[data-testid="sum"]')).toBeNull()
    expect(page.box.querySelectorAll('[data-testid="row"]')).toHaveLength(3)
  })
})