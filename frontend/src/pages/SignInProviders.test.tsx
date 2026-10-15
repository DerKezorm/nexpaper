/**
 * Sign-in through providers as the shared blueprint lays it out (Bauplan 04), against a stand-in of the server: the
 * sign-in and invitation pages with a button per provider, the three cards under Settings, Sign-in (the form in the
 * blueprint's order, the questions before an issuer or an address changes, the steps of the authentik button with their
 * names and reasons), the row per provider on the account page, and the marks in the account list.
 */
import { Route, Routes } from 'react-router-dom'

import type { Me, OidcProvider } from '../api/client'
import i18n, { changeLanguage } from '../i18n'
import { Page, Server, plain } from '../test/harness'
import { AccountPage } from './AccountPage'
import { InvitePage, LoginPage } from './AuthPages'
import { AccountsCard, useServerSettings } from './settings/ServerCards'
import { SignInPart } from './settings/SignInCards'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: 'jule@example.com', language: 'de',
  email_confirmed: true, email_pending: '', oidc_linked: true, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8,
  avatar: null, version: '1.0.1', whats_new_seen: '1.0.1', session_stage: 'full', second_factor_required: false, mail: true,
  profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true, deadlines: true },
}
const auth = { status: 'signedOut' as string, me: me as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth, safeNext: (next: string | null) => next ?? '/' }))

const server = new Server()
const page = new Page()

const AUTHENTIK: OidcProvider = {
  id: 3, slug: 'authentik', label: 'authentik', issuer: 'https://auth.example.com/application/o/nexpaper', client_id: 'nexpaper',
  has_secret: true, scopes: 'openid profile email', enabled: true, auto_create: false, trusts_second_factor: true, managed: 'authentik',
  position: 0, redirect_uri: 'https://paper.example.com/api/v1/oidc/authentik/callback', links: 2, editable: true,
}
const ENTRA: OidcProvider = {
  ...AUTHENTIK, id: 4, slug: 'entra', label: 'Microsoft', issuer: 'https://login.microsoftonline.com/common/v2.0', managed: '',
  enabled: false, position: 1, redirect_uri: 'https://paper.example.com/api/v1/oidc/entra/callback', links: 0,
}
const ADDRESS = {
  public_url: 'https://paper.example.com', seen: 'https://paper.example.com', forwarded_proto: '', forwarded_host: '', proxy_ignored: false,
  callback_path: '/api/v1/oidc/authentik/callback', redirect_uri: 'https://paper.example.com/api/v1/oidc/authentik/callback',
  registered_redirect_uri: '', stale: false,
}

beforeEach(async () => {
  await changeLanguage('de', false)
  auth.status = 'signedOut'
  auth.me = me
  server.answers = {
    'GET /api/v1/auth/methods': { password: true, providers: [{ slug: 'authentik', label: 'authentik' }, { slug: 'entra', label: 'Microsoft' }], passkeys: false },
    'GET /api/v1/settings': { public_url: 'https://paper.example.com', password_login: true, two_factor_required: true },
    'GET /api/v1/oidc/admin/providers': [AUTHENTIK, ENTRA],
    'GET /api/v1/oidc/authentik/address': ADDRESS,
  }
  server.fails = {}
  server.install()
})

afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

function links(): HTMLButtonElement[] {
  return [...document.querySelectorAll<HTMLButtonElement>('[data-testid="provider-buttons"] button')]
}

/** Where a provider's button sends the browser (a full page load). */
async function target(button: HTMLButtonElement): Promise<string> {
  const assign = vi.fn()
  vi.stubGlobal('location', { ...window.location, assign })
  await page.click(button)
  return String(assign.mock.calls[0]?.[0])
}

function Cards() {
  const settings = useServerSettings()
  return settings.settings ? <SignInPart server={settings} /> : null
}

