/**
 * Deadlines as the page and the fields show them: the last day to cancel a contract worked
 * out while it is typed (the server works it out the same way, `services/deadlines.py`), the words of each kind of
 * deadline, and how far away a day is.
 */
import { useTranslation } from 'react-i18next'

import type { DeadlineKind, DeadlineWhat, Me, Notice } from '../api/client'
import { shortDate } from './dates'

/** Whether the person uses deadlines (My account, Reminders; on from the start). Off, the menu has no "Fristen", the
 * archive no filter "Frist" and a document no "paid" or "later"; the dates themselves stay on the documents. */
export function usesDeadlines(me: { profile?: Pick<Me['profile'], 'deadlines'> } | null | undefined): boolean {
  return me?.profile?.deadlines !== false
}

function parse(day: string): Date {
  const [y, m, d] = day.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d))
}

function iso(day: Date): string {
  return day.toISOString().slice(0, 10)
}

/** Whether `day` is a whole day as a date field gives it (`2026-10-08`). */
export function isDay(day: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(day) && !Number.isNaN(parse(day).getTime())
}

/** Months back or ahead, the day kept where the month has it, else its last day; the last day of a month stays the
 * last day of the other one (31.12. minus 3 months is 30.09.). */
export function addMonths(day: string, n: number): string {
  const d = parse(day)
  const y = d.getUTCFullYear()
  const m = d.getUTCMonth() + n
  const last = new Date(Date.UTC(y, m + 1, 0)).getUTCDate()
  const wasLast = d.getUTCDate() === new Date(Date.UTC(y, d.getUTCMonth() + 1, 0)).getUTCDate()
  return iso(new Date(Date.UTC(y, m, wasLast ? last : Math.min(d.getUTCDate(), last))))
}

export function addDays(day: string, n: number): string {
  const d = parse(day)
  d.setUTCDate(d.getUTCDate() + n)
  return iso(d)
}

/** The last day to cancel a contract that ends on `end`. */
export function lastToCancel(end: string, notice: Notice): string {
  return notice.unit === 'weeks' ? addDays(end, -7 * notice.n) : addMonths(end, -notice.n)
}

/** Days from `today` to `day`; negative is past. */
export function daysBetween(today: string, day: string): number {
  return Math.round((parse(day).getTime() - parse(today).getTime()) / 86_400_000)
}

/** Sunday is 0, as `deadlines.weekdays` counts. */
export function weekday(day: string): number {
  return parse(day).getUTCDay()
}

/** What a done deadline of a date is called: paid, cancelled, done. */
export function whatOfKind(kind: DeadlineKind | string): DeadlineWhat {
  return kind === 'due' ? 'pay' : kind === 'contract_end' ? 'cancel' : 'warranty'
}

/** The words of "in 4 Tagen", "seit gestern": a key under `deadlines.relative` and its count. */
export function relative(days: number): { key: string; count: number } {
  if (days === 0) return { key: 'today', count: 0 }
  if (days === 1) return { key: 'tomorrow', count: 1 }
  if (days === -1) return { key: 'sinceYesterday', count: 1 }
  if (days < 0) return { key: 'since', count: -days }
  if (days < 60) return { key: 'inDays', count: days }
  return { key: 'inMonths', count: Math.round(days / 30) }
}

/** How far ahead the page and the menu count as "soon". */
export const SOON_DAYS = 14
/** "Later": by how many days. */
export const SNOOZE_DAYS = [1, 3, 7] as const
/** How many of "Später" show before "Alle zeigen". */
export const LATER_SHOWN = 6

/** "Mi, 30.09.2026": a day with its short weekday, in the language of the page. */
export function useDayName(): (day: string) => string {
  const { t, i18n } = useTranslation()
  return (day: string) => t('deadlines.dayDate', { day: (t('deadlines.weekdays', { returnObjects: true }) as string[])[weekday(day)] ?? '', date: shortDate(day, i18n.language) })
}
