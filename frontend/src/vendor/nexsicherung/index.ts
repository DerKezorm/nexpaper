/** nexsicherung in the browser (bauplaene/sicherung). Changed only in bauplaene, copied unchanged into each app. */
export { BackupCard, BriefBox, StorageArea, StorageCard } from './StorageArea'
export type { StorageAreaProps } from './StorageArea'
export {
  EVERY,
  PASSWORD_HEADER,
  PREFIX,
  SICHERUNG_TEXTS,
  SicherungError,
  bytes,
  errorText,
  fill,
  makeSicherungApi,
  partName,
  passwordHeader,
  shares,
  useSicherungTexts,
  when,
} from './sicherung'
export type { Backups, Brief, Entry, Every, Fetcher, Language, Overview, Part, Restored, Schedule, SicherungApi, SicherungTexts } from './sicherung'
