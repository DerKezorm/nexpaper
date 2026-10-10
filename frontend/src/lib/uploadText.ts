import { errorText } from './errors'
import type { Failure, Summary } from './uploader'

type Say = (key: string, values?: Record<string, unknown>) => string

/** One sentence for what a run of the queue took (the files that were not taken are told apart: `failureLines`). */
export function summaryText(summary: Summary, t: Say, vault: string | null = null): string {
  const parts: string[] = []
  // The vault is named when every file went to the same one (and its name is known).
  if (summary.done === 1) parts.push(vault ? t('upload.toast.oneIn', { vault }) : t('upload.toast.one'))
  else if (summary.done > 1) parts.push(vault ? t('upload.toast.manyIn', { count: summary.done, vault }) : t('upload.toast.many', { count: summary.done }))
  if (summary.exists > 0) parts.push(t('upload.toast.exists', { count: summary.exists }))
  return parts.join(' ')
}

/** The files that were not taken, each with the reason in words, where the notice about the run appears (it does not
 * point to a list that may be out of sight). */
export function failureLines(summary: Summary, t: Say): { head: string; lines: Array<{ name: string; reason: string }>; more: string | null } {
  const shown: Failure[] = summary.failures
  const rest = summary.failed - shown.length
  return {
    head: t('upload.toast.failed', { count: summary.failed }),
    lines: shown.map((failure) => ({ name: failure.name, reason: errorText(failure.code, failure.values) })),
    more: rest > 0 ? t('upload.toast.more', { count: rest }) : null,
  }
}
