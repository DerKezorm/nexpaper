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
import { AccountsTab } from './settings/AccountsTab'
import { AllKeys } from './settings/KeysCards'
import { PasskeysBox } from './settings/SecurityBoxes'
import { SignInArea } from './settings/SignInArea'
import { StorageArea } from './settings/StorageArea'
import { idle } from '../test/wait'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: 'jule@example.com', language: 'de',
  oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.1.0', whats_new_seen: '0.1.0',
  session_stage: 'full', second_factor_required: true,
  email_confirmed: true, email_pending: '',
  profile: { mode: 'light', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true, deadlines: true },
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

/** A field by the start of its label; the kit's fields are joined to their label by an id. */
function field(label: string, within: ParentNode = box): HTMLInputElement | null {
  const found = [...within.querySelectorAll('label')].find((item) => item.textContent?.startsWith(label))
  if (!found) return null
  return found.querySelector('input') ?? (found.htmlFor ? (document.getElementById(found.htmlFor) as HTMLInputElement | null) : null)
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
    await type(field('Benutzername oder E-Mail'), '  ghost ')
    await submit(box.querySelector('form'))
    expect(calls.find((call) => call.url === '/api/v1/auth/forgot')!.body).toEqual({ name: 'ghost' })
    expect(box.textContent).toContain('Wenn es dazu ein Konto mit Adresse gibt, ist ein Link unterwegs.')
    expect(box.textContent).not.toContain('nicht gefunden')
  })

  it('says at once that nothing is sent when the server has no mail set up, and asks nothing of it', async () => {
    await show(<ForgotPage />, '/forgot')
    // The shared account module's sentence: the operator makes the link under Accounts.
    expect(box.textContent).toContain('Der Betreiber kann dir unter Konten einen Link erstellen')
    expect(box.querySelector('form')).toBeNull()
    expect(calls.some((call) => call.url === '/api/v1/auth/forgot')).toBe(false)
  })

  it('still says so when the mail was switched off between the page opening and the request', async () => {
    answers['GET /api/v1/auth/methods'] = { password: true, providers: [], passkeys: false, forgot: true }
    answers['POST /api/v1/auth/forgot'] = { refused: 'reset_off' }
    await show(<ForgotPage />, '/forgot')
    await type(field('Benutzername oder E-Mail'), 'anna')
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
    await type(field('Passwort'), 'a long enough password')
    await type(field('Passwort wiederholen'), 'another long password')
    await submit(box.querySelector('form'))
    expect(calls.some((call) => call.method === 'POST')).toBe(false)
    expect(box.textContent).toContain('Die beiden neuen Passwörter sind nicht gleich.')
    await type(field('Passwort wiederholen'), 'a long enough password')
    await submit(box.querySelector('form'))
    expect(calls.find((call) => call.method === 'POST')!.body).toEqual({ password: 'a long enough password', password_confirm: 'a long enough password' })
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
    await type(field('Passwort'), 'a long enough password')
    await type(field('Passwort wiederholen'), 'a long enough password')
    await submit(box.querySelector('form'))
    expect(box.querySelector('h1')!.textContent).toBe('Link nicht gültig')
  })
})

