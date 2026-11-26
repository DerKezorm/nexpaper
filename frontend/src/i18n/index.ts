/**
 * Languages, as in nexlore. English, German and French ship with the app; the operator can add more as JSON files,
 * which the server offers under `/api/v1/locales` (the shared module sprachen 1.0.0, `vendor/nexsprachen`).
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

import { kontenVariables } from '../vendor/nexkonten/konten'
import kontenDe from '../vendor/nexkonten/konten.de.json'
import kontenEn from '../vendor/nexkonten/konten.en.json'
import kontenFr from '../vendor/nexkonten/konten.fr.json'
import { postVariables } from '../vendor/nexpost/post'
import postDe from '../vendor/nexpost/post.de.json'
import postEn from '../vendor/nexpost/post.en.json'
import postFr from '../vendor/nexpost/post.fr.json'
import oidcDe from '../vendor/nexoidc/oidc.de.json'
import oidcEn from '../vendor/nexoidc/oidc.en.json'
import { oidcVariables, oidcWording } from '../vendor/nexoidc/oidc'
import ownDe from './de.json'
import ownEn from './en.json'
import ownFr from './fr.json'
import oidcFr from './oidc.fr.json'
import { tabFetch } from '../api/client'
import { ownLanguages, type BuiltIn } from '../vendor/nexsprachen/languages'
import { CODE, type Texts as SprachenTexts } from '../vendor/nexsprachen/sprachen'

type Texts = Record<string, unknown>

/** The name of the app in the texts of the shared sign-in module (`{{app}}`, and `{{slug}}` for its authentik
 * application). */
export const APP_NAME = 'nexpaper'
/**
 * The texts of sign-in through providers (`oidc.…`) come with the shared module `vendor/nexoidc`, the same words in
 * every nex app; nexpaper has invitations and more than one account. So do those of accounts (`account.…`, the shared
 * module `vendor/nexkonten`) and of system mail (`mail.…`, `vendor/nexpost`), in German, English and French.
 */
const en: Texts = { ...ownEn, ...oidcWording(oidcEn, { singleAccount: false, invitations: true }), ...kontenEn, ...postEn }
const de: Texts = { ...ownDe, ...oidcWording(oidcDe, { singleAccount: false, invitations: true }), ...kontenDe, ...postDe }
/**
 * The shared module has no French yet, so nexpaper keeps the French words of the module next to its own, in the same
 * shape as `oidc.en.json`. When the module brings `oidc.fr.json` itself, this file goes to the module.
 */
const fr: Texts = { ...ownFr, ...oidcWording(oidcFr, { singleAccount: false, invitations: true }), ...kontenFr, ...postFr }

export const SHIPPED: Record<string, { name: string; texts: Texts }> = {
  en: { name: 'English', texts: en },
  de: { name: 'Deutsch', texts: de },
  fr: { name: 'Français', texts: fr },
}

export type { LanguageOption } from '../vendor/nexsprachen/languages'

/** The built-in languages for the menus, in the order of the server's `BUILT_IN` (`services/locales.py`). */
export const BUILT_IN: BuiltIn = [
  { code: 'de', name: SHIPPED.de.name },
  { code: 'en', name: SHIPPED.en.name },
  { code: 'fr', name: SHIPPED.fr.name },
]
/** The English texts as the template to translate (the card "Sprachen" makes the file on the page). */
export const TEMPLATE = en as SprachenTexts

const FALLBACK = 'en'
const STORAGE_KEY = 'nexpaper.language'

/** The languages the operator added, from the shared module sprachen under `/api/v1/locales`: the list once per page
 * load (an empty one when the server is not reachable: the app still works), a file's texts on demand. After a
 * change the card calls `own.forget`. */
export const own = ownLanguages({ base: '/api/v1/locales', fetcher: tabFetch })

/** Shipped texts first, the operator's file on top. False when there is nothing for this code at all. */
async function loadTexts(code: string): Promise<boolean> {
  const texts = await own.texts(code)
  if (texts) i18n.addResourceBundle(code, 'translation', texts, true, true)
  return code in SHIPPED || texts !== null
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
  resources: { en: { translation: en }, de: { translation: de }, fr: { translation: fr } },
  lng: first in SHIPPED ? first : FALLBACK,
  fallbackLng: FALLBACK,
  // A value a sentence is asked without (a title before the name is known) stays empty: the page never shows a raw
  // placeholder such as {{day}}.
  interpolation: {
    escapeValue: false,
    defaultVariables: { ...oidcVariables(APP_NAME), ...postVariables(APP_NAME), ...kontenVariables(APP_NAME) },
  },
  missingInterpolationHandler: () => '',
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

export default i18n
