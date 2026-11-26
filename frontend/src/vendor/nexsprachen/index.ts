/** nexsprachen in the browser (bauplaene/sprachen). Changed only in bauplaene, copied unchanged into each app. */
export { LanguagesCard } from './LanguagesCard'
export type { LanguagesCardProps } from './LanguagesCard'
export { byName, ownLanguages, useLanguageOptions } from './languages'
export type { BuiltIn, LanguageOption, OwnLanguages } from './languages'
export {
  BASE,
  CODE,
  MAX_KB,
  SPRACHEN_TEXTS,
  SprachenError,
  builtInNames,
  errorText,
  fill,
  hintOf,
  isTexts,
  makeSprachenApi,
  mergeTexts,
  plainFetch,
  refusalOf,
  saveFile,
  templateFile,
  textsCount,
  useSprachenTexts,
  validEntries,
} from './sprachen'
export type { Fetcher, LanguageEntry, SprachenApi, SprachenTexts, Texts } from './sprachen'