describe("the operator sends a link instead of setting a password", () => {
  const rows = [
    { ...me, locked: false, blocked: false, blocked_at: null, has_password: true, email_duplicate: false, self: true, documents: 0, created_at: '2026-10-01T10:00:00Z', last_seen_at: null },
    { ...me, id: 2, name: 'anna', display_name: 'Anna', role: 'member', email: 'anna@example.com', locked: false, blocked: false, blocked_at: null, has_password: true, email_duplicate: false, self: false, documents: 0, created_at: '2026-10-01T10:00:00Z', last_seen_at: null },
  ]

  async function ask(): Promise<void> {
    answers['GET /api/v1/accounts'] = rows
    answers['GET /api/v1/invites'] = []
    answers['GET /api/v1/oidc/admin/links'] = []
    await show(<AccountsTab />, '/settings/accounts')
    expect(box.textContent).not.toContain('Passwort geben')
    // As in every nex app, the link sits in the dialog "Verwalten" of the row, not as a button of the list.
    expect(button('Link für ein neues Passwort', box)).toBeUndefined()
    await click(button('Verwalten', document.querySelector<HTMLElement>('[data-testid="account-row-anna"]')!))
    await click(button('Link für ein neues Passwort', document.body))
    const dialogs = document.querySelectorAll('[role="dialog"]')
    const dialog = dialogs[dialogs.length - 1]!
    // The operator's own password in the account module's word.
    expect(field('Passwort', dialog)!.type).toBe('password')
    await type(dialog.querySelector<HTMLInputElement>('input[type="password"]'), 'the own password')
    await submit(dialog.querySelector('form'))
  }

  it('sends it by mail where that works, and the interface says where it went', async () => {
    answers['POST /api/v1/accounts/2/reset-link'] = { sent: true, email: 'anna@example.com', expires_at: '2026-10-08T10:00:00Z' }
    await ask()
    expect(calls.find((call) => call.url === '/api/v1/accounts/2/reset-link')!.body).toEqual({ days: 1, current_password: 'the own password', send: false })
    expect(document.body.textContent).toContain('Der Link ist an anna@example.com unterwegs.')
    expect(calls.some((call) => call.url.endsWith('/password'))).toBe(false)
  })

  it('shows the link once where mail does not work, and never a password', async () => {
    answers['POST /api/v1/accounts/2/reset-link'] = { sent: false, link: 'https://paper.example.com/reset/abc', expires_at: '2026-10-08T10:00:00Z' }
    await ask()
    expect(document.body.textContent).toContain('Gib diesen Link weiter. Er gilt nur einmal.')
    // The kit's row to copy it (`CopyRow`): the link to read and "Kopieren".
    const copy = document.body.querySelector<HTMLElement>('[data-part="copy-row"]')!
    expect(copy.querySelector<HTMLInputElement>('input[readonly]')!.value).toContain('https://paper.example.com/reset/abc')
    expect(button('Kopieren', copy)).toBeTruthy()
    expect(document.body.textContent).not.toContain('Das neue Passwort für')
    // The link shows once: Escape does not close the window (ui `dismissable`, E38), only "Fertig" does.
    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
    expect(document.body.querySelector('[data-testid="reset-link-dialog"]')).toBeTruthy()
  })
})

describe('what the server offers', () => {
  it('offers no passkey button where the server offers no passkeys, and says what is missing (konten, E49)', async () => {
    Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
    vi.stubGlobal('PublicKeyCredential', function PublicKeyCredential() {})
    answers['GET /api/v1/auth/passkeys'] = []
    answers['GET /api/v1/auth/methods'] = { password: true, providers: [], passkeys: false }
    await show(<PasskeysBox me={me} />, '/settings/security')
    expect(button('Passkey hinzufügen', box)).toBeUndefined()
    expect(box.querySelector('[data-testid="passkey-needs-address"]')).not.toBeNull()
    act(() => root.unmount())
    box.remove()
    answers['GET /api/v1/auth/methods'] = { password: true, providers: [], passkeys: true }
    await show(<PasskeysBox me={me} />, '/settings/security')
    expect(button('Passkey hinzufügen', box)!.disabled).toBe(false)
  })

  /** Server › Sign-in with "Bereit fürs Internet?" in the module's form; every point opened (all are closed at first). */
  async function ready(points: unknown[]): Promise<void> {
    answers['GET /api/v1/server/sign-in'] = {
      password_login: true, factor_required: true, passkeys_allowed: true, password_may_go_off: false, factor_may_go_on: true,
      public_url: 'https://paper.example.com', public_url_effective: 'https://paper.example.com', operator_has_password: true,
    }
    answers['GET /api/v1/oidc/admin/providers'] = []
    answers['GET /api/v1/oidc/authentik/address'] = { public_url: 'https://paper.example.com', seen: 'https://paper.example.com', forwarded_proto: '', forwarded_host: '', proxy_ignored: false, callback_path: '' }
    answers['GET /api/v1/server/readiness'] = { state: 'bad', open: points.length, points }
    localStorage.removeItem('nexpaper.fold.ready')
    await show(<SignInArea />, '/settings/sign-in')
    for (const head of [...box.querySelectorAll<HTMLElement>('[id^="ready-"] [aria-expanded="false"]')]) await click(head)
  }

  it('says why the brake and the proxy are red when public networks are trusted', async () => {
    await ready([
      { key: 'brake', state: 'bad', title: 'account.ready.brake.title', text: 'account.ready.brake.bad', values: { networks: '0.0.0.0/0' } },
      { key: 'proxy', state: 'bad', title: 'account.ready.proxy.title', text: 'account.ready.proxy.bad', values: { proxies: '0.0.0.0/0', networks: '0.0.0.0/0', variable: 'NEXPAPER_TRUSTED_PROXIES' } },
    ])
    expect([...box.querySelectorAll('[id^="ready-"] [data-state]')].map((item) => item.getAttribute('data-state'))).toEqual(['bad', 'bad'])
    expect(box.querySelector('[data-testid="ready-text-brake"]')!.textContent).toContain('enthält öffentliche Netze (0.0.0.0/0)')
    expect(box.querySelector('[data-testid="ready-text-proxy"]')!.textContent).toContain('nicht auf das ganze Internet')
  })

  it('says when the protection against guessing fails its own test', async () => {
    await ready([{ key: 'brake', state: 'bad', title: 'account.ready.brake.title', text: 'account.ready.brake.broken', values: { broken: true, app: 'nexpaper' } }])
    expect(box.querySelector('[data-testid="ready-text-brake"]')!.textContent).toContain('besteht seinen eigenen Test nicht')
  })
})

