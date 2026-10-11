/**
 * A new password by a link, in the interface, against a stand-in of the server: "Forgot your password?" only where the
 * server offers it, the page that asks for the link (the same answer for every name), the page of the link (two equal
 * passwords, a link that does not hold), and the operator who sends a link instead of setting a password: by mail, or
 * shown once to pass on. Also the passkey button that follows what the server offers, and the new red points.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import type { Me } from '../api/client'
import '../i18n'
import { changeLanguage } from '../i18n'
import { ForgotPage, LoginPage, MailConfirmPage, ResetPage } from './AuthPages'
import { ReadinessCard } from './settings/ReadinessCards'
import { PasskeysCard } from './settings/SecurityCards'
import { AccountsCard, ApiKeysCard, BackupsCard, type ServerSettings } from './settings/ServerCards'
import { idle } from '../test/wait'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: 'jule@example.com', language: 'de',
  oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.1.0', whats_new_seen: '0.1.0',
  session_stage: 'full', second_factor_required: true,
  email_confirmed: true, email_pending: '',
  profile: { mode: 'light', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true },
}
const auth = { status: 'signedOut' as string, me: me as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
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
      if (found && typeof found === 'object' && 'refused' in found) {
        return new Response(JSON.stringify({ detail: { code: (found as { refused: string }).refused } }), { status: 404, headers: { 'Content-Type': 'application/json' } })
      }
      return new Response(JSON.stringify(found ?? {}), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }),
  )
}

let root: Root
let box: HTMLDivElement


async function show(element: React.ReactNode, at = '/login', path = '*'): Promise<void> {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  box = document.createElement('div')
  document.body.appendChild(box)
  root = createRoot(box)
  await act(async () =>
    root.render(
      <MemoryRouter initialEntries={[at]}>
        <Routes>
          <Route path={path} element={element} />
        </Routes>
      </MemoryRouter>,
    ),
  )
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
  return found?.querySelector('input') ?? null
}

async function submit(form: HTMLFormElement | null): Promise<void> {
  expect(form).toBeTruthy()
  await act(async () => form!.requestSubmit())
  await idle()
}

beforeEach(async () => {
  await changeLanguage('de', false)
  auth.status = 'signedOut'
  auth.me = me
  answers = { 'GET /api/v1/auth/methods': { password: true, providers: [], passkeys: false, forgot: false } }
  serve()
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

describe('"Passwort vergessen?" on the sign-in page', () => {
  it('shows the link only where the server offers it', async () => {
    await show(<LoginPage />)
    expect(box.textContent).not.toContain('Passwort vergessen?')
    act(() => root.unmount())
    box.remove()
    answers['GET /api/v1/auth/methods'] = { password: true, providers: [], passkeys: false, forgot: true }
    await show(<LoginPage />)
    const link = [...box.querySelectorAll('a')].find((item) => item.textContent === 'Passwort vergessen?')
    expect(link?.getAttribute('href')).toBe('/forgot')
  })

  it('asks for the link with the name, and says the same whatever the name is', async () => {
    answers['GET /api/v1/auth/methods'] = { password: true, providers: [], passkeys: false, forgot: true }
    answers['POST /api/v1/auth/forgot'] = { ok: true }
    await show(<ForgotPage />, '/forgot')
    expect(box.querySelector('h1')!.textContent).toBe('Passwort vergessen')
    await type(field('Name oder Mailadresse'), '  ghost ')
    await submit(box.querySelector('form'))
    expect(calls.find((call) => call.url === '/api/v1/auth/forgot')!.body).toEqual({ name: 'ghost' })
    expect(box.textContent).toContain('Wenn es dazu ein Konto gibt, ist ein Link unterwegs.')
    expect(box.textContent).not.toContain('nicht gefunden')
  })

  it('says at once that nothing is sent when the server has no mail set up, and asks nothing of it', async () => {
    await show(<ForgotPage />, '/forgot')
    expect(box.textContent).toContain('Das ist auf diesem Server nicht eingerichtet.')
    expect(box.querySelector('form')).toBeNull()
    expect(calls.some((call) => call.url === '/api/v1/auth/forgot')).toBe(false)
  })

  it('still says so when the mail was switched off between the page opening and the request', async () => {
    answers['GET /api/v1/auth/methods'] = { password: true, providers: [], passkeys: false, forgot: true }
    answers['POST /api/v1/auth/forgot'] = { refused: 'reset_off' }
    await show(<ForgotPage />, '/forgot')
    await type(field('Name oder Mailadresse'), 'anna')
    await submit(box.querySelector('form'))
    expect(box.textContent).toContain('Das ist auf diesem Server nicht eingerichtet.')
  })
})

describe('the page of the link', () => {
  const at = '/reset/' + 'a'.repeat(30)

  it('takes two equal passwords and sets them', async () => {
    answers[`GET /api/v1/reset/${'a'.repeat(30)}`] = { name: 'anna', min_password: 12 }
    answers[`POST /api/v1/reset/${'a'.repeat(30)}`] = 204
    await show(<ResetPage />, at, '/reset/:token')
    expect(box.textContent).toContain('Wähle ein neues Passwort für anna.')
    await type(field('Neues Passwort'), 'a long enough password')
    await type(field('Noch einmal'), 'another long password')
    await submit(box.querySelector('form'))
    expect(calls.some((call) => call.method === 'POST')).toBe(false)
    expect(box.textContent).toContain('Die beiden neuen Passwörter sind nicht gleich.')
    await type(field('Noch einmal'), 'a long enough password')
    await submit(box.querySelector('form'))
    expect(calls.find((call) => call.method === 'POST')!.body).toEqual({ password: 'a long enough password' })
    expect(box.querySelector('h1')!.textContent).toBe('Passwort gespeichert')
  })

  it('says so when the link does not hold, at once and after trying', async () => {
    answers[`GET /api/v1/reset/${'a'.repeat(30)}`] = { refused: 'reset_invalid' }
    await show(<ResetPage />, at, '/reset/:token')
    expect(box.querySelector('h1')!.textContent).toBe('Link nicht gültig')
    act(() => root.unmount())
    box.remove()
    answers[`GET /api/v1/reset/${'a'.repeat(30)}`] = { name: 'anna', min_password: 12 }
    answers[`POST /api/v1/reset/${'a'.repeat(30)}`] = { refused: 'reset_invalid' }
    await show(<ResetPage />, at, '/reset/:token')
    await type(field('Neues Passwort'), 'a long enough password')
    await type(field('Noch einmal'), 'a long enough password')
    await submit(box.querySelector('form'))
    expect(box.querySelector('h1')!.textContent).toBe('Link nicht gültig')
  })
})

describe("the operator sends a link instead of setting a password", () => {
  const rows = [
    { ...me, locked: false, has_password: true, created_at: '2026-10-01T10:00:00Z', last_seen_at: null },
    { ...me, id: 2, name: 'anna', display_name: 'Anna', role: 'member', locked: false, has_password: true, created_at: '2026-10-01T10:00:00Z', last_seen_at: null },
  ]

  async function ask(): Promise<void> {
    answers['GET /api/v1/accounts'] = rows
    answers['GET /api/v1/invites'] = []
    await show(<AccountsCard />, '/einstellungen')
    expect(box.textContent).not.toContain('Passwort geben')
    await click(button('Link zum Zurücksetzen schicken', box))
    const dialog = document.querySelector('[role="dialog"]')!
    expect(dialog.textContent).toContain('Die Person wählt ihr Passwort selbst.')
    await type(dialog.querySelector<HTMLInputElement>('input[type="password"]'), 'the own password')
    await submit(dialog.querySelector('form'))
  }

  it('sends it by mail where that works, and the interface says where it went', async () => {
    answers['POST /api/v1/accounts/2/reset-link'] = { sent: true, email: 'anna@example.com', expires_at: '2026-10-08T10:00:00Z' }
    await ask()
    expect(calls.find((call) => call.url === '/api/v1/accounts/2/reset-link')!.body).toEqual({ current_password: 'the own password' })
    expect(box.textContent).toContain('Der Link für anna ging an anna@example.com.')
    expect(calls.some((call) => call.url.endsWith('/password'))).toBe(false)
  })

  it('shows the link once where mail does not work, and never a password', async () => {
    answers['POST /api/v1/accounts/2/reset-link'] = { sent: false, link: 'https://paper.example.com/reset/abc', expires_at: '2026-10-08T10:00:00Z' }
    await ask()
    expect(box.textContent).toContain('Der Link für anna, nur jetzt zu sehen')
    expect(box.querySelector<HTMLInputElement>('input[readonly]')?.value ?? box.textContent).toContain('https://paper.example.com/reset/abc')
    expect(box.textContent).not.toContain('Das neue Passwort für')
  })
})

describe('what the server offers', () => {
  it('turns the passkey button off where the server offers no passkeys', async () => {
    Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
    vi.stubGlobal('PublicKeyCredential', function PublicKeyCredential() {})
    answers['GET /api/v1/auth/passkeys'] = []
    answers['GET /api/v1/auth/methods'] = { password: true, providers: [], passkeys: false }
    await show(<PasskeysCard me={me} />, '/konto')
    expect(button('Passkey anlegen', box)!.disabled).toBe(true)
    act(() => root.unmount())
    box.remove()
    answers['GET /api/v1/auth/methods'] = { password: true, providers: [], passkeys: true }
    await show(<PasskeysCard me={me} />, '/konto')
    expect(button('Passkey anlegen', box)!.disabled).toBe(false)
  })

  it('says why the brake and the proxy are red when public networks are trusted', async () => {
    answers['GET /api/v1/settings/readiness'] = {
      open: 2,
      points: [
        { key: 'brake', state: 'bad', values: { networks: '0.0.0.0/0' } },
        { key: 'proxy', state: 'bad', values: { proxies: '0.0.0.0/0', networks: '0.0.0.0/0' } },
      ],
    }
    await show(<ReadinessCard />, '/einstellungen')
    expect([...box.querySelectorAll('li')].map((item) => item.getAttribute('data-state'))).toEqual(['bad', 'bad'])
    expect(box.textContent).toContain('enthält öffentliche Netze (0.0.0.0/0)')
    expect(box.textContent).toContain('nicht auf das ganze Internet')
  })

  it('says when the protection against guessing fails its own test', async () => {
    answers['GET /api/v1/settings/readiness'] = { open: 1, points: [{ key: 'brake', state: 'bad', values: { broken: true } }] }
    await show(<ReadinessCard />, '/einstellungen')
    expect(box.textContent).toContain('besteht seinen eigenen Test nicht')
  })
})

describe("the operator's pages say what they hold", () => {
  const settings: ServerSettings = {
    public_url: 'https://paper.example.com', password_login: true, two_factor_required: true,
    backup_schedule: 'daily', backup_keep: 7, smtp_host: '', smtp_port: 587, smtp_security: 'starttls', smtp_user: '', smtp_password_set: false, smtp_from: '',
    api_keys_allowed: true, update_check: true, links_allowed: true, link_max_days: 30,
    upload_max_mb: 200, upload_max_pages: 2000, upload_max_megapixels: 100, upload_open_count: 10, upload_open_mb: 4096, process_timeout_seconds: 300, process_memory_mb: 2048, cache_max_mb: 1024,
  }
  const server = { settings, save: vi.fn(), setSettings: vi.fn(), busy: false, problem: null, done: null, run: vi.fn() } as unknown as Parameters<typeof BackupsCard>[0]['server']

  it('tells that a backup holds the secrets of the server and not the documents, in German and in English', async () => {
    answers['GET /api/v1/backups'] = []
    await show(<BackupsCard server={server} />, '/einstellungen')
    expect(box.textContent).toContain('die Zugänge für Mail und KI und die Adressen offener Links. Bewahre sie darum geschützt auf, wie ein Passwort.')
    const notice = box.querySelector('[data-testid="backup-without-documents"]')!
    expect(notice.textContent).toContain('Die Dokumente selbst sind nicht in der Sicherung.')
    expect(notice.textContent).toContain('/data/dokumente')
    act(() => root.unmount())
    box.remove()
    await changeLanguage('en', false)
    await show(<BackupsCard server={server} />, '/einstellungen')
    expect(box.textContent).toContain('the mail and AI credentials and the addresses of open links, so keep it protected, like a password.')
    expect(box.querySelector('[data-testid="backup-without-documents"]')!.textContent).toContain('The documents themselves are not in the backup.')
  })

  it('points from the switch to where the own keys are made', async () => {
    await show(<ApiKeysCard server={server} />, '/einstellungen')
    const link = [...box.querySelectorAll('a')].find((a) => a.textContent === 'Eigene Schlüssel anlegen')
    expect(link).toBeTruthy()
    expect(link!.getAttribute('href')).toBe('/konto?tab=devices')
  })

  it('shows the operator whose key it is, what it is called and its first characters, never the key', async () => {
    answers['GET /api/v1/admin/api-keys'] = [
      { id: 1, account: 'anna', name: 'nexdeck', scope: 'read', prefix: 'npk_Ab3d', created_at: '2026-10-01T10:00:00Z', last_used_at: null, expires_at: null, blocked: false },
    ]
    await show(<ApiKeysCard server={server} />, '/einstellungen')
    const row = box.querySelector('[data-testid="admin-api-keys"] li')!
    expect(row.textContent).toContain('npk_Ab3d')
    expect(row.textContent).toContain('nexdeck')
    expect(row.textContent).toContain('anna')
    expect(row.textContent).not.toContain('undefined')
  })
})


describe('the page of a link that confirms a mail address', () => {
  const link = 'x'.repeat(30)

  it('says whom the address is for, writes it only on the button, and says when the old address was told', async () => {
    answers[`GET /api/v1/email/confirm/${link}`] = { name: 'jule', address: 'new@example.com' }
    answers[`POST /api/v1/email/confirm/${link}`] = { name: 'jule', address: 'new@example.com', old_told: true }
    await show(<MailConfirmPage />, `/mail/${link}`, '/mail/:token')
    expect(box.textContent).toContain('new@example.com')
    expect(calls.map((call) => call.method)).toEqual(['GET'])
    await submit(box.querySelector('form'))
    expect(calls.map((call) => call.method)).toEqual(['GET', 'POST'])
    expect(box.querySelector('[role="status"]')!.textContent).toBe(
      'new@example.com gilt jetzt für dein Konto. Die bisherige Adresse haben wir über die Änderung benachrichtigt.',
    )
  })

  it('does not claim the old address was told when it was not', async () => {
    answers[`GET /api/v1/email/confirm/${link}`] = { name: 'jule', address: 'new@example.com' }
    answers[`POST /api/v1/email/confirm/${link}`] = { name: 'jule', address: 'new@example.com', old_told: false }
    await show(<MailConfirmPage />, `/mail/${link}`, '/mail/:token')
    await submit(box.querySelector('form'))
    expect(box.querySelector('[role="status"]')!.textContent).toBe('new@example.com gilt jetzt für dein Konto.')
  })

  it('says so when the link does not hold', async () => {
    answers[`GET /api/v1/email/confirm/${link}`] = { refused: 'email_link_invalid' }
    await show(<MailConfirmPage />, `/mail/${link}`, '/mail/:token')
    expect(box.querySelector('form')).toBeNull()
    expect(box.textContent).toContain('Link')
  })
})
