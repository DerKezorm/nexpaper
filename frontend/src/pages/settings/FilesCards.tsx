/**
 * Server › Storage and backups, nexpaper's own card after the module's: "Dateien prüfen" (every file carries a checksum;
 * once a week and on a click nexpaper looks whether all documents are still there and unchanged). While a check runs,
 * the page asks again every few seconds. What nexpaper takes on its disk is the module's card "Speicher" now.
 */
import { ShieldCheck } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api } from '../../api/client'
import { ago } from '../../lib/ago'
import { Badge, Button, Card } from '../../vendor/nexui'
import { useAction } from './actions'
import { Outcome } from './Outcome'

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

/** "Dateien prüfen" on its own, loading what it shows itself. */
export function FilesCards() {
  const storage = useStorage()
  if (!storage.info) return null
  return <FilesCheckCard info={storage.info} reload={storage.load} />
}

export function FilesCheckCard({ info, reload }: { info: StorageInfo; reload: () => Promise<unknown> }) {
  const { t, i18n } = useTranslation()
  const action = useAction()
  const files = info.files
  const last = files.last_finished_at
  const number = (value: number) => new Intl.NumberFormat(i18n.language).format(value)
  return (
    <Card id="files-check" icon={ShieldCheck} title={t('filesCheck.title')} subtitle={t('filesCheck.text')}>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        {files.running ? (
          <span role="status">
            <Badge tone="off" testId="check-running">
              {t('filesCheck.running', { done: number(files.documents_done), total: number(files.documents_total) })}
            </Badge>
          </span>
        ) : last === null ? (
          <span className="text-[var(--nexui-text-muted)]">{t('filesCheck.never')}</span>
        ) : files.flagged_documents > 0 ? (
          <Badge tone="danger" testId="check-problems">
            {t('filesCheck.problems', { count: files.flagged_documents, n: number(files.flagged_documents) })}
          </Badge>
        ) : (
          <Badge tone="on" testId="check-fine">
            {t('filesCheck.allFine', { count: files.last_files, n: number(files.last_files) })}
          </Badge>
        )}
        {last !== null && !files.running && <span className="text-xs text-[var(--nexui-text-muted)]">{t('filesCheck.last', { when: ago(last, i18n.language, t('me.justNow')) })}</span>}
      </div>
      <div>
        <Button
          kind="secondary"
          icon="ShieldCheck"
          busy={action.busy}
          disabled={files.running}
          testId="files-check-now"
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
      {files.last_skipped > 0 && !files.running && <p className="m-0 text-xs text-[var(--nexui-text-muted)]">{t('filesCheck.skipped', { count: files.last_skipped })}</p>}
      <p className="m-0 text-xs text-[var(--nexui-text-muted)]">{t('filesCheck.note')}</p>
      <Outcome problem={action.problem} done={action.done} />
    </Card>
  )
}
