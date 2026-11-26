// nexsprachen in the browser: what the routes answer, the calls to them, the module's words, merging texts and the
// template as a file. The card is LanguagesCard.tsx (built from the kit nexui), the app's i18n uses languages.ts.
//
// Copied unchanged into frontend/src/vendor/nexsprachen/ by bauplaene/sprachen/tools/sync.py; changed only there.

import { NEXUI_TEXTS, languageOf, useNexuiTexts } from '../nexui'

import de from './sprachen.de.json'
import en from './sprachen.en.json'
import fr from './sprachen.fr.json'

/** One entry of `GET <base>`: a built-in language, the operator's file, or both (a file over a built-in language). */
export type LanguageEntry = { code: string; name: string; keys: number; built_in: boolean; own: boolean }

/** Texts as i18next takes them: texts and groups of texts. */
export type Texts = { [key: string]: string | Texts }

/** `de`, `es`, `fil`, `pt-BR`, `zh-Hant`: as the server checks it (`store.CODE_PATTERN`). */
export const CODE = /^[a-z]{2,3}(?:-(?:[A-Z]{2}|[A-Z][a-z]{3}))?$/
export const BASE = '/api/locales'
export const MAX_KB = 512

/** The app's way to the server: `fetch` with what the app adds (cookies, a base path, its own headers). */
export type Fetcher = (path: string, init: RequestInit) => Promise<Response>

export const plainFetch: Fetcher = (path, init) => fetch(path, { credentials: 'same-origin', ...init })

/** A refusal of the server: its code (`errors.<code>`), its values (`reason`, `max_kb`), its status. */
export class SprachenError extends Error {
  constructor(
    readonly code: string,
    readonly values: Record<string, unknown>,
    readonly status: number,
  ) {
    super(code)
  }
}

/** The code and values of a refusal, in nexnotes' form (`{detail: {code, message, …}}`) or nexmail's (`{detail:
 * "<code>", werte: {…}}`). */
export async function refusalOf(response: Response): Promise<SprachenError> {
  let code = 'unknown'
  let values: Record<string, unknown> = {}
  try {
    const body = (await response.json()) as { detail?: unknown; werte?: unknown }
    if (typeof body.detail === 'string') {
      code = body.detail
      if (body.werte && typeof body.werte === 'object') values = body.werte as Record<string, unknown>
    } else if (body.detail && typeof body.detail === 'object') {
      const detail = body.detail as Record<string, unknown>
      if (typeof detail.code === 'string') code = detail.code
      values = Object.fromEntries(Object.entries(detail).filter(([key]) => key !== 'code' && key !== 'message'))
    }
  } catch {
    // Not JSON: the status says enough.
  }
  return new SprachenError(code, values, response.status)
}

/** Whether `value` is a tree of texts the server would take (only texts and groups of texts). */
export function isTexts(value: unknown): value is Texts {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  return Object.values(value).every((child) => typeof child === 'string' || isTexts(child))
}

/** Keys a merge must never take over: they would reach the prototype of every object of the page. */
const UNSAFE = new Set(['__proto__', 'constructor', 'prototype'])

/** Two trees of texts in one: `over` wins, what it leaves out comes from `under`. A file for a built-in language
 * replaces only the texts it holds. Neither tree changes. */
export function mergeTexts(under: Texts, over: Texts): Texts {
  const merged = new Map<string, string | Texts>()
  for (const [key, value] of Object.entries(under)) if (!UNSAFE.has(key)) merged.set(key, value)
  for (const [key, value] of Object.entries(over)) {
    if (UNSAFE.has(key)) continue
    const below = merged.get(key)
    merged.set(key, typeof value === 'object' && typeof below === 'object' ? mergeTexts(below, value) : value)
  }
  return Object.fromEntries(merged) as Texts
}

/** The app's texts as a file to translate, with the `_meta` entry the server reads the name from (nexnotes'
 * template). */
export function templateFile(texts: Texts): Blob {
  const template = { _meta: { name: 'Name of the language in itself, for example Nederlands' }, ...texts }
  return new Blob([JSON.stringify(template, null, 2) + '\n'], { type: 'application/json' })
}

