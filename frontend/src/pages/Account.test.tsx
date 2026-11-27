/**
 * My account in the interface, against a stand-in of the server: the seven tabs in their order and in the
 * address, the mail address with the link it waits for (the password asked again, the old address standing until the
 * link is opened, withdrawn on request), the devices as in nexnotes (pairing by a code in a dialog, disconnecting after a
 * question), API keys in the form of nexnotes' tokens (off until the operator allows them, one dialog to make one, the
 * key shown once) and the choices of the look.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

import type { Me } from '../api/client'
import '../i18n'
import { changeLanguage } from '../i18n'
import { idle } from '../test/wait'
import { SettingsRoutes } from '../test/settings'

const baseMe: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: '', language: 'de',
  email_confirmed: false, email_pending: '', oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8,
  avatar: null, version: '0.0.1', whats_new_seen: '0.0.1', session_stage: 'full', second_factor_required: false, mail: true,
  profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true, deadlines: true },
}
const auth = { status: 'signedIn', me: baseMe as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth, safeNext: (next: string | null) => next ?? '/' }))

type Call = { method: string; url: string; body: Record<string, unknown> | undefined }
let calls: Call[] = []
let answers: Record<string, unknown> = {}
let fails: Record<string, { status: number; code: string }> = {}

function serve(): void {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, url, body })
      const failed = fails[`${method} ${url}`]
      if (failed) return new Response(JSON.stringify({ detail: { code: failed.code } }), { status: failed.status, headers: { 'Content-Type': 'application/json' } })
      const found = answers[`${method} ${url}`]
      if (found === 204) return new Response(null, { status: 204 })
      return new Response(JSON.stringify(found ?? {}), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }),
  )
}

let root: Root
let box: HTMLDivElement

async function show(at = '/settings'): Promise<void> {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  box = document.createElement('div')
  document.body.appendChild(box)
  root = createRoot(box)
  await act(async () => root.render(<MemoryRouter initialEntries={[at]}><SettingsRoutes /></MemoryRouter>))
  await idle()
}

function button(text: string, within: ParentNode = box): HTMLButtonElement | undefined {
  return [...within.querySelectorAll<HTMLButtonElement>('button')].find((item) => item.textContent?.trim() === text || item.getAttribute('aria-label') === text)
}

async function click(target: HTMLElement | undefined): Promise<void> {
  expect(target).toBeTruthy()
  await act(async () => target!.click())
  await idle()
}

async function type(input: HTMLInputElement | null | undefined, value: string): Promise<void> {
  expect(input).toBeTruthy()
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), 'value')!.set!
  await act(async () => {
    setter.call(input, value)
    input!.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await idle()
}

function field(label: string, within: ParentNode = box): HTMLInputElement | null {
  const found = [...within.querySelectorAll('label')].find((item) => item.textContent?.startsWith(label))
  if (!found) return null
  // The kit's fields name their input with `for`; older ones hold it inside the label.
  return found.querySelector('input') ?? (found.htmlFor ? document.getElementById(found.htmlFor) as HTMLInputElement | null : null)
}

/** The dialog open last (the kit's dialogs stand outside the page's box). */
function lastDialog(): HTMLElement {
  const dialogs = document.querySelectorAll<HTMLElement>('[role="dialog"]')
  return dialogs[dialogs.length - 1]!
}

beforeEach(async () => {
  await changeLanguage('de', false)
  auth.me = baseMe
  auth.setMe.mockClear()
  answers = {
    'GET /api/v1/connections/mcp/requests?status=waiting': [],
    // The card "Geräte" of the shared module geraete 0.1.0 (`/api/v1/app-devices`).
    'GET /api/v1/app-devices': { devices: [], max: 30, app_store_url: 'https://apps.apple.com/app/nexpaper/id6824032969', has_app: true },
    'GET /api/connect/partners': [],
    'GET /api/v1/auth/methods': { password: true, providers: [], passkeys: true },
    'GET /api/v1/auth/passkeys': [],
    'GET /api/v1/auth/sessions': [],
    'GET /api/v1/locales': [],
    'GET /api/v1/api-keys': { allowed: false, keys: [] },
    'GET /api/v1/connections/keys': listing(false),
    'GET /api/v1/devices': [],
    'GET /api/v1/push': { key: '', devices: [] },
    'GET /api/v1/ai': { provider: 'none', to: '', model: '', mine: true, allowed: true, available: false },
  }
  fails = {}
  serve()
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
  vi.unstubAllGlobals()
})

/** The account's keys as the key module lists them (`GET /api/v1/connections/keys`, schluessel 1.0.0) with nexpaper's
 * kind: read or upload, 30, 90, 365 days or never, a year from the start, never for a key that only uploads. */
