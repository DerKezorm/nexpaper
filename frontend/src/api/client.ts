/**
 * The server's API, `/api/v1`. Every call names this browser tab in `X-Nexpaper-Client` (changes without it are refused, the
 * wall against requests from other sites). Errors come back as `ApiError` with the server's code; the page builds
 * its sentence from `errors.<code>` in the language files.
 */

import i18n from 'i18next'

import type { AuthentikAddress } from '../vendor/nexoidc/oidc'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    public readonly values: Record<string, unknown> = {},
  ) {
    super(code)
  }
}

const CLIENT_KEY = 'nexpaper.client'
/** Sent on `window` when a request finds that the session is gone: the page goes back to the sign-in. */
export const SIGNED_OUT_EVENT = 'nexpaper:signed-out'

function randomId(): string {
  const bytes = new Uint8Array(12)
  crypto.getRandomValues(bytes)
  return 'tab-' + Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}

let clientId: string | null = null

/** One id per tab: sessionStorage survives a reload of the tab but is not shared with other tabs. */
export function tabId(): string {
  if (clientId) return clientId
  try {
    clientId = sessionStorage.getItem(CLIENT_KEY)
    if (!clientId) {
      clientId = randomId()
      sessionStorage.setItem(CLIENT_KEY, clientId)
    }
  } catch {
    clientId = randomId()
  }
  return clientId
}

type Options = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  query?: Record<string, string | number | boolean | string[] | undefined>
  body?: unknown
  /** A file as the body (an upload), sent as it is. */
  raw?: Blob
  /** Files in a form (the browser's upload); the browser makes the boundary. */
  form?: FormData
  /** Stops the request (a cancelled upload). */
  signal?: AbortSignal
  /** The answer is a file, not JSON. */
  blob?: boolean
  /** Headers of its own, next to the ones every request carries (the password of an upload). */
  headers?: Record<string, string>
  /** Sent even while the page closes (the last draft). */
  keepalive?: boolean
}

const BUSY_TRIES = 3
const BUSY_WAIT_MS = 1500

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const repeatable = (options.method ?? 'GET') === 'GET'
  for (let attempt = 1; ; attempt++) {
    try {
      return await once<T>(path, options)
    } catch (error) {
      if (!(error instanceof ApiError && error.code === 'busy' && repeatable && attempt < BUSY_TRIES)) throw error
      await new Promise((resolve) => setTimeout(resolve, BUSY_WAIT_MS))
    }
  }
}

async function once<T>(path: string, options: Options): Promise<T> {
  const url = new URL(path, window.location.origin)
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (Array.isArray(value)) for (const item of value) url.searchParams.append(key, item)
    else if (value !== undefined) url.searchParams.set(key, String(value))
  }
  // The language the page is shown in: what an account without a language of its own starts with (its values).
  const headers: Record<string, string> = { ...options.headers, Accept: 'application/json', 'X-Nexpaper-Client': tabId(), ...(i18n.language ? { 'X-Nexpaper-Language': i18n.language } : {}) }
  let body: BodyInit | undefined
  if (options.raw) body = options.raw
  else if (options.form) body = options.form
  else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  let response: Response
  try {
    response = await fetch(url.pathname + url.search, { method: options.method ?? 'GET', headers, body, ...(options.keepalive ? { keepalive: true } : {}), ...(options.signal ? { signal: options.signal } : {}) })
  } catch (error) {
    // A request the page stopped on purpose is no network trouble.
    if (options.signal?.aborted || (error instanceof DOMException && error.name === 'AbortError')) throw new ApiError(0, 'cancelled')
    throw new ApiError(0, 'network')
  }
  if (response.status === 204) return undefined as T
  if (options.blob && response.ok) return (await response.blob()) as T
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = data?.detail
    if (detail && typeof detail === 'object' && typeof detail.code === 'string') {
      const { code, message: _message, ...values } = detail
      if (code === 'sign_in_required') window.dispatchEvent(new Event(SIGNED_OUT_EVENT))
      // How long the server asks to wait (a brake, a busy moment), in seconds, for the page to try again then.
      const wait = Number(response.headers?.get?.('Retry-After') ?? NaN)
      if (Number.isFinite(wait) && wait >= 0 && values.retry_after === undefined) values.retry_after = wait
      throw new ApiError(response.status, code, values)
    }
    throw new ApiError(response.status, response.status === 401 ? 'sign_in_required' : 'internal_error')
  }
  return data as T
}

// ---- Types ----------------------------------------------------------------------------------------------------------

export type ThemeChoice = 'system' | 'light' | 'dark'
export type ArchiveView = 'list' | 'grid'

export type Profile = {
  mode: ThemeChoice
  /** A phone opens on the quick upload instead of the archive (it works with the phone block). */
  quick_start: boolean
  /** How the archive shows the documents. */
  view: ArchiveView
  /** The vault new documents go to; none: the personal one. */
  default_vault: number | null
  /** The time zone; what a notice of a new sign-in names its time in. */
  timezone: string
  /** Reported by a browser, or chosen by the person (then no browser changes it). */
  timezone_source: 'browser' | 'manual'
  /** The AI for this person (Account, AI); off: no proposals, and the server refuses. */
  ai: boolean
  /** A push and a mail when the account signs in from a new device. */
  notify_login: boolean
}

export type Me = {
  id: number
  name: string
  display_name: string
  role: 'operator' | 'member'
  sign_in: 'password' | 'oidc'
  email: string
  /** Confirmed by a link sent to it; an address the operator typed or a sign-in provider sent is not. */
  email_confirmed: boolean
  /** A new address waiting for its link; `email` stays until it is opened. */
  email_pending: string
  language: string
  /** Linked to at least one sign-in provider (which ones: `oidcApi.mine`). */
  oidc_linked: boolean
  /** A second factor of any kind: a code from an app or a passkey. */
  two_factor: boolean
  /** A code from an app. */
  totp: boolean
  /** How many passkeys. */
  passkeys: number
  two_factor_recovery_left: number
  avatar: string | null
  version: string
  whats_new_seen: string
  profile: Profile
  mail?: boolean
  /** Whether this session may only set up the second factor, or (until set up) reaches only its own account page. */
  second_factor_setup_required?: boolean
  /** `setup`: right after the password, only the setup; `codes`: the recovery codes to confirm; `full`. */
  session_stage?: SessionStage
  /** The operator asks this account for a second factor: the last one cannot be turned off. */
  second_factor_required?: boolean
  /** What the operator allows this account (on from the start): the AI. */
  ai_allowed?: boolean
  /**
   * This session came in through a provider that checks the second factor, and the account (with a password) has none
   * of its own: its device tokens and API keys wait until it sets one up. Making one stays possible.
   */
  keys_wait_for_second_factor?: boolean
}

export type SessionStage = 'full' | 'setup' | 'codes'
/** The first step went through and the account has a second factor: which kinds it may give. */
export type SecondFactorWaiting = { second_factor: true; totp: boolean; passkey: boolean }

export type SetupState = { needs_setup: boolean; code_required: boolean; signed_in: boolean; version: string; min_password: number }
/** A button on the sign-in and invitation page: one per active provider, in the order of the operator's list. */
export type ProviderButton = { slug: string; label: string }
export type Methods = { password: boolean; providers: ProviderButton[]; passkeys?: boolean; forgot?: boolean; session_days?: number }
export type SignedSession = { id: string; device: string; phone: boolean; network: string; created_at: string; last_seen_at: string; remember: boolean; here: boolean }
export type Passkey = { id: string; name: string; created_at: string; last_used_at: string | null; credential: string }
export type Readiness = { points: { key: string; state: 'ok' | 'warn' | 'bad'; values: Record<string, unknown> }[]; open: number }

// ---- Calls ----------------------------------------------------------------------------------------------------------

