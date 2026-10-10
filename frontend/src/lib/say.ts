/**
 * Small things the pages with documents share: a sentence after something was done (handed to the frame's toast through
 * the navigation state, as the vaults page does), a signal that the inbox changed (the frame counts it anew), and how
 * a moment and a source are said.
 */
import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate } from 'react-router-dom'

import { daysAgo } from './ago'
import { shortDate } from './dates'

/** A way on from a notice ("Papierkorb öffnen"): where it leads and what it says. */
export type NoticeLink = { to: string; label: string }

/** Says `notice` on the current page; `to` goes elsewhere and says it there; `link` adds a way on to the sentence. */
export function useSay() {
  const navigate = useNavigate()
  const location = useLocation()
  return useCallback(
    (notice: string, to?: string, link?: NoticeLink) =>
      navigate(to ?? location.pathname + location.search, { replace: !to, state: { notice, ...(link ? { link } : {}) } }),
    [navigate, location.pathname, location.search],
  )
}

/** Sent on `window` when documents came into the inbox or left it: the menu counts them again. */
export const INBOX_CHANGED = 'nexpaper:inbox-changed'

export function inboxChanged(): void {
  window.dispatchEvent(new Event(INBOX_CHANGED))
}

/** "heute, 07:42", "gestern, 21:08", or the date for anything older. `now` from outside, for a test. */
export function moment(value: string, language: string, now: number = Date.now()): string {
  const at = new Date(value)
  const days = Math.round((new Date(now).setHours(0, 0, 0, 0) - new Date(value).setHours(0, 0, 0, 0)) / 86_400_000)
  const time = new Intl.DateTimeFormat(language, { hour: '2-digit', minute: '2-digit' }).format(at)
  if (days === 0 || days === 1) return `${daysAgo(value, language, now)}, ${time}`
  return shortDate(value, language)
}

/** Where a document came from, in words: the inbox's own texts for the folder and the mailbox. */
export function useSourceText() {
  const { t } = useTranslation()
  return (source: string) => (source === 'folder' || source === 'mail' ? t(`intake.origin.${source}`) : t(`docs.source.${source}`, { defaultValue: t('docs.source.upload') }))
}

/** An answer that should be a list, as a list: a page never breaks on a server that answers something else. */
export function listOf<T>(value: T[] | unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : []
}

const FSI = String.fromCharCode(0x2068)
const PDI = String.fromCharCode(0x2069)

/** A person's text (a title, a sender, a name, a file) put into a sentence, kept apart from it: characters inside it that
 * turn the direction of text cannot spill over the sentence around it (Unicode's first-strong isolate, the text form of
 * `<bdi>`). */
export function iso(text: string): string {
  return FSI + text + PDI
}
