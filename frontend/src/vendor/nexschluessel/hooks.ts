// The module's words in the language of the ui kit. Copied unchanged into frontend/src/vendor/nexschluessel/ by
// bauplaene/schluessel/tools/sync.py; changed only there.
import { NEXUI_TEXTS, languageOf, useNexuiTexts } from '../nexui'
import { KEY_TEXTS, type KeyTexts } from './schluessel'

/** The module's words in the kit's language (or the one given). */
export function useKeyTexts(language?: string): { texts: KeyTexts; code: 'de' | 'en' | 'fr' } {
  const kit = useNexuiTexts()
  if (language) {
    const code = languageOf(language)
    return { texts: KEY_TEXTS[code], code }
  }
  const code = (Object.keys(NEXUI_TEXTS) as (keyof typeof NEXUI_TEXTS)[]).find((key) => NEXUI_TEXTS[key] === kit) ?? 'en'
  return { texts: KEY_TEXTS[code], code }
}
