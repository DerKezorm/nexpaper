/**
 * Everything that deletes or locks out asks first: for each place that has no test of its own for it, the
 * click on the button sends nothing and shows what happens, "Abbrechen" sends nothing, and the red button sends the one
 * request. The places that have such a test in their own file: the trash, the notes, the senders, kinds and tags (order page), the rules,
 * links, shares, exports (and their links), versions, sessions, devices, members and the connection to Paperless.
 */
import type { Me } from '../api/client'
import { changeLanguage } from '../i18n'
import { INBOX, Page, Server, inboxOf, plain } from '../test/harness'
import { SettingsRoutes } from '../test/settings'
import { InboxPage } from './InboxPage'
import { AccountsTab } from './settings/AccountsTab'
import { ApiKeys } from './settings/KeysCards'
import { LanguagesCard } from './settings/ServerCards'
import { SignInArea } from './settings/SignInArea'
import { Route, Routes } from 'react-router-dom'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: 'jule@example.com', language: 'de',
  email_confirmed: true, email_pending: '', oidc_linked: true, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8,
  avatar: 'a1', version: '0.0.1', whats_new_seen: '0.0.1', session_stage: 'full', second_factor_required: false, mail: true,
  profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true, deadlines: true },
}
const auth = { status: 'signedIn', me: me as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth, safeNext: (next: string | null) => next ?? '/' }))

const server = new Server()
const page = new Page()

