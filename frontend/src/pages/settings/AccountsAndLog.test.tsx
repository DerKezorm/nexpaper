/**
 * Server › Accounts and Log against a stand-in of the server: the accounts as the shared account module lays them out
 * (a row each with "Verwalten", the dialog with nexpaper's box "KI erlaubt" and the documents), the open invitations as a
 * card of their own, "Was du siehst"; the keys of all accounts in the module's table (schluessel 1.0.0) with a small red
 * "Sperren"; the module's log (log 1.0.0) under nexpaper's route: one bar (level filter, search, level of detail,
 * download, clear after a question) above a table of its lines.
 */
import type { Me } from '../../api/client'
import { changeLanguage } from '../../i18n'
import { Page, Server } from '../../test/harness'
import { until } from '../../test/wait'
import { AccountsTab } from './AccountsTab'
import { AllKeys } from './KeysCards'
import { LogArea } from './ServerCards'

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

  it('switch the AI for one account with the module\'s box "KI erlaubt" under "Rechte", and name the documents of its own vault', async () => {
    await page.show(<AccountsTab />)
    const dialog = await manage('tom')
    expect(dialog.textContent).toContain('Rechte')
    expect(dialog.textContent).toContain('Dokumente')
    expect(dialog.textContent).toContain('1.637')
    const box = [...dialog.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')][0]!
    expect(document.querySelector(`label[for="${box.id}"]`)!.textContent).toBe('KI erlaubt')
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

  it('set the storage limit of an account in GB with the operator\'s password, and show what its documents take', async () => {
    server.answers['GET /api/v1/accounts'] = [row({ self: true }), row({ id: 2, name: 'tom', display_name: 'Tom', role: 'member', storage_limit: null, storage_used: 1_500_000_000 })]
    server.answers['PUT /api/v1/accounts/2/storage-limit'] = row({ id: 2, name: 'tom', storage_limit: 2 * 1024 ** 3 })
    await page.show(<AccountsTab />)
    const dialog = await manage('tom')
    expect(dialog.querySelector('[data-testid="fact-storage"]')!.textContent).toContain('1,5 GB, ohne Grenze')
    await page.click(page.button('Speichergrenze', dialog))
    const limit = document.querySelector<HTMLElement>('[data-testid="limit-dialog"]')!
    expect(limit.textContent).toContain('Speichergrenze für Tom')
    expect(limit.textContent).toContain('Ist die Grenze erreicht, nimmt nexpaper keine neuen Dateien dieses Kontos mehr an')
    const inputs = [...limit.querySelectorAll<HTMLInputElement>('input')]
    await page.type(inputs.find((input) => input.type === 'number')!, '2')
    await page.type(inputs.find((input) => input.type === 'password')!, 'the own password')
    await page.click(page.button('Speichern', limit))
    expect(server.called('PUT', '/api/v1/accounts/2/storage-limit')!.body).toEqual({ limit: 2 * 1024 ** 3, current_password: 'the own password' })
  })

  it('bring a deleted account back within its 30 days, and offer nothing else for it', async () => {
    const deleted = new Date(Date.now() - 2 * 24 * HOUR).toISOString()
    const purge = new Date(Date.now() + 28 * 24 * HOUR).toISOString()
    server.answers['GET /api/v1/accounts'] = [row({ self: true }), row({ id: 2, name: 'tom', display_name: 'Tom', role: 'member', deleted_at: deleted, purge_at: purge })]
    server.answers['POST /api/v1/accounts/2/restore'] = row({ id: 2, name: 'tom' })
    await page.show(<AccountsTab />)
    expect(rowOf('tom')!.textContent).toContain('Gelöscht')
    const dialog = await manage('tom')
    for (const word of ['Sperren', 'Konto löschen', 'Zum Betreiber machen']) expect(page.button(word, dialog), word).toBeUndefined()
    await page.click(page.button('Zurückholen', dialog))
    expect(server.changes()).toEqual([])
    const confirm = document.querySelector<HTMLElement>('[data-testid="manage-confirm"]')!
    await page.type(confirm.querySelector<HTMLInputElement>('input[type="password"]'), 'the own password')
    await page.click(page.button('Zurückholen', confirm))
    expect(server.called('POST', '/api/v1/accounts/2/restore')!.body).toEqual({ current_password: 'the own password' })
  })

  it('say under the list what the operator sees and never sees, in nexpaper\'s sentence', async () => {
    await page.show(<AccountsTab />)
    const card = document.querySelector('[data-card="what-you-see"]') ?? [...document.querySelectorAll('[data-card]')].find((found) => found.textContent?.includes('Was du siehst'))
    expect(card!.textContent).toContain('aber nie die Dokumente in den Tresoren anderer')
    expect(document.querySelector('[data-card="accounts"]')!.compareDocumentPosition(card!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('show no card of open invitations while there are none', async () => {
    await page.show(<AccountsTab />)
    expect(document.getElementById('open-invites')).toBeNull()
  })
})

describe('the keys of all accounts', () => {
  const key = (over: Record<string, unknown>) => ({
    id: 1, kind: 'api', name: 'nexdeck', right: 'read', options: {}, areas: null, created_at: '2026-10-01T10:00:00Z', last_used_at: null, expires_at: null,
    expired: false, expiring: false, blocked: false, legacy: null, program: false, account: { id: 2, name: 'anna', display_name: 'Anna', out: false }, ...over,
  })

  it('list them in the module\'s table under nexpaper\'s route, in nexpaper\'s words, and block one after the question', async () => {
    server.answers['GET /api/v1/connections/admin/keys'] = { keys: [key({}), key({ id: 2, name: 'Scanner', right: 'upload', blocked: true, account: { id: 3, name: 'tom', display_name: 'Tom', out: false } })] }
    server.answers['POST /api/v1/connections/admin/keys/1/block'] = key({ blocked: true })
    await page.show(<AllKeys />)
    const card = document.querySelector<HTMLElement>('[data-card="all-api-keys"]')!
    expect(card.querySelector('h2')!.textContent).toBe('API-Schlüssel aller Konten')
    const table = card.querySelector<HTMLElement>('table')!
    const rows = [...table.querySelectorAll<HTMLElement>('[data-testid="all-keys-row"]')]
    expect(rows[0].textContent).toContain('Anna')
    expect(rows[0].textContent).toContain('nexdeck')
    expect(rows[0].textContent).toContain('Nur lesen')
    expect(rows[1].textContent).toContain('Nur hochladen')
    // Never the start of a key for the operator (E36).
    expect(card.textContent).not.toContain('npk_')
    expect(rows[1].getAttribute('data-blocked')).toBe('true')
    expect(page.button('Sperren', rows[1])).toBeUndefined()
    expect(page.button('Entsperren', rows[1])).toBeTruthy()
    const block = page.button('Sperren', rows[0])!
    expect([block.dataset.kind, block.dataset.size]).toEqual(['danger', 'sm'])
    await page.click(block)
    expect(server.changes()).toEqual([])
    await page.inDialog('Sperren')
    expect(server.changes()).toEqual(['POST /api/v1/connections/admin/keys/1/block'])
  })

  it('say so when nobody has a key', async () => {
    server.answers['GET /api/v1/connections/admin/keys'] = { keys: [] }
    await page.show(<AllKeys />)
    expect(document.querySelector('[data-card="all-api-keys"]')!.textContent).toContain('Noch kein Konto hat einen API-Schlüssel.')
  })
})

describe('the log', () => {
  const lines = [
    { time: '2026-11-23 10:00:01', level: 'ERROR', logger: 'nexpaper.ocr', message: 'Reading failed', request_id: 'a1b2c3', user: 'jule', at: null },
    { time: '2026-11-23 09:59:00', level: 'INFO', logger: 'nexpaper.web', message: 'Started', request_id: null, user: null, at: null },
  ]

  beforeEach(() => {
    // The module asks page by page (`limit` 200, `offset`) under nexpaper's route.
    server.answers['GET /api/v1/logs?limit=200&offset=0'] = lines
    server.answers['GET /api/v1/logs?level=WARNING&limit=200&offset=0'] = [lines[0]]
    server.answers['GET /api/v1/logs?search=a1b2c3&limit=200&offset=0'] = [lines[0]]
    server.answers['GET /api/v1/logs/level'] = { mode: 'normal', until: null, fixed_by_env: false, variable: 'NEXPAPER_LOG_LEVEL', modes: ['quiet', 'normal', 'detailed', 'trace'], durations: [30, 60, 120, 480] }
    server.answers['DELETE /api/v1/logs'] = 204
  })

  /** The lines of the table (the search waits for typing to stop). */
  const rows = (count: number) =>
    until(() => {
      const found = document.querySelectorAll('[data-testid="log-table"] tbody [data-testid="log-row"]')
      return found.length === count && found
    }, `${count} lines`)

  it('has one bar with the level filter, the search, the level of detail, download and clear, and nexpaper\'s word in the line', async () => {
    await page.show(<LogArea />)
    const card = document.querySelector<HTMLElement>('[data-card="log"]')!
    expect(card.textContent).toContain('Nie Inhalte von Dokumenten')
    const bar = document.querySelector<HTMLElement>('[data-testid="log-bar"]')!
    expect([...bar.querySelectorAll('[role="radio"]')].map((chip) => chip.textContent)).toEqual(['Alle', 'INFO', 'WARNING', 'ERROR'])
    expect(bar.querySelector('[aria-checked="true"]')!.textContent).toBe('Alle')
    expect(bar.querySelector<HTMLInputElement>('[data-testid="log-search"]')).toBeTruthy()
    expect(bar.querySelector<HTMLSelectElement>('[data-testid="log-mode"]')!.value).toBe('normal')
    expect(bar.querySelector('a[href="/api/v1/logs/download"]')).toBeTruthy()
    expect(bar.querySelector<HTMLElement>('[data-testid="log-clear"]')!.dataset.kind).toBe('danger')
  })

  it('shows the lines in a table of time, level, source, request and account, and message', async () => {
    await page.show(<LogArea />)
    const found = await rows(2)
    const table = document.querySelector('[data-testid="log-table"] table')!
    expect([...table.querySelectorAll('th')].map((cell) => cell.textContent)).toEqual(['Zeit', 'Stufe', 'Quelle', 'Anfrage / Konto', 'Meldung'])
    const cells = [...found[0].querySelectorAll('td')].map((cell) => cell.textContent)
    expect(cells[0]).toBe('2026-11-23 10:00:01')
    expect(cells[1]).toBe('ERROR')
    expect(cells[2]).toBe('nexpaper.ocr')
    expect(cells[3]).toContain('a1b2c3')
    expect(cells[3]).toContain('jule')
    expect(cells[4]).toBe('Reading failed')
  })

  it('asks the server for the level of a filter, and a request number filters by it', async () => {
    await page.show(<LogArea />)
    await rows(2)
    await page.click(document.querySelector<HTMLElement>('[data-testid="log-level-WARNING"]'))
    await rows(1)
    expect(server.called('GET', '/api/v1/logs?level=WARNING&limit=200&offset=0')).toBeTruthy()
    await page.click(document.querySelector<HTMLElement>('[data-testid="log-level-all"]'))
    await rows(2)
    await page.click(document.querySelector<HTMLElement>('[data-testid="log-table"] tbody [data-testid="log-request"]'))
    expect(document.querySelector<HTMLInputElement>('[data-testid="log-search"]')!.value).toBe('a1b2c3')
    await rows(1)
    expect(server.called('GET', '/api/v1/logs?search=a1b2c3&limit=200&offset=0')).toBeTruthy()
  })

  it('clears the log only after the question', async () => {
    await page.show(<LogArea />)
    await rows(2)
    await page.click(document.querySelector<HTMLElement>('[data-testid="log-clear"]'))
    expect(server.changes()).toEqual([])
    await page.inDialog('Abbrechen')
    expect(server.changes()).toEqual([])
    await page.click(document.querySelector<HTMLElement>('[data-testid="log-clear"]'))
    await page.inDialog('Protokoll leeren')
    expect(server.changes()).toEqual(['DELETE /api/v1/logs'])
    expect(page.text).toContain('Nichts im Log.')
  })
})
