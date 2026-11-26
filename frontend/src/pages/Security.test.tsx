/**
 * Security in the interface, against a stand-in of the server: the sign-in with "stay signed in", the code step (and a
 * passkey-only account), the setup of the second factor right after the password with the recovery codes shown once,
 * the signed-in devices, the passkeys, the last factor that cannot go where the operator requires one, "Ready for the
 * internet?".
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

import type { Me } from '../api/client'
import '../i18n'
import { changeLanguage } from '../i18n'
import { LoginPage } from './AuthPages'
import { PasskeysBox, SecondFactorBox, SessionsBox } from './settings/SecurityBoxes'
import { SignInArea } from './settings/SignInArea'
import { idle } from '../test/wait'

const NOW = Date.now()
const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: 'jule@example.com', language: 'de',
  oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.1.0', whats_new_seen: '0.1.0',
  session_stage: 'full', second_factor_required: true,
  email_confirmed: true, email_pending: '',
  profile: { mode: 'light', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true, deadlines: true },
}
const auth = { status: 'signedOut' as string, me: null as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth, safeNext: (next: string | null) => next ?? '/' }))

type Call = { method: string; url: string; body: Record<string, unknown> | undefined }
let calls: Call[] = []
let answers: Record<string, unknown> = {}

function serve(): void {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, url, body })
      const found = answers[`${method} ${url}`]
      if (found === 204) return new Response(null, { status: 204 })
      // A file answer as plain bytes: Node 22's Response does not take jsdom's Blob (it did in Node 25), so the
      // test hands over the text and lets the real Response make the blob the client reads.
      if (found instanceof Blob) return new Response(await found.text(), { status: 200 })
      return new Response(JSON.stringify(found ?? {}), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }),
  )
}

let root: Root
let box: HTMLDivElement

async function show(element: React.ReactNode, at = '/login'): Promise<void> {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  box = document.createElement('div')
  document.body.appendChild(box)
  root = createRoot(box)
  await act(async () => root.render(<MemoryRouter initialEntries={[at]}>{element}</MemoryRouter>))
  await idle()
}


function button(text: string, within: ParentNode = document): HTMLButtonElement | undefined {
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

async function submit(form: HTMLFormElement | null): Promise<void> {
  expect(form).toBeTruthy()
  await act(async () => form!.requestSubmit())
  await idle()
}

function passkeysInTheBrowser(on: boolean): void {
  Object.defineProperty(window, 'isSecureContext', { value: on, configurable: true })
  if (on) vi.stubGlobal('PublicKeyCredential', function PublicKeyCredential() {})
}

beforeEach(async () => {
  await changeLanguage('de', false)
  auth.status = 'signedOut'
  auth.me = null
  auth.setMe.mockClear()
  answers = { 'GET /api/v1/auth/methods': { password: true, providers: [], passkeys: true } }
  serve()
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
  vi.unstubAllGlobals()
})

describe('signing in', () => {
  it('stays signed in when ticked, and the code step may change that', async () => {
    passkeysInTheBrowser(false)
    answers['POST /api/v1/auth/login'] = { second_factor: true, totp: true, passkey: false }
    answers['POST /api/v1/auth/login/totp'] = me
    answers['GET /api/v1/auth/me'] = me
    await show(<LoginPage />)
    const remember = box.querySelector<HTMLInputElement>('input[type="checkbox"]')!
    expect(remember.checked).toBe(true)
    expect(box.textContent).toContain('Auf diesem Gerät angemeldet bleiben')
    // No passkey button where the browser has none.
    expect(button('Mit Passkey anmelden')).toBeUndefined()
    await type(field('Benutzername oder E-Mail'), 'jule')
    await type(field('Passwort'), 'a long enough password')
    await submit(box.querySelector('form'))
    expect(calls.find((call) => call.url === '/api/v1/auth/login')!.body).toEqual({ name: 'jule', password: 'a long enough password', remember: true })
    expect(box.querySelector('h1')!.textContent).toBe('Zweiter Faktor')
    await click(box.querySelector<HTMLInputElement>('input[type="checkbox"]')!)
    await type(field('Code aus der App'), '123456')
    await submit(box.querySelector('form'))
    expect(calls.find((call) => call.url === '/api/v1/auth/login/totp')!.body).toEqual({ code: '123456', remember: false })
    expect(auth.setMe).toHaveBeenCalledWith(me)
  })

  it('says so when "stay signed in" is taken off at the password', async () => {
    passkeysInTheBrowser(false)
    answers['POST /api/v1/auth/login'] = me
    answers['GET /api/v1/auth/me'] = me
    await show(<LoginPage />)
    await click(box.querySelector<HTMLInputElement>('input[type="checkbox"]')!)
    await type(field('Benutzername oder E-Mail'), 'jule')
    await type(field('Passwort'), 'a long enough password')
    await submit(box.querySelector('form'))
    expect(calls.find((call) => call.url === '/api/v1/auth/login')!.body).toEqual({ name: 'jule', password: 'a long enough password', remember: false })
  })

  it('offers the passkey, and an account with only a passkey is asked for it or a recovery code', async () => {
    passkeysInTheBrowser(true)
    answers['POST /api/v1/auth/login'] = { second_factor: true, totp: false, passkey: true }
    await show(<LoginPage />)
    expect(button('Mit Passkey anmelden')).toBeTruthy()
    await type(field('Benutzername oder E-Mail'), 'jule')
    await type(field('Passwort'), 'a long enough password')
    await submit(box.querySelector('form'))
    expect(box.textContent).toContain('Melde dich mit deinem Passkey an oder gib einen Wiederherstellungscode ein.')
    expect(field('Wiederherstellungscode')).toBeTruthy()
    expect(button('Mit Passkey anmelden')).toBeTruthy()
  })
})

describe('the second factor right after the password', () => {
  it('shows the code for the app, then the recovery codes once, and only "I have them" makes the session full', async () => {
    auth.status = 'signedIn'
    auth.me = { ...me, two_factor: false, totp: false, session_stage: 'setup', second_factor_setup_required: true }
    // Made at run time: a seed written out in a test looks like a real one to the scanners.
    const seed = Array.from({ length: 16 }, (_, index) => 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'[(index * 7 + 3) % 32]).join('')
    answers['POST /api/v1/auth/totp/begin'] = { secret: seed, uri: 'otpauth://totp/x', qr_svg: '<svg xmlns="http://www.w3.org/2000/svg"></svg>' }
    const codes = ['abcde-fghjk', 'mnpqr-stuvw', 'xyz23-45678', 'abcde-23456', 'fghjk-78923', 'mnpqr-xyz23', 'stuvw-45678', 'abcde-mnpqr']
    answers['POST /api/v1/auth/totp/confirm'] = { recovery_codes: codes }
    answers['POST /api/v1/auth/setup/done'] = me
    await show(<LoginPage />)
    expect(box.querySelector('h1')!.textContent).toBe('Zweiten Faktor einrichten')
    expect(calls.filter((call) => call.url === '/api/v1/auth/totp/begin')).toHaveLength(1)
    expect(box.querySelector('[data-testid="totp-secret"]')!.textContent).toBe(seed.match(/.{4}/g)!.join(' '))
    expect(box.querySelector('img')!.getAttribute('src')).toContain('data:image/svg+xml')
    await type(field('Code aus der App'), '123456')
    await submit(box.querySelector('form'))
    expect(calls.find((call) => call.url === '/api/v1/auth/totp/confirm')!.body).toEqual({ code: '123456' })
    expect(box.querySelector('h1')!.textContent).toBe('Deine Wiederherstellungscodes')
    expect([...box.querySelectorAll('[data-testid="recovery-codes"] li')].map((item) => item.textContent)).toEqual(codes)
    expect(calls.some((call) => call.url === '/api/v1/auth/setup/done')).toBe(false)
    await click(button('Ich habe sie, weiter', box))
    expect(calls.some((call) => call.url === '/api/v1/auth/setup/done')).toBe(true)
    expect(auth.setMe).toHaveBeenCalledWith(me)
  })

  it('makes the codes anew after a reload, while they wait to be confirmed', async () => {
    auth.status = 'signedIn'
    auth.me = { ...me, session_stage: 'codes', second_factor_setup_required: true }
    answers['POST /api/v1/auth/setup/codes'] = { recovery_codes: ['abcde-fghjk'] }
    await show(<LoginPage />)
    expect(calls.filter((call) => call.url === '/api/v1/auth/setup/codes')).toHaveLength(1)
    expect(calls.some((call) => call.url === '/api/v1/auth/totp/begin')).toBe(false)
    expect(box.textContent).toContain('abcde-fghjk')
  })
})

describe('the own account, Security', () => {
  it('lists the signed-in devices and signs out one', async () => {
    answers['GET /api/v1/auth/sessions'] = [
      { id: 'a'.repeat(32), device: 'Firefox unter Windows', phone: false, network: 'Netz 203.0.113.0/24', created_at: new Date(NOW).toISOString(), last_seen_at: new Date(NOW).toISOString(), remember: true, here: true },
      { id: 'b'.repeat(32), device: 'Safari unter iPhone', phone: true, network: 'eigenes Netz 192.168.1.0/24', created_at: new Date(NOW).toISOString(), last_seen_at: new Date(NOW - 2 * 3600_000).toISOString(), remember: true, here: false },
    ]
    answers[`DELETE /api/v1/auth/sessions/${'b'.repeat(32)}`] = 204
    answers['POST /api/v1/auth/logout-all'] = 204
    await show(<SessionsBox />, '/settings/security')
    const rows = [...box.querySelectorAll('[data-testid="sessions"] li')]
    expect(rows[0].textContent).toContain('dieses Gerät')
    expect(rows[1].textContent).toContain('eigenes Netz 192.168.1.0/24 · zuletzt vor 2 Stunden')
    expect(button('Abmelden', rows[0])).toBeUndefined()
    // The module's button in a row: small, red, with its symbol (konten 1.1.0, ui 1.1.0).
    const end = button('Abmelden', rows[1])!
    expect([end.dataset.kind, end.dataset.size, end.dataset.icon]).toEqual(['danger', 'sm', 'LogOut'])
    await click(end)
    // Asked first: Abbrechen sends nothing, the red button sends the one request.
    const sessionCall = (call: { method: string; url: string }) => call.method === 'DELETE' && call.url === `/api/v1/auth/sessions/${'b'.repeat(32)}`
    expect(calls.some(sessionCall)).toBe(false)
    await click(button('Abbrechen', document.body.querySelector<HTMLElement>('[role="dialog"]')!))
    expect(calls.some(sessionCall)).toBe(false)
    await click(button('Abmelden', rows[1]))
    await click(button('Sitzung beenden', document.body.querySelector<HTMLElement>('[role="dialog"]')!))
    expect(calls.some(sessionCall)).toBe(true)
    expect(box.textContent).toContain('Safari unter iPhone ist abgemeldet.')
    // The module's part "sessions": its title and hint; "Überall sonst abmelden" comes with the page (Account.test.tsx),
    // the mail of a new sign-in is a part of its own.
    expect(box.textContent).toContain('Angemeldete Geräte')
    expect(box.textContent).not.toContain('Bei einer neuen Anmeldung Bescheid geben')
  })

  it('lists the passkeys and removes one with the password', async () => {
    passkeysInTheBrowser(true)
    const id = 'c'.repeat(32)
    answers['GET /api/v1/auth/passkeys'] = [{ id, name: 'Windows Hello', created_at: new Date(NOW).toISOString(), last_used_at: null, credential: 'abcdefgh' }]
    answers[`POST /api/v1/auth/passkeys/${id}/remove`] = me
    await show(<PasskeysBox me={me} />, '/settings/security')
    expect(box.querySelector('[data-testid="passkeys"]')!.textContent).toContain('angelegt heute · zuletzt noch nie')
    const remove = button('Passkey Windows Hello entfernen', box)!
    expect([remove.dataset.kind, remove.dataset.size]).toEqual(['danger', 'sm'])
    await click(remove)
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]')!
    // The password field in the account module's words.
    expect(field('Passwort', dialog)!.type).toBe('password')
    await type(dialog.querySelector<HTMLInputElement>('input[type="password"]'), 'the own password')
    await submit(dialog.querySelector('form'))
    expect(calls.find((call) => call.url === `/api/v1/auth/passkeys/${id}/remove`)!.body).toEqual({ password: 'the own password' })
  })

  describe('the hint under "Passkey hinzufügen"', () => {
    const hint = () => box.querySelector('[data-testid="passkeys-unavailable"]')

    it('tells the operator where to enter the public address, with a link there, when the server has none', async () => {
      passkeysInTheBrowser(true)
      answers['GET /api/v1/auth/methods'] = { password: true, providers: [], passkeys: false }
      await show(<PasskeysBox me={me} />, '/settings/security')
      expect(hint()!.textContent).toBe('Trag zuerst die öffentliche Adresse ein (Einstellungen → Anmeldung).')
      expect(hint()!.querySelector('a')!.getAttribute('href')).toBe('/settings/sign-in')
      expect(hint()!.textContent).not.toContain('nur über https')
      expect(button('Passkey hinzufügen', box)!.disabled).toBe(true)
    })

    it('tells a member that the operator has to enter it, and links nowhere', async () => {
      passkeysInTheBrowser(true)
      answers['GET /api/v1/auth/methods'] = { password: true, providers: [], passkeys: false }
      await show(<PasskeysBox me={{ ...me, role: 'member' }} />, '/settings/security')
      expect(hint()!.textContent).toBe('Dein Betreiber muss erst die öffentliche Adresse eintragen.')
      expect(hint()!.querySelector('a')).toBeNull()
    })

    it('says it in English as well, for both', async () => {
      await changeLanguage('en', false)
      passkeysInTheBrowser(true)
      answers['GET /api/v1/auth/methods'] = { password: true, providers: [], passkeys: false }
      await show(<PasskeysBox me={me} />, '/settings/security')
      expect(hint()!.textContent).toBe('Enter the public address first (Settings → Sign-in).')
      expect(hint()!.querySelector('a')!.getAttribute('href')).toBe('/settings/sign-in')
      act(() => root.unmount())
      box.remove()
      await show(<PasskeysBox me={{ ...me, role: 'member' }} />, '/settings/security')
      expect(hint()!.textContent).toBe('Your operator has to enter the public address first.')
    })

    it('keeps the old sentence for a browser that cannot (no https, no API), whatever the server says', async () => {
      passkeysInTheBrowser(false)
      answers['GET /api/v1/auth/methods'] = { password: true, providers: [], passkeys: true }
      await show(<PasskeysBox me={me} />, '/settings/security')
      expect(hint()!.textContent).toBe('Passkeys gibt es nur über https (oder localhost) und in Browsern, die sie kennen.')
      expect(hint()!.querySelector('a')).toBeNull()
    })

    it('says nothing when passkeys can be made', async () => {
      passkeysInTheBrowser(true)
      await show(<PasskeysBox me={me} />, '/settings/security')
      expect(hint()).toBeNull()
      expect(button('Passkey hinzufügen', box)!.disabled).toBe(false)
    })
  })

  it('cannot turn off the last factor where the operator requires one', async () => {
    await show(<SecondFactorBox me={me} part="factor" />, '/settings/security')
    expect(box.textContent).toContain('Ausschalten geht nicht: Der Betreiber verlangt ihn für alle.')
    expect(button('Authenticator-App entfernen', box)).toBeUndefined()
    act(() => root.unmount())
    await show(<SecondFactorBox me={{ ...me, passkeys: 1 }} part="factor" />, '/settings/security')
    expect(button('Authenticator-App entfernen', box)).toBeTruthy()
  })
})

describe("the operator's checks", () => {
  /** Server › Sign-in with the server's answers: the module's page, nexpaper's points among the shared ones. */
  async function signIn(readiness: unknown): Promise<void> {
    auth.status = 'signedIn'
    auth.me = me
    answers['GET /api/v1/server/sign-in'] = {
      password_login: true, factor_required: false, passkeys_allowed: true, password_may_go_off: false, factor_may_go_on: true,
      public_url: 'https://paper.example.com', public_url_effective: 'https://paper.example.com', operator_has_password: true,
    }
    answers['GET /api/v1/oidc/admin/providers'] = []
    answers['GET /api/v1/oidc/authentik/address'] = { public_url: 'https://paper.example.com', seen: 'https://paper.example.com', forwarded_proto: '', forwarded_host: '', proxy_ignored: false, callback_path: '/api/v1/oidc/authentik/callback' }
    answers['GET /api/v1/server/readiness'] = readiness
    // Which points are open is kept per device; each look starts with all closed.
    localStorage.removeItem('nexpaper.fold.ready')
    await show(<SignInArea />, '/settings/sign-in')
  }
  /** A point of "Bereit fürs Internet?", opened (all are closed at first): its state and its sentence. */
  async function opened(key: string): Promise<{ state: string | null; text: string }> {
    const point = box.querySelector(`#ready-${key}`)!
    expect(point.querySelector('[aria-expanded]')!.getAttribute('aria-expanded')).toBe('false')
    await click(point.querySelector<HTMLElement>('[aria-expanded]')!)
    return { state: point.querySelector('[data-state]')!.getAttribute('data-state'), text: box.querySelector(`[data-testid="ready-text-${key}"]`)!.textContent ?? '' }
  }

  it('shows each point with its state and counts the open ones', async () => {
    await signIn({
      state: 'bad',
      open: 2,
      points: [
        { key: 'address', state: 'ok', title: 'account.ready.address.title', text: 'account.ready.address.ok', values: { address: 'https://paper.example.com', app: 'nexpaper' } },
        { key: 'factorForAll', state: 'bad', title: 'account.ready.factorForAll.title', text: 'account.ready.factorForAll.bad', values: {} },
        { key: 'proxy', state: 'warn', title: 'account.ready.proxy.title', text: 'account.ready.proxy.warn', values: { proxy: '172.18.0.2', variable: 'NEXPAPER_TRUSTED_PROXIES' } },
      ],
    })
    // The module's card, asked of the module's route (the old /api/v1/settings/readiness stays for scripts).
    expect(calls.some((call) => call.url === '/api/v1/server/readiness')).toBe(true)
    expect(box.querySelector('[data-card="sign-in-ready"]')).toBeTruthy()
    expect(box.querySelector('[data-testid="ready-summary"]')!.textContent).toBe('2 Punkte offen')
    expect([...box.querySelectorAll('[id^="ready-"] [data-state]')].map((item) => item.getAttribute('data-state'))).toEqual(['ok', 'bad', 'warn'])
    expect((await opened('address')).text).toContain('https://paper.example.com')
    expect((await opened('factorForAll')).text).toContain('Aus: Ein erratenes oder gestohlenes Passwort reicht')
    expect((await opened('proxy')).text).toContain('Setze NEXPAPER_TRUSTED_PROXIES auf seine Adresse.')
  })

  it('names the secrets of the server, the backups and the upload requests as points of their own', async () => {
    await signIn({
      state: 'warn',
      open: 2,
      points: [
        { key: 'secrets', state: 'ok', title: 'ready.secrets.title', text: 'ready.secrets.env', values: { source: 'environment' } },
        { key: 'backups', state: 'warn', title: 'ready.backups.title', text: 'ready.backups.warn', values: { schedule: 'off' } },
        { key: 'upload_requests', state: 'warn', title: 'uploadRequest.ready.title', text: 'uploadRequest.ready.warn', values: { on: true, count: 2 } },
      ],
    })
    expect(box.textContent).toContain('Server-Geheimnisse')
    expect((await opened('secrets')).text).toContain('Der Schlüssel kommt aus NEXPAPER_SECRET_KEY, nicht aus einer Datei.')
    expect((await opened('backups')).text).toContain('Keine automatische Sicherung. Schalte sie unter Einstellungen, Sicherung ein.')
    expect((await opened('upload_requests')).text).toContain('Gerade nehmen 2 Bitten etwas an.')
  })
})