function listing(api: boolean, keys: unknown[] = []) {
  return {
    app: 'nexpaper', api, mcp: null, programs: false, api_path: '/api/v1', mcp_path: null, keys_wait: false, warn_days: 7, address: 'https://paper.example.com',
    kinds: [{
      id: 'api', prefix: 'npk_', creatable: true, editable: true, rights: ['read', 'upload'], default_right: 'read', options: [], areas: null, areas_required: false,
      expiry_days: [30, 90, 365, null], default_days: 365, default_days_by_right: { upload: null }, max_keys: 20, count: keys.length, name_max: 100,
    }],
    keys,
  }
}
function keyOf(id: number, name: string, right: string, prefix: string) {
  return { id, kind: 'api', name, right, options: {}, areas: null, prefix, created_at: '2026-10-08T10:00:00Z', last_used_at: null, expires_at: null, expired: false, expiring: false, blocked: false, legacy: null, program: false }
}

/** The names in the group "Mein Konto" of the settings' navigation, in their order. */
function accountAreas(): (string | undefined)[] {
  return [...box.querySelectorAll('[aria-labelledby="settings-group-account"] a')].map((item) => item.textContent?.trim())
}
/** The name of the area the navigation marks as the current one. */
function current(): string | undefined {
  return box.querySelector('[data-testid^="settings-nav-"][aria-current="page"]')?.textContent?.trim()
}

describe('the areas of my account', () => {
  it('are those of nexnotes in its order, then nexpaper\'s own, and the profile opens first', async () => {
    await show('/settings')
    // Plan "Einstellungen": Profil, Sicherheit, Darstellung, nexpaper's own (Hochladen, KI), Benachrichtigungen, Verbindungen.
    expect(accountAreas()).toEqual(['Profil', 'Sicherheit', 'Darstellung', 'Hochladen', 'KI', 'Benachrichtigungen', 'Verbindungen'])
    expect(current()).toBe('Profil')
    expect(box.querySelector('h1')!.textContent).toBe('Profil')
    // "Über nexpaper" at the end, outside the groups, as "Über nexnotes".
    expect(box.querySelector('[data-testid="settings-nav-about"]')!.textContent).toContain('Über nexpaper')
  })

  it('stand in the address, and the addresses of before lead to their area', async () => {
    await show('/konto?tab=devices')
    expect(current()).toBe('Verbindungen')
    expect(box.querySelector('[data-testid="settings-area-connections"]')).toBeTruthy()
    expect(box.textContent).toContain('iPhone oder iPad verbinden')
    act(() => root.unmount())
    box.remove()
    // The slug of before, "Erinnerungen", leads to "Benachrichtigungen" (E1); the deadlines' own cards have their test.
    auth.me = { ...baseMe, profile: { ...baseMe.profile, deadlines: false } }
    await show('/settings/reminders')
    expect(current()).toBe('Benachrichtigungen')
    expect(box.querySelector('[data-testid="settings-area-notifications"]')).toBeTruthy()
    auth.me = baseMe
    act(() => root.unmount())
    box.remove()
    await show('/konto?tab=nonsense')
    expect(current()).toBe('Profil')
    act(() => root.unmount())
    box.remove()
    await show('/settings/nonsense')
    expect(current()).toBe('Profil')
  })

  it('come in English too, with the same seven', async () => {
    await changeLanguage('en', false)
    await show('/settings')
    expect(accountAreas()).toEqual(['Profile', 'Security', 'Appearance', 'Upload', 'AI', 'Notifications', 'Connections'])
  })

  it("lay out Security as the shared account module's parts in its order, and sign out everywhere else after a question", async () => {
    auth.me = { ...baseMe, password_changed_at: '2026-11-20T08:00:00Z' }
    await show('/settings/security')
    // One card "Sicherheit" (konten 1.1.0, as nexnotes), the module's parts (PAGES.security) as its boxes in its order.
    const security = box.querySelector<HTMLElement>('[data-card="security"]')!
    expect(security.querySelector('h2')!.textContent).toBe('Sicherheit')
    const parts = [...security.querySelectorAll('[data-testid]')].map((part) => part.getAttribute('data-testid'))
    const order = ['password-row', 'second-factor', 'recovery-codes-part', 'passkeys-part', 'sessions-part', 'security-newSignInMail']
    expect(parts.filter((id) => order.includes(id!))).toEqual(order)
    expect(box.querySelector('[data-testid="password-row"]')!.textContent).toContain('Zuletzt geändert am 20.11.2026')
    const card = box.querySelector<HTMLElement>('[data-testid="sessions-part"]')!
    expect(card.textContent).toContain('Angemeldete Geräte')
    const everywhere = button('Überall sonst abmelden', card)!
    expect([everywhere.dataset.kind, everywhere.dataset.icon]).toEqual(['danger', 'LogOut'])
    await click(everywhere)
    expect(calls.some((call) => call.url === '/api/v1/auth/logout-all')).toBe(false)
    await click(button('Überall sonst abmelden', document.body.querySelector<HTMLElement>('[role="dialog"]')!))
    expect(calls.some((call) => call.url === '/api/v1/auth/logout-all')).toBe(true)
  })

  it('show the AI of the shared module: not ready while no AI is set up, and why (ki 0.1.0, E61)', async () => {
    answers['GET /api/v1/me/ai'] = { available: false, reason: 'ai_off', enabled: false, allowed: true, mine: true, mode: 'shared', api: '', model: '', local: false, to: '' }
    answers['GET /api/v1/me/ai/events'] = []
    await show('/settings/ai')
    const card = box.querySelector('[data-card="ai-me"]')!
    const own = field('KI für mich', card)!
    expect([own.type, own.getAttribute('role'), own.checked]).toEqual(['checkbox', null, true])
    expect(card.querySelector('[data-testid="ki-me-state"]')!.textContent).toContain('Auf diesem Server ist keine KI eingerichtet oder erlaubt.')
    // nexpaper's card says what goes out, after the module's cards.
    expect(box.querySelector('[data-card="ai-what"]')!.textContent).toContain('der erkannte Text der ersten zwei Seiten')
    expect(box.querySelector('[data-card="ai-events"]')).toBeTruthy()
  })

  it('switch the own AI off through the module, for this account on every device', async () => {
    answers['GET /api/v1/me/ai'] = { available: true, reason: null, enabled: true, allowed: true, mine: true, mode: 'shared', api: 'openai', model: 'llama3.1:8b', local: true, to: '' }
    answers['GET /api/v1/me/ai/events'] = []
    answers['PUT /api/v1/me/ai'] = { available: false, reason: 'ai_switched_off', enabled: true, allowed: true, mine: false, mode: 'shared', api: 'openai', model: 'llama3.1:8b', local: true, to: '' }
    await show('/settings/ai')
    const own = field('KI für mich')!
    expect(own.checked).toBe(true)
    await click(own)
    expect(calls.find((call) => call.url === '/api/v1/me/ai' && call.method === 'PUT')!.body).toEqual({ mine: false })
  })

  it('end the profile with signing out, the one place for it', async () => {
    await show('/settings/profile')
    const card = box.querySelector('[data-testid="sign-out-card"]')!
    expect(card.querySelector('[data-card="sign-out"]')).toBeTruthy()
    // The module's sentence with nexpaper's word for its things (konten 1.1.0, `SignOutCard`).
    expect(card.textContent).toContain('Beendet deine Sitzung in diesem Browser. Deine Dokumente bleiben, wie sie sind.')
    expect(button('Abmelden', card)).toBeTruthy()
    // The last card of the profile.
    const cards = [...box.querySelectorAll('[data-card]')].map((item) => item.getAttribute('data-card'))
    expect(cards.at(-1)).toBe('sign-out')
  })
})

