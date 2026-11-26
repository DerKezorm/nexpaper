// nexki in the browser: what the module's routes answer, the tiles of common services, the module's words and their
// helpers. The parts themselves are ServiceFields.tsx, AiProviderArea.tsx and AiAccountArea.tsx (built from the ui
// kit). Copied unchanged into frontend/src/vendor/nexki/ by bauplaene/ki/tools/sync.py; changed only there.

import { NEXUI_TEXTS, languageOf, useNexuiTexts } from '../nexui'

import de from './ki.de.json'
import en from './ki.en.json'
import fr from './ki.fr.json'

/** The two interfaces a service may speak. "Local" is no interface but a place (the own network). */
export type AiApi = 'openai' | 'messages'
/** How the AI is set up on a server: one service of the operator for all, or each account its own. */
export type AiMode = 'shared' | 'own'

/** `GET /api/server/ai`: the operator's settings, without the key. */
export type AiOperatorView = {
  enabled: boolean
  mode: AiMode
  modes: AiMode[]
  api: AiApi | ''
  url: string
  model: string
  key_set: boolean
  complete: boolean
  hosts: string[]
  per_minute: number
  per_day: number
  server_day: number
  used_today: number
  messages_url: string
}

/** `GET /api/me/ai`: whether the AI works for this person, why not, and where the text goes. */
export type AiState = {
  available: boolean
  /** The first switch that says no (`ai_off`, `ai_not_allowed`, `ai_switched_off`, `ai_incomplete` …). */
  reason: string | null
  enabled: boolean
  allowed: boolean
  mine: boolean
  mode: AiMode
  api: AiApi | ''
  model: string
  local: boolean
  /** The host on the internet the text goes to; "" in the own network (never named to a member). */
  to: string
  own?: { api: AiApi; url: string; model: string; key_set: boolean } | null
}

/** One line of "what went out". `sent` only for a task a person started, `null` for an automatic one. */
export type AiEvent = {
  id: string | number | null
  at: string
  task: string
  to: string
  model: string
  manual: boolean
  chars: number
  outcome: string
  sent: { system: string; user: string } | null
}

export type AiModel = { id: string; name: string }

/** The app's client: `request(path, { method, body })`, refusals thrown with FastAPI's `detail`. */
export type AiRequest = <T>(path: string, init?: { method?: 'GET' | 'POST' | 'PUT' | 'DELETE'; body?: unknown }) => Promise<T>

/** Where the module's routes are mounted. */
export const KI_SERVER_BASE = '/api/server/ai'
export const KI_ME_BASE = '/api/me/ai'

/** Tiles that fill in an address. The only product names of the module's frontend stand here (the apps' guard against
 * attributions lists this file for them); no prices or conditions, those change. */
export type AiTile = { id: string; name: string; api: AiApi; url: string; keys: string | null }
export const AI_TILES: readonly AiTile[] = [
  { id: 'messages', name: 'Anthropic', api: 'messages', url: 'https://api.anthropic.com/v1/', keys: 'https://console.anthropic.com/settings/keys' },
  { id: 'openai', name: 'OpenAI', api: 'openai', url: 'https://api.openai.com/v1/', keys: 'https://platform.openai.com/api-keys' },
  { id: 'gemini', name: 'Gemini', api: 'openai', url: 'https://generativelanguage.googleapis.com/v1beta/openai/', keys: 'https://aistudio.google.com/apikey' },
  { id: 'openrouter', name: 'OpenRouter', api: 'openai', url: 'https://openrouter.ai/api/v1/', keys: 'https://openrouter.ai/settings/keys' },
  { id: 'ollama', name: 'Ollama', api: 'openai', url: 'http://ollama:11434/v1/', keys: null },
]

/** The tile an address belongs to, if any. */
export function tileOf(url: string): AiTile | undefined {
  const bare = url.trim().replace(/\/?$/, '/')
  return AI_TILES.find((tile) => tile.url === bare)
}

export type KiTexts = typeof de
export const KI_TEXTS: Record<'de' | 'en' | 'fr', KiTexts> = { de, en, fr }

/** `{name}` in a text, from `values`; an unknown name stays as it is. */
export function fillKi(text: string, values: Record<string, string | number>): string {
  return text.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? String(values[key] ?? '') : whole))
}

/** The code of a refused request: the module's `{code}` in FastAPI's `detail`, or on the error itself. */
export function refusalOf(error: unknown): { code?: string; values: Record<string, string | number> } {
  const found = error as { code?: unknown; detail?: unknown; body?: unknown } | null
  const inner = (found?.detail ?? (found?.body as { detail?: unknown } | undefined)?.detail ?? found) as Record<string, unknown> | string | null
  if (typeof inner === 'string') return { code: inner, values: {} }
  const values: Record<string, string | number> = {}
  for (const [key, value] of Object.entries(inner ?? {})) if (typeof value === 'string' || typeof value === 'number') values[key] = value
  return { code: typeof inner?.code === 'string' ? inner.code : undefined, values }
}

/** The words of a refusal of the module, with the service's own words where it sent some. */
export function refusalText(texts: KiTexts, error: unknown, app = ''): string {
  const { code, values } = refusalOf(error)
  const known = code ? (texts.errors as Record<string, string>)[code] : undefined
  // A part in brackets whose value did not come (a line of "what went out" keeps only the code) is left out.
  const filled = { app, ...values }
  const trimmed = known?.replace(/\s*\([^()]*\{(\w+)\}[^()]*\)/g, (whole, key: string) => (key in filled ? whole : ''))
  const base = trimmed ? fillKi(trimmed, filled) : texts.failed
  return values.said ? `${base} ${fillKi(texts.said, { said: values.said })}` : base
}

/** The module's words in the kit's language (or the one given). */
export function useKiTexts(language?: string): { texts: KiTexts; code: 'de' | 'en' | 'fr' } {
  const kit = useNexuiTexts()
  if (language) {
    const code = languageOf(language)
    return { texts: KI_TEXTS[code], code }
  }
  const code = (Object.keys(NEXUI_TEXTS) as (keyof typeof NEXUI_TEXTS)[]).find((key) => NEXUI_TEXTS[key] === kit) ?? 'en'
  return { texts: KI_TEXTS[code], code }
}

/** How a moment is written; the app may give its own (nextime: the account's zone). */
export type WhenFormat = (iso: string, language: string) => string

export function defaultWhen(iso: string, language: string): string {
  const moment = new Date(iso)
  return Number.isNaN(moment.getTime()) ? iso : moment.toLocaleString(language, { dateStyle: 'medium', timeStyle: 'short' })
}
