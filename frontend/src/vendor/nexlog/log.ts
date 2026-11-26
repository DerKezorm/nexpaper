// nexlog in the browser: what the server answers, the filters, the columns, the page size and the words of the card.
// The card itself is LogCard.tsx (built from the ui kit). Copied unchanged into frontend/src/vendor/nexlog/ by
// bauplaene/log/tools/sync.py; changed only there.

import de from './log.de.json'
import en from './log.en.json'
import fr from './log.fr.json'

/** One line as `GET <base>` gives it (newest first). `at`: the moment with its offset; `time`: the server's clock. */
export type LogLine = {
  time: string
  level: string
  logger: string
  message: string
  request_id?: string | null
  user?: string | null
  at?: string | null
}

/** `GET <base>/level`: the level in force, its end, whether the environment fixes it (and its name). */
export type LogMode = {
  mode: string
  until: string | null
  fixed_by_env: boolean
  variable?: string
  modes: string[]
  durations?: number[]
}

/** The app's way to call its server (its own client with its headers): `query` as search parameters, `body` as JSON. */
export type LogRequest = <T>(path: string, init?: { method?: 'GET' | 'PUT' | 'DELETE'; query?: Record<string, string | number | undefined>; body?: unknown }) => Promise<T>

/** The filters above the table: all, then each level that shows itself and the higher ones. */
export const LEVEL_FILTERS = ['', 'INFO', 'WARNING', 'ERROR'] as const
export type LevelFilter = (typeof LEVEL_FILTERS)[number]

/** The four levels of detail, in this order. */
export const MODES = ['quiet', 'normal', 'detailed', 'trace'] as const
export const DEEP_MODES: readonly string[] = ['detailed', 'trace']
/** A deep level from the page runs an hour ("Ausführlich (1 Stunde)"). */
export const DEEP_MINUTES = 60
/** Lines per page; "Load older" asks for the next. */
export const LOG_PAGE = 200
/** How long the search waits after the last key. */
export const SEARCH_DELAY = 250

/** The columns of the table, in this order. */
export const LOG_COLUMNS = ['time', 'level', 'source', 'request', 'message'] as const
export type LogColumn = (typeof LOG_COLUMNS)[number]
export const LOG_COLUMN_WIDTHS: Partial<Record<LogColumn, string>> = { time: '9.5rem', level: '5.5rem', source: '9rem', request: '9rem' }

/** The tone of a level's `Badge` (statuses are badges): ERROR and CRITICAL `danger`, WARNING `warn`, the rest
 * `off`. */
export function levelTone(level: string): 'danger' | 'warn' | 'off' {
  if (level === 'WARNING') return 'warn'
  if (level === 'ERROR' || level === 'CRITICAL') return 'danger'
  return 'off'
}

/** The query of one page. */
export function logQuery(level: string, search: string, offset: number): Record<string, string | number | undefined> {
  return { level: level || undefined, search: search.trim() || undefined, limit: LOG_PAGE, offset }
}

/** What `PUT <base>/level` gets for a choice of the page: a deep level for an hour, the others for good. */
export function modeChange(mode: string): { mode: string; minutes: number } {
  return { mode, minutes: DEEP_MODES.includes(mode) ? DEEP_MINUTES : 0 }
}

export type LogTexts = typeof de
export const LOG_TEXTS: Record<'de' | 'en' | 'fr', LogTexts> = { de, en, fr }

/** Fills `{things}`, `{thingsDative}` (since E34), `{time}`, `{variable}`. */
export function fillLog(text: string, values: Record<string, string>): string {
  return text.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? (values[key] ?? '') : whole))
}