describe('the mail address', () => {
  it('asks for the password and waits for the link: the old address stays until it is opened', async () => {
    auth.me = { ...baseMe, email: 'old@example.com', email_confirmed: true }
    answers['PUT /api/v1/me/profile'] = { ...baseMe, email: 'old@example.com', email_confirmed: true, email_pending: 'new@example.com' }
    await show()
    expect(field('E-Mail')!.value).toBe('old@example.com')
    // A confirmed address needs no box (konten 1.1.0, E23).
    expect(box.querySelector('[data-testid="email-unconfirmed"]')).toBeNull()
    // The shared account module's profile: one "Speichern" for all; a new address asks for the password once.
    expect(button('Speichern')!.disabled).toBe(true)
    await type(field('E-Mail'), 'new@example.com')
    await click(button('Speichern'))
    expect(calls.some((call) => call.method === 'PUT' && call.url === '/api/v1/me/profile')).toBe(false)
    // The password field in the account module's word.
    expect(field('Passwort', lastDialog())!.type).toBe('password')
    await type(field('Passwort', lastDialog()), 'the own password')
    await click(button('Speichern', lastDialog()))
    expect(calls.find((call) => call.method === 'PUT' && call.url === '/api/v1/me/profile')!.body).toEqual({ email: 'new@example.com', password: 'the own password' })
    expect(auth.setMe).toHaveBeenCalled()
  })

  it('shows what waits, and withdraws it', async () => {
    auth.me = { ...baseMe, email: 'old@example.com', email_confirmed: true, email_pending: 'new@example.com' }
    answers['GET /api/v1/auth/me'] = { ...baseMe, email: 'old@example.com', email_confirmed: true }
    await show()
    const pending = box.querySelector('[data-testid="mail-pending"]')!
    expect(pending.textContent).toContain('Wartet auf Bestätigung: new@example.com')
    expect(field('E-Mail')!.value).toBe('old@example.com')
    await click(button('Zurücknehmen', pending))
    expect(calls.some((call) => call.method === 'DELETE' && call.url === '/api/v1/me/email/pending')).toBe(true)
  })

  it('marks an address nobody confirmed and offers "Link schicken"', async () => {
    auth.me = { ...baseMe, email: 'typed@example.com', email_confirmed: false, mail_links: true, email_needs_proof: true }
    answers['POST /api/v1/me/email/prove'] = { ...baseMe, email: 'typed@example.com', email_confirmed: false, email_pending: 'typed@example.com' }
    await show()
    // The module's box (konten 1.1.0, `UnconfirmedEmailBox`, where the server says `email_needs_proof`, E23).
    const unconfirmed = box.querySelector<HTMLElement>('[data-testid="email-unconfirmed"]')!
    expect(unconfirmed.textContent).toContain('Adresse noch nicht bestätigt')
    expect(unconfirmed.textContent).toContain('typed@example.com')
    const send = button('Link schicken', unconfirmed)!
    expect([send.dataset.kind, send.dataset.size, send.dataset.icon]).toEqual(['secondary', 'sm', 'Send'])
    // The link goes to the address there is (profiles.prove_email).
    await click(send)
    expect(calls.some((call) => call.method === 'POST' && call.url === '/api/v1/me/email/prove')).toBe(true)
    expect(auth.setMe).toHaveBeenCalled()
  })

  it('says what stands in the way, in words', async () => {
    fails['PUT /api/v1/me/profile'] = { status: 409, code: 'mail_off' }
    await show()
    await type(field('E-Mail'), 'new@example.com')
    await click(button('Speichern'))
    await type(lastDialog().querySelector<HTMLInputElement>('input[type="password"]'), 'the own password')
    await click(button('Speichern', lastDialog()))
    expect(document.body.textContent).toContain('Es ist kein Mailserver eingetragen.')
  })
})

