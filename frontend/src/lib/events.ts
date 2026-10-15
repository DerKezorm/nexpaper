/**
 * The history of a document in words. The server names each line with an English action and numbers or field names in
 * `detail`, never contents (`services/changes.py`); here they become a sentence in the language of the page: who did it
 * (a person, somebody through a link, or nexpaper itself) and what. An action this page does not know yet is still a
 * line ("changed something"), never a raw code.
 */
import type { TFunction } from 'i18next'

import type { DocumentEvent, Person } from '../api/client'
import i18n from '../i18n'
import { shortDate } from './dates'
import { personName } from './people'
import { iso } from './say'

export type EventContext = {
  /** The people of the server, to name whom a document was shared with. */
  people: Map<number, Person>
  /** The vaults the reader sees, by id, with the name to show. */
  vaults: Map<number, string>
  /** "Aus dem Postfach" and so on. */
  sourceText: (source: string) => string
}

function list(t: TFunction, names: string[]): string {
  const words = names.map((name) => t(`docs.events.field.${name}`, { defaultValue: name }))
  if (words.length < 2) return words.join('')
  return t('docs.events.and', { first: words.slice(0, -1).join(', '), last: words[words.length - 1] })
}

/** A line that is a sentence of its own, without a name in front (what happened to the document by itself). */
export function standsAlone(event: DocumentEvent): boolean {
  return event.action === 'taken_over' || (event.action === 'link_revoked' && event.detail?.reason === 'account_deleted')
}

/** Who did it: the person, somebody through the link made for whom, or nexpaper (reading, a deleted account). */
export function eventWho(event: DocumentEvent, t: TFunction): string {
  if (event.by) return iso(personName(event.by))
  if (event.by_link) return t('docs.events.byLink', { recipient: iso(event.by_link) })
  return 'nexpaper'
}

