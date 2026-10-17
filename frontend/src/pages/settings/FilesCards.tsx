/**
 * Settings, Backups: the two cards that belong to the backup. "Check files" (every file
 * carries a checksum; once a week and on a click nexpaper looks whether all documents are still there and unchanged)
 * and "Storage" (what the data folder holds, the free room, and a warning when the database lies on a network share).
 * One request fills both; while a check runs, the page asks again every few seconds.
 */
import { AlertTriangle, Check, HardDrive, ShieldCheck } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api } from '../../api/client'
import { ago } from '../../lib/ago'
import { formatBytes } from '../../lib/bytes'
import { Button, Card, Feedback, useAction } from './ui'

type Where = { kind: 'network' | 'local' | 'unknown'; fstype: string; network: boolean }
type Sized = { bytes: number; files: number; complete: boolean }

export type StorageInfo = {
  database: { bytes: number; index_bytes: number | null; where: Where }
  documents: Sized & { originals_bytes: number; where: Where }
  cache: Sized
  exports: Sized
  backups: Sized
  free_bytes: number
  total_bytes: number
  data: { where: Where }
  files: {
    running: boolean
    documents_total: number
    documents_done: number
    last_finished_at: string | null
    last_files: number
    last_documents: number
    last_problems: number
    last_skipped: number
    flagged_documents: number
    every_days: number
  }
}

/** How often the page asks again while a check runs (milliseconds). */
const POLL = 3000

// eslint-disable-next-line react-refresh/only-export-components
export function useStorage() {
  const [info, setInfo] = useState<StorageInfo | null>(null)
  const load = useCallback(() => api<StorageInfo>('/api/v1/storage').then(setInfo, () => undefined), [])
  useEffect(() => {
    void load()
  }, [load])
  const running = info?.files.running ?? false
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => void load(), POLL)
    return () => window.clearInterval(timer)
  }, [running, load])
  return { info, load }
}

export function FilesCards() {
  const storage = useStorage()
  if (!storage.info) return null
  return (
    <>
      <FilesCheckCard info={storage.info} reload={storage.load} />
      <SpaceCard info={storage.info} />
    </>
  )
}

function FilesCheckCard({ info, reload }: { info: StorageInfo; reload: () => Promise<unknown> }) {
  const { t, i18n } = useTranslation()
  const action = useAction()
  const files = info.files
  const last = files.last_finished_at
  const number = (value: number) => new Intl.NumberFormat(i18n.language).format(value)
  const badge = 'inline-flex items-center gap-2 rounded-full px-3 py-1 font-semibold'
  return (
    <Card id="files-check" icon={ShieldCheck} title={t('filesCheck.title')} text={t('filesCheck.text')}>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        {files.running ? (
          <span className={`${badge} bg-sheet-2 text-ink-2`} data-testid="check-running" role="status">
            {t('filesCheck.running', { done: number(files.documents_done), total: number(files.documents_total) })}
          </span>
        ) : last === null ? (
          <span className="text-muted">{t('filesCheck.never')}</span>
        ) : files.flagged_documents > 0 ? (
          <span className={`${badge} bg-bad/10 text-bad`} data-testid="check-problems">
            <AlertTriangle size={14} aria-hidden /> {t('filesCheck.problems', { count: files.flagged_documents, n: number(files.flagged_documents) })}
          </span>
        ) : (
          <span className={`${badge} bg-ok-soft text-ok`} data-testid="check-fine">
            <Check size={14} aria-hidden /> {t('filesCheck.allFine', { count: files.last_files, n: number(files.last_files) })}
          </span>
        )}
        {last !== null && !files.running && <span className="text-xs text-muted">{t('filesCheck.last', { when: ago(last, i18n.language, t('me.justNow')) })}</span>}
        <Button
          busy={action.busy}
          disabled={files.running}
          onClick={() =>
            void action.run(async () => {
              await api('/api/v1/storage/files/check', { method: 'POST' })
              await reload()
            }, t('filesCheck.started'))
          }
        >
          {t('filesCheck.now')}
        </Button>
      </div>
      {files.last_skipped > 0 && !files.running && <p className="text-xs text-muted">{t('filesCheck.skipped', { count: files.last_skipped })}</p>}
      <p className="text-xs text-muted">{t('filesCheck.note')}</p>
      <Feedback problem={action.problem} done={action.done} />
    </Card>
  )
}

function SpaceCard({ info }: { info: StorageInfo }) {
  const { t, i18n } = useTranslation()
  const size = (bytes: number) => formatBytes(bytes, i18n.language, 1000)
  const where = info.database.where
  const partial = !info.documents.complete || !info.cache.complete || !info.exports.complete || !info.backups.complete
  const tiles: [string, string, string | null][] = [
    [size(info.documents.bytes), t('space.documents'), info.documents.originals_bytes > 0 ? t('space.originals', { size: size(info.documents.originals_bytes) }) : null],
    [size(info.database.bytes), t('space.database'), info.database.index_bytes ? t('space.index', { size: size(info.database.index_bytes) }) : null],
    [size(info.cache.bytes), t('space.cache'), null],
    [size(info.exports.bytes), t('space.exports'), null],
    [size(info.backups.bytes), t('space.backups'), null],
    [size(info.free_bytes), t('space.free'), info.total_bytes > 0 ? t('space.of', { size: size(info.total_bytes) }) : null],
  ]
  return (
    <Card id="space" icon={HardDrive} title={t('space.title')} text={t('space.text')}>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {tiles.map(([value, label, note]) => (
          <div key={label} className="rounded-xl bg-sheet-2 px-4 py-3">
            <p className="font-display text-xl font-semibold">{value}</p>
            <p className="text-xs text-muted">{label}</p>
            {note && <p className="text-xs text-muted">{note}</p>}
          </div>
        ))}
      </div>
      {partial && <p className="text-xs text-muted">{t('space.partial')}</p>}
      <div
        className={`flex items-start gap-3 rounded-xl border px-4 py-3 text-sm ${where.network ? 'border-bad/40 bg-bad/10' : where.kind === 'local' ? 'border-ok/40 bg-ok-soft' : 'border-warn/40 bg-warn-soft'}`}
        role={where.network ? 'alert' : undefined}
        data-testid={`database-${where.kind}`}
      >
        {where.kind === 'local' ? <Check size={16} className="mt-0.5 shrink-0 text-ok" aria-hidden /> : <AlertTriangle size={16} className={`mt-0.5 shrink-0 ${where.network ? 'text-bad' : 'text-warn'}`} aria-hidden />}
        <span>
          <span className="font-semibold">{t(`space.${where.kind}.title`, { type: where.fstype })}</span>
          <span className="block text-xs text-ink-2">{t(`space.${where.kind}.text`)}</span>
        </span>
      </div>
      {info.documents.where.network && <p className="text-xs text-muted">{t('space.documentsOnShare')}</p>}
    </Card>
  )
}
