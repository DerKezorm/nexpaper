// nexschluessel in the browser: what the server answers, the columns, the buttons, the lifetimes and the words of the
// cards. The cards themselves are ApiKeysCard.tsx, ToolsCard.tsx, InterfacesCard.tsx and AllKeysCard.tsx (built from
// the ui kit). Copied unchanged into frontend/src/vendor/nexschluessel/ by bauplaene/schluessel/tools/sync.py; changed
// only there.

import type { ReactNode } from 'react'

import { formatDay, formatMoment } from '../nexui'

import de from './schluessel.de.json'
import en from './schluessel.en.json'
import fr from './schluessel.fr.json'

export type AreaRef = { id: number | string; name?: string | null }

/** One key as `GET <base>/keys` lists it: never its secret, never its hash. */
export type KeyEntry = {
  id: number | string
  kind: 'api' | 'mcp'
  name: string | null
  right: string
  options: Record<string, boolean>
  /** `null`: everything the account reaches, later too. In the operator's list a count instead. */
  areas: AreaRef[] | number | null
  prefix: string
  created_at: string | null
  last_used_at: string | null
  expires_at: string | null
  expired: boolean
  expiring: boolean
  blocked: boolean
  /** A form no longer made, still valid (`card`: only the nexdeck card). */
  legacy: string | null
  /** Issued to a program that connected itself with the account's consent. */
  program: boolean
}

/** What the account may make of one kind. */
export type KindChoice = {
  id: 'api' | 'mcp'
  prefix: string
  creatable: boolean
  editable: boolean
  rights: string[]
  default_right: string | null
  /** The extras offered on a new key. */
  options: string[]
  /** Since 1.1.0: extras no longer offered; a key that has one may switch it off. */
  retired_options?: string[]
  areas: AreaRef[] | null
  areas_required: boolean
  /** `null`: the app knows no end of a key. A `null` inside: never. */
  expiry_days: (number | null)[] | null
  default_days: number | null
  default_days_by_right: Record<string, number | null>
  max_keys: number
  count: number
  name_max: number
}

/** `GET <base>/keys`. */
export type KeyListing = {
  app: string
  api: boolean
  /** `null`: the app has no MCP. */
  mcp: boolean | null
  programs: boolean
  api_path: string
  mcp_path: string | null
  keys_wait: boolean
  /** Since 1.1.0: whether the operator lets the account use AI (MCP keys and programs rest without it). */
  ai_allowed?: boolean
  warn_days: number
  kinds: KindChoice[]
  keys: KeyEntry[]
  address: string
}

/** One row of `GET <base>/admin/keys`. */
/** A row of `GET <base>/admin/keys`: never the start of the key (no `prefix`, since E36); `extra` holds the values of
 * the app's own columns (`AppConfig.admin_extra`). */
export type AdminKey = Omit<KeyEntry, 'prefix'> & {
  account: { id: number | string; name: string; display_name: string; out: boolean }
  extra?: Record<string, unknown>
}

/** A column of the app in "API-Schlüssel aller Konten" (nexnotes: the folders a key reaches), before the button. */
export type AdminExtraColumn = { key: string; label: string; width?: string; cell?: (row: AdminKey) => ReactNode }

/** `GET <base>/interfaces`: the switches the app has. */
export type Interfaces = Partial<Record<'api' | 'mcp' | 'app' | 'pairing', boolean>>

/** `POST <base>/keys`. */
export type NewKeyBody = {
  kind: 'api' | 'mcp'
  name: string
  right?: string
  areas?: (number | string)[] | 'all'
  options?: Record<string, boolean>
  days?: number | null
  client_ref?: string
}

/** The app's way to call its server (its own client with its headers), as for the log card. A refusal throws; the
 * cards read its code with `refusalCode`. */
