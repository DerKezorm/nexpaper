/**
 * Languages, as in nexlore. English and German ship with the app; the operator can add more as JSON files, which the
 * server offers under `/api/v1/locales`.
 *
 * English is always loaded and is the fallback: an added language may be incomplete, and whatever it leaves out
 * appears in English instead of as a raw key. An added file for `en` or `de` is laid over the shipped texts, so a
 * wording can be changed without a release.
 *
 * Texts are rendered as text by React. No translation is ever put into the page as HTML, because an added file
 * comes from outside the code.
 */

import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import oidcDe from '../vendor/nexoidc/oidc.de.json'
import oidcEn from '../vendor/nexoidc/oidc.en.json'
import { oidcVariables, oidcWording } from '../vendor/nexoidc/oidc'
import ownDe from './de.json'
import ownEn from './en.json'

type Texts = Record<string, unknown>

/** The name of the app in the texts of the shared sign-in module (`{{app}}`, and `{{slug}}` for its authentik
 * application). */
export const APP_NAME = 'nexpaper'
/**
 * The texts of sign-in through providers (`oidc.…`) come with the shared module `vendor/nexoidc`, the same words in
 * every nex app (Bauplan 04); nexpaper has invitations and more than one account.
 */
const en: Texts = { ...ownEn, ...oidcWording(oidcEn, { singleAccount: false, invitations: true }) }
const de: Texts = { ...ownDe, ...oidcWording(oidcDe, { singleAccount: false, invitations: true }) }

export const SHIPPED: Record<string, { name: string; texts: Texts }> = {
  en: { name: 'English', texts: en },
  de: { name: 'Deutsch', texts: de },
}

export type LanguageOption = { code: string; name: string; added: boolean }

const FALLBACK = 'en'
const STORAGE_KEY = 'nexpaper.language'
const CODE = /^[a-z]{2,3}(?:-(?:[A-Z]{2}|[A-Z][a-z]{3}))?$/

type AddedEntry = { code: string; name: string; keys: number }

let addedList: Promise<AddedEntry[]> | null = null

/** The languages the operator added. An empty list when the server is not reachable: the app still works. */
export function addedLanguages(): Promise<AddedEntry[]> {
  addedList ??= fetch('/api/v1/locales', { headers: { Accept: 'application/json' } })
    .then((response) => (response.ok ? response.json() : []))
    .then((list: unknown) =>
      Array.isArray(list) ? list.filter((entry): entry is AddedEntry => !!entry && typeof entry.code === 'string' && CODE.test(entry.code)) : [],
    )
    .catch(() => [])
  return addedList
}

/** After the operator added or removed one: ask the server again. */
export function forgetAddedLanguages(): void {
  addedList = null
}

async function fetchAdded(code: string): Promise<Texts | null> {
  if (!CODE.test(code)) return null
  try {
    const response = await fetch(`/api/v1/locales/${encodeURIComponent(code)}`, { headers: { Accept: 'application/json' } })
    if (!response.ok) return null
    const texts: unknown = await response.json()
    return texts && typeof texts === 'object' && !Array.isArray(texts) ? (texts as Texts) : null
  } catch {
    return null
  }
}

/** Shipped texts first, the operator's file on top. False when there is nothing for this code at all. */
async function loadTexts(code: string): Promise<boolean> {
  let found = code in SHIPPED
  const added = await addedLanguages()
  if (added.some((entry) => entry.code === code)) {
    const texts = await fetchAdded(code)
    if (texts) {
      i18n.addResourceBundle(code, 'translation', texts, true, true)
      found = true
    }
  }
  return found
}

/**
 * Languages in the order of their names, the same everywhere in the family: Deutsch, English, and every added one
 * in its place among them, never simply at the end.
 */
export function byName(a: { name: string }, b: { name: string }): number {
  return a.name.localeCompare(b.name)
}

export async function languageOptions(): Promise<LanguageOption[]> {
  const options: LanguageOption[] = Object.entries(SHIPPED).map(([code, entry]) => ({ code, name: entry.name, added: false }))
  for (const entry of await addedLanguages()) {
    if (!(entry.code in SHIPPED)) options.push({ code: entry.code, name: entry.name || entry.code, added: true })
  }
  return options.sort(byName)
}

function storedLanguage(): string | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored && CODE.test(stored) ? stored : null
  } catch {
    return null
  }
}

/** The first browser language nexpaper ships (only the language part counts: `de-AT` is `de`). */
function browserLanguage(): string {
  for (const wanted of navigator.languages ?? [navigator.language]) {
    const primary = wanted.toLowerCase().split(/[-_]/)[0]
    if (primary in SHIPPED) return primary
  }
  return FALLBACK
}

// The shipped languages at once, so the first picture is never raw keys; an added one follows from the server.
const first = storedLanguage() ?? browserLanguage()
i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, de: { translation: de } },
  lng: first in SHIPPED ? first : FALLBACK,
  fallbackLng: FALLBACK,
  interpolation: { escapeValue: false, defaultVariables: oidcVariables(APP_NAME) },
  returnNull: false,
})
document.documentElement.lang = i18n.language
if (!(first in SHIPPED)) void changeLanguage(first, false)
else void loadTexts(first).then(() => i18n.changeLanguage(first))

/** Switches the page to a language; false when nexpaper has none by that code. */
export async function changeLanguage(code: string, remember = true): Promise<boolean> {
  if (!(await loadTexts(code))) return false
  if (remember) {
    try {
      localStorage.setItem(STORAGE_KEY, code)
    } catch {
      // Then the choice only holds until the next reload.
    }
  }
  document.documentElement.lang = code
  await i18n.changeLanguage(code)
  return true
}

/** The English texts as a file to translate, with the `_meta` entry the server reads the name from. */
export function templateFile(): Blob {
  const template = { _meta: { name: 'Name of the language in itself, for example Español' }, ...en }
  return new Blob([JSON.stringify(template, null, 2) + '\n'], { type: 'application/json' })
}

export default i18n
