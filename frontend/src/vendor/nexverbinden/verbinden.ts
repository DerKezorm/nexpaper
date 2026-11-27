// nexverbinden in the browser: what the module's routes answer, the buttons, the module's words and their helpers.
// The parts themselves are ConnectionCard.tsx, ConnectionsArea.tsx, ConsentPage.tsx, ReturnPage.tsx and
// ConnectionsOperatorCard.tsx (built from the ui kit). Copied unchanged into frontend/src/vendor/nexverbinden/ by
// bauplaene/verbinden/tools/sync.py; changed only there.

import { useSyncExternalStore } from 'react'

import { NEXUI_TEXTS, formatDay, formatMoment, languageOf, useNexuiTexts } from '../nexui'

import { APP_MARKS } from './logos'

import de from './verbinden.de.json'
import en from './verbinden.en.json'
import fr from './verbinden.fr.json'

/** Where the module's routes are mounted (the same in every app). */
export const VERBINDEN_BASE = '/api/connect'
/** The page of the settings that holds the cards (the return page goes back there). */
export const CONNECTIONS_PAGE = '/settings/connections'

/** Since 0.1.8 (B2, B3): Server › Allgemein with the card "Andere nex-Apps" (`id="nex-apps"`), the same in every app;
 * the cards link there for the operator, here and in the partner app. */
export const OPERATOR_PAGE = '/settings/general#nex-apps'

/** Since 0.1.8 (B5, V48): the frame of the module's own pages (`/connect/app`, `/connect/return`): the whole height of
 * the window, the card in its middle, the same in every app; the app shows the page without a frame of its own. */
export const PAGE_FRAME = 'flex min-h-dvh w-full items-center justify-center px-4 py-8'

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
  /** Since 0.1.8 (V42, B3): whether the account can connect from here (an address of the operator, of the connection
   * or of an older one). Left out by an older server: an address there means set up. */
  set_up?: boolean
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
  /** V16, V41: this app's areas to choose before the click, where the partner reads or writes areas here (else empty). */
  areas_choice: AreaRef[]
  version: string | null
}

/** One purpose on the consent page. */
export type PurposeInfo = { id: string; level: string; areas: boolean }

/** Since 0.1.8 (B1, V43): who is signed in on the consent page: the shown name ("" where it is the user name), the
 * user name, the address of the own picture and the app's colour of the person (or none). */
export type AccountCard = { name: string; username: string; picture: string | null; color: string | null }

/** `GET <base>/consent`: what the consent page shows. */
export type ConsentInfo = {
  app: string
  partner: string
  partner_host: string
  account: string
  /** Since 0.1.8 (B1); left out by an older server. */
  account_card?: AccountCard
  /** What the asking app may do here, and what this app gets there. */
  partner_may: PurposeInfo[]
  app_may: PurposeInfo[]
  areas: AreaRef[]
  replaces: boolean
}

/** Since 0.1.8 (B6, V47): `GET <base>/consent` where the app that asks cannot connect here but has a safe way back:
 * the page sends the browser there at once, and the refusal stands in the card where "Verbinden" was clicked. */
export type ConsentBack = { back: string; refused: string }

/** `GET` and `PUT <base>/admin`. */
export type ConnectionsAdmin = {
  connections: boolean
  partners: string[]
  addresses: Record<string, string>
  /** Since 0.1.4 (V-12): connections into the own network (the app's setting `connections_local_network`). */
  local: boolean
}

/** The values of the consent page's address that go back to the server. */
export const CONSENT_PARAMS = ['client_id', 'redirect_uri', 'state', 'code_challenge', 'code_challenge_method'] as const

/** The app's way to call its server (its own client with its headers), as for the cards of schluessel and mcp. A
 * refusal throws; the parts read its code with `refusalCode`. */
