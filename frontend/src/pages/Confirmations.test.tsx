/**
 * Everything that deletes or locks out asks first: for each place that has no test of its own for it, the
 * click on the button sends nothing and shows what happens, "Abbrechen" sends nothing, and the red button sends the one
 * request. The places that have such a test in their own file: the trash, the notes, the senders, kinds and tags (order page), the rules,
 * links, shares, exports (and their links), versions, sessions, devices, members and the connection to Paperless.
 */
import type { Me } from '../api/client'
import { ApiKeys } from '../components/ApiKeys'
import { changeLanguage } from '../i18n'
import { INBOX, Page, Server, inboxOf, plain } from '../test/harness'
import { AccountPage } from './AccountPage'
import { InboxPage } from './InboxPage'
import { AccountsCard, LanguagesCard, useServerSettings } from './settings/ServerCards'
import { SignInPart } from './settings/SignInCards'
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
    'GET /api/v1/api-keys': {
      allowed: true,
      keys: [{ id: 4, name: 'Scanner im Flur', prefix: 'npk_ab12', scope: 'upload', created_at: '2026-10-01T10:00:00Z', last_used_at: null, expires_at: null, blocked: false }],
    },
    'GET /api/v1/devices': [],
    'GET /api/v1/push': { key: '', devices: [] },
    'GET /api/v1/ai': { provider: 'none', to: '', model: '', mine: true, allowed: true, available: false },
    'DELETE /api/v1/auth/avatar': { ...me, avatar: null },
    'PUT /api/v1/me/email': { ...me, email: '' },
    'DELETE /api/v1/oidc/authentik/link': 204,
    'DELETE /api/v1/api-keys/4': 204,
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
    await page.show(<AccountPage />, '/konto')
    await asksFirst(() => page.button('Entfernen'), 'Bild entfernen', 'DELETE /api/v1/auth/avatar')
  })

  it('asks before the mail address goes, and names it', async () => {
    await page.show(<AccountPage />, '/konto')
    // The password is asked again for a change of the address.
    await page.type(document.querySelector<HTMLInputElement>('input[type="password"]'), 'geheimwort')
    await page.click(page.button('Adresse entfernen'))
    expect(plain(page.dialog!.textContent)).toContain('Die Adresse jule@example.com wird gelöscht.')
    await page.inDialog('Abbrechen')
    expect(server.changes()).toEqual([])
  })

  it('asks before the link to the provider is let go', async () => {
    await page.show(<AccountPage />, '/konto?tab=security')
    await asksFirst(() => page.button('Lösen'), 'Verknüpfung lösen', 'DELETE /api/v1/oidc/authentik/link')
  })

  it('asks before an API key is deleted, and names it', async () => {
    await page.show(<ApiKeys />, '/konto?tab=devices')
    await page.click(page.button('Schlüssel „Scanner im Flur“ löschen') ?? document.querySelector<HTMLElement>('button[aria-label*="Scanner im Flur"]'))
    expect(plain(page.dialog!.textContent)).toContain('Programme mit dem Schlüssel „Scanner im Flur“ kommen danach nicht mehr in nexpaper.')
    expect(server.changes()).toEqual([])
    await page.inDialog('Abbrechen')
    await page.click(document.querySelector<HTMLElement>('button[aria-label*="Scanner im Flur"]'))
    await page.inDialog('Schlüssel löschen')
    expect(server.changes()).toEqual(['DELETE /api/v1/api-keys/4'])
  })
})

describe('the operator', () => {
  it('asks before a language is removed', async () => {
    await page.show(<LanguagesCard />)
    await asksFirst(() => page.button('Español entfernen') ?? document.querySelector<HTMLElement>('button[aria-label*="Español"]') ?? undefined, 'Sprache entfernen', 'DELETE /api/v1/locales/es')
  })

  it('asks before an invitation is withdrawn', async () => {
    server.answers['GET /api/v1/accounts'] = []
    server.answers['GET /api/v1/invites'] = [{ id: 9, email: 'neu@example.com', expires_at: '2026-10-20T10:00:00Z' }]
    await page.show(<AccountsCard />)
    await asksFirst(() => page.button('Zurückziehen'), 'Einladung zurückziehen', 'DELETE /api/v1/invites/9')
  })

  it('asks before a sign-in provider is removed, with the number of accounts that lose their link', async () => {
    server.answers['GET /api/v1/oidc/admin/providers'] = [{
      id: 3, slug: 'authentik', label: 'authentik', issuer: 'https://auth.example.com/application/o/nexpaper', client_id: 'nexpaper',
      has_secret: true, scopes: 'openid profile email', enabled: true, auto_create: false, trusts_second_factor: true, managed: 'authentik',
      position: 0, redirect_uri: 'https://paper.example.com/api/v1/oidc/authentik/callback', links: 1, editable: true,
    }]
    server.answers['GET /api/v1/oidc/admin/providers/3/impact'] = { issuer_change: 0, count: 1, only: 0, only_names: [] }
    server.answers['GET /api/v1/oidc/authentik/address'] = { public_url: 'https://paper.example.com', seen: 'https://paper.example.com', forwarded_proto: '', forwarded_host: '', proxy_ignored: false, callback_path: '/api/v1/oidc/authentik/callback', redirect_uri: '', registered_redirect_uri: '', stale: false }
    server.answers['GET /api/v1/settings'] = { public_url: 'https://paper.example.com', password_login: true, two_factor_required: true }
    function Cards() {
      const settings = useServerSettings()
      return settings.settings ? <SignInPart server={settings} /> : null
    }
    await page.show(<Cards />)
    await asksFirst(() => page.button('Entfernen'), 'Entfernen', 'DELETE /api/v1/oidc/admin/providers/3')
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
