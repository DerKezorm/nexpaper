/**
 * What the upload is made of on screen: the button of the menu, the sheet that says "drop it" while files are dragged
 * over the page (the mock's wording), the list of uploads with their progress and what came of each, and the sentence
 * after a run. The queue itself is `lib/uploader.ts`.
 */
import { AlertTriangle, Camera, Check, Copy, FileText, Loader2, Pause, Upload, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { vaultsApi, type Vault } from '../api/client'
import { errorText } from '../lib/errors'
import { canRetry, type Entry, type Summary } from '../lib/uploader'
import { failureLines, summaryText } from '../lib/uploadText'
import { useAuth } from '../state/auth'
import { useUploads } from '../state/uploads'

/** The big button in the menu: opens the dialog that chooses files. */
export function UploadButton() {
  const { t } = useTranslation()
  const { pick } = useUploads()
  return (
    <button type="button" onClick={pick} className="flex h-11 w-full items-center justify-center gap-2 rounded-full bg-accent font-semibold text-accent-ink shadow-soft hover:brightness-105">
      <Upload size={17} aria-hidden /> {t('upload.button')}
    </button>
  )
}

/** Below it on the computer, as the mock: the camera (a laptop has one too). */
export function CameraLink() {
  const { t } = useTranslation()
  return (
    <Link to="/kamera" className="mt-2 flex h-9 w-full items-center justify-center gap-2 rounded-full text-sm font-semibold text-ink-2 hover:bg-sheet-2">
      <Camera size={16} aria-hidden /> {t('phone.quick.photo')}
    </Link>
  )
}

/** The round button in the phone's header: the quick upload, with the camera and the file choice. */
export function UploadRound() {
  const { t } = useTranslation()
  return (
    <Link to="/schnell" className="rounded-full bg-accent p-2 text-accent-ink" aria-label={t('upload.button')}>
      <Upload size={18} aria-hidden />
    </Link>
  )
}

/** Shown while files are dragged over the page. */
export function DropSheet() {
  const { t } = useTranslation()
  const { dragging } = useUploads()
  if (!dragging) return null
  return (
    <div data-testid="drop-sheet" className="pointer-events-none fixed inset-3 z-[60] flex items-center justify-center rounded-3xl border-4 border-dashed border-accent bg-paper/85">
      <div className="text-center">
        <Upload size={40} className="mx-auto text-accent" aria-hidden />
        <p className="mt-3 font-display text-2xl font-semibold">{t('upload.dropTitle')}</p>
        <p className="text-sm text-ink-2">{t('upload.dropText')}</p>
      </div>
    </div>
  )
}

function percent(entry: Entry): number {
  return entry.size > 0 ? Math.min(100, Math.floor((entry.sent / entry.size) * 100)) : 0
}

const ACTIVE = ['waiting', 'hashing', 'sending', 'finishing']

/** The names of the vaults, as the Vaults page shows them ("My vault" for the own one), fetched once when the first file
 * is taken; `label(id)` is null until they are known. */
function useVaultLabels(entries: readonly Entry[]): (id: number | null) => string | null {
  const { t } = useTranslation()
  const { me } = useAuth()
  const [vaults, setVaults] = useState<Vault[] | null>(null)
  const needed = entries.some((entry) => entry.vaultId !== null)
  const known = vaults !== null
  useEffect(() => {
    if (needed && !known) vaultsApi.list().then(setVaults, () => setVaults([]))
  }, [needed, known])
  return (id) => {
    const vault = id === null ? undefined : vaults?.find((v) => v.id === id)
    if (!vault) return null
    return me && vault.personal_of === me.id ? t('vaults.mine') : vault.name
  }
}

function statusText(entry: Entry, t: (key: string, values?: Record<string, unknown>) => string, vault: string | null): string {
  switch (entry.phase) {
    case 'hashing':
      return t('upload.status.hashing', { percent: percent(entry) })
    case 'sending':
      return entry.chunked ? t('upload.status.sendingPercent', { percent: percent(entry) }) : t('upload.status.sending')
    case 'done':
      if (entry.duplicate?.kind === 'same') return t('upload.status.doneSame', { title: entry.duplicate.title })
      if (entry.duplicate) return t('upload.status.doneSimilar', { title: entry.duplicate.title })
      return vault ? t('upload.status.doneIn', { vault }) : t('upload.status.done')
    case 'exists':
      return t('upload.status.exists', { title: entry.document?.title ?? '' })
    case 'paused':
      return t('upload.status.paused', { percent: percent(entry) })
    case 'failed':
      return errorText(entry.error?.code ?? 'upload_failed', entry.error?.values)
    default:
      return t(`upload.status.${entry.phase}`)
  }
}

function Row({ entry, vault }: { entry: Entry; vault: string | null }) {
  const { t } = useTranslation()
  const { cancel, resume, retry } = useUploads()
  const running = entry.phase === 'hashing' || entry.phase === 'sending'
  const Icon = entry.phase === 'done' || entry.phase === 'exists' ? (entry.duplicate ? Copy : Check) : entry.phase === 'failed' ? AlertTriangle : entry.phase === 'paused' ? Pause : running || entry.phase === 'finishing' ? Loader2 : FileText
  const tone = entry.phase === 'failed' ? 'text-bad' : entry.phase === 'done' || entry.phase === 'exists' ? (entry.duplicate ? 'text-warn' : 'text-ok') : 'text-muted'
  const link = 'rounded-full border border-line px-3 py-1 text-xs font-semibold text-ink-2 hover:bg-sheet-2'
  return (
    <li data-phase={entry.phase} className="flex items-start gap-3 px-4 py-3">
      <Icon size={18} aria-hidden className={`mt-0.5 shrink-0 ${tone} ${running ? 'animate-spin' : ''}`} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold" title={entry.name}>{entry.name}</p>
        <p className={`text-xs ${entry.phase === 'failed' ? 'text-bad' : 'text-ink-2'}`}>{statusText(entry, t, vault)}</p>
        {running && entry.chunked && (
          <div role="progressbar" aria-label={entry.name} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent(entry)} className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-line">
            <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${percent(entry)}%` }} />
          </div>
        )}
        <div className="mt-1.5 flex flex-wrap gap-2 empty:hidden">
          {entry.phase === 'paused' && (
            <button type="button" className={link} onClick={() => resume(entry.id)}>
              {t('upload.resume')}
            </button>
          )}
          {entry.phase === 'failed' && canRetry(entry.error?.code ?? '') && (
            <button type="button" className={link} onClick={() => retry(entry.id)}>
              {t('upload.retry')}
            </button>
          )}
          {['waiting', 'hashing', 'sending', 'paused'].includes(entry.phase) && (
            <button type="button" className={link} onClick={() => cancel(entry.id)}>
              {t('upload.cancel')}
            </button>
          )}
        </div>
      </div>
    </li>
  )
}

/** The notice after a run of the queue. When all went well, one sentence. When files were not taken, each one is named
 * with its reason, here, and the notice stays until it is closed (the list of uploads may be out of sight). */
export function UploadNotice({ lead, summary, onClose }: { lead: string; summary: Summary; onClose: () => void }) {
  const { t } = useTranslation()
  if (summary.failed === 0) {
    if (!lead) return null
    return (
      <div role="status" className="rise fixed inset-x-0 bottom-24 z-50 flex justify-center px-4 lg:bottom-8">
        <p className="max-w-lg rounded-full bg-ink px-5 py-2.5 text-center text-sm font-semibold text-paper shadow-soft">{lead}</p>
      </div>
    )
  }
  const { head, lines, more } = failureLines(summary, t)
  return (
    <div role="alert" data-testid="upload-failures" className="rise fixed inset-x-0 bottom-24 z-50 flex justify-center px-4 lg:bottom-8">
      <div className="relative w-full max-w-lg rounded-2xl bg-ink px-5 py-3.5 text-paper shadow-soft">
        {lead && <p className="pr-8 text-sm font-semibold">{lead}</p>}
        <p className={`pr-8 text-sm font-semibold ${lead ? 'mt-2' : ''}`}>{head}</p>
        <ul className="mt-2 max-h-[40vh] space-y-2 overflow-y-auto text-sm">
          {lines.map((line, index) => (
            <li key={index}>
              <span className="block break-words font-semibold">{line.name}</span>
              <span className="block opacity-80">{line.reason}</span>
            </li>
          ))}
        </ul>
        {more && <p className="mt-2 text-sm opacity-80">{more}</p>}
        <button type="button" onClick={onClose} aria-label={t('upload.toast.close')} title={t('upload.toast.close')} className="absolute right-2.5 top-2.5 rounded-full p-1.5 hover:bg-white/10">
          <X size={16} aria-hidden />
        </button>
      </div>
    </div>
  )
}

export function UploadPanel() {
  const { t } = useTranslation()
  const { entries, clear, summary, dismissSummary } = useUploads()
  const label = useVaultLabels(entries)
  const only = summary && summary.vaults.length > 0 && summary.vaults.every((id) => id === summary.vaults[0]) ? label(summary.vaults[0]) : null
  useEffect(() => {
    // A notice about files that were not taken stays until it is closed: the reason is what the person is to read.
    if (!summary || summary.failed > 0) return
    const timer = window.setTimeout(dismissSummary, 6000)
    return () => window.clearTimeout(timer)
  }, [summary, dismissSummary])
  const finished = entries.some((entry) => !ACTIVE.includes(entry.phase) && entry.phase !== 'paused')
  return (
    <>
      {entries.length > 0 && (
        <section aria-label={t('upload.panelTitle')} className="fixed right-4 bottom-52 z-40 w-[min(24rem,calc(100vw-2rem))] overflow-hidden rounded-2xl border border-line bg-sheet shadow-soft lg:bottom-6 lg:right-6">
          <header className="flex items-center justify-between border-b border-line px-4 py-2.5">
            <h2 className="font-display text-base font-semibold">{t('upload.panelTitle')}</h2>
            {finished && (
              <button type="button" onClick={clear} aria-label={t('upload.panelClear')} title={t('upload.panelClear')} className="rounded-full p-1.5 text-muted hover:bg-sheet-2 hover:text-ink">
                <X size={16} aria-hidden />
              </button>
            )}
          </header>
          <ul className="max-h-72 divide-y divide-line overflow-y-auto">
            {entries.map((entry) => (
              <Row key={entry.id} entry={entry} vault={label(entry.vaultId)} />
            ))}
          </ul>
        </section>
      )}
      {summary && <UploadNotice lead={summaryText(summary, t, only)} summary={summary} onClose={dismissSummary} />}
    </>
  )
}