/** Hands a file to the browser. */
export function saveFile(name: string, data: Blob): void {
  const url = URL.createObjectURL(data)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export type SprachenApi = {
  list(): Promise<LanguageEntry[]>
  texts(code: string): Promise<Texts | null>
  upload(code: string, file: Blob): Promise<{ code: string; name: string; keys: number }>
  remove(code: string): Promise<void>
  template(): Promise<Blob>
}

/** The entries of a list that are what they claim (a valid code, a name, a count). */
export function validEntries(list: unknown): LanguageEntry[] {
  if (!Array.isArray(list)) return []
  return list.filter(
    (entry): entry is LanguageEntry =>
      !!entry && typeof entry === 'object' && typeof entry.code === 'string' && CODE.test(entry.code) && typeof entry.name === 'string',
  ).map((entry) => ({ code: entry.code, name: entry.name || entry.code, keys: Number(entry.keys) || 0, built_in: entry.built_in === true, own: entry.own !== false }))
}

/** The calls to the module's routes under `base` (where the app mounted `api.router`). */
export function makeSprachenApi(fetcher: Fetcher = plainFetch, base: string = BASE): SprachenApi {
  const call = async (path: string, init: RequestInit): Promise<Response> => {
    const response = await fetcher(base + path, init)
    if (!response.ok) throw await refusalOf(response)
    return response
  }
  const part = (code: string) => `/${encodeURIComponent(code)}`
  return {
    list: async () => validEntries(await (await call('', { method: 'GET', headers: { Accept: 'application/json' } })).json()),
    texts: async (code) => {
      if (!CODE.test(code)) return null
      const found: unknown = await (await call(part(code), { method: 'GET', headers: { Accept: 'application/json' } })).json()
      return isTexts(found) ? found : null
    },
    upload: async (code, file) =>
      (await call(part(code), { method: 'PUT', body: file, headers: { 'Content-Type': 'application/json' } })).json() as Promise<{
        code: string
        name: string
        keys: number
      }>,
    remove: async (code) => {
      await call(part(code), { method: 'DELETE' })
    },
    template: async () => (await call('/template', { method: 'GET' })).blob(),
  }
}

// --- Words ------------------------------------------------------------------------------------------------------------

export type SprachenTexts = typeof de
export const SPRACHEN_TEXTS: Record<'de' | 'en' | 'fr', SprachenTexts> = { de, en, fr }

/** The module's words in the kit's language (`NexuiLanguage`, else `<html lang>`) or in the one given. */
export function useSprachenTexts(language?: string): SprachenTexts {
  const kit = useNexuiTexts()
  if (language) return SPRACHEN_TEXTS[languageOf(language)]
  return kit === NEXUI_TEXTS.de ? SPRACHEN_TEXTS.de : kit === NEXUI_TEXTS.fr ? SPRACHEN_TEXTS.fr : SPRACHEN_TEXTS.en
}

/** Fills `{builtIn}`, `{count}`, `{reason}`, `{max_kb}`. */
export function fill(text: string, values: Record<string, string | number>): string {
  return text.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? String(values[key]) : whole))
}

/** The words of a refusal: the code's sentence, for an unusable file with its reason; anything else `unknown`. */
export function errorText(texts: SprachenTexts, error: unknown): string {
  if (!(error instanceof SprachenError)) return texts.errors.unknown
  const reasons = texts.reasons as Record<string, string>
  if (error.code === 'locale_unusable') {
    const reason = typeof error.values.reason === 'string' ? reasons[error.values.reason] : undefined
    return reason ? fill(texts.errors.locale_unusable, { reason }) : texts.errors.locale_unusable_plain
  }
  if (error.code === 'too_large') return fill(texts.errors.too_large, { max_kb: Number(error.values.max_kb) || MAX_KB })
  const known = (texts.errors as Record<string, string>)[error.code]
  return known ?? texts.errors.unknown
}

/** The built-in languages named in the page's language, joined as a person writes a list: "Deutsch und Englisch",
 * "German and English", "allemand et anglais". */
export function builtInNames(entries: readonly LanguageEntry[], language: string): string {
  const names = entries
    .filter((entry) => entry.built_in)
    .map((entry) => {
      try {
        return new Intl.DisplayNames([language], { type: 'language' }).of(entry.code) ?? entry.name
      } catch {
        return entry.name
      }
    })
  try {
    return new Intl.ListFormat(language, { style: 'long', type: 'conjunction' }).format(names)
  } catch {
    return names.join(', ')
  }
}

/** The card's line: which languages are built in, and what a file adds. */
export function hintOf(texts: SprachenTexts, entries: readonly LanguageEntry[], language: string): string {
  const count = entries.filter((entry) => entry.built_in).length
  const names = builtInNames(entries, language)
  const shown = language.startsWith('fr') ? names : names.charAt(0).toUpperCase() + names.slice(1)
  return fill(count === 1 ? texts.hintOne : texts.hint, { builtIn: shown })
}

/** "ein Text", "12 Texte". */
export function textsCount(texts: SprachenTexts, count: number): string {
  return count === 1 ? texts.textsOne : fill(texts.textsOther, { count })
}
