/**
 * My account in the interface, against a stand-in of the server: the seven tabs in their order and in the
 * address, the mail address with the link it waits for (the password asked again, the old address standing until the
 * link is opened, withdrawn on request), pairing a device (the key shown once, then blocked), API keys (off until the
 * operator allows them, the key shown once) and the choices of the look.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

import type { Me } from '../api/client'
import '../i18n'
import { changeLanguage } from '../i18n'
import { idle } from '../test/wait'
import { AccountPage } from './AccountPage'

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

async function show(at = '/konto'): Promise<void> {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  box = document.createElement('div')
  document.body.appendChild(box)
  root = createRoot(box)
  await act(async () => root.render(<MemoryRouter initialEntries={[at]}><AccountPage /></MemoryRouter>))
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
  return found?.querySelector('input') ?? null
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

describe('the tabs', () => {
  it('are the seven tabs, in their order', async () => {
    await show()
    const tabs = [...box.querySelectorAll('[role="tab"]')].map((item) => item.textContent?.trim())
    expect(tabs).toEqual(['Profil', 'Sicherheit', 'Geräte und Apps', 'Hochladen', 'Erinnerungen', 'KI', 'Aussehen'])
    expect(box.querySelector('h1')!.textContent).toBe('Mein Konto')
  })

  it('stand in the address and open on the profile without one', async () => {
    await show('/konto?tab=devices')
    expect(box.querySelector('[role="tab"][aria-selected="true"]')!.textContent).toContain('Geräte und Apps')
    expect(box.textContent).toContain('Gerät koppeln')
    act(() => root.unmount())
    box.remove()
    await show('/konto?tab=nonsense')
    expect(box.querySelector('[role="tab"][aria-selected="true"]')!.textContent).toContain('Profil')
  })

  it('come in English too, with the same seven', async () => {
    await changeLanguage('en', false)
    await show()
    expect([...box.querySelectorAll('[role="tab"]')].map((item) => item.textContent?.trim())).toEqual(['Profile', 'Security', 'Devices and apps', 'Upload', 'Reminders', 'AI', 'Look'])
  })
})

describe('the mail address', () => {
  it('asks for the password and waits for the link: the old address stays until it is opened', async () => {
    auth.me = { ...baseMe, email: 'old@example.com', email_confirmed: true }
    answers['PUT /api/v1/me/email'] = { ...baseMe, email: 'old@example.com', email_confirmed: true, email_pending: 'new@example.com' }
    await show()
    expect(box.textContent).toContain('old@example.com')
    expect(box.querySelector('[data-testid="mail-state"]')!.textContent).toBe('bestätigt')
    await type(field('Neue Mailadresse'), 'new@example.com')
    expect(button('Bestätigung schicken')!.disabled).toBe(true)
    await type(field('Passwort'), 'the own password')
    await click(button('Bestätigung schicken'))
    expect(calls.find((call) => call.method === 'PUT' && call.url === '/api/v1/me/email')!.body).toEqual({ email: 'new@example.com', password: 'the own password' })
    expect(auth.setMe).toHaveBeenCalled()
  })

  it('shows what waits, and withdraws it', async () => {
    auth.me = { ...baseMe, email: 'old@example.com', email_confirmed: true, email_pending: 'new@example.com' }
    answers['GET /api/v1/auth/me'] = { ...baseMe, email: 'old@example.com', email_confirmed: true }
    await show()
    const pending = box.querySelector('[data-testid="mail-pending"]')!
    expect(pending.textContent).toContain('Link an new@example.com verschickt.')
    expect(pending.textContent).toContain('Bis du ihn öffnest, bleibt old@example.com.')
    expect(field('Neue Mailadresse')).toBeNull()
    await click(button('Zurückziehen'))
    expect(calls.some((call) => call.method === 'DELETE' && call.url === '/api/v1/me/email/pending')).toBe(true)
  })

  it('marks an address nobody confirmed and offers the link', async () => {
    auth.me = { ...baseMe, email: 'typed@example.com', email_confirmed: false }
    await show()
    expect(box.querySelector('[data-testid="mail-state"]')!.textContent).toBe('nicht bestätigt')
    expect(button('Bestätigung schicken')).toBeTruthy()
  })

  it('says what stands in the way, in words', async () => {
    fails['PUT /api/v1/me/email'] = { status: 409, code: 'mail_off' }
    await show()
    await type(field('Neue Mailadresse'), 'new@example.com')
    await type(field('Passwort'), 'the own password')
    await click(button('Bestätigung schicken'))
    expect(box.textContent).toContain('Es ist kein Mailserver eingetragen.')
  })
})

describe('devices and apps', () => {
  it('pairs a device by a code shown as a QR code, and says when the device took it', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      answers['POST /api/v1/devices/pairing'] = {
        code: 'KRAF-T7Q2-K9XW', expires_at: new Date(Date.now() + 300_000).toISOString(), server: 'https://paper.example.com',
        link: 'nexpaper://pair?server=https%3A%2F%2Fpaper.example.com&code=KRAF-T7Q2-K9XW', qr_svg: '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
      }
      answers['GET /api/v1/devices/pairing'] = { state: 'open', expires_at: null, device: null }
      await show('/konto?tab=devices')
      expect(box.textContent).toContain('Für eigene Programme und Apps.')
      await click(button('Code zum Koppeln zeigen'))
      const shown = box.querySelector('[data-testid="pairing-code"]')!
      expect(shown.textContent).toContain('Mit dem Gerät scannen. Der Code gilt 5 Minuten und nur einmal.')
      expect(shown.textContent).toContain('Oder von Hand: Adresse https://paper.example.com, Code KRAF-T7Q2-K9XW')
      expect(shown.querySelector('img')!.getAttribute('alt')).toBe('QR-Code zum Koppeln')
      answers['GET /api/v1/devices/pairing'] = { state: 'used', expires_at: null, device: { id: 'a'.repeat(32), name: 'iPhone von jule', prefix: 'npd_AbCd', created_at: '2026-10-08T10:00:00Z', last_used_at: null, via: 'qr' } }
      await act(async () => vi.advanceTimersByTime(2100))
      await idle()
      expect(box.querySelector('[data-testid="pairing-code"]')).toBeNull()
      expect(box.textContent).toContain('Gekoppelt. Das Gerät steht jetzt unter Sicherheit bei den angemeldeten Geräten.')
    } finally {
      vi.useRealTimers()
    }
  })

  it('ends a code that is not wanted, and offers a new one when it ran out', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      answers['POST /api/v1/devices/pairing'] = { code: 'KRAF-T7Q2-K9XW', expires_at: new Date(Date.now() + 300_000).toISOString(), server: 'https://paper.example.com', link: '', qr_svg: '<svg/>' }
      answers['POST /api/v1/devices/pairing/cancel'] = 204
      await show('/konto?tab=devices')
      await click(button('Code zum Koppeln zeigen'))
      await click(button('Abbrechen'))
      expect(calls.some((call) => call.method === 'POST' && call.url === '/api/v1/devices/pairing/cancel')).toBe(true)
      expect(box.querySelector('[data-testid="pairing-code"]')).toBeNull()
      await click(button('Code zum Koppeln zeigen'))
      answers['GET /api/v1/devices/pairing'] = { state: 'expired', expires_at: null, device: null }
      await act(async () => vi.advanceTimersByTime(2100))
      await idle()
      expect(box.textContent).toContain('Der Code ist abgelaufen.')
      expect(button('Neuen Code zeigen')).toBeTruthy()
    } finally {
      vi.useRealTimers()
    }
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
    expect(box.querySelector('[data-testid="shortcut-warning"]')!.textContent).toContain('Trag deinen Schlüssel nie in einen Kurzbefehl ein, den du mit anderen teilst')
    answers['GET /api/v1/api-keys'] = { allowed: true, keys: [(answers['POST /api/v1/api-keys'] as { key: unknown }).key] }
    await click(button('Schlüssel für den Kurzbefehl'))
    expect(calls.find((call) => call.method === 'POST' && call.url === '/api/v1/api-keys')!.body).toEqual({ name: 'iPhone-Kurzbefehl', days: null, scope: 'upload' })
    expect(calls.some((call) => call.method === 'POST' && call.url === '/api/v1/devices')).toBe(false)
    const shown = box.querySelector('[data-testid="shortcut-key"]')!
    const values = [...shown.querySelectorAll('input')].map((input) => input.value)
    expect(values).toEqual(['https://paper.example.com/api/v1/documents?source=share', 'Bearer npk_' + 'k'.repeat(43)])
    // The list of keys below shows it at once.
    expect(box.querySelector('[data-testid="api-key"]')!.textContent).toContain('iPhone-Kurzbefehl')
    await click(button('Fertig', shown))
    expect(box.textContent).not.toContain('k'.repeat(43))
  })

  it('says when the operator has not switched keys on, and makes none', async () => {
    answers['GET /api/v1/shortcut'] = { link: '', address: 'https://paper.example.com', upload_url: 'https://paper.example.com/api/v1/documents?source=share' }
    answers['GET /api/v1/api-keys'] = { allowed: false, keys: [] }
    await show('/konto?tab=devices')
    expect(box.querySelector('[data-testid="shortcut-off"]')!.textContent).toContain('API-Schlüssel hat der Betreiber nicht freigegeben')
    expect(box.querySelector('[data-testid="shortcut-off"] a')!.getAttribute('href')).toBe('/einstellungen?tab=api')
    expect(button('Schlüssel für den Kurzbefehl')).toBeUndefined()
  })

  it('offers the shortcut the operator shared', async () => {
    const link = 'https://www.icloud.com/shortcuts/' + '0123456789abcdef'.repeat(2)
    answers['GET /api/v1/shortcut'] = { link, address: 'https://paper.example.com', upload_url: 'https://paper.example.com/api/v1/documents?source=share' }
    await show('/konto?tab=devices')
    expect(box.querySelector('[data-testid="shortcut-link"]')!.getAttribute('href')).toBe(link)
    expect(box.querySelector('[data-testid="shortcut-steps"]')!.textContent).toContain('Auf dem iPhone „Kurzbefehl laden“ antippen und hinzufügen.')
  })

  it('keeps API keys off until the operator allows them, and says where', async () => {
    await show('/konto?tab=devices')
    expect(box.querySelector('[data-testid="api-keys-off"]')!.textContent).toContain('API-Schlüssel sind noch nicht freigegeben.')
    expect(box.querySelector('[data-testid="api-keys-off"] a')!.getAttribute('href')).toBe('/einstellungen?tab=api')
  })

  it('lets the operator allow API keys right there, after asking what it means', async () => {
    answers['PUT /api/v1/settings'] = { api_keys_allowed: true }
    await show('/konto?tab=devices')
    await click(button('Jetzt freigeben'))
    const dialog = document.querySelector('[role="dialog"]')!
    expect(dialog.textContent).toContain('Danach kann jede Person auf diesem Server unter Mein Konto Schlüssel anlegen.')
    expect(dialog.textContent).toContain('jederzeit wieder ausschalten')
    // Nothing was sent before the answer.
    expect(calls.some((call) => call.method === 'PUT')).toBe(false)
    answers['GET /api/v1/api-keys'] = { allowed: true, keys: [] }
    await click(button('Freigeben', dialog))
    expect(calls.find((call) => call.method === 'PUT' && call.url === '/api/v1/settings')!.body).toEqual({ api_keys_allowed: true })
    expect(box.querySelector('[data-testid="api-keys-off"]')).toBeNull()
    expect(button('Neuer Schlüssel')).toBeTruthy()
  })

  it('asks first and sends nothing when the operator says no', async () => {
    await show('/konto?tab=devices')
    await click(button('Jetzt freigeben'))
    await click(button('Abbrechen', document.querySelector('[role="dialog"]')!))
    expect(calls.some((call) => call.method === 'PUT')).toBe(false)
    expect(box.querySelector('[data-testid="api-keys-off"]')).toBeTruthy()
  })

  it('offers no way to allow API keys to somebody who is not the operator', async () => {
    auth.me = { ...baseMe, role: 'member' }
    await show('/konto?tab=devices')
    expect(box.querySelector('[data-testid="api-keys-off"]')!.textContent).toContain('Der Betreiber hat API-Schlüssel nicht freigegeben.')
    expect(button('Jetzt freigeben')).toBeUndefined()
  })

  it('calls the button for the upload key by what it is for, and says what such a key may do', async () => {
    answers['GET /api/v1/api-keys'] = { allowed: true, keys: [] }
    await show('/konto?tab=devices')
    expect(button('Schlüssel zum Hochladen (für Scanner und Apps)')).toBeTruthy()
    expect(box.querySelector('[data-testid="api-keys-upload-note"]')!.textContent).toContain('legt Dokumente nur in einen Eingang: in den deines Ziel-Tresors oder, wenn das Programm einen anderen nennt, in den eines Tresors, in dem du ablegen darfst')
  })

  it('makes a key that is shown once, with its header line, and lists only its first characters after', async () => {
    answers['GET /api/v1/api-keys'] = { allowed: true, keys: [] }
    answers['POST /api/v1/api-keys'] = {
      key: { id: 1, name: 'nexdeck', scope: 'read', prefix: 'npk_AbCd', created_at: '2026-10-08T10:00:00Z', last_used_at: null, expires_at: null, blocked: false },
      secret: 'npk_' + 's'.repeat(43),
    }
    await show('/konto?tab=devices')
    await click(button('Neuer Schlüssel'))
    await type(field('Name'), 'nexdeck')
    answers['GET /api/v1/api-keys'] = { allowed: true, keys: [(answers['POST /api/v1/api-keys'] as { key: unknown }).key] }
    await click(button('Schlüssel anlegen'))
    expect(calls.find((call) => call.method === 'POST' && call.url === '/api/v1/api-keys')!.body).toEqual({ name: 'nexdeck', days: 365, scope: 'read' })
    const shown = box.querySelector('[data-testid="api-key-shown"]')!
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
    await click(button('Neuer Schlüssel'))
    expect(box.textContent).toContain('Ein Schlüssel, der nie abläuft, ist der, an den sich niemand mehr erinnert')
    const chosen = [...box.querySelectorAll('[role="radio"]')].filter((item) => item.getAttribute('aria-checked') === 'true').map((item) => item.textContent)
    expect(chosen).toContain('365 Tage')
    await type(field('Name'), 'forever')
    await click(button('Ohne Ablauf'))
    await click(button('Schlüssel anlegen'))
    expect(calls.find((call) => call.method === 'POST' && call.url === '/api/v1/api-keys')!.body).toEqual({ name: 'forever', days: null, scope: 'read' })
  })

  it('offers no end as the default for a key that only uploads, and a year for one that reads; both stay a choice', async () => {
    answers['GET /api/v1/api-keys'] = { allowed: true, keys: [] }
    answers['POST /api/v1/api-keys'] = {
      key: { id: 4, name: 'Scanner', scope: 'upload', prefix: 'npk_Sc12', created_at: '2026-10-08T10:00:00Z', last_used_at: null, expires_at: null, blocked: false },
      secret: 'npk_' + 'c'.repeat(43),
    }
    await show('/konto?tab=devices')
    const chosenLifetime = () => [...box.querySelectorAll('[aria-label="Gültig"] [role="radio"]')].filter((item) => item.getAttribute('aria-checked') === 'true').map((item) => item.textContent)
    await click(button('Schlüssel zum Hochladen (für Scanner und Apps)'))
    expect(chosenLifetime()).toEqual(['Ohne Ablauf'])
    expect(box.textContent).toContain('läuft er von sich aus nicht ab')
    // The person's own pick is kept when the kind of key changes afterwards; a pick of none is not overridden.
    await click(button('365 Tage'))
    expect(chosenLifetime()).toEqual(['365 Tage'])
    await click(button('nur lesen'))
    expect(chosenLifetime()).toEqual(['365 Tage'])
    await click(button('nur hochladen'))
    await type(field('Name'), 'Scanner')
    await click(button('Schlüssel anlegen'))
    expect(calls.find((call) => call.method === 'POST' && call.url === '/api/v1/api-keys')!.body).toEqual({ name: 'Scanner', days: 365, scope: 'upload' })
  })

  it('makes a key for uploading, with the command that uploads and the limits', async () => {
    answers['GET /api/v1/api-keys'] = { allowed: true, keys: [] }
    answers['POST /api/v1/api-keys'] = {
      key: { id: 2, name: 'Scanner im Flur', scope: 'upload', prefix: 'npk_Up12', created_at: '2026-10-08T10:00:00Z', last_used_at: null, expires_at: null, blocked: false },
      secret: 'npk_' + 'u'.repeat(43),
    }
    await show('/konto?tab=devices')
    expect(box.textContent).toContain('Grenzen je Schlüssel: 120 Anfragen in der Minute, 50 Uploads in der Stunde.')
    await click(button('Schlüssel zum Hochladen (für Scanner und Apps)'))
    expect(box.querySelector('[aria-checked="true"]')!.textContent).toBe('nur hochladen')
    await type(field('Name'), 'Scanner im Flur')
    answers['GET /api/v1/api-keys'] = { allowed: true, keys: [(answers['POST /api/v1/api-keys'] as { key: unknown }).key] }
    await click(button('Schlüssel anlegen'))
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
    expect(box.textContent).toContain('Hell oder dunkel')
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
    expect(box.querySelector('button[role="switch"]')!.getAttribute('aria-checked')).toBe('true')
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
