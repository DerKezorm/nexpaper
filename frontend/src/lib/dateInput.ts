/**
 * Dates as people type them into a date field: a year of two digits (27, or 0027 from a browser's date field) means
 * 2027, and a date the server refused is marked at its field with the year it probably meant.
 */
import { ApiError } from '../api/client'

/** The years the server takes (`DATE_MIN` and `DATE_MAX` there). */
export const YEAR_FROM = 1900
export const YEAR_TO = 2200

const DAY = /^(\d{1,6})-(\d{1,2})-(\d{1,2})$/

/** The year of `2027-02-28`, as typed (`0027`), and as a number; nothing for what is no day. */
export function yearOf(value: string): { text: string; number: number } | null {
  const match = DAY.exec(value)
  return match ? { text: match[1].padStart(4, '0'), number: Number(match[1]) } : null
}

/** A year under 100 read as 20xx: `0027-02-28` and `27-02-28` become `2027-02-28`; any other value stays as it is. */
export function expandYear(value: string): string {
  const match = DAY.exec(value)
  if (!match || Number(match[1]) >= 100) return value
  return `${String(2000 + Number(match[1])).padStart(4, '0')}-${match[2].padStart(2, '0')}-${match[3].padStart(2, '0')}`
}

/** What the server refused: which field it was (`date`, or `dates[n]`) and the value that was sent. */
export type Refused = { field: string; value: string }

/** The sentence's code and values of an error, with, for a refused date, the value that was sent in `value`. */
export function problemOf(error: unknown, sent?: { date?: string | null; dates?: { date: string }[] }): { code: string; values: Record<string, unknown> } {
  if (!(error instanceof ApiError)) return { code: 'internal_error', values: {} }
  const values: Record<string, unknown> = { ...error.values }
  if (error.code === 'invalid_date' && typeof values.field === 'string' && sent) {
    const entry = /^dates\[(\d+)\]$/.exec(values.field)
    const value = values.field === 'date' ? sent.date : entry ? sent.dates?.[Number(entry[1])]?.date : undefined
    if (typeof value === 'string') values.value = value
  }
  return { code: error.code, values }
}

/** The value of `field` that the server refused, if the problem is that; else nothing. */
export function refusedValue(problem: { code: string; values?: Record<string, unknown> } | null | undefined, field: string): string | undefined {
  if (problem?.code !== 'invalid_date' || problem.values?.field !== field) return undefined
  return typeof problem.values.value === 'string' ? problem.values.value : undefined
}

/** The field and the value the server refused, if the problem is that; else nothing. */
export function refusedOf(problem: { code: string; values?: Record<string, unknown> } | null | undefined): Refused | null {
  if (problem?.code !== 'invalid_date' || typeof problem.values?.field !== 'string' || typeof problem.values.value !== 'string') return null
  return { field: problem.values.field, value: problem.values.value }
}

/** True when the problem is shown at a field of its own, so the page need not say it again below. */
export function shownAtField(problem: { code: string; values?: Record<string, unknown> } | null | undefined): boolean {
  return problem?.code === 'invalid_date' && typeof problem.values?.value === 'string'
}
