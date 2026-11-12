/** Small things "Gehört zu" shows: where a document opens, and a proposal said in one line. */
import type { RelatedDocument } from '../api/client'
import { shortDate } from './dates'

export type RelatedShown = Pick<RelatedDocument, 'id' | 'title' | 'kind' | 'sender' | 'date' | 'status'>

/** Where a document opens: the inbox for one that waits there, else its page. */
export function pageOf(document: Pick<RelatedShown, 'id' | 'status'>): string {
  return document.status === 'inbox' || document.status === 'processing' ? `/eingang/${document.id}` : `/dokument/${document.id}`
}

/** "Lieferschein, Stadtwerke Lindenau, 03.11.2026": what a proposal is, in one line (its kind, else its title). */
export function proposalLine(found: RelatedShown, language: string): string {
  return [found.kind?.name ?? found.title, found.sender?.name, found.date ? shortDate(found.date, language) : null].filter(Boolean).join(', ')
}
