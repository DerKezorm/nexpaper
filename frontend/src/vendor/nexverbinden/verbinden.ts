// nexverbinden in the browser: what the module's routes answer, the buttons, the module's words and their helpers.
// The parts themselves are ConnectionCard.tsx, ConnectionsArea.tsx, ConsentPage.tsx, ReturnPage.tsx and
// ConnectionsOperatorCard.tsx (built from the ui kit). Copied unchanged into frontend/src/vendor/nexverbinden/ by
// bauplaene/verbinden/tools/sync.py; changed only there.

import { NEXUI_TEXTS, languageOf, useNexuiTexts } from '../nexui'

import de from './verbinden.de.json'
import en from './verbinden.en.json'
import fr from './verbinden.fr.json'

/** Where the module's routes are mounted (the same in every app). */
export const VERBINDEN_BASE = '/api/connect'
/** The page of the settings that holds the cards (the return page goes back there). */
export const CONNECTIONS_PAGE = '/settings/connections'

/** The state of a card: the module's states, an older connection by API key (`legacy`, `expiring`), none. */
export type ConnectionState = 'none' | 'connected' | 'unreachable' | 'refused' | 'resting' | 'off' | 'legacy' | 'expiring'

export type AreaRef = { id: number | string; name: string }

/** One partner as `GET <base>/partners` lists it. No token, no hash. */
export type PartnerView = {
  partner: string
  state: ConnectionState
  /** The partner's address: of the connection, of the older one, else the operator's (may be empty). */
  address: string
  address_from_operator: boolean
  host: string
  /** What this app may do at the partner, and what the partner may do here (purpose ids). */
  uses: string[]
  grants: string[]
  /** The right each purpose stands for (`read`, `write`), for the arrows of "Was fließt". */
  uses_levels: Record<string, string>
  grants_levels: Record<string, string>
  /** The account's name in the partner app. */
  account: string | null
  since: string | null
  ok_at: string | null
  used_at: string | null
  stale_since: string | null
  problem: string | null
  /** The partner's areas this app reaches (`null`: all, also later ones). */
  areas_used: AreaRef[] | null
  /** This app's areas the partner reaches (`null`: all). */
  areas_granted: AreaRef[] | null
  legacy: { shown: string; expires_at: string | null } | null
  /** Decision V16: this app's areas to choose before the click, where the partner reads areas here (else empty). */
  areas_choice: AreaRef[]
  version: string | null
}

/** One purpose on the consent page. */
export type PurposeInfo = { id: string; level: string; areas: boolean }

/** `GET <base>/consent`: what the consent page shows. */
export type ConsentInfo = {
  app: string
  partner: string
  partner_host: string
  account: string
  /** What the asking app may do here, and what this app gets there. */
  partner_may: PurposeInfo[]
  app_may: PurposeInfo[]
  areas: AreaRef[]
  replaces: boolean
}

/** `GET` and `PUT <base>/admin`. */
export type ConnectionsAdmin = { connections: boolean; partners: string[]; addresses: Record<string, string> }

/** The values of the consent page's address that go back to the server. */
export const CONSENT_PARAMS = ['client_id', 'redirect_uri', 'state', 'code_challenge', 'code_challenge_method'] as const

/** The app's way to call its server (its own client with its headers), as for the cards of schluessel and mcp. A
 * refusal throws; the parts read its code with `refusalCode`. */