describe("the operator's pages say what they hold", () => {
  it('tells that a backup holds the secrets of the server and not the documents, in German and in English', async () => {
    // nexpaper's sentence under the module's card "Sicherung" (`holds`).
    answers['GET /api/v1/server/storage/backups'] = {
      schedule: { every: 'daily', time: '03:00', keep: 7 }, zone: 'Europe/Berlin', last: null, count: 0, kept: 7, failure: null, running: false,
      restore_failure: null, restored: null, restore: 'restart', download_password: false, backups: [],
    }
    // The check of the files has its own test (Files.test.tsx); here it does not answer.
    answers['GET /api/v1/storage'] = { refused: 'not_found' }
    answers['GET /api/v1/server/storage'] = {
      app: 'nexpaper', used: 0, parts: [], complete: true, total: 1_000_000, disk_used: 0, free: 1_000_000, nearly_full: false, where: {}, network: [],
    }
    await show(<StorageArea />, '/settings/storage')
    const card = () => box.querySelector('[data-card="backups"]')!
    expect(card().textContent).toContain('die Zugänge für Mail und KI und die Adressen offener Links, bewahre sie darum geschützt auf, wie ein Passwort.')
    expect(card().textContent).toContain('nicht die Dokumente selbst')
    expect(card().textContent).toContain('/data/dokumente')
    act(() => root.unmount())
    box.remove()
    await changeLanguage('en', false)
    await show(<StorageArea />, '/settings/storage')
    expect(card().textContent).toContain('the access for mail and AI and the addresses of open links, so keep it protected, like a password.')
    expect(card().textContent).toContain('not the documents themselves')
    expect(card().textContent).toContain('/data/dokumente')
  })

  it('shows the operator whose key it is and what it is called, never the key and never its start (E36)', async () => {
    answers['GET /api/v1/connections/admin/keys'] = {
      keys: [{ id: 1, kind: 'api', name: 'nexdeck', right: 'read', options: {}, areas: null, created_at: '2026-10-01T10:00:00Z', last_used_at: null, expires_at: null, expired: false, expiring: false, blocked: false, legacy: null, program: false, account: { id: 2, name: 'anna', display_name: 'Anna', out: false } }],
    }
    await show(<AllKeys />, '/settings/accounts')
    const row = box.querySelector('[data-testid="all-keys-row"]')!
    expect(row.textContent).toContain('nexdeck')
    expect(row.textContent).toContain('Anna')
    expect(row.textContent).not.toContain('npk_')
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