export type VerbindenRequest = <T>(path: string, init?: { method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'; body?: unknown }) => Promise<T>

/** Kind and symbol of every button (at most one primary per box; what ends something is `danger`). Since 0.1.4 (MCP 20)
 * the consent page has "Ablehnen" (secondary, X) on the left and "Verbinden erlauben" (primary, Check) on the right. */
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
  /** Since 0.1.8 (B2, B3): the operator's way to Server › Allgemein › Andere nex-Apps, here or in the partner app. */
  setUp: { kind: 'secondary', icon: 'SlidersHorizontal' },
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

/** Since 0.1.8 (B6): the partner a refusal belongs to (`partner` in the module's `detail`), if it names one. */
export function refusalPartner(error: unknown): string | undefined {
  const found = error as { detail?: unknown; body?: unknown } | null
  const inner = (found?.detail ?? (found?.body as { detail?: unknown } | undefined)?.detail ?? found) as { partner?: unknown } | null
  return typeof inner?.partner === 'string' ? inner.partner : undefined
}

/** The words of a refusal of the module (by its code). Since 0.1.8 `{partner}` is filled too: the partner given, else
 * the one the refusal names, else "die andere App". */
export function refusalText(texts: VerbindenTexts, error: unknown, app: string, partner?: string): string {
  return codeText(texts, refusalCode(error), app, partner ?? refusalPartner(error))
}

/** Since 0.1.8: the words of a code of the module, with `{app}` and `{partner}`. */
export function codeText(texts: VerbindenTexts, code: string | undefined, app: string, partner?: string): string {
  const found = code ? (texts.errors as Record<string, string>)[code] : undefined
  return fillVerbinden(found ?? texts.failed, { app, partner: partner ?? texts.card.otherApp })
}

/** Since 0.1.8 (B2, B3): where the operator changes what a refusal names: this app's Server › Allgemein (`here`), the
 * partner app's (`there`), or nowhere. */
export function setUpPlace(code: string | null | undefined): 'here' | 'there' | null {
  if (code === 'local_off' || code === 'partner_not_set_up') return 'here'
  if (code === 'partner_local_off' || code === 'partner_cannot_reach') return 'there'
  return null
}

/** Since 0.1.8 (B6, V47): a refusal on the way to the partner and back, kept for the card while the browser goes from
 * the return page to the cards (in `sessionStorage` of this app; read once). */
export type CarriedProblem = { partner: string | null; code: string }
const CARRIED = 'nexverbinden.problem'

export function carryProblem(problem: CarriedProblem): boolean {
  try {
    window.sessionStorage.setItem(CARRIED, JSON.stringify(problem))
    return true
  } catch {
    return false
  }
}

export function takeProblem(): CarriedProblem | null {
  try {
    const raw = window.sessionStorage.getItem(CARRIED)
    if (!raw) return null
    window.sessionStorage.removeItem(CARRIED)
    const found = JSON.parse(raw) as { partner?: unknown; code?: unknown } | null
    if (!found || typeof found.code !== 'string') return null
    return { partner: typeof found.partner === 'string' ? found.partner : null, code: found.code }
  } catch {
    return null
  }
}

/** Since 0.1.8 (B1): the picture of an account without a photo, one letter and a hue from the name; the same rule as
 * `avatarPlaceholder` of the module konten (and the iPhone apps), kept here so the module needs only the kit. */
export function placeholderOf(name: string): { letter: string; hue: number } {
  const text = name.trim()
  const first = Array.from(text)[0] ?? ''
  const letter = first ? (Array.from(first.toUpperCase())[0] ?? '?') : '?'
  let hash = 0x811c9dc5
  for (const byte of new TextEncoder().encode(text.toLowerCase())) {
    hash ^= byte
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return { letter, hue: hash % 360 }
}

/** Since 0.1.8 (B1): "Kim Example (kim)", or the user name alone where there is no other shown name. */
export function accountLine(card: AccountCard): string {
  return card.name && card.name !== card.username ? `${card.name} (${card.username})` : card.username
}

/** How a moment is written; the app may give its own (nextime: the account's zone). */
export type WhenFormat = (iso: string, language: string) => string

/** Since 0.1.5 (E65): the one form of every app, "heute, 14:05" / "24.02.2027, 14:05" (`formatMoment`, `ui` 1.1.2). */
export function defaultWhen(iso: string, language: string): string {
  return formatMoment(iso, language)
}

/** Since 0.1.5 (E65): a day, "24.02.2027" (`formatDay`). */
export function defaultDay(iso: string, language: string): string {
  return formatDay(iso, language)
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

/** V-11, V37 (0.1.4): what the partner does in this app's areas, from its purposes, for the question "Wo darf {partner}
 * {actions}?". Each purpose of the catalog has its words under `areaActions` as a thing and what is done with it
 * (`object`, `verbs`); purposes with the same thing say it once with all their verbs ("Kontakte lesen, anlegen und
 * ändern", "Termine lesen, anlegen und ändern und Einladungen beantworten"), in the language's order
 * (`card.actionOrder`). Purposes the module does not know say together "lesen", or "lesen und ändern" when one of them
 * writes. */
export function areaActions(texts: VerbindenTexts, app: string, purposes: string[], levels: Record<string, string>): string {
  type Words = { object: string; verbs: string[] }
  const own = (texts.areaActions as Record<string, Record<string, Words> | undefined>)[app] ?? {}
  const list = (items: string[]) => (items.length <= 1 ? (items[0] ?? '') : `${items.slice(0, -1).join(', ')}${texts.card.and}${items.at(-1)}`)
  const things: { object: string; verbs: string[] }[] = []
  for (const purpose of purposes) {
    const words = own[purpose]
    if (!words) continue
    const thing = things.find((found) => found.object === words.object) ?? things[things.push({ object: words.object, verbs: [] }) - 1]!
    for (const verb of words.verbs) if (!thing.verbs.includes(verb)) thing.verbs.push(verb)
  }
  const said = things.map((thing) => fillVerbinden(texts.card.actionOrder, { object: thing.object, verbs: list(thing.verbs) }))
  const unknown = purposes.filter((purpose) => !own[purpose])
  if (unknown.length > 0) said.push(unknown.some((purpose) => levels[purpose] === 'write') ? texts.card.actionWrite : texts.card.actionRead)
  return list(said)
}

/** Whether the page is dark: the luminance of the kit's surface (`--nexui-surface`, which every app sets for light and
 * dark), else the system. Apps mark their theme differently (`data-theme="light"` or `"dark"`, a class); the surface
 * is the same everywhere. */
export function pageIsDark(): boolean {
  if (typeof window === 'undefined' || typeof document === 'undefined') return false
  const value = getComputedStyle(document.documentElement).getPropertyValue('--nexui-surface').trim()
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value)
  const rgb = /^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/i.exec(value)
  let parts: number[] | null = null
  if (hex) {
    const digits = hex[1] ?? ''
    const full = digits.length === 3 ? [...digits].map((one) => one + one).join('') : digits
    parts = [0, 2, 4].map((at) => parseInt(full.slice(at, at + 2), 16))
  } else if (rgb) {
    parts = [rgb[1], rgb[2], rgb[3]].map((one) => Number(one))
  }
  if (parts) {
    const [red = 0, green = 0, blue = 0] = parts
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue < 128
  }
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches
}

function subscribeTheme(changed: () => void): () => void {
  if (typeof window === 'undefined' || typeof MutationObserver === 'undefined') return () => undefined
  const watcher = new MutationObserver(changed)
  watcher.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme', 'style'] })
  const system = typeof window.matchMedia === 'function' ? window.matchMedia('(prefers-color-scheme: dark)') : null
  system?.addEventListener?.('change', changed)
  return () => {
    watcher.disconnect()
    system?.removeEventListener?.('change', changed)
  }
}

/** The page's light or dark, kept up to date when the account switches it. */
export function usePageDark(): boolean {
  return useSyncExternalStore(subscribeTheme, pageIsDark, () => false)
}

/** The mark of a nex app for the page's light or dark (decision V21: in the module, the app gives nothing). */
export function markOf(app: string, dark: boolean): string | undefined {
  const found = APP_MARKS[app]
  return found ? (dark ? found.dark : found.light) : undefined
}
