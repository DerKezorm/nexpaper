// nexsicherung in the browser: the shapes the module's routes answer, the calls to them, the module's words and small
// helpers. The page itself is StorageArea.tsx (the cards "Speicher" and "Sicherung", built from the kit nexui).
//
// Copied unchanged into frontend/src/vendor/nexsicherung/ by bauplaene/sicherung/tools/sync.py; changed only there.

import { NEXUI_TEXTS, useNexuiTexts } from '../nexui'

import de from './sicherung.de.json'
import en from './sicherung.en.json'
import fr from './sicherung.fr.json'

export type Every = 'off' | 'daily' | 'weekly' | 'monthly'
export const EVERY: readonly Every[] = ['off', 'daily', 'weekly', 'monthly']

/** The languages of the page (the kit's). */
export type Language = 'de' | 'en' | 'fr'

export type Schedule = { every: Every; time: string; keep: number }

export type Part = { key: string; bytes: number; within: string; complete: boolean }

/** The card "Speicher" (GET {prefix}). */
export type Overview = {
  app: string
  used: number
  parts: Part[]
  complete: boolean
  total: number
  disk_used: number
  free: number
  nearly_full: boolean
  where: Record<string, { kind: 'network' | 'local' | 'unknown'; fstype: string }>
  network: string[]
}

export type Entry = {
  name: string
  size: number
  created: string
  kind: 'manual' | 'scheduled' | 'update'
  note: string
  version: string
  uploaded: boolean
  locked: boolean
  readable: boolean
  facts: Record<string, unknown>
}

/** The card "Sicherung" (GET {prefix}/backups). */
export type Backups = {
  schedule: Schedule
  zone: string
  last: { created: string; size: number; kind: string } | null
  count: number
  kept: number
  failure: { at: string; reason: string } | null
  running: boolean
  restore_failure: { at: string; name: string } | null
  restored: { at: string; name: string } | null
  restore: 'restart' | 'now'
  /** A download asks for a password of its own (nexmail's encrypted archive). */
  download_password: boolean
  backups: Entry[]
}

/** The result of a check (POST {prefix}/backups/{name}/check). `details` are the app's own findings. */
export type Brief = {
  name: string
  created: string
  kind: string
  note: string
  version: string
  uploaded: boolean
  database_ok: boolean
  files_ok: boolean
  damaged: string[]
  too_new: boolean
  blocked: string
  blocked_text: string
  usable: boolean
  facts: Record<string, unknown>
  details: Record<string, unknown>
}

export type Restored = Brief & { result: Record<string, unknown>; restarting: boolean }

/** A refusal of the server: its code (`sicherung.error.<code>`), its English text, its status. */
export class SicherungError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}

/** The app's way to the server: `fetch` with what the app adds (cookies, its own headers). */
export type Fetcher = (path: string, init: RequestInit) => Promise<Response>

export const PREFIX = '/api/server/storage'
/** The header of the upload: the body is the archive, so the password comes as base64 of its UTF-8. */
export const PASSWORD_HEADER = 'X-Backup-Password'

/** The password for a header: base64 of its UTF-8 (a header carries no umlauts). */
export function passwordHeader(password: string): string {
  const bytes = new TextEncoder().encode(password)
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary)
}

async function refusal(response: Response): Promise<SicherungError> {
  let code = 'unknown'
  let message = response.statusText
  try {
    const body = (await response.json()) as { detail?: unknown }
    const detail = (body.detail ?? body) as { code?: unknown; message?: unknown }
    if (detail && typeof detail === 'object' && typeof detail.code === 'string') {
      code = detail.code
      message = typeof detail.message === 'string' ? detail.message : message
    }
  } catch {
    // Not JSON: the status says enough.
  }
  return new SicherungError(code, message, response.status)
}

export type SicherungApi = {
  overview(): Promise<Overview>
  backups(): Promise<Backups>
  saveSchedule(schedule: Schedule): Promise<Schedule>
  make(note?: string): Promise<{ name: string }>
  upload(file: Blob, password: string): Promise<{ name: string }>
  check(name: string, archivePassword?: string): Promise<Brief>
  download(name: string, password: string, archivePassword?: string): Promise<Blob>
  /** `options` (since E38): the answers to the app's questions in the dialog (`StorageArea restoreOptions`). */
  restore(name: string, password: string, archivePassword?: string, options?: RestoreAnswers): Promise<Restored>
  remove(name: string, password: string): Promise<void>
  dismissFailed(): Promise<void>
}

/** Since E38: a question of the app in the dialog "Wiederherstellen" (nexmail: whether the public address of the
 * archive applies), in the app's words: a box to tick without `choices`, else one of them. The answer goes to the
 * server under `key` (`AppConfig.restore_options`) and on to the app's hook. */
export type RestoreOption = {
  key: string
  label: string
  hint?: string
  choices?: readonly { value: string; label: string }[]
  /** The answer before the operator changes it: false, or the first choice. */
  initial?: string | boolean
}

/** The answers, by the key of each question. */
export type RestoreAnswers = Record<string, string | boolean>

/** What the questions answer before anybody touches them. */
export function initialAnswers(questions: readonly RestoreOption[] | undefined): RestoreAnswers {
  const found: RestoreAnswers = {}
  for (const question of questions ?? []) found[question.key] = question.initial ?? (question.choices ? (question.choices[0]?.value ?? '') : false)
  return found
}

