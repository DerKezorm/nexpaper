/**
 * Settings, Accounts and Log against a stand-in of the server: the accounts as the shared account module lays them out
 * (a row each with "Verwalten", the dialog with nexpaper's box "KI erlaubt" and the documents), the open invitations as a
 * card of their own, the keys of all accounts with a red word to block one; the log as one bar (level chips, search,
 * level of detail, download, clear after a question) above a table of its lines.
 */
import type { Me } from '../../api/client'
import { changeLanguage } from '../../i18n'
import { Page, Server } from '../../test/harness'
import { until } from '../../test/wait'
import { AccountsTab } from './AccountsTab'
import { AllApiKeysCard, LogCard } from './ServerCards'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: 'jule@example.com', language: 'de', email_confirmed: true,
  email_pending: '', oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.0.1',
  whats_new_seen: '0.0.1', session_stage: 'full', profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true, deadlines: true },
}
const auth = { status: 'signedIn', me: me as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()
const row = (over: Record<string, unknown>) => ({ ...me, locked: false, blocked: false, blocked_at: null, has_password: true, email_duplicate: false, self: false, documents: 1637, created_at: '2026-10-01T10:00:00Z', last_seen_at: null, ai_allowed: true, ...over })
const HOUR = 3600_000

beforeEach(async () => {
  await changeLanguage('de', false)
  auth.me = me
  server.answers = {
    'GET /api/v1/accounts': [
      row({ self: true, last_seen_at: new Date(Date.now() - 2 * HOUR).toISOString() }),
      row({ id: 2, name: 'tom', display_name: 'Tom', role: 'member', email: '', two_factor: false, ai_allowed: false }),
      row({ id: 3, name: 'lea', display_name: 'Lea', role: 'member', email: 'lea@example.com', sign_in: 'oidc', has_password: false, two_factor: false, blocked: true }),
      row({ id: 4, name: 'ben', display_name: '', role: 'member', two_factor: false, locked: true }),
    ],
    'GET /api/v1/invites': [],
    'GET /api/v1/oidc/admin/links': [{ account_id: 3, provider_id: 5, slug: 'authentik', label: 'authentik' }],
    'PUT /api/v1/accounts/2/permissions': { ai_allowed: true },
    'DELETE /api/v1/invites/9': 204,
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

/** The row of an account in the list (``Row`` of the kit, by its test id). */
const rowOf = (name: string) => document.querySelector<HTMLElement>(`[data-testid="account-row-${name}"]`)

/** "Verwalten" of a row: the dialog "Manage" of the shared account module. */
async function manage(name: string): Promise<HTMLElement> {
  await page.click(page.button('Verwalten', rowOf(name)!))
  return page.dialog!
}

describe('the accounts', () => {
  it("stand one per row as the shared account module lays them out: picture, name, badges, username and address, \"Verwalten\"", async () => {
    await page.show(<AccountsTab />)
    expect(page.text).toContain('Konten')
    expect(document.querySelector('table')).toBeNull()
    expect(rowOf('jule')!.textContent).toContain('Jule')
    expect(rowOf('jule')!.textContent).toContain('jule · jule@example.com')
    expect(rowOf('jule')!.textContent).toContain('Betreiber')
    // An account through a provider shows its provider, a blocked one says so; one held back by the brake too.
    expect(rowOf('lea')!.textContent).toContain('authentik')
    expect(rowOf('lea')!.textContent).toContain('Gesperrt')
    expect(page.button('Verwalten', rowOf('tom')!)).toBeTruthy()
    expect(document.querySelector('[role="menu"]')).toBeNull()
  })

  it('switch the AI for one account with the box under "Rechte", and name the documents of its own vault', async () => {
    await page.show(<AccountsTab />)
    const dialog = await manage('tom')
    expect(dialog.textContent).toContain('Rechte')
    expect(dialog.textContent).toContain('Dokumente')
    expect(dialog.textContent).toContain('1.637')
    const box = [...dialog.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')][0]!
    expect(box.checked).toBe(false)
    await page.click(box)
    expect(server.called('PUT', '/api/v1/accounts/2/permissions')!.body).toEqual({ ai_allowed: true })
  })

  it('keep every act of before in the dialog, the link for a new password among them, and none of them at the own account', async () => {
    await page.show(<AccountsTab />)
    const own = await manage('jule')
    for (const word of ['Konto löschen', 'Sperren', 'Zum Mitglied machen']) expect(page.button(word, own)).toBeUndefined()
    await page.click(page.button('Schließen', own))
    const theirs = await manage('tom')
    for (const word of ['Zum Betreiber machen', 'Überall abmelden', 'Sperren', 'Konto löschen']) expect(page.button(word, theirs), word).toBeTruthy()
    expect([...theirs.querySelectorAll('button')].some((button) => /Link/.test(button.textContent ?? ''))).toBe(true)
  })

  it('invite a person with the button above the list', async () => {
    await page.show(<AccountsTab />)
    const card = document.getElementById('accounts')!
    const invite = page.button('Person einladen', card) ?? [...card.querySelectorAll('button')].find((b) => /einladen/i.test(b.textContent ?? ''))
    expect(invite).toBeTruthy()
    await page.click(invite)
    expect(page.dialog).toBeTruthy()
  })

  it('show the open invitations as a card of their own, and withdraw one only after the question', async () => {
    server.answers['GET /api/v1/invites'] = [{ id: 9, email: 'neu@example.com', display_name: '', by: 'jule', created_at: '2026-10-13T10:00:00Z', expires_at: '2026-10-20T10:00:00Z', expired: false, mailed: false }]
    await page.show(<AccountsTab />)
    const card = document.getElementById('open-invites')!
    expect(card.textContent).toContain('neu@example.com')
    expect(document.getElementById('accounts')!.contains(card)).toBe(false)
    await page.click([...card.querySelectorAll('button')][0])
    expect(server.changes()).toEqual([])
    const confirm = [...page.dialog!.querySelectorAll('button')].filter((button) => button.textContent?.trim()).pop()
    await page.click(confirm)
    expect(server.changes()).toEqual(['DELETE /api/v1/invites/9'])
  })

  it('show no card of open invitations while there are none', async () => {
    await page.show(<AccountsTab />)
    expect(document.getElementById('open-invites')).toBeNull()
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