describe('the sign-in page', () => {
  it('has a button per provider below the password, in the order of the list, taking the page along', async () => {
    await page.show(<LoginPage />, '/login?next=%2Foauth%2Fauthorize%3Fx%3D1')
    expect(links().map((link) => link.textContent)).toEqual(['Mit authentik anmelden', 'Mit Microsoft anmelden'])
    expect(await target(links()[0])).toBe('/api/v1/oidc/authentik/start?next=%2Foauth%2Fauthorize%3Fx%3D1')
    const text = page.text
    expect(text.indexOf('Passwort')).toBeLessThan(text.indexOf('oder'))
    expect(text.indexOf('oder')).toBeLessThan(text.indexOf('Mit authentik anmelden'))
  })

  it('says a refusal of the provider in a sentence of the module, never the code', async () => {
    await page.show(<LoginPage />, '/login?error=oidc_no_account')
    expect(page.text).toContain('Für dich gibt es hier kein Konto. Bitte um eine Einladung, oder melde dich mit Passwort an und verknüpfe dein Konto in deinen Kontoeinstellungen.')
    expect(page.text).not.toContain('oidc_no_account')
  })

  it("shows only the buttons while the password is off, and the operator's way in below", async () => {
    server.answers['GET /api/v1/auth/methods'] = { password: false, providers: [{ slug: 'authentik', label: 'authentik' }], passkeys: false }
    await page.show(<LoginPage />, '/login')
    expect(document.querySelector('input[type="password"]')).toBeNull()
    expect(links()).toHaveLength(1)
    await page.click(page.button('Als Betreiber mit Passwort anmelden'))
    expect(document.querySelector('input[type="password"]')).not.toBeNull()
  })
})

describe('the invitation page', () => {
  it('offers "Continue with" per provider and takes the invitation along', async () => {
    server.answers['GET /api/v1/invite/key-1'] = { valid: true }
    await page.show(
      <Routes>
        <Route path="/invite/:token" element={<InvitePage />} />
      </Routes>,
      '/invite/key-1',
    )
    expect(links().map((link) => link.textContent)).toEqual(['Weiter mit authentik', 'Weiter mit Microsoft'])
    expect(await target(links()[1])).toBe('/api/v1/oidc/entra/start?invite=key-1')
  })
})

