/** nexsicherung in the browser (bauplaene/sicherung). Changed only in bauplaene, copied unchanged into each app. */
export { BackupCard, BriefBox, StorageArea, StorageCard, blockedWords } from './StorageArea'
export type { BlockedTexts, StorageAreaProps } from './StorageArea'
export {
  EVERY,
  PASSWORD_HEADER,
  PREFIX,
  SICHERUNG_TEXTS,
  SicherungError,
  bytes,
  errorText,
  fill,
  initialAnswers,
  makeSicherungApi,
  partName,
  passwordHeader,
  shares,
  useSicherungTexts,
  when,
} from './sicherung'
export type { Backups, Brief, Entry, Every, Fetcher, Language, Overview, Part, Restored, RestoreAnswers, RestoreOption, Schedule, SicherungApi, SicherungTexts } from './sicherung'
