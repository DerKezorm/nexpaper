/**
 * Server › Storage and backups (plan "Einstellungen", Speicher und Sicherung): the cards "Speicher" and "Sicherung" of
 * the shared module sicherung (`vendor/nexsicherung`, 1.0.1) over its routes (`/api/v1/server/storage`), then
 * nexpaper's own: how the files lie on the disk, and the check of the files. nexpaper hands the module its sentence of
 * what a backup holds (the database and the server's key, never the documents), its words for its own parts of the
 * storage (the originals among the documents, the page pictures), the counts of an entry and what a restore would do
 * to the documents. The old routes (`/api/v1/backups`, `/api/v1/storage`) stay for scripts; the check of the files
 * keeps its own.
 */
import { useTranslation } from 'react-i18next'

import { tabId } from '../../api/client'
import i18n from '../../i18n'
import { useAuth } from '../../state/auth'
import { StorageArea as SharedStorageArea } from '../../vendor/nexsicherung/StorageArea'
import { makeSicherungApi, type Brief, type Entry } from '../../vendor/nexsicherung/sicherung'
import { languageOf } from '../../vendor/nexui'
import { FilesCheckCard, useStorage } from './FilesCards'
import { DiskCard } from './StorageCards'

/** nexpaper's own client for the module: every request names its tab and its language, as `api` does. */
const api = makeSicherungApi((path, init) => {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  headers.set('X-Nexpaper-Client', tabId())
  if (i18n.language) headers.set('X-Nexpaper-Language', i18n.language)
  return fetch(path, { ...init, headers })
}, '/api/v1/server/storage')

const number = (value: unknown) => (typeof value === 'number' ? value : 0)

export function StorageArea() {
  const { t, i18n: shown } = useTranslation()
  const { me } = useAuth()
  const storage = useStorage()
  const partLabel = (key: string) => (key === 'originals' ? t('space.originalsName') : key === 'pages' ? t('space.cache') : undefined)
  const facts = (entry: Entry) => {
    if (!entry.facts || !('accounts' in entry.facts || 'documents' in entry.facts)) return null
    const accounts = t('server.countAccounts', { count: number(entry.facts.accounts) })
    return number(entry.facts.documents) ? `${accounts}, ${t('server.countDocuments', { count: number(entry.facts.documents) })}` : accounts
  }
  /** What a restore would do, line by line: the documents the backup knows, which files are missing or changed on the
   * disk, which documents of today would go, what comes back, and that the search is built anew. */
  const details = (brief: Brief) => {
    const found = brief.details ?? {}
    const count = (key: string) => number(found[key])
    const lines: string[] = []
    if (count('documents') > 0) {
      lines.push(t('server.restorePreview.documents', { count: count('documents') }))
      if (count('missing_documents') === 0 && count('changed_documents') === 0) lines.push(t('server.restorePreview.allThere'))
      if (count('missing_documents') > 0) lines.push(t('server.restorePreview.missing', { count: count('missing_documents') }))
      if (count('changed_documents') > 0) lines.push(t('server.restorePreview.changed', { count: count('changed_documents') }))
      if (count('not_compared') > 0) lines.push(t('server.restorePreview.notCompared', { count: count('not_compared') }))
    }
    if (count('newer_documents') > 0) lines.push(t('server.restorePreview.newer', { count: count('newer_documents') }))
    if (count('revived_devices')) lines.push(t('server.restorePreview.revivedDevices', { count: count('revived_devices') }))
    if (count('revived_keys')) lines.push(t('server.restorePreview.revivedKeys', { count: count('revived_keys') }))
    if (count('revived_links')) lines.push(t('server.restorePreview.revivedLinks', { count: count('revived_links') }))
    if (count('revived_link_documents')) lines.push(t('linkRelated.revived', { count: count('revived_link_documents') }))
    if (count('revived_pdf_passwords')) lines.push(t('server.restorePreview.revivedPdfPasswords', { count: count('revived_pdf_passwords') }))
    if (count('revived_upload_requests')) lines.push(t('uploadRequest.revived', { count: count('revived_upload_requests') }))
    if (found.rebuilds_index) lines.push(t('server.restorePreview.index'))
    if (lines.length === 0) return null
    return (
      <ul className="m-0 flex list-none flex-col gap-1 p-0 text-xs" data-testid="restore-preview">
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    )
  }
  const language = languageOf(shown.language)
  return (
    <SharedStorageArea
      app="nexpaper"
      things={t('settings.things')}
      holds={t('server.backupHolds')}
      api={api}
      password={me?.sign_in === 'password'}
      partLabel={partLabel}
      facts={facts}
      details={details}
      language={language}
      when={(iso) => new Date(iso).toLocaleString(shown.language, { dateStyle: 'medium', timeStyle: 'short', ...(me?.profile.timezone ? { timeZone: me.profile.timezone } : {}) })}
    >
      <DiskCard info={storage.info} />
      {storage.info && <FilesCheckCard info={storage.info} reload={storage.load} />}
    </SharedStorageArea>
  )
}
