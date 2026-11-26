// nexsicherung in the browser: helpers of the page that are no component (a file of components exports only
// components, the rule react-refresh/only-export-components of the apps). Copied unchanged into
// frontend/src/vendor/nexsicherung/ by bauplaene/sicherung/tools/sync.py; changed only there.

import type { Language } from './sicherung'

/** Since E37: the app's words for its own blocking codes, per language (English stands in for a language it lacks). */
export type BlockedTexts = Readonly<Record<string, Partial<Record<Language, string>>>>

/** The app's sentence for a code, in the page's language, or null. */
export function blockedWords(blockedText: BlockedTexts | undefined, code: string | null | undefined, language: Language): string | null {
  const found = code ? blockedText?.[code] : undefined
  return found?.[language] ?? found?.en ?? null
}