describe('Settings, Sign-in', () => {
  beforeEach(() => {
    auth.status = 'signedIn'
  })

  it('has the three cards one below the other, and the list with its marks', async () => {
    await page.show(<Cards />)
    const titles = [...document.querySelectorAll('h2')].map((title) => title.textContent)
    expect(titles).toEqual(['Anmeldung', 'Anmeldeanbieter', 'authentik in einem Schritt'])
    const rows = [...document.querySelectorAll('[data-testid="provider-list"] li')].map((row) => plain(row.textContent))
    for (const part of ['authentik', 'aktiv', 'über authentik eingerichtet']) expect(rows[0]).toContain(part)
    for (const part of ['Microsoft', 'aus']) expect(rows[1]).toContain(part)
    expect(rows[1]).not.toContain('über authentik eingerichtet')
  })

  it('opens the form with the fields in the order of the blueprint and suggests the short name', async () => {
    await page.show(<Cards />)
    await page.click(page.button('Anbieter hinzufügen'))
    const form = document.querySelector('[data-testid="provider-form"]')!
    const labels = [...form.querySelectorAll('label, span')].map((item) => item.textContent?.trim() ?? '')
    const order = ['Name auf dem Knopf', 'Kurzname', 'Aussteller (Issuer)', 'Client-ID', 'Client-Geheimnis', 'Rückleitadresse für den Anbieter', 'Aktiv',
      'Neue Personen bekommen ein Konto', 'Der Anbieter prüft den zweiten Faktor selbst']
    const found = order.map((label) => labels.findIndex((text) => text.startsWith(label)))
    expect(found.every((index) => index >= 0)).toBe(true)
    expect([...found].sort((a, b) => a - b)).toEqual(found)
    await page.type(form.querySelector<HTMLInputElement>('input'), 'Mein SSO')
    const values = [...form.querySelectorAll<HTMLInputElement>('input')].map((input) => input.value)
    expect(values).toContain('mein-sso')
    expect(values).toContain('https://paper.example.com/api/v1/oidc/mein-sso/callback')
  })

  it('asks with the number of accounts before another issuer takes the links', async () => {
    server.answers['GET /api/v1/oidc/admin/providers/3/impact?issuer=https%3A%2F%2Fother.example.com'] = { issuer_change: 2, count: 2, only: 0, only_names: [] }
    server.answers['PUT /api/v1/oidc/admin/providers/3'] = { ...AUTHENTIK, issuer: 'https://other.example.com', dropped: 2 }
    await page.show(<Cards />)
    await page.click(page.button('Bearbeiten'))
    const issuer = [...document.querySelectorAll<HTMLInputElement>('[data-testid="provider-form"] input')].find((input) => input.value === AUTHENTIK.issuer)
    await page.type(issuer, 'https://other.example.com')
    await page.click(page.button('Speichern', document.querySelector('[data-testid="provider-form"]')!))
    expect(plain(page.dialog?.textContent)).toContain('Ein anderer Aussteller ist ein anderer Anbieter. 2 Konten müssen sich danach neu verknüpfen.')
    expect(server.changes()).toEqual([])
    await page.inDialog('Speichern')
    expect(server.changes()).toEqual(['PUT /api/v1/oidc/admin/providers/3'])
  })

  it('lists the steps of the authentik button by their names, with the reason of the one that failed', async () => {
    server.answers['POST /api/v1/oidc/authentik/setup'] = {
      ok: false, links_dropped: 0, steps: [
        { key: 'reached', ok: true, detail: 'GET /admin/version/ 200' },
        { key: 'signingKey', ok: false, detail: 'POST 403', reason: 'token', status: 403 },
      ],
    }
    await page.show(<Cards />)
    const inputs = [...document.querySelectorAll<HTMLInputElement>('#sign-in-authentik input')]
    await page.type(inputs[0], 'https://auth.example.com')
    await page.type(inputs[1], 'one-time-token')
    await page.click(page.button('Einrichten'))
    const steps = plain(document.querySelector('[data-testid="authentik-steps"]')?.textContent)
    expect(steps).toContain('Verbindung zu authentik')
    expect(steps).toContain('Schlüssel zum Signieren')
    expect(steps).toContain('authentik hat das Token nicht angenommen (Antwort 403).')
    expect(steps).not.toContain('POST 403')
    // The token stays after a failure; the operator corrects and tries again.
    expect(inputs[1].value).toBe('one-time-token')
  })

  it("proposes the browser's address while nexpaper has none, and the button says so", async () => {
    server.answers['GET /api/v1/oidc/authentik/address'] = { ...ADDRESS, public_url: '', redirect_uri: '' }
    server.answers['GET /api/v1/settings'] = { public_url: '', password_login: true, two_factor_required: true }
    await page.show(<Cards />)
    expect(document.querySelector('[data-testid="authentik-proposal"]')?.textContent).toBe(window.location.origin)
    expect(page.button('Übernehmen und einrichten')).toBeTruthy()
    expect(page.button('Nur übernehmen')).toBeTruthy()
  })

  it('asks before a new public address leaves the redirect addresses behind', async () => {
    server.fails['PUT /api/v1/settings'] = { status: 409, code: 'public_url_change', values: { count: 1, address: 'https://paper.example.com/api/v1/oidc/authentik/callback', hand: 1 } }
    await page.show(<Cards />)
    const field = [...document.querySelectorAll<HTMLInputElement>('#sign-in input')].find((input) => input.value === 'https://paper.example.com')
    await page.type(field, 'https://papers.example.com')
    await page.click(page.button('Speichern', document.querySelector('#sign-in')!))
    const asked = plain(page.dialog?.textContent)
    expect(asked).toContain('authentik kennt noch die Rückleitadresse https://paper.example.com/api/v1/oidc/authentik/callback.')
    expect(asked).toContain('Bei 1 von Hand eingetragenen Anbieter musst du die Rückleitadresse dort selbst anpassen.')
    delete server.fails['PUT /api/v1/settings']
    await page.inDialog('Speichern')
    const sent = server.calls.filter((call) => call.method === 'PUT' && call.url === '/api/v1/settings').map((call) => call.body)
    expect(sent).toEqual([
      { public_url: 'https://papers.example.com', confirm_address: false },
      { public_url: 'https://papers.example.com', confirm_address: true },
    ])
  })

  // A password account that comes in through a provider with "the provider checks the second factor itself" is not sent
  // away (Bauplan 04); both hints under "Require a second factor" say so and name that switch.
  for (const language of ['de', 'en'] as const) {
    for (const own of [true, false]) {
      it(`names the provider switch that exempts a sign-in (${language}, ${own ? 'with' : 'without'} an own second factor)`, async () => {
        await changeLanguage(language, false)
        auth.me = { ...me, two_factor: own }
        server.answers['GET /api/v1/settings'] = { public_url: 'https://paper.example.com', password_login: true, two_factor_required: false }
        await page.show(<Cards />)
        const card = plain(document.querySelector('#sign-in')?.textContent)
        const name = i18n.t('oidc.admin.trustsSecondFactor')
        const hint = plain(i18n.t(own ? 'server.twoFactorRequiredHint' : 'server.ownSecondFactorFirst', { trusts: name }))
        expect(card).toContain(hint)
        // The words of the switch itself between the quotes of the sentence, not a gap.
        const [open, close] = language === 'de' ? ['„', '“'] : ['“', '”']
        expect(card).toContain(`${open}${name}${close}`)
      })
    }
  }
})

