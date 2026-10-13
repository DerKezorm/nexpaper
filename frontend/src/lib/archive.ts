/**
 * The archive's filters as the address holds them, and what the search is asked for: the archive shows what was filed;
 * a year becomes the dates from its first to its last day.
 */
import type { SearchFilters, SearchOrder } from '../api/client'

/** The filters as the address holds them. */
export type Chosen = { vault: string; kind: string; sender: string; tag: string; owner: string; year: string }
export const KEYS: (keyof Chosen)[] = ['vault', 'kind', 'sender', 'tag', 'owner', 'year']
/** The filters that open the table; the vault alone keeps the overview. */
export const NARROWING: (keyof Chosen)[] = ['kind', 'sender', 'tag', 'owner', 'year']

export const ORDERS: SearchOrder[] = ['-date', 'date', '-title', 'title', '-sender', 'sender', '-amount', 'amount']
export const SIZES = [25, 50, 100]
export const DEFAULT_SIZE = 50

/** What the server is asked for: the archive is what was filed. */
export function filtersOf(chosen: Chosen): SearchFilters {
  const number = (value: string) => (/^\d+$/.test(value) ? Number(value) : undefined)
  const year = /^\d{4}$/.test(chosen.year) ? chosen.year : ''
  return {
    status: 'filed',
    ...(chosen.vault === 'shared' ? { via_share: true } : chosen.vault ? { vault_id: number(chosen.vault) } : {}),
    ...(number(chosen.kind) ? { kind_id: number(chosen.kind) } : {}),
    ...(chosen.sender ? { sender: chosen.sender } : {}),
    ...(chosen.tag ? { tag: chosen.tag } : {}),
    ...(number(chosen.owner) ? { owner_id: number(chosen.owner) } : {}),
    ...(year ? { date_from: `${year}-01-01`, date_to: `${year}-12-31` } : {}),
  }
}

/** The order in the address, or the newest first. */
export function orderOf(value: string | null): SearchOrder {
  return ORDERS.includes(value as SearchOrder) ? (value as SearchOrder) : '-date'
}

/** The size of a page in the address, or the usual one. */
export function sizeOf(value: string | null): number {
  const n = Number(value)
  return SIZES.includes(n) ? n : DEFAULT_SIZE
}

/** The page in the address, from 1. */
export function pageOf(value: string | null): number {
  const n = Number(value)
  return Number.isInteger(n) && n >= 1 && n <= 100_000 ? n : 1
}

/** The numbers a pager shows: the first, the last and the neighbours of the current one, with gaps as `null`. */
export function pageList(current: number, pages: number): (number | null)[] {
  const keep = [...new Set([1, pages, current - 1, current, current + 1])].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b)
  const out: (number | null)[] = []
  let last = 0
  for (const n of keep) {
    if (n - last > 1) out.push(null)
    out.push(n)
    last = n
  }
  return out
}

/** What a click on a column heading asks for: the same column turned around, else dates and amounts largest first and
 * words from A. */
export function nextOrder(current: SearchOrder, column: 'date' | 'title' | 'sender' | 'amount'): SearchOrder {
  if (current === column) return `-${column}` as SearchOrder
  if (current === `-${column}`) return column
  return column === 'date' || column === 'amount' ? (`-${column}` as SearchOrder) : column
}