export type KeyRequest = <T>(
  path: string,
  init?: { method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'; query?: Record<string, string | number | undefined>; body?: unknown },
) => Promise<T>

/** Where the module's routes are mounted. */
export const KEYS_BASE = '/api/connections'

/** The order of the switches on the card "Interfaces". */
export const SWITCH_ORDER = ['api', 'mcp', 'app', 'pairing'] as const
export type SwitchName = (typeof SWITCH_ORDER)[number]

/** The columns of the account's list and of the operator's list, in this order. */
export const KEY_COLUMNS = ['name', 'right', 'expires', 'used', 'action'] as const
export type KeyColumn = (typeof KEY_COLUMNS)[number]
export const ADMIN_COLUMNS = ['account', 'name', 'right', 'used', 'action'] as const
export type AdminColumn = (typeof ADMIN_COLUMNS)[number]
export const COLUMN_WIDTHS: Partial<Record<KeyColumn | AdminColumn, string>> = { account: '9rem', expires: '9rem', used: '8rem', action: '13rem' }

/** Since 1.1.1 (M-7): room for the buttons of a row side by side, never one under the other on a wide place: about
 * 7.5rem for each of the module's `sm` buttons ("Bearbeiten", "Widerrufen"), 11rem for the app's own (`extra`,
 * "Rechte je Werkzeug"), half a rem between them and 1.5rem for the cell. */
export function actionWidth(buttons: number, extra = false): string {
  const count = buttons + (extra ? 1 : 0)
  return `${1.5 + buttons * 7.5 + (extra ? 11 : 0) + Math.max(0, count - 1) * 0.5}rem`
}

/** Kind and symbol of every button of the cards (the rules of the ui kit: what ends or removes is `danger`, at most one
 * primary per box). "Neuer MCP-Schlüssel" is secondary (plan E48), "Neuer API-Schlüssel" primary. */
export const BUTTONS = {
  newKey: { kind: 'primary', icon: 'Plus' },
  newMcpKey: { kind: 'secondary', icon: 'Plus' },
  create: { kind: 'primary', icon: 'Check' },
  save: { kind: 'primary', icon: 'Check' },
  done: { kind: 'primary', icon: 'Check' },
  edit: { kind: 'secondary', icon: 'Pencil' },
  revoke: { kind: 'danger', icon: 'Trash2' },
  block: { kind: 'danger', icon: 'Ban' },
  unblock: { kind: 'secondary', icon: 'CircleCheck' },
  docs: { kind: 'secondary', icon: 'BookOpen' },
} as const

/** The lifetime the form starts with for a right. */
export function defaultDays(kind: KindChoice, right: string): number | null {
  if (kind.expiry_days === null) return null
  return right in kind.default_days_by_right ? (kind.default_days_by_right[right] ?? null) : kind.default_days
}

/** The value of a lifetime in a select (a select holds text). */
export function daysValue(days: number | null): string {
  return days === null ? 'never' : String(days)
}

export function daysOf(value: string): number | null {
  return value === 'never' ? null : Number(value)
}

/** The keys a card shows: the API keys (and old forms of them), the MCP keys made by hand, the connected programs. */
export function apiKeys(listing: KeyListing): KeyEntry[] {
  return listing.keys.filter((key) => key.kind === 'api' && !key.program)
}

export function mcpKeys(listing: KeyListing): KeyEntry[] {
  return listing.keys.filter((key) => key.kind === 'mcp' && !key.program)
}

export function programs(listing: KeyListing): KeyEntry[] {
  return listing.keys.filter((key) => key.program)
}

/** The code of a refused request: the module's `{code}` in FastAPI's `detail`, or on the error itself. */
export function refusalCode(error: unknown): { code?: string; key_code?: string; max?: number } {
  const found = error as { code?: unknown; key_code?: unknown; max?: unknown; detail?: unknown; body?: unknown } | null
  const inner = (found?.detail ?? (found?.body as { detail?: unknown } | undefined)?.detail ?? found) as { code?: unknown; key_code?: unknown; max?: unknown } | null
  const code = typeof inner?.key_code === 'string' ? inner.key_code : typeof inner?.code === 'string' ? inner.code : undefined
  return { code, max: typeof inner?.max === 'number' ? inner.max : undefined }
}

/** A reference for one form, so that a double click makes one key (nextime's `client_ref`). */
export function newClientRef(): string {
  return `form-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

export type KeyTexts = typeof de
export const KEY_TEXTS: Record<'de' | 'en' | 'fr', KeyTexts> = { de, en, fr }

/** Fills `{things}`, `{thingsDative}` (since E34), `{name}`, `{count}` … */
export function fillKeys(text: string, values: Record<string, string | number>): string {
  return text.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? String(values[key] ?? '') : whole))
}

/** How a moment or a day is written; the app may give its own (nextime: the account's zone). */
export type WhenFormat = (iso: string, language: string) => string

/** Since 1.1.2 (E65): a moment as every app writes it, "heute, 14:05" (last use). */
export function defaultWhen(iso: string, language: string): string {
  return formatMoment(iso, language)
}

/** Since 1.1.2 (E65): a day as every app writes it, "24.02.2027" (expiry). */
export function defaultDay(iso: string, language: string): string {
  return formatDay(iso, language)
}

/** Words the app brings: its own rights (nexmail `count`, `headers`; nexlore `draft`), its extras (nexmail `tasks`,
 * `tags`) and the word for its areas (folders, spaces, calendars, mailboxes). */
export type AppWords = {
  rights?: Record<string, string>
  rightHints?: Record<string, string>
  options?: Record<string, string>
  optionHints?: Record<string, string>
  /** The app's word for its areas, in the plural ("Ordner", "Bereiche", "Kalender", "Postfächer"): above the choice and,
   * since 1.1.1, in it ("Alle Ordner, auch spätere", "Nur diese Ordner"; M-5, the same words as mcp and verbinden). */
  areas?: string
  /** Older own words for the two choices; since 1.1.1 not needed (the module says it with `areas`). */
  areasAll?: string
  areasSome?: string
}

export function rightLabel(texts: KeyTexts, words: AppWords | undefined, right: string): string {
  return words?.rights?.[right] ?? (texts.rights as Record<string, string>)[right] ?? right
}

export function optionLabel(texts: KeyTexts, words: AppWords | undefined, option: string): string {
  return words?.options?.[option] ?? (texts.options as Record<string, string>)[option] ?? option
}

export function optionHint(texts: KeyTexts, words: AppWords | undefined, option: string): string | undefined {
  return words?.optionHints?.[option] ?? (texts.options as Record<string, string>)[`${option}Hint`]
}

/** The words of a refusal of the module. */
export function refusalText(texts: KeyTexts, error: unknown): string {
  const { code, max } = refusalCode(error)
  const known = code ? (texts.errors as Record<string, string>)[code] : undefined
  return known ? fillKeys(known, { max: max ?? '' }) : texts.key.failed
}
