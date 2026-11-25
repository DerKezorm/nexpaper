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
    'GET /api/v1/auth/methods': { password: true, providers: [], passkeys: true },
    'GET /api/v1/auth/passkeys': [],
    'GET /api/v1/auth/sessions': [],
    'GET /api/v1/locales': [],
    'GET /api/v1/api-keys': { allowed: false, keys: [] },
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
    expect(accountAreas()).toEqual(['Profil', 'Sicherheit', 'Darstellung', 'Verbindungen', 'Hochladen', 'Erinnerungen', 'KI'])
    expect(current()).toBe('Profil')
    expect(box.querySelector('h1')!.textContent).toBe('Profil')
    // "Über nexpaper" at the end, outside the groups, as "Über nexnotes".
    expect(box.querySelector('[data-testid="settings-nav-about"]')!.textContent).toContain('Über nexpaper')
  })

  it('stand in the address, and the addresses of before lead to their area', async () => {
    await show('/konto?tab=devices')
    expect(current()).toBe('Verbindungen')
    expect(box.textContent).toContain('Gerät koppeln')
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
    expect(accountAreas()).toEqual(['Profile', 'Security', 'Appearance', 'Connections', 'Upload', 'Reminders', 'AI'])
  })

  it("lay out Security as the shared account module's parts in its order, and sign out everywhere else after a question", async () => {
    auth.me = { ...baseMe, password_changed_at: '2026-11-20T08:00:00Z' }
    await show('/settings/security')
    // The module's parts (PAGES.security) in its order, nexpaper's own (the providers) after them.
    const parts = [...box.querySelectorAll('[id^="security-"]')].map((part) => part.id).filter((id) => /^security-[A-Za-z]+$/.test(id))
    expect(parts).toEqual(['security-password', 'security-secondFactor', 'security-recoveryCodes', 'security-passkeys', 'security-sessions', 'security-newSignInMail'])
    expect(box.querySelector('#security-password')!.textContent).toContain('Zuletzt geändert am 20.11.2026')
    const card = box.querySelector<HTMLElement>('#security-sessions')!
    expect(card.textContent).toContain('Angemeldete Geräte')
    await click(button('Überall sonst abmelden', card))
    expect(calls.some((call) => call.url === '/api/v1/auth/logout-all')).toBe(false)
    await click(button('Überall sonst abmelden', document.body.querySelector<HTMLElement>('[role="dialog"]')!))
    expect(calls.some((call) => call.url === '/api/v1/auth/logout-all')).toBe(true)
  })

  it('lock the own AI switch while no AI is set up, say why, and lead the operator there', async () => {
    auth.me = { ...baseMe, role: 'operator' }
    await show('/settings/ai')
    const own = box.querySelector<HTMLInputElement>('[role="switch"][aria-label="KI-Vorschläge für meine Dokumente"]')!
    expect(own.disabled).toBe(true)
    expect(own.checked).toBe(false)
    const note = box.querySelector('[data-ai-none]')!
    expect(note.textContent).toContain('Es ist keine KI eingerichtet.')
    expect(note.querySelector('a')!.getAttribute('href')).toBe('/settings/ai-setup')
  })

  it('let the own AI switch work once the operator set one up', async () => {
    answers['GET /api/v1/ai'] = { provider: 'local', to: 'http://ollama:11434', model: 'llama3.1:8b', mine: true, allowed: true, available: true }
    answers['PUT /api/v1/me/preferences'] = { ...baseMe.profile, ai: false }
    await show('/settings/ai')
    const own = box.querySelector<HTMLInputElement>('[role="switch"][aria-label="KI-Vorschläge für meine Dokumente"]')!
    expect(own.disabled).toBe(false)
    expect(own.checked).toBe(true)
    expect(box.querySelector('[data-ai-none]')).toBeNull()
    await click(own)
    expect(calls.find((call) => call.url === '/api/v1/me/preferences')!.body).toEqual({ ai: false })
  })

  it('end the profile with signing out, the one place for it', async () => {
    await show('/settings/profile')
    expect(box.querySelector('[data-testid="sign-out-card"]')!.textContent).toContain('Abmelden')
  })
})

