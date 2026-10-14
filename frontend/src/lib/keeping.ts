/**
 * Keeping documents (the mock's `keepOf`): until when a document is kept, and why. The server works `keep_until` out
 * from the kind (`services/keeping.py`); here the same sum is done for what the page shows before it is saved (a kind
 * chosen in the inbox, a date typed), and the stored one is read with where it came from.
 */
import type { DocumentInfo } from '../api/client'

/** The years the select offers (the mock's list). */
export const KEEP_CHOICES = [1, 2, 3, 5, 6, 8, 10, 30]

/** The year a keeping time counts from: of the document's date, else of the day it came in. */
export function baseYear(date: string | null | undefined, addedAt: string): number {
  return Number((date || addedAt).slice(0, 4))
}

/** The end of the year of the document's date plus `years`. */
export function keepUntil(years: number, date: string | null | undefined, addedAt: string): string {
  return `${baseYear(date, addedAt) + years}-12-31`
}

export type Kept = { date: string; from: 'hand' | 'kind'; years?: number }

/** The stored `keep_until` of a document and where it came from: set by hand, or worked out from the kind. */
export function keptOf(d: Pick<DocumentInfo, 'date' | 'added_at' | 'dates'>): Kept | null {
  const entry = d.dates.find((x) => x.kind === 'keep_until')
  if (!entry) return null
  // Left out (an older server) counts as set by hand, as the server reads a date sent without saying.
  if (entry.manual !== false) return { date: entry.date, from: 'hand' }
  return { date: entry.date, from: 'kind', years: Number(entry.date.slice(0, 4)) - baseYear(d.date, d.added_at) }
}