describe('devices and apps', () => {
  /** The open dialog (the kit's dialogs stand outside the page's box). */
  const dialog = () => document.body.querySelector<HTMLElement>('[role="dialog"]')
  async function choose(select: HTMLSelectElement | null | undefined, value: string): Promise<void> {
    expect(select).toBeTruthy()
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!
    await act(async () => {
      setter.call(select, value)
      select!.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await idle()
  }
  /** The key module's fields of its dialog (schluessel 1.0.0). */
  const expiry = () => dialog()!.querySelector<HTMLSelectElement>('[data-testid="key-expiry"]')!
  const right = (value: 'read' | 'upload') => dialog()!.querySelector<HTMLButtonElement>(`[data-testid="key-right-${value}"]`)!
  const made = () => calls.find((call) => call.method === 'POST' && call.url === '/api/v1/connections/keys')
  /** The connections in the plan's order (Verbindungen 1, 2, 4, 5). */
  const cards = () => [...box.querySelectorAll('[data-testid="settings-area-connections"] section[data-card]')].map((card) => card.getAttribute('data-card'))

  it('pairs a device in the window of the shared module, with a QR code the published iPhone app reads too', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const link = 'nexpaper://pair?server=https%3A%2F%2Fpaper.example.com&code=KRAF-T7Q2-K9XW&address=https%3A%2F%2Fpaper.example.com&pairing=p1&secret=s'
      answers['POST /api/v1/app-pairing'] = {
        id: 'p1', secret: 's', code: 'KRAF-T7Q2-K9XW', link, address: 'https://paper.example.com',
        expires_at: new Date(Date.now() + 300_000).toISOString(), qr_svg: '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
        app_store_url: 'https://apps.apple.com/app/nexpaper/id6824032969',
      }
      answers['GET /api/v1/app-pairing/p1'] = { state: 'waiting', device: null }
      await show('/settings/connections')
      const card = box.querySelector<HTMLElement>('[data-card="devices"]')!
      expect(card.querySelector('h2')!.textContent).toBe('Geräte')
      expect(card.querySelector('[data-testid="devices-none"]')!.textContent).toBe('Noch kein Gerät verbunden.')
      const pair = button('iPhone oder iPad verbinden', card)!
      expect([pair.dataset.kind, pair.dataset.icon]).toEqual(['primary', 'Smartphone'])
      await click(pair)
      // The module's pairing (G58): the link holds `pair` with `server` and `code` for nexpaper-ios 1.3.
      expect(calls.some((call) => call.method === 'POST' && call.url === '/api/v1/app-pairing')).toBe(true)
      expect(calls.some((call) => call.method === 'POST' && call.url === '/api/v1/devices/app-pairing')).toBe(false)
      expect(dialog()!.textContent).toContain('KRAF-T7Q2-K9XW')
      // Once the device took the code, the window says so and the list comes again.
      const phone = { id: 'a'.repeat(32), name: 'iPhone von jule', kind: 'ios', model: null, system: null, app_version: null, via: 'code', created_at: '2026-10-08T10:00:00Z', last_seen_at: null, push: false }
      answers['GET /api/v1/app-pairing/p1'] = { state: 'used', device: phone }
      answers['GET /api/v1/app-devices'] = { devices: [phone], max: 30, app_store_url: null, has_app: true }
      await act(async () => vi.advanceTimersByTime(2100))
      await idle()
      expect(dialog()!.querySelector('[data-testid="pair-paired"]')).toBeTruthy()
    } finally {
      vi.useRealTimers()
    }
  })

  it('lists the connected devices and disconnects one only after the question', async () => {
    const id = 'd'.repeat(32)
    const ipad = { id, name: 'iPad von jule', kind: 'ipados', model: null, system: null, app_version: null, via: 'icloud', created_at: '2026-10-08T10:00:00Z', last_seen_at: null, push: false }
    answers['GET /api/v1/app-devices'] = { devices: [ipad], max: 30, app_store_url: null, has_app: true }
    answers[`DELETE /api/v1/app-devices/${id}`] = 204
    await show('/settings/connections')
    const row = box.querySelector<HTMLElement>('[data-card="devices"] [data-testid="device-row"]')!
    expect(row.textContent).toContain('iPad von jule')
    expect(row.textContent).toContain('über iCloud übernommen')
    const sent = () => calls.some((call) => call.method === 'DELETE' && call.url === `/api/v1/app-devices/${id}`)
    await click(button('iPad von jule trennen', row) ?? button('Trennen', row))
    expect(sent()).toBe(false)
    answers['GET /api/v1/app-devices'] = { devices: [], max: 30, app_store_url: null, has_app: true }
    await click(button('Trennen', dialog()!))
    expect(sent()).toBe(true)
    expect(box.querySelector('[data-card="devices"] [data-testid="device-row"]')).toBeNull()
  })

  it('makes a key that only uploads for the iPhone shortcut, once, and shows the address and the header to copy', async () => {
    answers['GET /api/v1/shortcut'] = { link: '', address: 'https://paper.example.com', upload_url: 'https://paper.example.com/api/v1/documents?source=share' }
    answers['GET /api/v1/api-keys'] = { allowed: true, keys: [] }
    answers['GET /api/v1/connections/keys'] = listing(true)
    answers['POST /api/v1/api-keys'] = {
      key: { id: 5, name: 'iPhone-Kurzbefehl', scope: 'upload', prefix: 'npk_Xy12', created_at: '2026-10-08T10:00:00Z', last_used_at: null, expires_at: null, blocked: false },
      secret: 'npk_' + 'k'.repeat(43),
    }
    await show('/konto?tab=devices')
    const steps = box.querySelector('[data-testid="shortcut-steps"]')!
    expect(steps.textContent).toContain('Aktion „Inhalte von URL abrufen“')
    expect(box.querySelector('[data-testid="shortcut-link"]')).toBeNull()
    expect(box.querySelector('[data-testid="shortcut-warning"]')!.textContent).toContain('Trag deinen Schlüssel nie in einen Kurzbefehl ein, den du mit anderen teilst')
    answers['GET /api/v1/connections/keys'] = listing(true, [keyOf(5, 'iPhone-Kurzbefehl', 'upload', 'npk_Xy12')])
    // The old way of the shortcut's key stays (nexpaper-ios and the shortcut must not notice).
    await click(button('Schlüssel für den Kurzbefehl'))
    expect(calls.find((call) => call.method === 'POST' && call.url === '/api/v1/api-keys')!.body).toEqual({ name: 'iPhone-Kurzbefehl', days: null, scope: 'upload' })
    expect(calls.some((call) => call.method === 'POST' && call.url === '/api/v1/devices')).toBe(false)
    const shown = box.querySelector('[data-testid="shortcut-key"]')!
    const values = [...shown.querySelectorAll('input')].map((input) => input.value)
    expect(values).toEqual(['https://paper.example.com/api/v1/documents?source=share', 'Bearer npk_' + 'k'.repeat(43)])
    // The list of keys (the module's card) shows it at once.
    expect(box.querySelector('[data-card="api-keys"] [data-testid="key-row"]')!.textContent).toContain('iPhone-Kurzbefehl')
    await click(button('Fertig', shown))
    expect(box.textContent).not.toContain('k'.repeat(43))
  })

  it('says when the operator has not switched keys on, and makes none', async () => {
    answers['GET /api/v1/shortcut'] = { link: '', address: 'https://paper.example.com', upload_url: 'https://paper.example.com/api/v1/documents?source=share' }
    answers['GET /api/v1/api-keys'] = { allowed: false, keys: [] }
    await show('/konto?tab=devices')
    expect(box.querySelector('[data-testid="shortcut-off"]')!.textContent).toContain('die Programmschnittstelle (API) hat der Betreiber nicht freigegeben. Unter Server › Verbindungen › Schnittstellen freigeben.')
    // The switch stands under Server › Verbindungen (Schnittstellen) now (E67).
    expect(box.querySelector('[data-testid="shortcut-off"] a')!.getAttribute('href')).toBe('/settings/server-connections#interfaces')
    expect(button('Schlüssel für den Kurzbefehl')).toBeUndefined()
  })

  it('offers the shortcut the operator shared', async () => {
    const link = 'https://www.icloud.com/shortcuts/' + '0123456789abcdef'.repeat(2)
    answers['GET /api/v1/shortcut'] = { link, address: 'https://paper.example.com', upload_url: 'https://paper.example.com/api/v1/documents?source=share' }
    await show('/konto?tab=devices')
    expect(box.querySelector('[data-testid="shortcut-link"]')!.getAttribute('href')).toBe(link)
    expect(box.querySelector('[data-testid="shortcut-steps"]')!.textContent).toContain('Auf dem iPhone „Kurzbefehl laden“ antippen und hinzufügen.')
  })

  it('stands in the order of the plan: devices, installing, nexpaper\'s own, then the keys', async () => {
    answers['GET /api/v1/shortcut'] = { link: '', address: 'https://paper.example.com', upload_url: 'https://paper.example.com/api/v1/documents?source=share' }
    answers['GET /api/v1/phone/shortcut-link'] = { link: '' }
    await show('/konto?tab=devices')
    // The operator sees the card of the shared shortcut too (from the area "API" of before); since mcp 1.1.0 the card
    // "KI-Werkzeuge (MCP)" at the end (place 6).
    expect(cards()).toEqual(['devices', 'install', 'shortcut', 'shortcut-link', 'api-keys', 'ai-tools'])
    act(() => root.unmount())
    box.remove()
    auth.me = { ...baseMe, role: 'member' }
    await show('/settings/connections')
    expect(cards()).toEqual(['devices', 'install', 'shortcut', 'api-keys', 'ai-tools'])
  })

  it('lets only the operator set another nex app up or connect a new one by hand (verbinden 0.1.8, V42, V46)', async () => {
    const notSetUp = {
      partner: 'nextime', state: 'none', address: '', address_from_operator: false, set_up: false, host: '', uses: [],
      grants: ['deadlines.read'], uses_levels: {}, grants_levels: { 'deadlines.read': 'read' }, account: null, since: null,
      ok_at: null, used_at: null, stale_since: null, problem: null, areas_used: null, areas_granted: null, legacy: null,
      areas_choice: [], version: null,
    }
    answers['GET /api/connect/partners'] = [notSetUp]
    await show('/settings/connections#nextime')
    const open = async () => {
      if (!box.querySelector('[data-testid="connection-not-set-up"]')) await click(box.querySelector<HTMLElement>('[data-testid="connection-nextime"] button')!)
      return box.querySelector('[data-testid="connection-not-set-up"]')!
    }
    expect((await open()).textContent).toContain('nextime ist auf diesem Server nicht eingerichtet')
    expect(box.querySelector('[data-testid="connection-set-up"]')?.getAttribute('href')).toBe('/settings/server-connections#nex-apps')
    expect(box.querySelector('[data-testid="connection-address"]')).toBeNull()
    act(() => root.unmount())
    box.remove()
    auth.me = { ...baseMe, role: 'member' }
    await show('/settings/connections#nextime')
    expect((await open()).textContent).toContain('Der Betreiber trägt die Adresse')
    expect(box.querySelector('[data-testid="connection-set-up"]')).toBeNull()
  })

  it('keeps API keys off until the operator allows them, and says where', async () => {
    await show('/konto?tab=devices')
    const off = box.querySelector('[data-card="api-keys"] [data-testid="api-keys-off"]')!
    expect(off.textContent).toContain('Der Betreiber hat die Programmschnittstelle abgeschaltet.')
    // The operator is told where the switch is (Server › Verbindungen › Schnittstellen).
    expect(off.textContent).toContain('Einschalten unter Server › Verbindungen › Schnittstellen.')
    expect(button('Neuer API-Schlüssel')!.disabled).toBe(true)
  })

  it('offers no way to allow API keys to somebody who is not the operator', async () => {
    auth.me = { ...baseMe, role: 'member' }
    await show('/konto?tab=devices')
    const off = box.querySelector('[data-testid="api-keys-off"]')!
    expect(off.textContent).toContain('Der Betreiber hat die Programmschnittstelle abgeschaltet.')
    expect(off.textContent).not.toContain('Einschalten unter')
    expect(button('Jetzt freigeben')).toBeUndefined()
  })

  it('has one button for a new key, with what it may as a choice of two, and says what an upload key may do', async () => {
    answers['GET /api/v1/connections/keys'] = listing(true)
    await show('/konto?tab=devices')
    const card = box.querySelector<HTMLElement>('[data-card="api-keys"]')!
    // nexpaper's word in the module's line ("mit deinen Dokumenten").
    expect(card.textContent).toContain('mit deinen Dokumenten arbeiten')
    // The address for programs, how they send the key, and the description of the interface.
    expect(card.querySelector<HTMLInputElement>('[data-testid="api-keys-address"] input')!.value).toBe('https://paper.example.com/api/v1')
    expect(card.textContent).toContain('Programme schicken den Schlüssel als „Authorization: Bearer …“.')
    expect(card.querySelector('[data-testid="api-keys-docs"]')!.getAttribute('href')).toBe('/api/v1/docs')
    const add = button('Neuer API-Schlüssel', card)!
    expect([add.dataset.kind, add.dataset.icon]).toEqual(['primary', 'Plus'])
    await click(add)
    expect(right('read').textContent).toBe('Nur lesen')
    expect(right('upload').textContent).toBe('Nur hochladen')
    expect(right('read').getAttribute('aria-checked')).toBe('true')
    // nexpaper's sentence of each right (words.rightHints).
    expect(dialog()!.textContent).toContain('Dokumente, Tresore und Suche lesen, so weit dein Konto darf.')
    await click(right('upload'))
    expect(dialog()!.textContent).toContain('legt Dokumente in einen Eingang und liest nichts')
  })

  it('makes a key that is shown once, with its header line, and lists only its first characters after', async () => {
    answers['GET /api/v1/connections/keys'] = listing(true)
    answers['POST /api/v1/connections/keys'] = { key: keyOf(1, 'nexdeck', 'read', 'npk_AbCd'), secret: 'npk_' + 's'.repeat(43) }
    await show('/konto?tab=devices')
    await click(button('Neuer API-Schlüssel'))
    await type(field('Name', dialog()!), 'nexdeck')
    answers['GET /api/v1/connections/keys'] = listing(true, [keyOf(1, 'nexdeck', 'read', 'npk_AbCd')])
    await click(dialog()!.querySelector<HTMLElement>('[data-testid="key-submit"]')!)
    expect(made()!.body).toEqual(expect.objectContaining({ kind: 'api', name: 'nexdeck', right: 'read', days: 365 }))
    // schluessel 1.2.0 (B23): the same window shows the new key once, nothing of it on the card.
    expect(document.querySelector('[data-testid="key-dialog"]')).not.toBeNull()
    expect([...document.querySelectorAll('[data-testid="key-made"]')].every((found) => found.closest('[role="dialog"]') !== null)).toBe(true)
    const shown = document.querySelector<HTMLElement>('[data-testid="key-dialog"]')!
    expect(shown.querySelector('[data-testid="key-made"]')).not.toBeNull()
    expect(shown.textContent).toContain('„nexdeck“ angelegt')
    expect(shown.textContent).toContain('Kopiere den Schlüssel jetzt. Er wird nur dieses eine Mal angezeigt; nexpaper speichert nur eine Prüfsumme.')
    expect(shown.querySelector<HTMLInputElement>('[data-testid="key-header"] input')!.value).toBe('Authorization: Bearer npk_' + 's'.repeat(43))
    await click(shown.querySelector<HTMLElement>('[data-testid="key-done"]')!)
    expect(document.querySelector('[data-testid="key-dialog"]')).toBeNull()
    expect(document.body.textContent).not.toContain('s'.repeat(43))
    expect(box.querySelector('[data-testid="key-row"]')!.textContent).toContain('npk_AbCd')
  })

  it('offers a year as the default lifetime, and still lets the key run without an end', async () => {
    answers['GET /api/v1/connections/keys'] = listing(true)
    answers['POST /api/v1/connections/keys'] = { key: keyOf(3, 'forever', 'read', 'npk_Ever'), secret: 'npk_' + 'e'.repeat(43) }
    await show('/konto?tab=devices')
    await click(button('Neuer API-Schlüssel'))
    expect(expiry().value).toBe('365')
    expect([...expiry().options].map((option) => option.textContent)).toEqual(['30 Tage', '90 Tage', '1 Jahr', 'Nie'])
    await type(field('Name', dialog()!), 'forever')
    await choose(expiry(), 'never')
    await click(dialog()!.querySelector<HTMLElement>('[data-testid="key-submit"]')!)
    expect(made()!.body).toEqual(expect.objectContaining({ name: 'forever', days: null, right: 'read' }))
  })

  it('offers no end as the default for a key that only uploads, and a year for one that reads; both stay a choice', async () => {
    answers['GET /api/v1/connections/keys'] = listing(true)
    answers['POST /api/v1/connections/keys'] = { key: keyOf(4, 'Scanner', 'upload', 'npk_Sc12'), secret: 'npk_' + 'c'.repeat(43) }
    await show('/konto?tab=devices')
    await click(button('Neuer API-Schlüssel'))
    await click(right('upload'))
    expect(expiry().value).toBe('never')
    // The person's own pick is kept when the kind of key changes afterwards.
    await choose(expiry(), '365')
    expect(expiry().value).toBe('365')
    await click(right('read'))
    expect(expiry().value).toBe('365')
    await click(right('upload'))
    await type(field('Name', dialog()!), 'Scanner')
    await click(dialog()!.querySelector<HTMLElement>('[data-testid="key-submit"]')!)
    expect(made()!.body).toEqual(expect.objectContaining({ name: 'Scanner', days: 365, right: 'upload' }))
  })

  it('makes a key for uploading, and lists it as one that only uploads', async () => {
    answers['GET /api/v1/connections/keys'] = listing(true)
    answers['POST /api/v1/connections/keys'] = { key: keyOf(2, 'Scanner im Flur', 'upload', 'npk_Up12'), secret: 'npk_' + 'u'.repeat(43) }
    await show('/konto?tab=devices')
    await click(button('Neuer API-Schlüssel'))
    await click(right('upload'))
    expect(right('upload').getAttribute('aria-checked')).toBe('true')
    await type(field('Name', dialog()!), 'Scanner im Flur')
    answers['GET /api/v1/connections/keys'] = listing(true, [keyOf(2, 'Scanner im Flur', 'upload', 'npk_Up12')])
    await click(dialog()!.querySelector<HTMLElement>('[data-testid="key-submit"]')!)
    expect(made()!.body).toEqual(expect.objectContaining({ kind: 'api', name: 'Scanner im Flur', days: null, right: 'upload' }))
    await click(document.querySelector<HTMLElement>('[data-testid="key-dialog"] [data-testid="key-done"]')!)
    expect(box.querySelector('[data-testid="key-row"]')!.textContent).toContain('Nur hochladen')
  })
})