/** What was done, after the name. */
export function eventWhat(event: DocumentEvent, t: TFunction, context: EventContext): string {
  const detail = event.detail ?? {}
  const number = (key: string) => (typeof detail[key] === 'number' ? (detail[key] as number) : null)
  const someone = (key: string) => {
    const id = number(key)
    const found = id !== null ? context.people.get(id) : undefined
    return found ? personName(found) : t('docs.events.somebody')
  }
  const vault = (key: string) => {
    const id = number(key)
    return (id !== null && context.vaults.get(id)) || t('docs.events.otherVault')
  }
  switch (event.action) {
    case 'created':
      {
      if (typeof detail.split_from === 'number') return t('pagetools.events.createdBySplit')
      if (typeof detail.from_archive === 'string') {
        const what = detail.from_archive === 'other' ? t('docs.events.otherFile') : `.${detail.from_archive}`
        return t('docs.events.createdFromArchive', { what })
      }
      if (detail.original_missing === true) return t('docs.events.createdOriginalMissing')
      const source = context.sourceText(String(detail.source ?? 'upload'))
      return t('docs.events.created', { source: source.charAt(0).toLocaleLowerCase() + source.slice(1) })
    }
    case 'changed': {
      const fields = Array.isArray(detail.fields) ? detail.fields.filter((f): f is string => typeof f === 'string') : []
      if (detail.by === 'catalog') return t('docs.events.catalog', { fields: list(t, fields) })
      const rest = fields.filter((f) => f !== 'status')
      if (fields.includes('status')) {
        const moved = detail.status === 'inbox' ? t('docs.events.toInbox') : t('docs.events.filed')
        return rest.length ? `${moved} ${t('docs.events.andChanged', { fields: list(t, rest) })}` : moved
      }
      return rest.length ? t('docs.events.changed', { fields: list(t, rest) }) : t('docs.events.something')
    }
    case 'moved':
      return detail.by === 'rule' ? t('sorting.events.movedByRule', { from: vault('from'), to: vault('to') }) : t('docs.events.moved', { from: vault('from'), to: vault('to') })
    case 'taken_over':
      return t('history.taken_over', { account: String(detail.account ?? '') })
    case 'shared':
      return t('docs.events.shared', { person: someone('to'), right: t(`rights.${String(detail.right ?? 'read')}.name`) })
    case 'share_changed':
      return t('docs.events.shareChanged', { person: someone('to'), right: t(`rights.${String(detail.right ?? 'read')}.name`) })
    case 'unshared':
      return t('docs.events.unshared', { person: someone('to') })
    case 'link_created':
      return t('docs.events.linkCreated', { count: number('days') ?? 0 })
    case 'link_opened':
      return t('docs.events.linkOpened')
    case 'link_revoked':
      return detail.reason === 'account_deleted' ? t('docs.events.linkEnded') : t('docs.events.linkRevoked')
    case 'link_copied':
      return t('docs.events.linkCopied')
    case 'trashed':
      return t('docs.events.trashed')
    case 'auto_trashed':
      // nexpaper itself put it there: its keeping time was over (D4, a kind with "expired ones into the trash by themselves").
      return typeof detail.keep_until === 'string' ? t('docs.events.autoTrashed', { date: shortDate(detail.keep_until, i18n.language) }) : t('docs.events.something')
    case 'restored':
      return t('docs.events.restored')
    case 'note_added':
      return t('docs.events.noteAdded')
    case 'note_changed':
      return t('docs.events.noteChanged')
    case 'note_deleted':
      return t('docs.events.noteDeleted')
    case 'processed': {
      const pages = number('pages') ?? 0
      const ocr = number('ocr_pages') ?? 0
      const said = t('docs.events.processed', { count: pages })
      if (detail.error) return `${said} ${t('docs.events.processedNoText')}`
      return ocr > 0 ? `${said} ${t('docs.events.recognised', { count: ocr })}` : said
    }
    case 'process_failed':
      return t('docs.events.processFailed', { reason: t(`docs.inbox.error.${String(detail.error ?? 'failed')}`, { defaultValue: t('docs.inbox.error.failed') }) })
    case 'retried':
      return t('docs.events.retried')
    case 'text_read':
      return t('docs.events.textRead')
    case 'proposed': {
      // B6: which fields nexpaper filled in when the document came (rules, the e-invoice, the text, the AI); a move to
      // another vault has a line of its own.
      const fields = Array.isArray(detail.fields) ? detail.fields.filter((f): f is string => typeof f === 'string' && f !== 'vault') : []
      return fields.length ? t('sorting.events.proposed', { fields: list(t, fields) }) : t('docs.events.something')
    }
    case 'pages_edited':
      return t('pagetools.events.pagesEdited', { version: number('version') ?? '' })
    case 'merged':
      return t('pagetools.events.merged', { count: Array.isArray(detail.from) ? detail.from.length : 1, version: number('version') ?? '' })
    case 'merged_into':
      return t('pagetools.events.mergedInto')
    case 'split':
      return t('pagetools.events.split', { count: number('parts') ?? 2 })
    case 'split_kept':
      return t('pagetools.events.splitKept')
    case 'version_uploaded':
      return t('pagetools.events.versionUploaded', { version: number('version') ?? '' })
    case 'version_added':
      return t('pagetools.events.versionAdded', { version: number('version') ?? '' })
    case 'version_failed':
      return t('pagetools.events.versionFailed', { version: number('version') ?? '' })
    case 'version_restored':
      return t('pagetools.events.versionRestored', { version: number('version') ?? '', from: number('from') ?? '' })
    case 'files_missing':
      return t('docs.events.filesMissing')
    case 'files_changed':
      return t('docs.events.filesChanged')
    case 'files_whole':
      return t('docs.events.filesWhole')
    case 'version_discarded':
      return t('pagetools.events.versionDiscarded', { version: number('version') ?? '' })
    // Deadlines (F1): done for everybody, open again, and a contract that renewed by itself.
    case 'deadline_done':
      return t(`deadlines.events.done.${['due', 'contract_end', 'warranty_end'].includes(String(detail.kind)) ? String(detail.kind) : 'due'}`)
    case 'deadline_reopened':
      return t('deadlines.events.reopened')
    case 'renewed':
      return typeof detail.to === 'string' ? t('deadlines.events.renewed', { date: shortDate(detail.to, i18n.language) }) : t('docs.events.something')
    default:
      return t('docs.events.something')
  }
}