beforeEach(async () => {
  await changeLanguage('de', false)
  auth.me = me
  server.answers = {
    'GET /api/v1/auth/methods': { password: true, providers: [{ slug: 'authentik', label: 'authentik' }], passkeys: true },
    'GET /api/v1/oidc/me': [{ slug: 'authentik', label: 'authentik', linked: true, address: null }],
    'GET /api/v1/auth/passkeys': [],
    'GET /api/v1/auth/sessions': [],
    'GET /api/v1/locales': [{ code: 'es', name: 'Español', keys: 120 }],
    // The module's list of keys (schluessel 1.0.0, `/api/v1/connections/keys`), with a key that only uploads.
    'GET /api/v1/connections/keys': {
      app: 'nexpaper', api: true, mcp: null, programs: false, api_path: '/api/v1', mcp_path: null, keys_wait: false, warn_days: 7, address: 'https://paper.example.com',
      kinds: [{ id: 'api', prefix: 'npk_', creatable: true, editable: true, rights: ['read', 'upload'], default_right: 'read', options: [], areas: [], areas_required: false, days: [30, 90, 365, null], default_days: 365, default_days_by_right: { upload: null }, max: 20 }],
      keys: [{ id: 4, kind: 'api', name: 'Scanner im Flur', right: 'upload', options: {}, areas: null, prefix: 'npk_ab12', created_at: '2026-10-01T10:00:00Z', last_used_at: null, expires_at: null, expired: false, expiring: false, blocked: false, legacy: null, program: false }],
    },
    'GET /api/v1/devices': [],
    'GET /api/v1/push': { key: '', devices: [] },
    'GET /api/v1/ai': { provider: 'none', to: '', model: '', mine: true, allowed: true, available: false },
    'DELETE /api/v1/auth/avatar': { ...me, avatar: null },
    'PUT /api/v1/me/email': { ...me, email: '' },
    'DELETE /api/v1/oidc/authentik/link': 204,
    'DELETE /api/v1/connections/keys/4': 204,
    'DELETE /api/v1/locales/es': 204,
    'DELETE /api/v1/oidc/admin/providers/3': { count: 1, only: 0, only_names: [] },
    'DELETE /api/v1/invites/9': 204,
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

/** The click on the trigger sends nothing; Abbrechen sends nothing; the red button sends exactly what is named. */
async function asksFirst(trigger: () => HTMLElement | undefined, red: string, sent: string) {
  await page.click(trigger())
  expect(page.dialog).toBeTruthy()
  expect(server.changes()).toEqual([])
  await page.inDialog('Abbrechen')
  expect(page.dialog).toBeNull()
  expect(server.changes()).toEqual([])
  await page.click(trigger())
  await page.inDialog(red)
  expect(server.changes()).toEqual([sent])
}

describe('my account', () => {
  it('asks before the profile picture goes', async () => {
    await page.show(<SettingsRoutes />, '/konto')
    await asksFirst(() => page.button('Bild entfernen'), 'Bild entfernen', 'DELETE /api/v1/auth/avatar')
  })

  it('asks before the mail address goes, and names it', async () => {
    await page.show(<SettingsRoutes />, '/konto')
    // An emptied address is removed; the one question asks the password (the shared account module) and names it.
    await page.type(document.querySelector<HTMLInputElement>('input[type="email"]'), '')
    await page.click(page.button('Speichern'))
    expect(plain(page.dialog!.textContent)).toContain('Die Adresse jule@example.com wird gelöscht.')
    await page.inDialog('Abbrechen')
    expect(server.changes()).toEqual([])
  })

  it('asks before the link to the provider is let go', async () => {
    await page.show(<SettingsRoutes />, '/konto?tab=security')
    // The button of the row names its provider (oidc 1.2.0, "<Aktion>: <Name>").
    expect(page.box.querySelector('[data-testid="settings-area-security"]')).toBeTruthy()
    await asksFirst(() => page.button('Lösen: authentik'), 'Verknüpfung lösen', 'DELETE /api/v1/oidc/authentik/link')
  })

  it('asks before an API key is revoked, and names it', async () => {
    await page.show(<ApiKeys />, '/settings/connections')
    const revoke = () => page.box.querySelector<HTMLElement>('[data-testid="key-revoke"]') ?? undefined
    await page.click(revoke())
    expect(plain(page.dialog!.textContent)).toContain('„Scanner im Flur“ widerrufen?')
    expect(plain(page.dialog!.textContent)).toContain('Das Programm kommt sofort nicht mehr herein.')
    expect(server.changes()).toEqual([])
    await page.inDialog('Abbrechen')
    expect(server.changes()).toEqual([])
    await page.click(revoke())
    await page.inDialog('Widerrufen')
    expect(server.changes()).toEqual(['DELETE /api/v1/connections/keys/4'])
  })
})

describe('the operator', () => {
  it('asks before a language is removed', async () => {
    await page.show(<LanguagesCard />)
    // The chip's own small button, named by the language (ui `Chip`).
    await asksFirst(() => page.button('Español entfernen'), 'Sprache entfernen', 'DELETE /api/v1/locales/es')
  })

  it('asks before an invitation is withdrawn', async () => {
    server.answers['GET /api/v1/accounts'] = []
    server.answers['GET /api/v1/invites'] = [{ id: 9, email: 'neu@example.com', display_name: '', by: 'jule', created_at: '2026-10-13T10:00:00Z', expires_at: '2026-10-20T10:00:00Z', expired: false, mailed: false }]
    server.answers['GET /api/v1/oidc/admin/links'] = []
    await page.show(<AccountsTab />)
    await asksFirst(() => page.button('Zurücknehmen', document.getElementById('open-invites')!), 'Zurücknehmen', 'DELETE /api/v1/invites/9')
  })

  it('asks before a sign-in provider is removed, with the number of accounts that lose their link', async () => {
    server.answers['GET /api/v1/oidc/admin/providers'] = [{
      id: 3, slug: 'authentik', label: 'authentik', issuer: 'https://auth.example.com/application/o/nexpaper', client_id: 'nexpaper',
      has_secret: true, scopes: 'openid profile email', enabled: true, auto_create: false, trusts_second_factor: true, managed: 'authentik',
      position: 0, redirect_uri: 'https://paper.example.com/api/v1/oidc/authentik/callback', links: 1, editable: true,
    }]
    server.answers['GET /api/v1/oidc/admin/providers/3/impact'] = { issuer_change: 0, count: 1, only: 0, only_names: [] }
    server.answers['GET /api/v1/oidc/authentik/address'] = { public_url: 'https://paper.example.com', seen: 'https://paper.example.com', forwarded_proto: '', forwarded_host: '', proxy_ignored: false, callback_path: '/api/v1/oidc/authentik/callback', redirect_uri: '', registered_redirect_uri: '', stale: false }
    server.answers['GET /api/v1/server/sign-in'] = {
      password_login: true, factor_required: true, passkeys_allowed: true, password_may_go_off: true, factor_may_go_on: true,
      public_url: 'https://paper.example.com', public_url_effective: 'https://paper.example.com', operator_has_password: true,
    }
    server.answers['GET /api/v1/server/readiness'] = { state: 'ok', open: 0, points: [] }
    await page.show(<SignInArea />, '/settings/sign-in')
    // The row's button names its provider (oidc 1.2.0, E37).
    await asksFirst(() => page.button('Entfernen: authentik'), 'Entfernen', 'DELETE /api/v1/oidc/admin/providers/3')
  })
})

describe('the vaults and the inbox', () => {
  it('asks before the document in the inbox goes to the trash, and says it can be brought back', async () => {
    const heating = {
      id: 11, vault_id: 9, owner: { id: 1, name: 'jule', display_name: 'Jule' }, title: 'Rechnung 2026-0473', sender: null, kind: null, date: null, amount: null, currency: 'EUR',
      tags: [], dates: [], pages: 1, source: 'upload', status: 'inbox', added_at: '2026-10-08T07:42:00Z', trashed_at: null, trash_ends_at: null, change_seq: 1,
      current_version: 1, my_right: 'manage', via_share: false, can_share: true, notes: 0, process_error: '', duplicate: null, einvoice: '', suggest: {},
    }
    server.answers[INBOX] = inboxOf([heating])
    server.answers['GET /api/v1/vaults'] = [{ id: 9, name: 'Haushalt', icon: 'sun', personal_of: null, my_right: 'manage', documents: 1, size: 1, members: [] }]
    server.answers['GET /api/v1/kinds?vault_id=9'] = []
    server.answers['GET /api/v1/senders'] = []
    server.answers['DELETE /api/v1/documents/11'] = { ...heating, status: 'trash' }
    await page.show(
      <Routes>
        <Route path="eingang/:id" element={<InboxPage />} />
      </Routes>,
      '/eingang/11',
    )
    await asksFirst(() => page.button('Löschen'), 'In den Papierkorb', 'DELETE /api/v1/documents/11')
  })
})