describe('the look', () => {
  it('keeps light or dark and the view of the archive with the account', async () => {
    answers['PUT /api/v1/me/theme'] = { theme: 'dark' }
    await show('/konto?tab=looks')
    // First the card "Aussehen" of every app (konten 1.1.0), then nexpaper's own "Archiv".
    expect([...box.querySelectorAll('section[data-card]')].map((card) => card.getAttribute('data-card'))).toEqual(['appearance', 'archive-look'])
    expect(box.querySelector('[data-card="appearance"] h2')!.textContent).toBe('Aussehen')
    expect(box.textContent).toContain('Darstellung des Archivs')
    const dark = [...box.querySelectorAll<HTMLElement>('[data-card="appearance"] [role="radio"]')].find((item) => item.textContent === 'Dunkel')!
    await click(dark)
    // Kept at the account on every device (`PUT /api/v1/me/theme`, E5).
    expect(calls.find((call) => call.url === '/api/v1/me/theme')!.body).toEqual({ theme: 'dark' })
    answers['PUT /api/v1/me/preferences'] = { ...baseMe.profile, view: 'grid' }
    await click([...box.querySelectorAll<HTMLElement>('[data-card="archive-look"] [role="radio"]')].find((item) => item.textContent === 'Kacheln'))
    expect(calls.filter((call) => call.url === '/api/v1/me/preferences').at(-1)!.body).toEqual({ view: 'grid' })
    // There is one accent and no palette to choose.
    expect(box.textContent).not.toMatch(/Salbei|Terrakotta|Pflaume|Altrosa|Tinte/)
  })

  it('has the phone start under Upload', async () => {
    await show('/konto?tab=upload')
    expect(box.textContent).toContain('Auf dem Handy mit dem Schnell-Upload starten')
    const start = field('Auf dem Handy mit dem Schnell-Upload starten')!
    expect([start.type, start.checked]).toEqual(['checkbox', true])
    expect(box.querySelector('[role="switch"]')).toBeNull()
  })

  it('chooses where uploads go among the vaults one may add to', async () => {
    answers['GET /api/v1/vaults'] = [
      { id: 7, name: 'Jule', icon: 'user', personal_of: 1, my_right: 'manage', documents: 0, size: 0, members: [] },
      { id: 9, name: 'Haushalt', icon: 'home', personal_of: null, my_right: 'edit', documents: 0, size: 0, members: [] },
      { id: 11, name: 'Firma', icon: 'folder', personal_of: null, my_right: 'read', documents: 0, size: 0, members: [] },
    ]
    answers['PUT /api/v1/me/preferences'] = { ...baseMe.profile, default_vault: 9 }
    await show('/konto?tab=upload')
    expect(box.textContent).toContain('Wohin deine Uploads gehen')
    const choices = [...box.querySelectorAll('[role="radiogroup"] [role="radio"]')]
    expect(choices.map((item) => item.textContent)).toEqual(['Mein Tresor', 'Haushalt'])
    expect(choices[0].getAttribute('aria-checked')).toBe('true')
    await click(choices[1] as HTMLElement)
    expect(calls.find((call) => call.url === '/api/v1/me/preferences')!.body).toEqual({ default_vault: 9 })
  })
})
