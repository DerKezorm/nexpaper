/**
 * Settings, Accounts and Log, laid out as nexnotes' cards, against a stand-in of the server: the accounts as a table
 * (person, sign-in, role, the AI checkbox, last use, the menu), "Person einladen" top right, the open invitations as a
 * card of their own, the keys of all accounts with a red word to block one; the log as one bar (level chips, search,
 * level of detail, download, clear after a question) above a table of its lines.
 */
import type { Me } from '../../api/client'
import { changeLanguage } from '../../i18n'
import { Page, Server } from '../../test/harness'
import { until } from '../../test/wait'
import { AccountsCard, AllApiKeysCard, LogCard } from './ServerCards'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: 'jule@example.com', language: 'de', email_confirmed: true,
  email_pending: '', oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.0.1',
  whats_new_seen: '0.0.1', session_stage: 'full', profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true, deadlines: true },
}
const auth = { status: 'signedIn', me: me as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()
const row = (over: Record<string, unknown>) => ({ ...me, locked: false, blocked: false, has_password: true, created_at: '2026-10-01T10:00:00Z', last_seen_at: null, ai_allowed: true, ...over })
const HOUR = 3600_000

beforeEach(async () => {
  await changeLanguage('de', false)
  auth.me = me
  server.answers = {
    'GET /api/v1/accounts': [
      row({ last_seen_at: new Date(Date.now() - 2 * HOUR).toISOString() }),
      row({ id: 2, name: 'tom', display_name: 'Tom', role: 'member', email: '', two_factor: false, ai_allowed: false }),
      row({ id: 3, name: 'lea', display_name: 'Lea', role: 'member', email: 'lea@example.com', sign_in: 'oidc', has_password: false, two_factor: false, blocked: true }),
      row({ id: 4, name: 'ben', display_name: '', role: 'member', two_factor: false, locked: true }),
    ],
    'GET /api/v1/invites': [],
    'GET /api/v1/oidc/admin/links': [{ account_id: 3, provider_id: 5, slug: 'authentik', label: 'authentik' }],
    'PUT /api/v1/accounts/2/permissions': 204,
    'DELETE /api/v1/invites/9': 204,
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

const cells = (name: string) => [...document.querySelectorAll(`[data-testid="account-${name}"] td`)].map((cell) => cell.textContent?.trim())

describe('the accounts', () => {
  it('stand in a table as in nexnotes, with nexpaper\'s AI column where nexnotes shows the storage', async () => {
    await page.show(<AccountsCard />)
    const head = [...document.querySelectorAll('[data-testid="account-table"] th')].map((cell) => cell.textContent?.trim())
    expect(head).toEqual(['Person', 'Anmeldung', 'Rolle', 'KI', 'Zuletzt', 'Aktionen'])
    expect(page.text).toContain('4 Konten. Jedes bekommt beim Anlegen seinen persönlichen Tresor.')
    // The person: the picture, the name shown and, below it, the mail address (else the account name).
    expect(cells('jule')[0]).toMatch(/Jule.*jule@example\.com$/)
    expect(cells('jule').slice(1, 3)).toEqual(['Passwort + 2FA', 'Betreiber'])
    expect(cells('jule')[4]).toBe('vor 2 Stunden')
    expect(cells('tom')[0]).toMatch(/Tom.*tom$/)
    expect(cells('tom').slice(1, 3)).toEqual(['Passwort', 'Mitglied'])
    expect(cells('tom')[4]).toBe('noch nie')
    // An account of a provider: the provider, no password; blocked says so where the last use would be.
    expect(cells('lea')[1]).toBe('authentik')
    expect(cells('lea')[4]).toBe('gesperrt')
    // Held back by the sign-in brake for a while.
    expect(cells('ben')[4]).toContain('eine Weile gesperrt')
  })

  it('switch the AI for one account with the checkbox of its row', async () => {
    await page.show(<AccountsCard />)
    const box = document.querySelector<HTMLInputElement>('input[aria-label="KI erlaubt: Tom"]')!
    expect(box.checked).toBe(false)
    await page.click(box)
    expect(server.called('PUT', '/api/v1/accounts/2/permissions')!.body).toEqual({ ai_allowed: true })
    expect(box.checked).toBe(true)
  })

  it('keep every action in the menu of a row, the link to reset the password among them, and none for the own account', async () => {
    await page.show(<AccountsCard />)
    expect(page.button('Aktionen für Jule')).toBeUndefined()
    await page.click(page.button('Aktionen für Tom'))
    const items = [...document.querySelectorAll('[role="menu"] [role="menuitem"]')].map((item) => item.textContent)
    expect(items).toEqual(['Zum Betreiber machen', 'Link zum Zurücksetzen …', 'Überall abmelden', 'Sperren', 'Löschen …'])
    await page.click(page.button('Aktionen für Lea'))
    const theirs = [...document.querySelectorAll('[role="menu"] [role="menuitem"]')].map((item) => item.textContent)
    // An account without a password gets a link for its first one; the link to the provider can be let go.
    expect(theirs).toEqual(['Zum Betreiber machen', 'Link für ein Passwort …', 'Überall abmelden', 'Verknüpfung mit authentik lösen', 'Entsperren', 'Löschen …'])
  })

  it('invite a person with the button top right', async () => {
    await page.show(<AccountsCard />)
    const card = document.getElementById('accounts')!
    const invite = page.button('Person einladen', card)!
    // Above the table, before it in the card.
    expect(invite.compareDocumentPosition(card.querySelector('table')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    await page.click(invite)
    expect(page.dialog!.getAttribute('aria-label')).toBe('Person einladen')
  })

  it('show the open invitations as a card of their own, and withdraw one only after the question', async () => {
    server.answers['GET /api/v1/invites'] = [{ id: 9, email: 'neu@example.com', expires_at: '2026-10-20T10:00:00Z' }]
    await page.show(<AccountsCard />)
    const card = document.getElementById('invites')!
    expect(card.textContent).toContain('Offene Einladungen')
    expect(card.textContent).toContain('neu@example.com')
    expect(document.getElementById('accounts')!.contains(card)).toBe(false)
    await page.click(page.button('Zurückziehen', card))
    expect(server.changes()).toEqual([])
    await page.inDialog('Einladung zurückziehen')
    expect(server.changes()).toEqual(['DELETE /api/v1/invites/9'])
  })

  it('show no card of open invitations while there are none', async () => {
    await page.show(<AccountsCard />)
    expect(document.getElementById('invites')).toBeNull()
  })
})

describe('the keys of all accounts', () => {
  it('list them in the row form of nexnotes and block one with the red word, after the question', async () => {
    server.answers['GET /api/v1/admin/api-keys'] = [
      { id: 1, account: 'anna', name: 'nexdeck', scope: 'read', prefix: 'npk_Ab3d', created_at: '2026-10-01T10:00:00Z', last_used_at: null, expires_at: null, blocked: false },
      { id: 2, account: 'tom', name: 'Scanner', scope: 'upload', prefix: 'npk_Sc12', created_at: '2026-10-01T10:00:00Z', last_used_at: null, expires_at: null, blocked: true },
    ]
    server.answers['POST /api/v1/admin/api-keys/1/block'] = { id: 1, blocked: true }
    await page.show(<AllApiKeysCard />)
    expect(page.text).toContain('API-Token aller Konten')
    const rows = [...document.querySelectorAll('[data-testid="admin-api-keys"] li')]
    expect(rows[0].textContent).toContain('anna · nexdeck')
    expect(rows[0].textContent).toContain('nur lesen · läuft nicht ab · noch nie benutzt')
    expect(rows[1].textContent).toContain('gesperrt')
    expect(page.button('Sperren', rows[1])).toBeUndefined()
    await page.click(page.button('Sperren', rows[0]))
    expect(server.changes()).toEqual([])
    await page.inDialog('Sperren')
    expect(server.changes()).toEqual(['POST /api/v1/admin/api-keys/1/block'])
  })

  it('say so when nobody has a key', async () => {
    server.answers['GET /api/v1/admin/api-keys'] = []
    await page.show(<AllApiKeysCard />)
    expect(document.querySelector('[data-testid="admin-api-keys-none"]')!.textContent).toBe('Noch kein Konto hat einen API-Token.')
  })
})

describe('the log', () => {
  const lines = [
    { time: '2026-11-23 10:00:01', level: 'ERROR', logger: 'nexpaper.ocr', message: 'Reading failed', request_id: 'a1b2c3', user: 'jule' },
    { time: '2026-11-23 09:59:00', level: 'INFO', logger: 'nexpaper.web', message: 'Started', request_id: null, user: null },
  ]

  beforeEach(() => {
    // The page asks for the newest 300 lines (the server gives no older ones page by page).
    server.answers['GET /api/v1/logs?limit=300'] = lines
    server.answers['GET /api/v1/logs?level=WARNING&limit=300'] = [lines[0]]
    server.answers['GET /api/v1/logs?search=a1b2c3&limit=300'] = [lines[0]]
    server.answers['GET /api/v1/logs/level'] = { mode: 'normal', until: null, fixed_by_env: false, modes: ['quiet', 'normal', 'detailed', 'trace'] }
    server.answers['DELETE /api/v1/logs'] = 204
  })

  /** The lines come a moment after the page (the search waits for typing to stop). */
  const rows = (count: number) => until(() => document.querySelectorAll('[data-testid="log-row"]').length === count && document.querySelectorAll('[data-testid="log-row"]'), `${count} lines`)

  it('has one bar with the chips, the search, the level of detail, download and clear', async () => {
    await page.show(<LogCard />)
    const bar = document.querySelector<HTMLElement>('[data-testid="log-bar"]')!
    expect([...bar.querySelectorAll('[role="radio"]')].map((chip) => chip.textContent)).toEqual(['Alle', 'INFO', 'WARNING', 'ERROR'])
    expect(bar.querySelector('[aria-checked="true"]')!.textContent).toBe('Alle')
    expect(bar.querySelector<HTMLInputElement>('[data-testid="log-search"]')!.placeholder).toBe('Im Text suchen …')
    expect(bar.querySelector<HTMLSelectElement>('[data-testid="log-mode"]')!.value).toBe('normal')
    expect(bar.querySelector('a[href="/api/v1/logs/download"]')).toBeTruthy()
    expect(page.button('Protokoll leeren', bar)).toBeTruthy()
  })

  it('shows the lines in a table of time, level, source, request and account, and message, and as cards on a phone', async () => {
    await page.show(<LogCard />)
    const found = await rows(2)
    const table = document.querySelector('[data-testid="log-table"]')!
    expect([...table.querySelectorAll('th')].map((cell) => cell.textContent)).toEqual(['Zeit', 'Stufe', 'Quelle', 'Nr. / Konto', 'Meldung'])
    expect([...found[0].querySelectorAll('td')].map((cell) => cell.textContent)).toEqual(['2026-11-23 10:00:01', 'ERROR', 'nexpaper.ocr', 'a1b2c3jule', 'Reading failed'])
    expect(document.querySelectorAll('[data-testid="log-card"]')).toHaveLength(2)
  })

  it('asks the server for the level of a chip, and a request number filters by it', async () => {
    await page.show(<LogCard />)
    await rows(2)
    await page.click(document.querySelector<HTMLElement>('[data-testid="log-level-WARNING"]'))
    await rows(1)
    expect(server.called('GET', '/api/v1/logs?level=WARNING&limit=300')).toBeTruthy()
    await page.click(document.querySelector<HTMLElement>('[data-testid="log-level-all"]'))
    await rows(2)
    await page.click(page.button('a1b2c3', document.querySelector<HTMLElement>('[data-testid="log-table"]')!))
    expect(document.querySelector<HTMLInputElement>('[data-testid="log-search"]')!.value).toBe('a1b2c3')
    await rows(1)
    expect(server.called('GET', '/api/v1/logs?search=a1b2c3&limit=300')).toBeTruthy()
  })

  it('clears the log only after the question', async () => {
    await page.show(<LogCard />)
    await rows(2)
    await page.click(page.button('Protokoll leeren'))
    expect(server.changes()).toEqual([])
    await page.inDialog('Abbrechen')
    expect(server.changes()).toEqual([])
    await page.click(page.button('Protokoll leeren'))
    await page.inDialog('Protokoll leeren')
    expect(server.changes()).toEqual(['DELETE /api/v1/logs'])
    expect(page.text).toContain('Nichts im Log.')
  })
})
