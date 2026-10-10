/**
 * The archive's filters as the address holds them, and what the search is asked for: the archive shows what was filed;
 * a span of time becomes dates (the clock comes from outside, so a test sets it).
 */
import type { SearchFilters } from '../api/client'

export const SPANS = ['year', 'lastyear', '12m'] as const
export type Span = (typeof SPANS)[number]

/** The filters as the address holds them. */
export type Chosen = { vault: string; kind: string; sender: string; tag: string; owner: string; span: string }
export const KEYS: (keyof Chosen)[] = ['vault', 'kind', 'sender', 'tag', 'owner', 'span']

function day(date: Date): string {
  const two = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${two(date.getMonth() + 1)}-${two(date.getDate())}`
}

/** The span of time as dates for the server; `now` from outside, so a test sets the clock. */
export function spanDates(span: string, now: Date = new Date()): { date_from?: string; date_to?: string } {
  const year = now.getFullYear()
  if (span === 'year') return { date_from: `${year}-01-01`, date_to: `${year}-12-31` }
  if (span === 'lastyear') return { date_from: `${year - 1}-01-01`, date_to: `${year - 1}-12-31` }
  if (span === '12m') return { date_from: day(new Date(year - 1, now.getMonth(), now.getDate())) }
  return {}
}

/** What the server is asked for: the archive is what was filed. */
export function filtersOf(chosen: Chosen, now: Date = new Date()): SearchFilters {
  const number = (value: string) => (/^\d+$/.test(value) ? Number(value) : undefined)
  return {
    status: 'filed',
    ...(chosen.vault === 'shared' ? { via_share: true } : chosen.vault ? { vault_id: number(chosen.vault) } : {}),
    ...(number(chosen.kind) ? { kind_id: number(chosen.kind) } : {}),
    ...(chosen.sender ? { sender: chosen.sender } : {}),
    ...(chosen.tag ? { tag: chosen.tag } : {}),
    ...(number(chosen.owner) ? { owner_id: number(chosen.owner) } : {}),
    ...spanDates(chosen.span, now),
  }
}
