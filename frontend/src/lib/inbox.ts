/**
 * The inbox's data: what waits there for the person, and what of a document's fields changed (the draft of the inbox
 * against the document as the server has it).
 */
import { documentsApi, type DateSet, type DocumentInfo, type DocumentPatch } from '../api/client'
import type { DateEntry } from '../components/DocumentFields'

/** Everything waiting in the inbox that the person may add to: being read first, then the newest. */
export async function inboxDocuments(): Promise<DocumentInfo[]> {
  const found: DocumentInfo[] = []
  for (const status of ['processing', 'inbox'] as const) {
    let after = 0
    for (let page = 0; page < 20; page++) {
      const answer = await documentsApi.list({ status, after, limit: 500 })
      found.push(...(Array.isArray(answer.items) ? answer.items : []))
      if (!answer.next) break
      after = answer.next
    }
  }
  return found.filter((d) => d.my_right !== 'read').sort((a, b) => b.added_at.localeCompare(a.added_at) || b.id - a.id)
}

export type Draft = {
  title: string
  sender: string
  kind_id: number | null
  date: string
  amount: number | null
  tags: string[]
  dates: DateEntry[]
  vault_id: number
}

/** A date of the document as the fields edit it: a contract with its notice period and renewal. */
export function dateEntry(x: DocumentInfo['dates'][number]): DateEntry {
  const kind = x.kind as DateEntry['kind']
  // Terms only where there are some: left out, they stay as they are on the server.
  return { kind, date: x.date, ...(kind === 'contract_end' && x.notice ? { notice: x.notice } : {}), ...(kind === 'contract_end' && x.renew_months ? { renew_months: x.renew_months } : {}) }
}

export function draftOf(d: DocumentInfo): Draft {
  return {
    title: d.title,
    sender: d.sender?.name ?? '',
    kind_id: d.kind?.id ?? null,
    date: d.date ?? '',
    amount: d.amount,
    tags: d.tags,
    dates: d.dates.map(dateEntry),
    vault_id: d.vault_id,
  }
}

/**
 * The draft after the server's copy of the document changed under it (a proposal that came later, another person's
 * edit): a field the person has not touched (still what the document was) takes the new value, a field they changed
 * stays as they typed it. Without this a draft made when the page opened would show, and later file, a stale copy.
 */
export function follow(was: Draft, now: Draft, mine: Draft): Draft {
  const out: Draft = { ...mine }
  const keep = <K extends keyof Draft>(key: K) => {
    if (JSON.stringify(mine[key]) === JSON.stringify(was[key])) out[key] = now[key]
  }
  keep('title')
  keep('sender')
  keep('kind_id')
  keep('date')
  keep('amount')
  keep('tags')
  keep('dates')
  keep('vault_id')
  return out
}

/** What changed against the document, as the server takes it. */
export function changesOf(d: DocumentInfo, f: Draft): DocumentPatch {
  const was = draftOf(d)
  const out: DocumentPatch = {}
  if (f.title.trim() !== was.title) out.title = f.title.trim()
  if (f.sender.trim() !== was.sender) out.sender = f.sender.trim() || null
  if (f.kind_id !== was.kind_id) out.kind_id = f.kind_id
  if (f.date !== was.date) out.date = f.date || null
  if (f.amount !== was.amount) out.amount = f.amount
  if (JSON.stringify(f.tags) !== JSON.stringify(was.tags)) out.tags = f.tags
  return { ...out, ...datesChanged(was.dates, f.dates) }
}

/**
 * What changed in the terms, as single terms (`set_dates`, `remove_dates`): a page sends only what the person changed,
 * so a page that is behind never sends back a day it did not see change (a contract that renewed meanwhile).
 */
export function datesChanged(was: DateEntry[], now: DateEntry[]): Pick<DocumentPatch, 'set_dates' | 'remove_dates'> {
  const setDates: DateSet[] = []
  for (const entry of now) {
    const before = was.find((d) => d.kind === entry.kind)
    if (!before) {
      setDates.push({ ...entry })
      continue
    }
    const changed: DateSet = { kind: entry.kind }
    if (entry.date !== before.date) changed.date = entry.date
    if (JSON.stringify(entry.notice ?? null) !== JSON.stringify(before.notice ?? null)) changed.notice = entry.notice ?? null
    if ((entry.renew_months ?? null) !== (before.renew_months ?? null)) changed.renew_months = entry.renew_months ?? null
    if (Object.keys(changed).length > 1) setDates.push(changed)
  }
  const removeDates = was.filter((d) => !now.some((x) => x.kind === d.kind)).map((d) => d.kind)
  return { ...(setDates.length ? { set_dates: setDates } : {}), ...(removeDates.length ? { remove_dates: removeDates } : {}) }
}