/** The calls to the module's routes under `prefix` (where the app mounted `routes.router`). */
export function makeSicherungApi(fetcher: Fetcher, prefix: string = PREFIX): SicherungApi {
  const call = async (path: string, init: RequestInit): Promise<Response> => {
    const response = await fetcher(prefix + path, init)
    if (!response.ok) throw await refusal(response)
    return response
  }
  const json = (method: string, body?: unknown): RequestInit => ({
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const part = (name: string) => `/backups/${encodeURIComponent(name)}`
  return {
    overview: async () => (await call('', { method: 'GET' })).json() as Promise<Overview>,
    backups: async () => (await call('/backups', { method: 'GET' })).json() as Promise<Backups>,
    saveSchedule: async (schedule) => (await call('/backups/schedule', json('PUT', schedule))).json() as Promise<Schedule>,
    make: async (note = '') => (await call('/backups', json('POST', { note }))).json() as Promise<{ name: string }>,
    upload: async (file, password) =>
      (await call('/backups/upload', { method: 'POST', body: file, headers: { [PASSWORD_HEADER]: passwordHeader(password) } })).json() as Promise<{ name: string }>,
    check: async (name, archivePassword) =>
      (await call(`${part(name)}/check`, json('POST', archivePassword === undefined ? {} : { archive_password: archivePassword }))).json() as Promise<Brief>,
    download: async (name, password, archivePassword) =>
      (await call(`${part(name)}/download`, json('POST', archivePassword === undefined ? { password } : { password, archive_password: archivePassword }))).blob(),
    restore: async (name, password, archivePassword, options) =>
      (
        await call(
          `${part(name)}/restore`,
          json('POST', {
            password,
            ...(archivePassword === undefined ? {} : { archive_password: archivePassword }),
            ...(options && Object.keys(options).length > 0 ? { options } : {}),
          }),
        )
      ).json() as Promise<Restored>,
    remove: async (name, password) => {
      await call(part(name), json('DELETE', { password }))
    },
    dismissFailed: async () => {
      await call('/backups/restore-failed', { method: 'DELETE' })
    },
  }
}

// --- Words ------------------------------------------------------------------------------------------------------------

export type SicherungTexts = (typeof de)['sicherung']
export const SICHERUNG_TEXTS: Record<Language, SicherungTexts> = { de: de.sicherung, en: en.sicherung, fr: fr.sicherung }

/** The module's words in the kit's language (`NexuiLanguage`, else `<html lang>`): German, English or French. */
export function useSicherungTexts(): SicherungTexts {
  const kit = useNexuiTexts()
  return kit === NEXUI_TEXTS.de ? SICHERUNG_TEXTS.de : kit === NEXUI_TEXTS.fr ? SICHERUNG_TEXTS.fr : SICHERUNG_TEXTS.en
}

const LOCALES: Record<Language, string> = { de: 'de-DE', en: 'en-GB', fr: 'fr-FR' }

/** Fills `{name}` and the like. */
export function fill(text: string, values: Record<string, string | number>): string {
  return text.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? String(values[key]) : whole))
}

/** A sentence with a time (`{when}`): without one (a locked archive whose app gave no date, E64) the time goes with
 * its brackets or its comma, never "()" or "Zuletzt: , 2 KB". */
export function fillWhen(text: string, at: string, values: Record<string, string | number> = {}): string {
  const shown = at.trim() ? text : text.replace(/\s*\(\{when\}\)/g, '').replace(/\{when\},\s*/g, '')
  return fill(shown, { ...values, when: at })
}

/** The words of an error code; the app's own codes (its password check) fall back to `unknown`. */
export function errorText(texts: SicherungTexts, error: unknown, app: string): string {
  const given = error && typeof error === 'object' && 'code' in error ? (error as { code: unknown }).code : null
  const code = typeof given === 'string' ? given : 'unknown'
  const known = (texts.error as Record<string, string>)[code]
  return fill(known ?? texts.error.unknown, { app })
}

/** Bytes as people read them: "1,2 MB" in German and French, "1.2 MB" in English. */
export function bytes(value: number, language: Language): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = Math.max(0, value)
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  const digits = unit === 0 || size >= 100 ? 0 : 1
  return `${size.toLocaleString(LOCALES[language], { maximumFractionDigits: digits, minimumFractionDigits: digits })} ${units[unit]}`
}

/** A moment as day and time in the browser's zone. */
export function when(iso: string, language: Language): string {
  const moment = new Date(iso)
  if (Number.isNaN(moment.getTime())) return iso
  return moment.toLocaleString(LOCALES[language], { dateStyle: 'medium', timeStyle: 'short' })
}

/** The share of the disk for the bar: what the app takes, and what else is in use, each in percent. */
export function shares(overview: Pick<Overview, 'used' | 'disk_used' | 'total'>): { own: number; other: number } {
  if (!overview.total) return { own: 0, other: 0 }
  const own = Math.min(100, (overview.used / overview.total) * 100)
  const other = Math.min(100 - own, (Math.max(0, overview.disk_used - overview.used) / overview.total) * 100)
  return { own, other }
}

/** The name of a part: the app's word first, then the module's, then the key. */
export function partName(texts: SicherungTexts, key: string, own?: (key: string) => string | undefined): string {
  return own?.(key) ?? (texts.storage.parts as Record<string, string>)[key] ?? key
}