export const authApi = {
  setupState: () => api<SetupState>('/api/v1/setup'),
  setup: (name: string, password: string, code: string, language: string) =>
    api<Me>('/api/v1/setup', { method: 'POST', body: { name, password, code, language } }),
  methods: () => api<Methods>('/api/v1/auth/methods'),
  login: (name: string, password: string, remember = true) => api<Me | SecondFactorWaiting>('/api/v1/auth/login', { method: 'POST', body: { name, password, remember } }),
  code: (code: string, remember?: boolean) => api<Me>('/api/v1/auth/login/totp', { method: 'POST', body: { code, remember } }),
  /** The recovery codes are kept: the session that set up the second factor becomes a full one. */
  setupDone: () => api<Me>('/api/v1/auth/setup/done', { method: 'POST' }),
  /** New recovery codes while they are being confirmed (a reload lost the ones shown). */
  setupCodes: () => api<{ recovery_codes: string[] }>('/api/v1/auth/setup/codes', { method: 'POST' }),
  sessions: () => api<SignedSession[]>('/api/v1/auth/sessions'),
  endSession: (id: string) => api<void>(`/api/v1/auth/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  logoutOthers: () => api<void>('/api/v1/auth/logout-all', { method: 'POST' }),
  cancelCode: () => api<void>('/api/v1/auth/login/totp/cancel', { method: 'POST' }),
  logout: () => api<void>('/api/v1/auth/logout', { method: 'POST' }),
  me: () => api<Me>('/api/v1/auth/me'),
  language: (language: string) => api<Me>('/api/v1/me/language', { method: 'PUT', body: { language } }),
  preferences: (change: Partial<Profile>) => api<Profile>('/api/v1/me/preferences', { method: 'PUT', body: change }),
  profile: (display_name: string) => api<Me>('/api/v1/me/profile', { method: 'PUT', body: { display_name } }),
  password: (current: string, next: string) => api<void>('/api/v1/auth/password', { method: 'PUT', body: { current, new: next } }),
  /** "Forgot your password?": a link to the address on record, if there is one; the answer is the same either way. */
  forgot: (name: string) => api<{ ok: true }>('/api/v1/auth/forgot', { method: 'POST', body: { name } }),
  whatsNewSeen: () => api<Me>('/api/v1/me/whats-new/seen', { method: 'POST' }),
}

// ---- Sign-in providers (the shared module `vendor/nexoidc`, Bauplan 04) -----------------------------------------------

/** An entry of the provider list as the operator sees it (never the secret). `managed`: "" by hand, "authentik" by the
 * authentik button. */
export type OidcProvider = {
  id: number
  slug: string
  label: string
  issuer: string
  client_id: string
  has_secret: boolean
  scopes: string
  enabled: boolean
  auto_create: boolean
  trusts_second_factor: boolean
  managed: '' | 'authentik' | 'nexsuite'
  position: number
  redirect_uri: string
  links: number
  editable: boolean
}
export type OidcProviderForm = {
  label: string
  slug?: string
  issuer: string
  client_id: string
  client_secret: string
  scopes: string
  enabled: boolean
  auto_create: boolean
  trusts_second_factor: boolean
}
export type ProviderImpact = { issuer_change: number; count: number; only: number; only_names: string[] }
export type AuthentikStep = { key: string; ok: boolean; detail: string; reason?: string; status?: number }
/** `count`: with the reason `issuer_change`, how many accounts would have to link again (nothing was changed). */
export type AuthentikResult = {
  ok: boolean
  steps: AuthentikStep[]
  links_dropped: number
  count?: number
  /** The public address the run stored (the card's suggestion, confirmed); it stays even when a later step failed. */
  public_url?: string
  /** With the reason `public_url_needed`: what the card shows about the address (the same as `oidcApi.address`). */
  address?: AuthentikAddress
}
/** What the server asks before a new public address leaves redirect addresses behind (409 `public_url_change`). */
export type AddressQuestion = { count: number; address: string; hand: number }
/** An active provider on the account page: linked or not, and the address it knows when it is not the account's. */
export type MyProvider = { slug: string; label: string; linked: boolean; address: string | null }
/** Which account is linked to which provider, for the marks in the operator's account list. */
export type AccountLink = { account_id: number; provider_id: number; slug: string; label: string }

export const oidcApi = {
  providers: () => api<OidcProvider[]>('/api/v1/oidc/admin/providers'),
  addProvider: (form: OidcProviderForm) => api<OidcProvider>('/api/v1/oidc/admin/providers', { method: 'POST', body: form }),
  saveProvider: (id: number, form: OidcProviderForm) => api<OidcProvider & { dropped: number }>(`/api/v1/oidc/admin/providers/${id}`, { method: 'PUT', body: form }),
  removeProvider: (id: number) => api<ProviderImpact>(`/api/v1/oidc/admin/providers/${id}`, { method: 'DELETE' }),
  providerImpact: (id: number, issuer = '') => api<ProviderImpact>(`/api/v1/oidc/admin/providers/${id}/impact`, { query: issuer ? { issuer } : {} }),
  orderProviders: (ids: number[]) => api<ProviderButton[]>('/api/v1/oidc/admin/providers/order', { method: 'PUT', body: { ids } }),
  links: () => api<AccountLink[]>('/api/v1/oidc/admin/links'),
  /** The operator takes an account's link away, with the own password. */
  unlinkAccount: (account: number, provider: number, current_password: string) =>
    api<void>(`/api/v1/oidc/admin/accounts/${account}/links/${provider}`, { method: 'DELETE', body: { current_password } }),
  /**
   * `confirm_issuer_change`: the answer to the question the button stops at when another issuer takes the links.
   * `public_url`: the suggested address ("Use it and set up"), only sent while nexpaper has none.
   */
  authentik: (url: string, token: string, confirm_issuer_change = false, public_url = '') =>
    api<AuthentikResult>('/api/v1/oidc/authentik/setup', { method: 'POST', body: { url, token, confirm_issuer_change, ...(public_url ? { public_url } : {}) } }),
  /** What the authentik card shows about the public address. */
  address: () => api<AuthentikAddress>('/api/v1/oidc/authentik/address'),
  /** "Use it only": the address becomes the public one; 409 `public_url_change` asks first, `confirm` answers it. */
  saveAddress: (public_url: string, confirm = false) => api<AuthentikAddress>('/api/v1/oidc/authentik/address', { method: 'POST', body: { public_url, confirm } }),
  mine: () => api<MyProvider[]>('/api/v1/oidc/me'),
  link: (slug: string, password: string) => api<{ url: string }>(`/api/v1/oidc/${encodeURIComponent(slug)}/link`, { method: 'POST', body: { password } }),
  unlink: (slug: string) => api<void>(`/api/v1/oidc/${encodeURIComponent(slug)}/link`, { method: 'DELETE' }),
  /** The address the provider knows becomes the own one (not confirmed: the link that confirms it is a step of its own). */
  takeAddress: (slug: string) => api<{ email: string; email_confirmed: boolean }>('/api/v1/oidc/me/address', { method: 'POST', body: { slug } }),
}

/** The address a provider's button leads to (a full page load: the browser leaves for the provider). */
export function providerStart(slug: string, extra: { invite?: string; next?: string } = {}): string {
  const query = new URLSearchParams()
  if (extra.invite) query.set('invite', extra.invite)
  if (extra.next && extra.next !== '/') query.set('next', extra.next)
  const text = query.toString()
  return `/api/v1/oidc/${encodeURIComponent(slug)}/start${text ? `?${text}` : ''}`
}

export const passkeyApi = {
  list: () => api<Passkey[]>('/api/v1/auth/passkeys'),
  begin: () => api<{ options: string }>('/api/v1/auth/passkeys/begin', { method: 'POST' }),
  add: (credential: unknown, name: string, password: string) =>
    api<{ passkey: Passkey; recovery_codes: string[] | null; account: Me }>('/api/v1/auth/passkeys', { method: 'POST', body: { credential, name, password } }),
  remove: (id: string, password: string) => api<Me>(`/api/v1/auth/passkeys/${encodeURIComponent(id)}/remove`, { method: 'POST', body: { password } }),
  signInBegin: () => api<{ options: string }>('/api/v1/auth/passkey/begin', { method: 'POST' }),
  signIn: (credential: unknown, remember: boolean) => api<Me>('/api/v1/auth/passkey', { method: 'POST', body: { credential, remember } }),
}

export type ApiKey = {
  id: number
  name: string
  /** `read`: programs that read; `upload`: a scanner or a script that brings files in and reads nothing. */
  scope: 'read' | 'upload'
  prefix: string
  created_at: string
  last_used_at: string | null
  expires_at: string | null
  blocked: boolean
}
/** What the operator sees of a key: whose it is, what it is called and its first characters, never the key. */
export type AnyApiKey = ApiKey & { account: string }

/** API keys for programs: reading, or bringing files in. */
export const apiKeysApi = {
  list: () => api<{ allowed: boolean; keys: ApiKey[] }>('/api/v1/api-keys'),
  make: (name: string, days: number | null, scope: ApiKey['scope'] = 'read') =>
    api<{ key: ApiKey; secret: string }>('/api/v1/api-keys', { method: 'POST', body: { name, days, scope } }),
  remove: (id: number) => api<void>(`/api/v1/api-keys/${id}`, { method: 'DELETE' }),
  /** The operator allows API keys for everybody (the switch under Settings, API). */
  allow: () => api<unknown>('/api/v1/settings', { method: 'PUT', body: { api_keys_allowed: true } }),
  every: () => api<AnyApiKey[]>('/api/v1/admin/api-keys'),
  block: (id: number) => api<AnyApiKey>(`/api/v1/admin/api-keys/${id}/block`, { method: 'POST' }),
}

/** A device or app paired with the account: it speaks with a token of its own (`Authorization: Bearer`). */
export type PairedDevice = {
  id: string
  name: string
  prefix: string
  created_at: string
  last_used_at: string | null
  /** How it was paired: `token` (made in the browser), `qr` (a pairing code), `app:<client>` (an app, OAuth with PKCE). */
  via?: string
}

export const devicesApi = {
  list: () => api<PairedDevice[]>('/api/v1/devices'),
  /** The token comes back once. */
  pair: (name: string) => api<{ device: PairedDevice; token: string }>('/api/v1/devices', { method: 'POST', body: { name } }),
  revoke: (id: string) => api<void>(`/api/v1/devices/${encodeURIComponent(id)}`, { method: 'DELETE' }),
}

// ---- The phone: pairing, apps, the quick upload, the iPhone shortcut ---------------------------------------------------

/** A code to pair a device: shown as a QR code and for typing; valid until `expires_at`, once. */
export type PairingCode = { code: string; expires_at: string; server: string; link: string; qr_svg: string }
export type PairingState = { state: 'open' | 'used' | 'expired' | 'none'; expires_at: string | null; device: PairedDevice | null }

export const pairingApi = {
  start: () => api<PairingCode>('/api/v1/devices/pairing', { method: 'POST' }),
  state: () => api<PairingState>('/api/v1/devices/pairing'),
  cancel: () => api<void>('/api/v1/devices/pairing/cancel', { method: 'POST' }),
}

/** What an app asks for (OAuth 2 with PKCE), as the address of `/oauth/authorize` carries it. */
export type OAuthAsk = {
  client_id: string
  redirect_uri: string
  response_type: string
  code_challenge: string
  code_challenge_method: string
  state: string
  device_name: string
}
export type OAuthAsked = { client_id: string; client_name: string; device_name: string; redirect_uri: string }

export const oauthApi = {
  check: (ask: OAuthAsk) => api<OAuthAsked>('/api/v1/oauth/authorize', { query: ask }),
  answer: (ask: OAuthAsk, allow: boolean) => api<{ redirect: string }>('/api/v1/oauth/authorize', { method: 'POST', body: { ...ask, allow } }),
}

export type QuickVault = { id: number; name: string; icon: string; mine: boolean }
/** What the quick upload of a phone shows. */
export type Quick = { target_vault_id: number; vaults: QuickVault[]; recent: DocumentInfo[]; inbox: number; processing: number }
export type Shortcut = { link: string; address: string; upload_url: string }

export const phoneApi = {
  quick: () => api<Quick>('/api/v1/quick'),
  shortcut: () => api<Shortcut>('/api/v1/shortcut'),
  shortcutLink: () => api<{ link: string }>('/api/v1/settings/shortcut'),
  setShortcutLink: (link: string) => api<{ link: string }>('/api/v1/settings/shortcut', { method: 'PUT', body: { link } }),
}

/** The password for an upload rides in a header, as base64 of its UTF-8: a header carries no umlauts. */
export function passwordHeader(password: string): string {
  let bytes = ''
  for (const byte of new TextEncoder().encode(password)) bytes += String.fromCharCode(byte)
  return btoa(bytes)
}

export function avatarUrl(person: { id: number; avatar: string | null }): string | null {
  return person.avatar ? `/api/v1/avatars/${person.id}?v=${encodeURIComponent(person.avatar)}` : null
}

// ---- The AI ---------------------------------------------------------------------------------------------------------

export type AiProvider = 'none' | 'local' | 'openai' | 'messages'
/** What a person may know about the AI: whether there is one for them (`available`), of which kind, the host the text
 * goes to for a service on the internet (`to`), and the own switch (`mine`). */
export type AiState = { provider: AiProvider; to: string; model: string; mine: boolean; allowed?: boolean; available: boolean; skip_personal?: boolean }
export type AiSettings = { provider: AiProvider; url: string; model: string; key_set: boolean; skip_personal?: boolean; daily_limit?: number; used_today?: number; instructions?: string }
export type AiModel = { id: string; name: string }

export const aiApi = {
  state: () => api<AiState>('/api/v1/ai'),
  settings: () => api<AiSettings>('/api/v1/settings/ai'),
  save: (change: Partial<Omit<AiSettings, 'key_set'>> & { key?: string }) => api<AiSettings>('/api/v1/settings/ai', { method: 'PUT', body: change }),
  models: (typed: { provider?: AiProvider; url?: string; key?: string }) => api<AiModel[]>('/api/v1/settings/ai/models', { method: 'POST', body: typed }),
  probe: () => api<{ seconds: number }>('/api/v1/settings/ai/probe', { method: 'POST' }),
}

// ---- Web Push -------------------------------------------------------------------------------------------------------

export type PushDevice = { id: string; name: string; phone: boolean; since: string; last: string | null }
export type PushState = { key: string; devices: PushDevice[] }
export type PushResult = { sent: number; gone: number; failed: number }
export type PushSettings = { devices: number; key: string; contact: string; contact_used: string; known: string[]; hosts: string[] }

/** Web Push: the own devices and a probe; the operator's card. */
export const pushApi = {
  state: () => api<PushState>('/api/v1/push'),
  add: (subscription: { endpoint: string; p256dh: string; auth: string; installed: boolean }) =>
    api<PushDevice>('/api/v1/push/devices', { method: 'POST', body: subscription }),
  lookup: (endpoint: string) => api<{ id: string | null }>('/api/v1/push/devices/lookup', { method: 'POST', body: { endpoint } }),
  rename: (id: string, name: string) => api<PushDevice>(`/api/v1/push/devices/${encodeURIComponent(id)}`, { method: 'PUT', body: { name } }),
  remove: (id: string) => api<void>(`/api/v1/push/devices/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  probe: () => api<PushResult>('/api/v1/push/test', { method: 'POST' }),
  settings: () => api<PushSettings>('/api/v1/settings/push'),
  saveSettings: (change: { contact?: string; hosts?: string[] }) => api<PushSettings>('/api/v1/settings/push', { method: 'PUT', body: change }),
  renew: (current_password: string) => api<PushSettings>('/api/v1/settings/push/renew', { method: 'POST', body: { current_password } }),
}

// ---- Vaults, documents, sharing -----------------------------------------------------------------------------------------

export type VaultRight = 'read' | 'edit' | 'manage'
export type Person = { id: number; name: string; display_name: string }
export type VaultMember = { user_id: number; name: string; display_name: string; right: VaultRight }
export type Vault = {
  id: number
  name: string
  icon: string
  /** The person whose own vault this is; none for a shared one. */
  personal_of: number | null
  my_right: VaultRight
  documents: number
  size: number
  members: VaultMember[]
}
/** `vault_id` is the vault a kind belongs to; empty for the kinds of the whole server. */
export type DocumentKind = { id: number; key: string; name: string; hue: number; position: number; vault_id?: number | null; keep_years?: number | null }
export type DocumentInfo = {
  id: number
  vault_id: number
  owner: Person | null
  title: string
  sender: { id: number; name: string } | null
  kind: DocumentKind | null
  date: string | null
  /** In cents. */
  amount: number | null
  currency: string
  tags: string[]
  dates: DocumentDate[]
  pages: number
  source: string
  status: 'processing' | 'inbox' | 'filed' | 'trash'
  added_at: string
  trashed_at: string | null
  trash_ends_at: string | null
  change_seq: number
  current_version: number
  my_right: VaultRight
  /** Seen only because it was shared with the person. */
  via_share: boolean
  can_share: boolean
  notes: number
  /** Why reading the file failed (`encrypted`, `broken`, `too_many_pages`, `too_large`, `timeout`, `failed`); empty when all is well. */
  process_error: string
  /** A document the person may see that this one repeats (`same`) or looks like (`similar`). */
  duplicate: { document_id: number; title: string; kind: 'same' | 'similar' } | null
  /** Where the proposals of the inbox came from, per field (`rule`, `ai`, `einvoice`, `text`, `default`, `last_time`;
   * `person` for a field the person changed since). */
  suggest?: Record<string, string>
  /** For who may share it: people it is shared with, links to the outside that work now; empty for everybody else. */
  share_count?: number | null
  link_count?: number | null
  /** The format of the e-invoice it carries (`ZUGFeRD (EN 16931)`, `XRechnung (UBL)` ...); empty when none. */
  einvoice?: string
  /** A split at blank separator pages is proposed (the page tools). */
  split_suggested?: boolean
  /** What the check of the files found: `missing` (a file is gone from the disk), `changed` (a file no longer has its
   * checksum); empty or left out when all is well. */
  files_state?: '' | 'missing' | 'changed'
}
export type DocumentShare = { user: Person; right: 'read' | 'edit'; created_at: string }
export type DocumentLink = {
  id: number
  document_id: number
  recipient: string
  until: string
  allow_download: boolean
  opened_count: number
  last_opened_at: string | null
  created_at: string
  created_by: Person | null
  revoked_at: string | null
  /** `ended`: the person who made it may no longer share the document. */
  status: 'active' | 'expired' | 'revoked' | 'off' | 'ended'
  /** The caller may copy the address again (the person who made it, the managers of the vault). */
  can_copy: boolean
}
export type LinkMade = DocumentLink & { token: string; url: string }
export type MyLink = DocumentLink & { document_title: string }
export type SharingRules = { links_allowed: boolean; link_max_days: number }
export type SharingOverview = { open_links: number; people: number; next_end: string | null }
export type PublicLink = {
  shared_by: string
  recipient: string
  title: string
  sender: string | null
  kind: string | null
  date: string | null
  pages: number
  until: string
  allow_download: boolean
  has_file: boolean
  /** The file can be fetched and the browser shows it in place. */
  viewable: boolean
  /** The pages can be had as pictures. */
  has_pages: boolean
}
export type AccountLeaving = {
  documents: number
  sole_manager_of: { id: number; name: string }[]
  /** `you_see`: the operator is in that vault and would see the documents put there. */
  shared_vaults: { id: number; name: string; you_see: boolean }[]
  /** The people whose own vault the operator is in, the operator included. */
  heirs_you_see: number[]
}
export type DocumentsChoice = 'transfer_to_user' | 'transfer_to_vault' | 'delete_documents'

export const vaultsApi = {
  list: () => api<Vault[]>('/api/v1/vaults'),
  create: (name: string, icon: string) => api<Vault>('/api/v1/vaults', { method: 'POST', body: { name, icon } }),
  setMember: (vault: number, user: number, right: VaultRight) => api<Vault>(`/api/v1/vaults/${vault}/members/${user}`, { method: 'PUT', body: { right } }),
  /** Everybody in the vault at once, in one write: a refusal changes nothing. */
  setMembers: (vault: number, members: { user_id: number; right: VaultRight }[]) => api<Vault>(`/api/v1/vaults/${vault}/members`, { method: 'PUT', body: { members } }),
  removeMember: (vault: number, user: number) => api<void>(`/api/v1/vaults/${vault}/members/${user}`, { method: 'DELETE' }),
  people: () => api<Person[]>('/api/v1/people'),
}

export const documentsApi = {
  retry: (id: number) => api<DocumentInfo>(`/api/v1/documents/${id}/retry`, { method: 'POST' }),
  list: (query: { vault_id?: number; status?: string; after?: number; limit?: number; via_share?: boolean } = {}) =>
    api<{ items: DocumentInfo[]; next: number | null }>('/api/v1/documents', { query }),
  read: (id: number) => api<DocumentInfo>(`/api/v1/documents/${id}`),
}

// ---- The inbox as a list (a page at a time) and the numbers of the menu -----------------------------------------------

export type InboxQuery = { vault_id?: number; shared?: boolean; q?: string; sender?: string; kind_id?: number; source?: string; owner_id?: number; sort?: 'new' | 'old' | 'date'; limit?: number; offset?: number }
export type InboxPage = {
  items: DocumentInfo[]
  /** What the filters (the vault too) find. */
  total: number
  /** By vault id: how many each vault shows under the same filters apart from the vault. */
  counts: Record<string, number>
  /** How many more come through a share of the document alone (they belong to no vault of the person's). */
  shared?: number
  all: number
  reading: number
}
export type MenuCounts = { inbox: number; reading: number; trash: number; deadlines?: number; deadlines_overdue?: number }
export type FiledMany = { filed: number[]; failed: { id: number; code: string }[] }

export const inboxApi = {
  list: (query: InboxQuery = {}) => api<InboxPage>('/api/v1/inbox', { query: query as Record<string, string | number | undefined> }),
  counts: () => api<MenuCounts>('/api/v1/counts'),
  /** Files many at once with a vault, a kind and tags for all of them; each is checked on its own. At most 200. */
  file: (body: { ids: number[]; vault_id?: number; kind_id?: number; add_tags?: string[] }) => api<FiledMany>('/api/v1/inbox/file', { method: 'POST', body }),
}

// ---- Uploads ----------------------------------------------------------------------------------------------------------

/** What became of one file of a browser upload. */
export type UploadResult = {
  filename: string
  status: 'accepted' | 'rejected'
  document: DocumentInfo | null
  error: { code: string; message: string; max_mb?: number } | null
  http_status: number | null
  duplicate: { document_id: number; title: string; kind: 'same' | 'similar' } | null
}
/** An upload in pieces, as the server keeps it. */
export type UploadState = { id: string; state: 'open' | 'finishing' | 'done'; size: number; received: number; chunk_size: number; max_piece: number; expires_at: string; document_id: number | null }
export type UploadStart = { exists: boolean; upload: UploadState | null; document: { id: number; title: string; status: string } | null }
export type UploadFinished = { document: DocumentInfo; duplicate: UploadResult['duplicate']; created: boolean }

/** Where an upload goes and where it came from; left out: the person's own choice, and a browser's upload. */
export type UploadTarget = { vaultId?: number | null; source?: 'camera' | 'share' }

export const uploadsApi = {
  /** Several small files in one request; each has its own result. When none is taken the server answers with the error of
   * the first (an `ApiError` whose `values.items` has all results). */
  send: (files: File[], signal?: AbortSignal, target: UploadTarget = {}) => {
    const form = new FormData()
    for (const file of files) form.append('file', file, file.name)
    const query = { ...(target.vaultId ? { vault_id: target.vaultId } : {}), ...(target.source ? { source: target.source } : {}) }
    return api<{ items: UploadResult[] }>('/api/v1/documents', { method: 'POST', form, signal, query })
  },
  start: (file: { name: string; size: number }, sha256: string, signal?: AbortSignal, target: UploadTarget = {}) =>
    api<UploadStart>('/api/v1/uploads', {
      method: 'POST',
      body: { filename: file.name, size: file.size, sha256, ...(target.vaultId ? { vault_id: target.vaultId } : {}), ...(target.source ? { source: target.source } : {}) },
      signal,
    }),
  state: (id: string, signal?: AbortSignal) => api<UploadState>(`/api/v1/uploads/${encodeURIComponent(id)}`, { signal }),
  piece: (id: string, offset: number, bytes: Blob, signal?: AbortSignal) =>
    api<UploadState>(`/api/v1/uploads/${encodeURIComponent(id)}`, { method: 'PUT', query: { offset }, raw: bytes, headers: { 'Content-Type': 'application/octet-stream' }, signal }),
  finish: (id: string, signal?: AbortSignal) => api<UploadFinished>(`/api/v1/uploads/${encodeURIComponent(id)}/finish`, { method: 'POST', signal }),
  cancel: (id: string) => api<void>(`/api/v1/uploads/${encodeURIComponent(id)}`, { method: 'DELETE' }),
}

export const sharingApi = {
  rules: () => api<SharingRules>('/api/v1/sharing'),
  overview: () => api<SharingOverview>('/api/v1/sharing/overview'),
  myLinks: () => api<MyLink[]>('/api/v1/links'),
  shares: (document: number) => api<DocumentShare[]>(`/api/v1/documents/${document}/shares`),
  share: (document: number, user: number, right: 'read' | 'edit') => api<DocumentShare>(`/api/v1/documents/${document}/shares/${user}`, { method: 'PUT', body: { right } }),
  unshare: (document: number, user: number) => api<void>(`/api/v1/documents/${document}/shares/${user}`, { method: 'DELETE' }),
  links: (document: number) => api<DocumentLink[]>(`/api/v1/documents/${document}/links`),
  makeLink: (document: number, recipient: string, days: number, allow_download: boolean) =>
    api<LinkMade>(`/api/v1/documents/${document}/links`, { method: 'POST', body: { recipient, days, allow_download } }),
  revokeLink: (document: number, link: number) => api<void>(`/api/v1/documents/${document}/links/${link}`, { method: 'DELETE' }),
  /** The address of a link again, to copy (the history notes it). */
  address: (document: number, link: number) => api<{ url: string }>(`/api/v1/documents/${document}/links/${link}/address`, { method: 'POST' }),
  /** What somebody without an account sees behind a link; no sign-in. */
  open: (token: string) => api<PublicLink>(`/api/v1/l/${encodeURIComponent(token)}`),
}

export const accountsApi = {
  /** How many documents the account's own vault holds, and what would keep it from being deleted. */
  leaving: (id: number) => api<AccountLeaving>(`/api/v1/accounts/${id}/leaving`),
  remove: (id: number, body: { current_password: string; confirm_name: string; documents?: DocumentsChoice; target_user_id?: number; target_vault_id?: number }) =>
    api<void>(`/api/v1/accounts/${id}`, { method: 'DELETE', body }),
}

// --- Inputs: the intake folder and the mailbox (block B8) ---------------------------------------------------------------

export type MailLast = { at: string | null; ok: boolean; code: string; mails: number; files: number; unknown: number; skipped?: number; flagged?: number; deferred?: number }
export type IntakeSettings = {
  folder: { on: boolean; path: string; used: string; problem: string; people: { name: string; display_name: string; path: string; problem?: string }[]; operator: string }
  mail: {
    on: boolean
    host: string
    port: number
    security: 'tls' | 'starttls' | 'none'
    user: string
    password_set: boolean
    address: string
    folder: string
    after: 'read' | 'move' | 'delete'
    private: boolean
    drop_unknown: boolean
    auth_server: string
    last: MailLast
  }
}
export type IntakeChange = Partial<{
  folder_on: boolean
  folder_path: string
  mail_on: boolean
  mail_host: string
  mail_port: number
  mail_security: 'tls' | 'starttls' | 'none'
  mail_user: string
  mail_password: string
  mail_address: string
  mail_folder: string
  mail_after: 'read' | 'move' | 'delete'
  mail_private: boolean
  mail_drop_unknown: boolean
  mail_auth_server: string
}>
export type MailFetched = { mails: number; files: number; unknown: number; passed: number; more: boolean; skipped: number; flagged: number; deferred: number; dropped: number; after: string }
export type MailSenderRow = { id: number; address: string; confirmed: boolean; until: string | null }
export type MyIntake = {
  mail_on: boolean
  mail_address: string
  plus_address: string
  account_address: string
  senders: MailSenderRow[]
  folder_on: boolean
  folder: string
  can_confirm: boolean
}
export type DocumentOrigin = { source: string; unknown: boolean; sender: string; subject: string; folder: string; file: string; at: string | null }

export const intakeApi = {
  settings: () => api<IntakeSettings>('/api/v1/settings/intake'),
  save: (change: IntakeChange) => api<IntakeSettings>('/api/v1/settings/intake', { method: 'PUT', body: change }),
  testMail: () => api<{ mails: number; after: 'read' | 'move' | 'delete' }>('/api/v1/settings/intake/mail/test', { method: 'POST' }),
  fetchMail: () => api<MailFetched>('/api/v1/settings/intake/mail/fetch', { method: 'POST' }),
  mine: () => api<MyIntake>('/api/v1/me/intake'),
  addSender: (address: string) => api<MailSenderRow>('/api/v1/me/mail-senders', { method: 'POST', body: { address } }),
  removeSender: (id: number) => api<void>(`/api/v1/me/mail-senders/${id}`, { method: 'DELETE' }),
  /** The link in the mail to a sender address; no sign-in. */
  senderLink: (token: string) => api<{ name: string; address: string }>(`/api/v1/mail-senders/confirm/${encodeURIComponent(token)}`),
  confirmSender: (token: string) => api<{ name: string; address: string }>(`/api/v1/mail-senders/confirm/${encodeURIComponent(token)}`, { method: 'POST' }),
  /** Where a document came from (the folder or the mailbox), for the inbox. */
  origin: (document: number) => api<DocumentOrigin>(`/api/v1/documents/${document}/origin`),
}

/** The text recognition (Settings, Storage). */
export type OcrSettings = {
  languages: string[]
  offered: string[]
  straighten: boolean
  blank_pages: boolean
  jobs: number
  /** ocrmypdf and Tesseract are installed on this server. */
  available: boolean
  running: number
  waiting: number
  seconds_per_page: number | null
  /** The longest the recognition of one document may take, in seconds. */
  max_seconds: number
  /** From this many pages a document waits long for its text (the inbox says so: `ocr.longDocument`). */
  long_document_pages: number
}

export const ocrApi = {
  read: () => api<OcrSettings>('/api/v1/settings/ocr'),
  save: (change: Partial<Pick<OcrSettings, 'languages' | 'straighten' | 'blank_pages' | 'jobs' | 'max_seconds'>>) => api<OcrSettings>('/api/v1/settings/ocr', { method: 'PUT', body: change }),
}

/** A range [start, end) in UTF-16 code units, as JavaScript counts a string. */
export type Mark = [number, number]
export type SearchHit = {
  document: DocumentInfo
  title_marks: Mark[]
  sender_marks: Mark[]
  excerpt: { text: string; marks: Mark[]; source: 'text' | 'notes' } | null
}
export type SearchResult = {
  items: SearchHit[]
  total: number
  next: string | null
  understood: { words: string[]; phrases: string[]; kinds: string[]; senders: string[]; tags: string[]; amounts: { op: '<' | '>' | '='; cents: number }[]; deadlines?: (string | number)[] }
}
export type SearchFilters = {
  vault_id?: number
  kind_id?: number
  owner_id?: number
  sender?: string
  tag?: string
  date_from?: string
  date_to?: string
  status?: 'processing' | 'inbox' | 'filed'
  trash?: boolean
  /** Only what was shared with the person one by one (true), or only what lies in their vaults (false). */
  via_share?: boolean
  /** Only documents with a deadline that is open, overdue, done, or open within that many days (`30`). */
  deadline?: string
  cursor?: string
  limit?: number
}
export type VersionText = { version: number; state: 'done' | 'pending' | 'none'; pages: string[]; ocr_pages: number; languages: string; long_document_pages?: number }

/** The orders of a numbered page: a minus is the largest (the newest, Z) first; empty senders and amounts come last. */
export type SearchOrder = '-date' | 'date' | '-title' | 'title' | '-sender' | 'sender' | '-amount' | 'amount'
/** A numbered page (`page` from 1) in an order, instead of the cursor. */
export type SearchPage = SearchFilters & { sort?: SearchOrder; page?: number }
export type NameCount = { name: string; count: number }
/** How the documents spread, for the start of the archive. A kind's id as `kind_id` finds its namesakes too. */
export type SearchOverview = {
  total: number
  senders: NameCount[]
  kinds: { kind: DocumentKind; count: number }[]
  years: { year: number; count: number }[]
  tags: NameCount[]
}

export const searchApi = {
  find: (q: string, filters: SearchPage = {}, signal?: AbortSignal) => api<SearchResult>('/api/v1/search', { query: { q, ...filters }, signal }),
  overview: (filters: Pick<SearchFilters, 'vault_id' | 'status' | 'via_share' | 'deadline'> = {}, signal?: AbortSignal) =>
    api<SearchOverview>('/api/v1/search/overview', { query: filters, signal }),
  text: (document: number, version: number) => api<VersionText>(`/api/v1/documents/${document}/versions/${version}/text`),
}

// ---- Paperless import (Settings, Import; the operator) ---------------------------------------------------------------

export type PaperlessRunState = 'idle' | 'queued' | 'running' | 'paused' | 'done' | 'failed'
export type PaperlessRun = {
  state: PaperlessRunState
  /** The documents in Paperless, and how many of them are here (from this run and the ones before). */
  total: number
  done: number
  /** Taken and skipped in this run, with the reasons of the skipped ones. */
  taken: number
  skipped: number
  reasons: Record<string, number>
  error: string
  stop: boolean
  started_at: string | null
  finished_at: string | null
}
export type PaperlessSettings = { url: string; token_set: boolean; private: boolean; where: 'owner' | 'vault'; vault_id: number | null; sort?: PaperlessSort; run: PaperlessRun }
/** The documents of the import that were skipped: their number in Paperless and the reason (a code), nothing else. */
export type PaperlessSkipped = { items: { paperless_id: number; reason: string }[]; total: number; more: number }
export type PaperlessChange = Partial<{ url: string; token: string; private: boolean }>
export type PaperlessOwner = { paperless_id: number | null; name: string; documents: number; user_id: number; matched: boolean }
export type PaperlessCheck = {
  version: string
  api_version: number
  documents: number
  tags: number
  correspondents: number
  document_types: number
  custom_fields: number
  new_kinds: string[]
  owners: PaperlessOwner[]
  users_hidden: boolean
  already: number
  /** Documents Paperless still has in its inbox. */
  inbox_documents?: number
  people: Person[]
  vaults: { id: number; name: string; own: boolean }[]
}
/** As in Paperless (its inbox into the inbox, the rest filed), or everything into the inbox. */
export type PaperlessSort = 'paperless' | 'inbox'
export type PaperlessStart = { where: 'owner' | 'vault'; vault_id?: number | null; sort?: PaperlessSort; people: { paperless_id: number | null; user_id: number }[] }

export const paperlessApi = {
  read: () => api<PaperlessSettings>('/api/v1/settings/paperless'),
  save: (change: PaperlessChange) => api<PaperlessSettings>('/api/v1/settings/paperless', { method: 'PUT', body: change }),
  forget: () => api<PaperlessSettings>('/api/v1/settings/paperless', { method: 'DELETE' }),
  check: () => api<PaperlessCheck>('/api/v1/settings/paperless/check', { method: 'POST' }),
  start: (plan: PaperlessStart) => api<PaperlessSettings>('/api/v1/settings/paperless/start', { method: 'POST', body: plan }),
  /** Goes on with what was chosen at the last start. */
  resume: () => api<PaperlessSettings>('/api/v1/settings/paperless/start', { method: 'POST', body: { resume: true } }),
  stop: () => api<PaperlessSettings>('/api/v1/settings/paperless/stop', { method: 'POST' }),
  skipped: () => api<PaperlessSkipped>('/api/v1/settings/paperless/skipped'),
}

// ---- Exports for the tax adviser ---------------------------------------------------------------------------------------

/** The filters of the archive an export starts from: the search and the filters of `GET /search`. */
export type ExportFilters = {
  q?: string
  vault_id?: number
  kind_id?: number
  owner_id?: number
  sender?: string
  tag?: string
  date_from?: string
  date_to?: string
  status?: 'inbox' | 'filed'
}
export type ExportContent = { pdf: boolean; original: boolean; csv: boolean; xml: boolean }
export type ExportLinkInfo = {
  id: number
  recipient: string
  until: string
  opened_count: number
  last_opened_at: string | null
  created_at: string
  revoked_at: string | null
  status: 'active' | 'expired' | 'revoked' | 'off' | 'ended'
}
export type ExportInfo = {
  id: number
  state: 'queued' | 'packing' | 'ready' | 'failed'
  documents: number
  size: number
  /** The sum of the amounts, in cents. */
  total: number
  error: string
  date_from: string | null
  date_to: string | null
  vault_ids: number[]
  content: ExportContent
  created_at: string
  finished_at: string | null
  expires_at: string
  links: ExportLinkInfo[]
}
export type ExportMade = ExportInfo & { link: (ExportLinkInfo & { token: string; url: string }) | null }
export type ExportPreview = { documents: number; total: number; totals: Record<string, number>; size: number; sample: string[]; too_many: boolean; max_documents: number; max_bytes: number }
export type ExportRequest = Omit<ExportFilters, 'vault_id'> & { vault_ids: number[]; content: ExportContent; link?: { recipient: string; days: number } }
export type PublicExport = { shared_by: string; recipient: string; state: 'packing' | 'ready'; documents: number; size: number; until: string; date_from: string | null; date_to: string | null }

export const exportsApi = {
  preview: (request: ExportRequest, signal?: AbortSignal) =>
    api<ExportPreview>('/api/v1/exports/preview', {
      query: {
        vault_ids: request.vault_ids.map(String),
        date_from: request.date_from || undefined,
        date_to: request.date_to || undefined,
        q: request.q || undefined,
        kind_id: request.kind_id,
        owner_id: request.owner_id,
        sender: request.sender,
        tag: request.tag,
        status: request.status,
        pdf: request.content.pdf,
        original: request.content.original,
        csv: request.content.csv,
        xml: request.content.xml,
      },
      signal,
    }),
  create: (request: ExportRequest) => api<ExportMade>('/api/v1/exports', { method: 'POST', body: request }),
  list: () => api<ExportInfo[]>('/api/v1/exports'),
  remove: (id: number) => api<void>(`/api/v1/exports/${id}`, { method: 'DELETE' }),
  fileUrl: (id: number) => `/api/v1/exports/${id}/file`,
  makeLink: (id: number, recipient: string, days: number) =>
    api<ExportLinkInfo & { token: string; url: string }>(`/api/v1/exports/${id}/links`, { method: 'POST', body: { recipient, days } }),
  address: (id: number, link: number) => api<{ url: string }>(`/api/v1/exports/${id}/links/${link}/address`, { method: 'POST' }),
  revokeLink: (id: number, link: number) => api<void>(`/api/v1/exports/${id}/links/${link}`, { method: 'DELETE' }),
  /** What somebody without an account sees behind a link to an export; no sign-in. */
  open: (token: string) => api<PublicExport>(`/api/v1/x/${encodeURIComponent(token)}`),
  publicFileUrl: (token: string) => `/api/v1/x/${encodeURIComponent(token)}/file`,
}

// ---- One document: fields, notes, history, versions; the catalog (block B4) --------------------------------------------

export type DateKind = 'due' | 'contract_end' | 'warranty_end' | 'keep_until'
/** What `PATCH /documents/{id}` takes: only the fields sent change. `sender` is a name (made when new; empty takes it
 * away), `amount` in cents, `tags` and `dates` replace the whole list. */
export type DocumentPatch = Partial<{
  title: string
  sender: string | null
  kind_id: number | null
  date: string | null
  amount: number | null
  status: 'inbox' | 'filed'
  tags: string[]
  dates: DateIn[]
  /** Only the terms named, and of them only what is sent (a left-out `date` keeps the day). Not with `dates`. */
  set_dates: DateSet[]
  remove_dates: DateKind[]
}>
/** A notice period of a contract. */
export type Notice = { n: number; unit: 'weeks' | 'months' }
/** A date as `PATCH` takes it: a contract may carry its notice period and renewal (left out: they stay, `null`: gone). */
export type DateIn = { kind: DateKind; date: string; notice?: Notice | null; renew_months?: number | null; manual?: boolean }
/** One term of `set_dates`: the kind and what changes of it. For `keep_until`, `manual: false` works it out from the kind
 * again, `manual: true` without a `date` sets the day it has by hand. */
export type DateSet = { kind: DateKind; date?: string; notice?: Notice | null; renew_months?: number | null; manual?: boolean }
/** A date of a document as the server has it: with a contract's terms, the last day to cancel worked out from them,
 * who marked it done and when, and the person's own "later". */
export type DocumentDate = {
  kind: string
  date: string
  /** Only on `keep_until`: set by a person (otherwise worked out from the kind's keeping time). */
  manual?: boolean
  notice?: Notice | null
  renew_months?: number | null
  last_to_cancel?: string | null
  done?: { at: string; by: Person | null } | null
  renewed_from?: string | null
  snoozed_until?: string | null
}

// ---- Deadlines (F1) ---------------------------------------------------------------------------------------------------

export type DeadlineKind = 'due' | 'contract_end' | 'warranty_end'
export type DeadlineWhat = 'pay' | 'cancel' | 'ends' | 'warranty'
export type Deadline = {
  document_id: number
  title: string
  status: 'inbox' | 'filed'
  vault_id: number
  via_share: boolean
  sender: string | null
  amount: number | null
  currency: string
  kind: DeadlineKind
  what: DeadlineWhat
  /** The day to act by and how far it is from today (below 0: overdue). */
  date: string
  days: number
  end: string
  notice: Notice | null
  renew_months: number | null
  renews_to: string | null
  missed: string | null
  done: { at: string; by: Person | null } | null
  snoozed_until: string | null
}
export type DeadlineSection = { total: number; items: Deadline[] }
export type Deadlines = {
  today: string
  soon_days: number
  overdue: DeadlineSection
  soon: DeadlineSection
  later: DeadlineSection
  done: DeadlineSection | null
  counts: Record<string, number>
  shared: number
}
export type DeadlineQuery = { vault_id?: number; shared?: boolean; what?: 'pay' | 'cancel' | 'warranty'; done?: boolean; limit?: number }

export const deadlinesApi = {
  list: (query: DeadlineQuery = {}) => api<Deadlines>('/api/v1/deadlines', { query: query as Record<string, string | number | boolean | undefined> }),
  /** Paid, cancelled, claimed: for everybody. */
  done: (id: number, kind: DeadlineKind) => api<DocumentInfo>(`/api/v1/documents/${id}/dates/${kind}/done`, { method: 'POST' }),
  reopen: (id: number, kind: DeadlineKind) => api<DocumentInfo>(`/api/v1/documents/${id}/dates/${kind}/done`, { method: 'DELETE' }),
  /** Later, only for oneself: 1, 3 or 7 days. */
  snooze: (id: number, kind: DeadlineKind, days: 1 | 3 | 7) => api<{ until: string }>(`/api/v1/documents/${id}/dates/${kind}/snooze`, { method: 'PUT', body: { days } }),
  unsnooze: (id: number, kind: DeadlineKind) => api<void>(`/api/v1/documents/${id}/dates/${kind}/snooze`, { method: 'DELETE' }),
}
export type DocumentNote = { id: number; author: Person | null; text: string; created_at: string; updated_at: string | null; mine: boolean }
export type DocumentEvent = { id: number; at: string; action: string; by: Person | null; by_link: string; detail: Record<string, unknown> | null }
export type DocumentVersion = {
  n: number
  current: boolean
  pages: number
  size: number
  sha256: string
  created_at: string
  created_by: Person | null
  note: string
  kind: string
  has_archive: boolean
  has_pages: boolean
  /** Where the original lies, from the folder for documents on: vault, year, sender, file. */
  path?: string
  /** How it came about (the page tools): `pages`, `merged`, `split`, `restored` (from `from_n`), `uploaded`; empty for
   * the file the document came with. */
  origin?: string
  from_n?: number | null
  /** `processing` while an uploaded version is read, `failed` (`error` says why) when it could not be. */
  state?: 'ready' | 'processing' | 'failed'
  error?: string
}
/** A sender or a tag: one name, and its rows in the vaults the person reaches. */
export type NameGroup = { name: string; items: { id: number; vault_id: number }[] }

/** How long a deleted document stays in the trash (the server's ``services/documents.TRASH_DAYS``). */
export const TRASH_DAYS = 30

const doc = (id: number) => `/api/v1/documents/${id}`

export const documentApi = {
  patch: (id: number, change: DocumentPatch) => api<DocumentInfo>(doc(id), { method: 'PATCH', body: change }),
  move: (id: number, vaultId: number) => api<DocumentInfo>(`${doc(id)}/move`, { method: 'POST', body: { vault_id: vaultId } }),
  trash: (id: number) => api<DocumentInfo>(doc(id), { method: 'DELETE' }),
  restore: (id: number) => api<DocumentInfo>(`${doc(id)}/restore`, { method: 'POST' }),
  /** Deletes a document in the trash for good. */
  purge: (id: number) => api<void>(`${doc(id)}/purge`, { method: 'POST' }),
  notes: (id: number) => api<DocumentNote[]>(`${doc(id)}/notes`),
  addNote: (id: number, text: string) => api<DocumentNote>(`${doc(id)}/notes`, { method: 'POST', body: { text } }),
  editNote: (id: number, note: number, text: string) => api<DocumentNote>(`${doc(id)}/notes/${note}`, { method: 'PUT', body: { text } }),
  deleteNote: (id: number, note: number) => api<void>(`${doc(id)}/notes/${note}`, { method: 'DELETE' }),
  events: (id: number) => api<DocumentEvent[]>(`${doc(id)}/events`),
  versions: (id: number) => api<DocumentVersion[]>(`${doc(id)}/versions`),
}

/** Addresses of the files and pictures of a version (each version has its own: a cache never shows an old one). */
export const fileUrls = {
  file: (id: number, version: number) => `${doc(id)}/versions/${version}/file`,
  archive: (id: number, version: number) => `${doc(id)}/versions/${version}/archive`,
  preview: (id: number, version: number) => `${doc(id)}/versions/${version}/preview`,
  page: (id: number, version: number, page: number, size: 'small' | 'large' = 'small') => `${doc(id)}/versions/${version}/pages/${page}?size=${size}`,
}

export const catalogApi = {
  senders: (vaultId?: number) => api<NameGroup[]>('/api/v1/senders', { query: { vault_id: vaultId } }),
  tags: (vaultId?: number) => api<NameGroup[]>('/api/v1/tags', { query: { vault_id: vaultId } }),
  /** The kinds to choose from: of the whole server and of the person's vaults; with a vault, the choice for its documents. */
  kinds: (vaultId?: number) => api<DocumentKind[]>('/api/v1/kinds', { query: { vault_id: vaultId } }),
  /** A kind for a vault (`edit` there). A name the vault can already choose answers with that kind. */
  createKind: (name: string, vaultId: number, hue: number) => api<DocumentKind>('/api/v1/kinds', { method: 'POST', body: { name, hue, vault_id: vaultId } }),
  /** Deletes a kind of a vault. While documents use it, anybody but a manager of the vault gets `409 in_use` with `documents`; `force` goes on. */
  removeKind: (id: number, force = false) => api<void>(`/api/v1/kinds/${id}`, { method: 'DELETE', query: force ? { force: true } : {} }),
  renameSender: (id: number, name: string) => api<{ id: number; name: string }>(`/api/v1/senders/${id}`, { method: 'PATCH', body: { name } }),
  /** While documents use the sender, anybody but a manager of the vault gets `409 in_use` with `documents`; `force` goes on. */
  deleteSender: (id: number, force = false) => api<void>(`/api/v1/senders/${id}`, { method: 'DELETE', query: force ? { force: true } : {} }),
  renameTag: (id: number, name: string) => api<{ id: number; name: string }>(`/api/v1/tags/${id}`, { method: 'PATCH', body: { name } }),
  deleteTag: (id: number) => api<void>(`/api/v1/tags/${id}`, { method: 'DELETE' }),
  renameKind: (id: number, name: string) => api<DocumentKind>(`/api/v1/kinds/${id}`, { method: 'PATCH', body: { name } }),
}

// ---- Order: what the senders, tags and kinds are used for ------------------------------------------------------------

export type OrderWhat = 'senders' | 'tags' | 'kinds'
export type OrderEntry = {
  id: number
  name: string
  /** Empty for a kind of the whole server. */
  vault_id: number | null
  /** The caller's right in that vault; empty for a kind of the server. */
  right: VaultRight | null
  /** Not in the trash. */
  documents: number
  in_trash: number
  /** Rename, merge and delete: `manage` in the vault, or the operator for a kind of the server. */
  can_change: boolean
  /** Only kinds. */
  key?: string
  hue?: number
  position?: number
  /** Only kinds: how many years their documents are kept (empty: not set), and whether only for newly filed ones. */
  keep_years?: number | null
  keep_new_only?: boolean
}
export type OrderPage = { items: OrderEntry[]; total: number }
export type OrderQuery = { vault_id?: number; q?: string; order?: 'name' | 'documents'; limit?: number; offset?: number }

export const orderApi = {
  list: (what: OrderWhat, query: OrderQuery = {}) => api<OrderPage>(`/api/v1/order/${what}`, { query }),
  /** All documents of the entry go to `into` (the same vault), and the entry is deleted. `manage` there. */
  merge: (what: OrderWhat, id: number, into: number) => api<unknown>(`/api/v1/${what}/${id}/merge`, { method: 'POST', body: { into } }),
}

// ---- Sorting in: rules and e-invoices (B6) ----------------------------------------------------------------------------

export type RuleCondition =
  | { field: 'sender'; op: 'is' | 'contains'; values: string[] }
  | { field: 'text'; op: 'contains'; values: string[] }
  | { field: 'kind'; op: 'is'; value: number }
  | { field: 'source'; op: 'is'; value: string }
  | { field: 'amount'; op: 'over' | 'under'; value: number }
export type RuleAction = { field: 'vault' | 'kind'; value: number } | { field: 'tag' | 'sender' | 'title'; value: string }
export type Rule = {
  id: number
  /** Empty for a rule of the whole server (the operator's). */
  vault_id: number | null
  position: number
  on: boolean
  hits: number
  last_hit_at: string | null
  when: RuleCondition[]
  then: RuleAction[]
  created_at: string
}
export type RuleDraft = { when: RuleCondition[]; then: RuleAction[]; on?: boolean }
export type RuleChange = Partial<RuleDraft> & { position?: number }

/** The rules of the vaults the person manages, and the operator's rules for the whole server (`server`). */
export const rulesApi = {
  list: () => api<Rule[]>('/api/v1/rules'),
  create: (vaultId: number, rule: RuleDraft) => api<Rule>('/api/v1/rules', { method: 'POST', body: { vault_id: vaultId, ...rule } }),
  change: (id: number, change: RuleChange) => api<Rule>(`/api/v1/rules/${id}`, { method: 'PATCH', body: change }),
  remove: (id: number) => api<void>(`/api/v1/rules/${id}`, { method: 'DELETE' }),
  serverList: () => api<Rule[]>('/api/v1/settings/rules'),
  serverCreate: (rule: RuleDraft) => api<Rule>('/api/v1/settings/rules', { method: 'POST', body: rule }),
  serverChange: (id: number, change: RuleChange) => api<Rule>(`/api/v1/settings/rules/${id}`, { method: 'PATCH', body: change }),
  serverRemove: (id: number) => api<void>(`/api/v1/settings/rules/${id}`, { method: 'DELETE' }),
  /** "Als Regel merken": documents of this sender get what was chosen for this one. */
  remember: (documentId: number, chosen: { kind_id?: number; vault_id?: number; tags?: string[] }) =>
    api<Rule>(`/api/v1/documents/${documentId}/rule`, { method: 'POST', body: chosen }),
}

export type EInvoiceLine = { text: string; quantity: string; unit: string; price: number | null; total: number | null }
export type EInvoice = {
  version: number
  /** The original of that version is the XML itself (an XRechnung); nexpaper set the readable page from it. */
  xml_only: boolean
  format: string
  number: string
  issued: string | null
  due: string | null
  seller: string
  seller_vat: string
  buyer: string
  buyer_ref: string
  iban: string
  currency: string
  net: number | null
  tax: number | null
  gross: number | null
  payable: number | null
  credit_note: boolean
  lines: EInvoiceLine[]
}

export const einvoiceApi = {
  read: (documentId: number) => api<EInvoice>(`/api/v1/documents/${documentId}/einvoice`),
  /** The XML of the e-invoice of a version: what came, or what was taken out of the PDF. */
  xmlUrl: (documentId: number, version: number) => `/api/v1/documents/${documentId}/versions/${version}/einvoice`,
}

/** The kinds of document, the operator's list (Settings, Filing). */
export const kindsApi = {
  list: () => api<DocumentKind[]>('/api/v1/kinds'),
  create: (name: string, hue: number) => api<DocumentKind>('/api/v1/kinds', { method: 'POST', body: { name, hue } }),
  remove: (id: number) => api<void>(`/api/v1/kinds/${id}`, { method: 'DELETE' }),
}

// Reminders (F2): how the own account is reminded of deadlines.
export type ReminderRhythm = 'single' | 'weekly' | 'both'
export type ReminderLead = { due: number; cancel: number; warranty: number }
export type ReminderVault = { id: number; name: string; icon: string; personal: boolean; personal_of_other: boolean }
export type Reminders = {
  rhythm: ReminderRhythm
  push: boolean
  mail: boolean
  lead: ReminderLead
  same_day: boolean
  muted: number[]
  muted_shared: boolean
  options: { due: number[]; cancel: number[]; warranty: number[] }
  hour: number
  time_zone: string
  push_devices: number
  mail_address: string
  mail_problem: 'no_server' | 'no_address' | 'unconfirmed' | null
  vaults: (ReminderVault & { muted: boolean; others: number })[]
  read_only: ReminderVault[]
  shared: number
}
export type RemindersChange = Partial<Pick<Reminders, 'rhythm' | 'push' | 'mail' | 'same_day' | 'muted' | 'muted_shared'>> & { lead?: Partial<ReminderLead> }
export type ReminderTest = { push: PushResult; mail: boolean; by_push: boolean; by_mail: boolean }

export const remindersApi = {
  get: () => api<Reminders>('/api/v1/me/reminders'),
  save: (change: RemindersChange) => api<Reminders>('/api/v1/me/reminders', { method: 'PUT', body: change }),
  test: () => api<ReminderTest>('/api/v1/me/reminders/test', { method: 'POST' }),
}

// ---- Keeping documents (F3): the keeping time of a kind, what may go ---------------------------------------------------

export type KeepPreview = { documents: number; by_hand: number; expired: number }
export type KeepSet = { kind: DocumentKind; changed: number; queued: boolean }
export type MayGoPage = { items: DocumentInfo[]; total: number }
export type TrashResult = { trashed: number[]; failed: { id: number; code: string }[] }

export const keepingApi = {
  /** What setting `years` (null: taking the time away) for the documents of the kind already there would do (only
   * documents the person sees). */
  preview: (kindId: number, years: number | null) => api<KeepPreview>(`/api/v1/kinds/${kindId}/keeping/preview`, { method: 'POST', body: { years } }),
  /** Sets the keeping time (`null` takes it away). `existing`: also for the documents already there. */
  set: (kindId: number, years: number | null, existing: boolean) => api<KeepSet>(`/api/v1/kinds/${kindId}/keeping`, { method: 'PUT', body: { years, existing } }),
  /** Filed documents whose keeping time is over, in the vaults where the person may change things. */
  mayGo: (query: { vault_id?: number; limit?: number; offset?: number } = {}) => api<MayGoPage>('/api/v1/keeping', { query }),
  /** Many documents into the trash, each checked on its own. */
  trashMany: (ids: number[]) => api<TrashResult>('/api/v1/documents/trash', { method: 'POST', body: { ids } }),
}