describe('the mail address', () => {
  it('asks for the password and waits for the link: the old address stays until it is opened', async () => {
    auth.me = { ...baseMe, email: 'old@example.com', email_confirmed: true }
    answers['PUT /api/v1/me/profile'] = { ...baseMe, email: 'old@example.com', email_confirmed: true, email_pending: 'new@example.com' }
    await show()
    expect(field('E-Mail')!.value).toBe('old@example.com')
    expect(box.querySelector('[data-testid="mail-state"]')!.textContent).toBe('Mailadresse bestätigt')
    // The shared account module's profile: one "Speichern" for all; a new address asks for the password once.
    expect(button('Speichern')!.disabled).toBe(true)
    await type(field('E-Mail'), 'new@example.com')
    await click(button('Speichern'))
    expect(calls.some((call) => call.method === 'PUT' && call.url === '/api/v1/me/profile')).toBe(false)
    await type(field('Aktuelles Passwort', lastDialog()) ?? lastDialog().querySelector<HTMLInputElement>('input[type="password"]'), 'the own password')
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

  it('marks an address nobody confirmed and offers "Per Link bestätigen"', async () => {
    auth.me = { ...baseMe, email: 'typed@example.com', email_confirmed: false, mail_links: true }
    answers['POST /api/v1/me/email/prove'] = { ...baseMe, email: 'typed@example.com', email_confirmed: false, email_pending: 'typed@example.com' }
    await show()
    expect(box.querySelector('[data-testid="mail-state"]')!.textContent).toContain('Mailadresse nicht bestätigt')
    // The module's button (konten 0.3.10, profiles.prove_email): the link goes to the address there is.
    await click(button('Per Link bestätigen'))
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
  /** The open dialog, inside the page (the settings draw it there). */
  const dialog = () => box.querySelector<HTMLElement>('[role="dialog"]')
  async function choose(select: HTMLSelectElement | null | undefined, value: string): Promise<void> {
    expect(select).toBeTruthy()
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!
    await act(async () => {
      setter.call(select, value)
      select!.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await idle()
  }
  const expiry = () => [...dialog()!.querySelectorAll('label')].find((item) => item.textContent?.startsWith('Ablauf'))!.querySelector('select')!
  const right = (name: string) => [...dialog()!.querySelectorAll('label')].find((item) => item.textContent?.startsWith(name))!.querySelector<HTMLInputElement>('input[type="radio"]')!

  it('pairs a device by a code shown as a QR code in a dialog, and lists it once the device took it', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      answers['POST /api/v1/devices/pairing'] = {
        code: 'KRAF-T7Q2-K9XW', expires_at: new Date(Date.now() + 300_000).toISOString(), server: 'https://paper.example.com',
        link: 'nexpaper://pair?server=https%3A%2F%2Fpaper.example.com&code=KRAF-T7Q2-K9XW', qr_svg: '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
      }
      answers['GET /api/v1/devices/pairing'] = { state: 'open', expires_at: null, device: null }
      await show('/konto?tab=devices')
      const card = box.querySelector<HTMLElement>('#devices')!
      expect(card.textContent).toContain('Geräte')
      expect(card.textContent).toContain('iPhone und iPad mit der nexpaper-App und eigene Programme.')
      expect(card.querySelector('[data-testid="devices-none"]')!.textContent).toBe('Noch kein Gerät gekoppelt.')
      // As in nexnotes: one accent button, the code in a dialog.
      expect(box.querySelector('[data-testid="pairing-code"]')).toBeNull()
      await click(button('Gerät koppeln', card))
      const shown = dialog()!.querySelector('[data-testid="pairing-code"]')!
      expect(shown.textContent).toContain('Mit dem Gerät scannen. Der Code gilt 5 Minuten und nur einmal.')
      expect(shown.textContent).toContain('Oder von Hand: Adresse https://paper.example.com, Code KRAF-T7Q2-K9XW')
      expect(dialog()!.querySelector('img')!.getAttribute('alt')).toBe('QR-Code zum Koppeln')
      answers['GET /api/v1/devices/pairing'] = { state: 'used', expires_at: null, device: { id: 'a'.repeat(32), name: 'iPhone von jule', prefix: 'npd_AbCd', created_at: '2026-10-08T10:00:00Z', last_used_at: null, via: 'qr' } }
      answers['GET /api/v1/devices'] = [{ id: 'a'.repeat(32), name: 'iPhone von jule', prefix: 'npd_AbCd', created_at: '2026-10-08T10:00:00Z', last_used_at: null, via: 'qr' }]
      await act(async () => vi.advanceTimersByTime(2100))
      await idle()
      expect(dialog()).toBeNull()
      expect(box.textContent).toContain('Gekoppelt. Das Gerät steht jetzt in der Liste.')
      expect(box.querySelector('[data-testid="paired-device"]')!.textContent).toContain('iPhone von jule')
      expect(box.querySelector('[data-testid="paired-device"]')!.textContent).toContain('gekoppelt per QR-Code · zuletzt noch nie benutzt')
    } finally {
      vi.useRealTimers()
    }
  })

  it('ends a code that is not wanted when the dialog closes, and offers a new one when it ran out', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      answers['POST /api/v1/devices/pairing'] = { code: 'KRAF-T7Q2-K9XW', expires_at: new Date(Date.now() + 300_000).toISOString(), server: 'https://paper.example.com', link: '', qr_svg: '<svg/>' }
      answers['POST /api/v1/devices/pairing/cancel'] = 204
      await show('/konto?tab=devices')
      await click(button('Gerät koppeln'))
      await click(button('Schließen', dialog()!.querySelector('[data-testid="pairing-dialog"]')!))
      expect(calls.some((call) => call.method === 'POST' && call.url === '/api/v1/devices/pairing/cancel')).toBe(true)
      expect(dialog()).toBeNull()
      await click(button('Gerät koppeln'))
      answers['GET /api/v1/devices/pairing'] = { state: 'expired', expires_at: null, device: null }
      await act(async () => vi.advanceTimersByTime(2100))
      await idle()
      expect(dialog()!.textContent).toContain('Der Code ist abgelaufen.')
      const before = calls.filter((call) => call.method === 'POST' && call.url === '/api/v1/devices/pairing').length
      await click(button('Neuen Code zeigen', dialog()!))
      expect(calls.filter((call) => call.method === 'POST' && call.url === '/api/v1/devices/pairing').length).toBe(before + 1)
      expect(dialog()!.querySelector('[data-testid="pairing-code"]')).toBeTruthy()
    } finally {
      vi.useRealTimers()
    }
  })

  it('lists the paired devices and disconnects one only after the question', async () => {
    const id = 'd'.repeat(32)
    answers['GET /api/v1/devices'] = [{ id, name: 'iPad von jule', prefix: 'npd_Ip12', created_at: '2026-10-08T10:00:00Z', last_used_at: null, via: 'device' }]
    answers[`DELETE /api/v1/devices/${id}`] = 204
    await show('/konto?tab=devices')
    const row = box.querySelector<HTMLElement>('[data-testid="paired-device"]')!
    expect(row.textContent).toContain('von einem anderen Gerät hinzugefügt')
    const sent = () => calls.some((call) => call.method === 'DELETE' && call.url === `/api/v1/devices/${id}`)
    await click(button('iPad von jule trennen', row))
    expect(document.body.querySelector('[role="dialog"]')!.textContent).toContain('„iPad von jule“ trennen?')
    expect(sent()).toBe(false)
    await click(button('Abbrechen', document.body.querySelector<HTMLElement>('[role="dialog"]')!))
    expect(sent()).toBe(false)
    answers['GET /api/v1/devices'] = []
    await click(button('iPad von jule trennen', row))
    await click(button('Trennen', document.body.querySelector<HTMLElement>('[role="dialog"]')!))
    expect(sent()).toBe(true)
    expect(box.textContent).toContain('iPad von jule ist getrennt.')
    expect(box.querySelector('[data-testid="paired-device"]')).toBeNull()
  })

  it('makes a key that only uploads for the iPhone shortcut, once, and shows the address and the header to copy', async () => {
    answers['GET /api/v1/shortcut'] = { link: '', address: 'https://paper.example.com', upload_url: 'https://paper.example.com/api/v1/documents?source=share' }
    answers['GET /api/v1/api-keys'] = { allowed: true, keys: [] }
    answers['POST /api/v1/api-keys'] = {
      key: { id: 5, name: 'iPhone-Kurzbefehl', scope: 'upload', prefix: 'npk_Xy12', created_at: '2026-10-08T10:00:00Z', last_used_at: null, expires_at: null, blocked: false },
      secret: 'npk_' + 'k'.repeat(43),
    }
    await show('/konto?tab=devices')
    const steps = box.querySelector('[data-testid="shortcut-steps"]')!
    expect(steps.textContent).toContain('Aktion „Inhalte von URL abrufen“')
    expect(box.querySelector('[data-testid="shortcut-link"]')).toBeNull()
    expect(box.querySelector('[data-testid="shortcut-warning"]')!.textContent).toContain('Trag deinen Token nie in einen Kurzbefehl ein, den du mit anderen teilst')
    answers['GET /api/v1/api-keys'] = { allowed: true, keys: [(answers['POST /api/v1/api-keys'] as { key: unknown }).key] }
    await click(button('Token für den Kurzbefehl'))
    expect(calls.find((call) => call.method === 'POST' && call.url === '/api/v1/api-keys')!.body).toEqual({ name: 'iPhone-Kurzbefehl', days: null, scope: 'upload' })
    expect(calls.some((call) => call.method === 'POST' && call.url === '/api/v1/devices')).toBe(false)
    const shown = box.querySelector('[data-testid="shortcut-key"]')!
    const values = [...shown.querySelectorAll('input')].map((input) => input.value)
    expect(values).toEqual(['https://paper.example.com/api/v1/documents?source=share', 'Bearer npk_' + 'k'.repeat(43)])
    // The list of keys shows it at once.
    expect(box.querySelector('[data-testid="api-key"]')!.textContent).toContain('iPhone-Kurzbefehl')
    await click(button('Fertig', shown))
    expect(box.textContent).not.toContain('k'.repeat(43))
  })

  it('says when the operator has not switched keys on, and makes none', async () => {
    answers['GET /api/v1/shortcut'] = { link: '', address: 'https://paper.example.com', upload_url: 'https://paper.example.com/api/v1/documents?source=share' }
    answers['GET /api/v1/api-keys'] = { allowed: false, keys: [] }
    await show('/konto?tab=devices')
    expect(box.querySelector('[data-testid="shortcut-off"]')!.textContent).toContain('API-Token hat der Betreiber nicht freigegeben')
    // The switch stands under General now, with the other switches for all accounts.
    expect(box.querySelector('[data-testid="shortcut-off"] a')!.getAttribute('href')).toBe('/settings/general')
    expect(button('Token für den Kurzbefehl')).toBeUndefined()
  })

  it('offers the shortcut the operator shared', async () => {
    const link = 'https://www.icloud.com/shortcuts/' + '0123456789abcdef'.repeat(2)
    answers['GET /api/v1/shortcut'] = { link, address: 'https://paper.example.com', upload_url: 'https://paper.example.com/api/v1/documents?source=share' }
    await show('/konto?tab=devices')
    expect(box.querySelector('[data-testid="shortcut-link"]')!.getAttribute('href')).toBe(link)
    expect(box.querySelector('[data-testid="shortcut-steps"]')!.textContent).toContain('Auf dem iPhone „Kurzbefehl laden“ antippen und hinzufügen.')
  })

  it('stands in the order of nexnotes, devices before keys, then nexpaper\'s own', async () => {
    answers['GET /api/v1/shortcut'] = { link: '', address: 'https://paper.example.com', upload_url: 'https://paper.example.com/api/v1/documents?source=share' }
    await show('/konto?tab=devices')
    const cards = [...box.querySelectorAll('[data-testid="account-connections"] > section')].map((card) => card.id)
    expect(cards.indexOf('devices')).toBeLessThan(cards.indexOf('api-keys'))
    expect(cards.indexOf('api-keys')).toBeLessThan(cards.indexOf('shortcut'))
  })

  it('keeps API keys off until the operator allows them, and says where', async () => {
    await show('/konto?tab=devices')
    expect(box.querySelector('[data-testid="api-keys-off"]')!.textContent).toContain('API-Token sind noch nicht freigegeben.')
    expect(box.querySelector('[data-testid="api-keys-off"] a')!.getAttribute('href')).toBe('/settings/general')
    expect(button('Neuer API-Token')!.disabled).toBe(true)
  })

  it('lets the operator allow API keys right there, after asking what it means', async () => {
    answers['PUT /api/v1/settings'] = { api_keys_allowed: true }
    await show('/konto?tab=devices')
    await click(button('Jetzt freigeben'))
    const asked = document.querySelector('[role="dialog"]')!
    expect(asked.textContent).toContain('Danach kann jede Person auf diesem Server unter Mein Konto Tokens anlegen.')
    expect(asked.textContent).toContain('jederzeit wieder ausschalten')
    // Nothing was sent before the answer.
    expect(calls.some((call) => call.method === 'PUT')).toBe(false)
    answers['GET /api/v1/api-keys'] = { allowed: true, keys: [] }
    await click(button('Freigeben', asked as HTMLElement))
    expect(calls.find((call) => call.method === 'PUT' && call.url === '/api/v1/settings')!.body).toEqual({ api_keys_allowed: true })
    expect(box.querySelector('[data-testid="api-keys-off"]')).toBeNull()
    expect(button('Neuer API-Token')!.disabled).toBe(false)
  })

  it('asks first and sends nothing when the operator says no', async () => {
    await show('/konto?tab=devices')
    await click(button('Jetzt freigeben'))
    await click(button('Abbrechen', document.querySelector<HTMLElement>('[role="dialog"]')!))
    expect(calls.some((call) => call.method === 'PUT')).toBe(false)
    expect(box.querySelector('[data-testid="api-keys-off"]')).toBeTruthy()
  })

  it('offers no way to allow API keys to somebody who is not the operator', async () => {
    auth.me = { ...baseMe, role: 'member' }
    await show('/konto?tab=devices')
    expect(box.querySelector('[data-testid="api-keys-off"]')!.textContent).toContain('Der Betreiber hat API-Token nicht freigegeben.')
    expect(button('Jetzt freigeben')).toBeUndefined()
  })

  it('has one button for a new key, with what it may as two cards to choose, and says what an upload key may do', async () => {
    answers['GET /api/v1/api-keys'] = { allowed: true, keys: [] }
    await show('/konto?tab=devices')
    expect(button('Token zum Hochladen (für Scanner und Apps)')).toBeUndefined()
    expect(box.querySelector('[data-testid="api-keys-upload-note"]')!.textContent).toContain('legt Dokumente nur in einen Eingang: in den deines Ziel-Tresors oder, wenn das Programm einen anderen nennt, in den eines Tresors, in dem du ablegen darfst')
    // As nexnotes' card: the address for programs, how they send the key, and the documentation.
    expect(box.textContent).toContain(`Adresse für Programme: ${window.location.origin}/api/v1`)
    expect(box.textContent).toContain('Programme schicken den Token als „Authorization: Bearer …“.')
    expect([...box.querySelectorAll('a')].find((a) => a.textContent === 'API-Dokumentation')!.getAttribute('href')).toBe('/api/v1/docs')
    await click(button('Neuer API-Token'))
    expect(dialog()!.textContent).toContain('Nur lesen')
    expect(dialog()!.textContent).toContain('Nur hochladen')
    expect(dialog()!.textContent).toContain('legt Dokumente in einen Eingang und liest nichts')
    expect(right('Nur lesen').checked).toBe(true)
  })

  it('makes a key that is shown once, with its header line, and lists only its first characters after', async () => {
    answers['GET /api/v1/api-keys'] = { allowed: true, keys: [] }
    answers['POST /api/v1/api-keys'] = {
      key: { id: 1, name: 'nexdeck', scope: 'read', prefix: 'npk_AbCd', created_at: '2026-10-08T10:00:00Z', last_used_at: null, expires_at: null, blocked: false },
      secret: 'npk_' + 's'.repeat(43),
    }
    await show('/konto?tab=devices')
    await click(button('Neuer API-Token'))
    await type(field('Name', dialog()!), 'nexdeck')
    answers['GET /api/v1/api-keys'] = { allowed: true, keys: [(answers['POST /api/v1/api-keys'] as { key: unknown }).key] }
    await click(button('Token anlegen', dialog()!))
    expect(calls.find((call) => call.method === 'POST' && call.url === '/api/v1/api-keys')!.body).toEqual({ name: 'nexdeck', days: 365, scope: 'read' })
    expect(dialog()).toBeNull()
    const shown = box.querySelector('[data-testid="api-key-shown"]')!
    expect(shown.textContent).toContain('„nexdeck“ angelegt')
    expect(shown.textContent).toContain('Kopiere den Token jetzt. Er wird nur dieses eine Mal angezeigt.')
    expect(shown.textContent).toContain('Authorization: Bearer npk_' + 's'.repeat(43))
    await click(button('Fertig'))
    expect(box.textContent).not.toContain('s'.repeat(43))
    expect(box.querySelector('[data-testid="api-key"]')!.textContent).toContain('npk_AbCd')
  })

  it('offers a year as the default lifetime, says why, and still lets the key run without an end', async () => {
    answers['GET /api/v1/api-keys'] = { allowed: true, keys: [] }
    answers['POST /api/v1/api-keys'] = {
      key: { id: 3, name: 'forever', scope: 'read', prefix: 'npk_Ever', created_at: '2026-10-08T10:00:00Z', last_used_at: null, expires_at: null, blocked: false },
      secret: 'npk_' + 'e'.repeat(43),
    }
    await show('/konto?tab=devices')
    await click(button('Neuer API-Token'))
    expect(dialog()!.textContent).toContain('Ein Token, der nie abläuft, ist der, an den sich niemand mehr erinnert')
    expect(expiry().value).toBe('365')
    expect([...expiry().options].map((option) => option.textContent)).toEqual(['365 Tage', '90 Tage', '30 Tage', 'Ohne Ablauf'])
    await type(field('Name', dialog()!), 'forever')
    await choose(expiry(), 'never')
    await click(button('Token anlegen', dialog()!))
    expect(calls.find((call) => call.method === 'POST' && call.url === '/api/v1/api-keys')!.body).toEqual({ name: 'forever', days: null, scope: 'read' })
  })

  it('offers no end as the default for a key that only uploads, and a year for one that reads; both stay a choice', async () => {
    answers['GET /api/v1/api-keys'] = { allowed: true, keys: [] }
    answers['POST /api/v1/api-keys'] = {
      key: { id: 4, name: 'Scanner', scope: 'upload', prefix: 'npk_Sc12', created_at: '2026-10-08T10:00:00Z', last_used_at: null, expires_at: null, blocked: false },
      secret: 'npk_' + 'c'.repeat(43),
    }
    await show('/konto?tab=devices')
    await click(button('Neuer API-Token'))
    await click(right('Nur hochladen'))
    expect(expiry().value).toBe('never')
    expect(dialog()!.textContent).toContain('läuft er von sich aus nicht ab')
    // The person's own pick is kept when the kind of key changes afterwards; a pick of none is not overridden.
    await choose(expiry(), '365')
    expect(expiry().value).toBe('365')
    await click(right('Nur lesen'))
    expect(expiry().value).toBe('365')
    await click(right('Nur hochladen'))
    await type(field('Name', dialog()!), 'Scanner')
    await click(button('Token anlegen', dialog()!))
    expect(calls.find((call) => call.method === 'POST' && call.url === '/api/v1/api-keys')!.body).toEqual({ name: 'Scanner', days: 365, scope: 'upload' })
  })

  it('makes a key for uploading, with the command that uploads and the limits', async () => {
    answers['GET /api/v1/api-keys'] = { allowed: true, keys: [] }
    answers['POST /api/v1/api-keys'] = {
      key: { id: 2, name: 'Scanner im Flur', scope: 'upload', prefix: 'npk_Up12', created_at: '2026-10-08T10:00:00Z', last_used_at: null, expires_at: null, blocked: false },
      secret: 'npk_' + 'u'.repeat(43),
    }
    await show('/konto?tab=devices')
    expect(box.textContent).toContain('Grenzen je Token: 120 Anfragen in der Minute, 50 Uploads in der Stunde.')
    await click(button('Neuer API-Token'))
    await click(right('Nur hochladen'))
    expect(right('Nur hochladen').checked).toBe(true)
    await type(field('Name', dialog()!), 'Scanner im Flur')
    answers['GET /api/v1/api-keys'] = { allowed: true, keys: [(answers['POST /api/v1/api-keys'] as { key: unknown }).key] }
    await click(button('Token anlegen', dialog()!))
    expect(calls.find((call) => call.method === 'POST' && call.url === '/api/v1/api-keys')!.body).toEqual({ name: 'Scanner im Flur', days: null, scope: 'upload' })
    expect(box.querySelector('[data-testid="api-key-shown"]')!.textContent).toContain('-F file=@Rechnung.pdf')
    await click(button('Fertig'))
    expect(box.querySelector('[data-testid="api-key"]')!.textContent).toContain('nur hochladen')
  })
})

describe('the look', () => {
  it('keeps light or dark and the view of the archive with the account', async () => {
    answers['PUT /api/v1/me/preferences'] = { ...baseMe.profile, mode: 'dark' }
    await show('/konto?tab=looks')
    expect(box.textContent).toContain('Aussehen')
    expect(box.textContent).toContain('Darstellung des Archivs')
    await click(button('Dunkel'))
    expect(calls.find((call) => call.url === '/api/v1/me/preferences')!.body).toEqual({ mode: 'dark' })
    answers['PUT /api/v1/me/preferences'] = { ...baseMe.profile, view: 'grid' }
    await click(button('Kacheln'))
    expect(calls.filter((call) => call.url === '/api/v1/me/preferences').at(-1)!.body).toEqual({ view: 'grid' })
    // There is one accent and no palette to choose.
    expect(box.textContent).not.toMatch(/Salbei|Terrakotta|Pflaume|Altrosa|Tinte/)
  })

  it('has the phone start under Upload', async () => {
    await show('/konto?tab=upload')
    expect(box.textContent).toContain('Auf dem Handy mit dem Schnell-Upload starten')
    expect(box.querySelector('[role="switch"]')!.getAttribute('aria-checked')).toBe('true')
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