describe('the account page', () => {
  beforeEach(() => {
    auth.status = 'signedIn'
    server.answers['GET /api/v1/auth/passkeys'] = []
    server.answers['GET /api/v1/auth/sessions'] = []
    server.answers['GET /api/v1/oidc/me'] = [
      { slug: 'authentik', label: 'authentik', linked: true, address: 'jule@work.example.com' },
      { slug: 'entra', label: 'Microsoft', linked: false, address: null },
    ]
  })

  it('has a row per provider, links with the password and offers the address the provider knows', async () => {
    server.answers['POST /api/v1/oidc/entra/link'] = { url: 'https://login.microsoftonline.com/authorize' }
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    await page.show(<AccountPage />, '/konto?tab=security&linked=authentik')
    expect(page.text).toContain('Dein Konto ist mit authentik verknüpft.')
    const rows = [...document.querySelectorAll('[data-testid="my-providers"] li')].map((row) => plain(row.textContent))
    expect(rows[0]).toContain('Verknüpft')
    expect(rows[0]).toContain('authentik kennt dich als jule@work.example.com.')
    expect(rows[1]).toContain('Nicht verknüpft')
    await page.click(page.button('Verknüpfen'))
    await page.type(document.querySelector<HTMLInputElement>('[data-testid="my-providers"] input[type="password"]'), 'geheimwort')
    await page.click(document.querySelector<HTMLElement>('[data-testid="my-providers"] button[type="submit"]'))
    expect(server.called('POST', '/api/v1/oidc/entra/link')?.body).toEqual({ password: 'geheimwort' })
    expect(assign).toHaveBeenCalledWith('https://login.microsoftonline.com/authorize')
  })

  it('keeps the last link of an account without a password', async () => {
    auth.me = { ...me, sign_in: 'oidc' }
    server.answers['GET /api/v1/oidc/me'] = [{ slug: 'authentik', label: 'authentik', linked: true, address: null }]
    await page.show(<AccountPage />, '/konto?tab=security')
    expect(page.text).toContain('Dieses Konto meldet sich nur über authentik an.')
    expect(page.button('Lösen')).toBeUndefined()
  })

  it("says beside devices and keys that they wait for a second factor of the account's own", async () => {
    auth.me = { ...me, keys_wait_for_second_factor: true }
    server.answers['GET /api/v1/devices'] = []
    server.answers['GET /api/v1/api-keys'] = { allowed: true, keys: [] }
    server.answers['GET /api/v1/push'] = { key: '', devices: [] }
    await page.show(<AccountPage />, '/konto?tab=devices')
    expect(document.querySelector('[data-testid="keys-wait"]')?.textContent).toContain('Geräte und API-Schlüssel wirken erst, wenn du einen zweiten Faktor einrichtest.')
  })
})

describe('the account list', () => {
  it("marks the providers an account is linked to and unlinks it with the operator's password", async () => {
    auth.status = 'signedIn'
    server.answers['GET /api/v1/accounts'] = [{ ...me, id: 7, name: 'tom', display_name: '', role: 'member', locked: false, blocked: false, has_password: true, created_at: '2026-10-01T10:00:00Z', last_seen_at: null, ai_allowed: true }]
    server.answers['GET /api/v1/invites'] = []
    server.answers['GET /api/v1/oidc/admin/links'] = [{ account_id: 7, provider_id: 3, slug: 'authentik', label: 'authentik' }]
    server.answers['DELETE /api/v1/oidc/admin/accounts/7/links/3'] = 204
    await page.show(<AccountsCard />)
    expect(document.querySelector('[data-testid="account-providers"]')?.textContent).toBe('authentik')
    await page.click(document.querySelector<HTMLElement>('button[aria-haspopup="true"]'))
    await page.click(page.button('Verknüpfung lösen: authentik'))
    expect(plain(page.dialog?.textContent)).toContain('tom meldet sich danach nicht mehr über authentik an und bekommt Bescheid.')
    await page.type(page.dialog!.querySelector<HTMLInputElement>('input[type="password"]'), 'geheimwort')
    await page.inDialog('Lösen')
    expect(server.called('DELETE', '/api/v1/oidc/admin/accounts/7/links/3')?.body).toEqual({ current_password: 'geheimwort' })
  })
})