export type VerbindenRequest = <T>(path: string, init?: { method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'; body?: unknown }) => Promise<T>

/** Kind and symbol of every button (at most one primary per box; what ends something is `danger`). */
export const VERBINDEN_BUTTONS = {
  connect: { kind: 'primary', icon: 'Link' },
  manual: { kind: 'secondary', icon: 'KeyRound' },
  renew: { kind: 'secondary', icon: 'RefreshCw' },
  renewNow: { kind: 'primary', icon: 'RefreshCw' },
  check: { kind: 'secondary', icon: 'RefreshCw' },
  reconnect: { kind: 'primary', icon: 'Link' },
  disconnect: { kind: 'danger', icon: 'Unplug' },
  remove: { kind: 'danger', icon: 'Trash2' },
  allow: { kind: 'primary', icon: 'Check' },
  decline: { kind: 'secondary', icon: 'X' },
  save: { kind: 'secondary', icon: 'Check' },
  back: { kind: 'secondary', icon: 'ArrowLeft' },
} as const

/** The badge of each state. */
export const STATE_TONES = {
  none: 'off',
  connected: 'on',
  unreachable: 'warn',
  refused: 'danger',
  resting: 'warn',
  off: 'off',
  legacy: 'on',
  expiring: 'warn',
} as const

export type VerbindenTexts = typeof de
export const VERBINDEN_TEXTS: Record<'de' | 'en' | 'fr', VerbindenTexts> = { de, en, fr }

/** Fills `{partner}`, `{app}`, `{when}` … */
export function fillVerbinden(text: string, values: Record<string, string | number>): string {
  return text.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? String(values[key] ?? '') : whole))
}

/** The words of a purpose, granted by `grantedBy`. */
export function purposeLabel(texts: VerbindenTexts, grantedBy: string, purpose: string): string {
  const own = (texts.purposes as Record<string, Record<string, string>>)[grantedBy]
  return own?.[purpose] ?? purpose
}

/** The sentence of a pair of apps (the card's line under the title). */
export function aboutPair(texts: VerbindenTexts, app: string, partner: string): string {
  const key = [app, partner].sort().join('+')
  return (texts.about as Record<string, string>)[key] ?? ''
}

/** Which way a purpose makes things go, seen from the app showing the card: reading at the partner brings things here,
 * writing there sends them there; the partner's reading here sends things there, its writing brings them here. */
export function wayOf(level: string, mine: boolean): 'in' | 'out' {
  const reads = level === 'read'
  return mine === reads ? 'in' : 'out'
}

/** The code of a refused request: the module's `{code}` in FastAPI's `detail`, or on the error itself. */
export function refusalCode(error: unknown): string | undefined {
  const found = error as { code?: unknown; detail?: unknown; body?: unknown } | null
  const inner = (found?.detail ?? (found?.body as { detail?: unknown } | undefined)?.detail ?? found) as { code?: unknown } | string | null
  if (typeof inner === 'string') return inner
  return typeof inner?.code === 'string' ? inner.code : undefined
}

/** The words of a refusal of the module. */
export function refusalText(texts: VerbindenTexts, error: unknown, app: string): string {
  const code = refusalCode(error)
  const found = code ? (texts.errors as Record<string, string>)[code] : undefined
  return fillVerbinden(found ?? texts.failed, { app })
}

/** How a moment is written; the app may give its own (nextime: the account's zone). */
export type WhenFormat = (iso: string, language: string) => string

export function defaultWhen(iso: string, language: string): string {
  const moment = new Date(iso)
  return Number.isNaN(moment.getTime()) ? iso : moment.toLocaleString(language, { dateStyle: 'medium', timeStyle: 'short' })
}

export function defaultDay(iso: string, language: string): string {
  const moment = new Date(iso)
  return Number.isNaN(moment.getTime()) ? iso : moment.toLocaleDateString(language, { dateStyle: 'medium' })
}

/** The module's words in the kit's language (or the one given). */
export function useVerbindenTexts(language?: string): { texts: VerbindenTexts; code: 'de' | 'en' | 'fr' } {
  const kit = useNexuiTexts()
  if (language) {
    const code = languageOf(language)
    return { texts: VERBINDEN_TEXTS[code], code }
  }
  const code = (Object.keys(NEXUI_TEXTS) as (keyof typeof NEXUI_TEXTS)[]).find((key) => NEXUI_TEXTS[key] === kit) ?? 'en'
  return { texts: VERBINDEN_TEXTS[code], code }
}
