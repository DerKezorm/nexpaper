// nexsprachen for the app's i18n: the operator's own languages fetched once, their texts on demand, the choices for
// the language menus of the profile and the sign-in page. What a file leaves out falls back to the app's English: an
// app with i18next's `fallbackLng: 'en'` lays the texts over with `addResourceBundle(code, 'translation', texts, true,
// true)`; an app that loads one language alone takes `merged()` (the file over its built-in texts, or over English).
//
// Texts are rendered as text by React. No translation is ever put into the page as HTML, because a file comes from
// outside the code.
//
// Copied unchanged into frontend/src/vendor/nexsprachen/ by bauplaene/sprachen/tools/sync.py; changed only there.

import { useEffect, useState } from 'react'

import { BASE, CODE, makeSprachenApi, mergeTexts, plainFetch, type Fetcher, type LanguageEntry, type Texts } from './sprachen'

/** A choice of a language menu: its code, its name in itself, whether the operator added it. */
export type LanguageOption = { code: string; name: string; added: boolean }

/** The app's built-in languages: code and name in itself ("Deutsch", "English"). */
export type BuiltIn = readonly { code: string; name: string }[]

export type OwnLanguages = {
  /** Every entry of the server's list; an empty list when the server does not answer (the app still works). */
  list(): Promise<LanguageEntry[]>
  /** After the operator added or removed one: ask the server again. */
  forget(): void
  /** The texts of the operator's file for `code`, or null (no file, not reachable, not texts). */
  texts(code: string): Promise<Texts | null>
  /** Whether the app speaks `code`: built in or added by the operator. */
  knows(code: string, builtIn: BuiltIn): Promise<boolean>
  /** The choices of a language menu: the built-in ones and every added one, ordered by name (Deutsch, English,
   * Nederlands …; an added one in its place among them, never simply at the end). */
  options(builtIn: BuiltIn): Promise<LanguageOption[]>
  /** The texts i18next gets for `code` when the app loads one language alone: a built-in one (`own`) with the
   * operator's file over it, an added one over `fallback` (English). Null when the app has no such language. */
  merged(code: string, own: Texts | null, fallback: Texts): Promise<Texts | null>
}

/** Languages in the order of their names, the same everywhere in the family. */
export function byName(a: { name: string }, b: { name: string }): number {
  return a.name.localeCompare(b.name)
}

/** The operator's languages, asked for once per page load (`base` where the app mounted the routes, `fetcher` its
 * way to the server; it runs before anybody signs in, so it needs nothing of a session). */
export function ownLanguages({ base = BASE, fetcher = plainFetch }: { base?: string; fetcher?: Fetcher } = {}): OwnLanguages {
  const api = makeSprachenApi(fetcher, base)
  let asked: Promise<LanguageEntry[]> | null = null
  const loaded = new Map<string, Promise<Texts | null>>()
  const list = () => (asked ??= api.list().catch(() => []))
  const texts = async (code: string): Promise<Texts | null> => {
    if (!CODE.test(code)) return null
    if (!(await list()).some((entry) => entry.code === code && entry.own)) return null
    let found = loaded.get(code)
    if (!found) {
      found = api.texts(code).catch(() => null)
      loaded.set(code, found)
    }
    return found
  }
  return {
    list,
    forget: () => {
      asked = null
      loaded.clear()
    },
    texts,
    knows: async (code, builtIn) => builtIn.some((entry) => entry.code === code) || (await list()).some((entry) => entry.code === code && entry.own),
    options: async (builtIn) => {
      const options: LanguageOption[] = builtIn.map((entry) => ({ code: entry.code, name: entry.name, added: false }))
      for (const entry of await list()) {
        if (entry.own && !options.some((option) => option.code === entry.code)) options.push({ code: entry.code, name: entry.name || entry.code, added: true })
      }
      return options.sort(byName)
    },
    merged: async (code, own, fallback) => {
      const file = await texts(code)
      if (own) return file ? mergeTexts(own, file) : own
      return file ? mergeTexts(fallback, file) : null
    },
  }
}

/** The choices of a language menu (profile, sign-in page): the built-in ones at once, the added ones when the server
 * answered. */
export function useLanguageOptions(languages: OwnLanguages, builtIn: BuiltIn): LanguageOption[] {
  const [options, setOptions] = useState<LanguageOption[]>(() => builtIn.map((entry) => ({ code: entry.code, name: entry.name, added: false })).sort(byName))
  useEffect(() => {
    let live = true
    void languages.options(builtIn).then((found) => {
      if (live) setOptions(found)
    })
    return () => {
      live = false
    }
  }, [languages, builtIn])
  return options
}
