/** What a request for many documents at once (`POST /api/v1/documents/bulk`) did, in the words of the archive. */

import type { BulkAction, BulkResult } from '../api/client'

/** The most the server takes in one request. */
export const BULK_MOST = 500
/** "Miteinander verknüpfen" takes two to this many documents (the server says so as well). */
export const LINK_MOST = 10

/** The reasons the server names, in the words of the line. */
const REASONS = ['forbidden', 'in_trash', 'kind_elsewhere', 'unchanged']

/** "12 geändert, 2 nicht (nur Lesen)", or "3 miteinander verknüpft" after `link`: what a request did, in one line. */
export function outcomeLine(result: Pick<BulkResult, 'changed' | 'reasons'>, t: (key: string, values?: Record<string, unknown>) => string, language: string, action?: BulkAction): string {
  const n = (value: number) => value.toLocaleString(language)
  const reasons = Object.entries(result.reasons ?? {}).filter(([, count]) => count > 0)
  const not = reasons.reduce((all, [, count]) => all + count, 0)
  const linked = action === 'link'
  if (!not) return t(linked ? 'archiveBulk.linked' : 'archiveBulk.changed', { n: n(result.changed.length) })
  const word = (reason: string) => t(`archiveBulk.why.${REASONS.includes(reason) ? reason : 'other'}`)
  const why = reasons.length === 1 ? word(reasons[0][0]) : reasons.map(([reason, count]) => t('archiveBulk.whyCount', { n: n(count), why: word(reason) })).join(', ')
  return t(linked ? 'archiveBulk.linkedNot' : 'archiveBulk.changedNot', { n: n(result.changed.length), not: n(not), why })
}

