/**
 * The phone's start, as the mock: nothing but the two ways in (camera, file) and what happened to the last uploads.
 * "Alles" leads into the full app. Large targets, one thumb. Where the files go is the person's choice (only vaults they
 * may add to); choosing here keeps it with the account. `/teilen` is the same page with what another app shared on top
 * (Android's share menu): it goes up only when the person says so (`lib/shared.ts`).
 */
import { ArrowRight, Camera, ChevronDown, FileUp, Images, Inbox, Loader2, Share2, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { authApi, phoneApi, type DocumentInfo, type Quick } from '../api/client'
import { LogoMark } from '../components/Logo'
import { UploadNotice } from '../components/UploadPanel'
import { ago } from '../lib/ago'
import { formatBytes } from '../lib/bytes'
import { errorText } from '../lib/errors'
import { dropShared, sharedFiles } from '../lib/shared'
import { canRetry, type Entry, type Summary } from '../lib/uploader'
import { useAuth } from '../state/auth'
import { ACCEPT, ACCEPT_PHOTOS } from '../lib/formats'
import { useUploads } from '../state/uploads'

const ACTIVE: Entry['phase'][] = ['waiting', 'hashing', 'sending', 'finishing', 'paused', 'failed']
/** While something is being read, the page asks again this often. */
const POLL_MS = 4000

export function QuickPage({ shared = false }: { shared?: boolean }) {
  const { t, i18n } = useTranslation()
  const { me, setMe } = useAuth()
  const uploads = useUploads()
  const [params, setParams] = useSearchParams()
  const file = useRef<HTMLInputElement>(null)
  const photos = useRef<HTMLInputElement>(null)
  const [quick, setQuick] = useState<Quick | null>(null)
  const [pick, setPick] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const [toast, setToast] = useState<string | null>(null)
  // Files that were not taken, with their reasons, until the person closes the notice.
  const [refused, setRefused] = useState<Summary | null>(null)
  const [offered, setOffered] = useState<File[] | null>(null)
  const shareId = shared ? (params.get('share') ?? '') : ''
  const missed = shared && params.get('missed') === '1'

  // A word handed over by the page before (the camera: "3 Seiten als ein Dokument hochgeladen."), shown once.
  const notice = (location.state as { notice?: unknown } | null)?.notice
  useEffect(() => {
    if (typeof notice !== 'string') return
    setToast(notice)
    navigate(location.pathname + location.search, { replace: true, state: null })
  }, [notice, navigate, location.pathname, location.search])

  const load = useCallback(() => phoneApi.quick().then(setQuick, () => undefined), [])
  useEffect(() => {
    void load()
  }, [load])

  // What another app shared: read from the cache of the service worker, shown, and uploaded only on a tap. Leaving the
  // page without that throws the files away (also when the tab closes).
  useEffect(() => {
    if (!shareId) return
    let alive = true
    void sharedFiles(shareId).then((files) => alive && setOffered(files))
    const drop = () => void dropShared(shareId)
    window.addEventListener('pagehide', drop)
    return () => {
      alive = false
      window.removeEventListener('pagehide', drop)
      drop()
    }
  }, [shareId])

  // When the queue is through: the list anew, and a word about it.
  const { summary, dismissSummary } = uploads
  useEffect(() => {
    if (!summary) return
    dismissSummary()
    void load()
    if (summary.done > 0) setToast(summary.done === 1 ? t('phone.quick.done') : t('phone.quick.doneMany', { count: summary.done }))
    if (summary.failed > 0) setRefused(summary)
  }, [summary, dismissSummary, load, t])
  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 3500)
    return () => window.clearTimeout(timer)
  }, [toast])

  // While a document is still being read, it changes by itself.
  const reading = quick?.recent.some((doc) => doc.status === 'processing') ?? false
  useEffect(() => {
    if (!reading) return
    const timer = window.setInterval(() => void load(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [reading, load])

  const target = quick?.vaults.find((vault) => vault.id === quick.target_vault_id) ?? null
  const label = (vault: { name: string; mine: boolean }) => (vault.mine ? t('phone.quick.mine') : vault.name)
  const take = (files: FileList | null, input: HTMLInputElement | null) => {
    const chosen = Array.from(files ?? [])
    if (input) input.value = ''
    if (chosen.length) uploads.add(chosen, { vaultId: quick?.target_vault_id ?? null })
  }
  const choose = (vaultId: number) => {
    setPick(false)
    if (!quick || vaultId === quick.target_vault_id) return
    setQuick({ ...quick, target_vault_id: vaultId })
    void authApi.preferences({ default_vault: vaultId }).then(
      (profile) => me && setMe({ ...me, profile }),
      () => void load(),
    )
  }
  const sendShared = () => {
    if (!offered?.length) return
    uploads.add(offered, { vaultId: quick?.target_vault_id ?? null, source: 'share' })
    setToast(offered.length === 1 ? t('phone.share.one') : t('phone.share.many', { count: offered.length }))
    setOffered(null)
    // The files are in the queue now; leaving the share (the address changes) throws the cached copies away.
    setParams({}, { replace: true })
  }
  const discardShared = () => {
    setOffered(null)
    setParams({}, { replace: true })
  }

  const busy = uploads.entries.filter((entry) => ACTIVE.includes(entry.phase))
  const percent = (entry: Entry) => (entry.size > 0 ? Math.min(100, Math.floor((entry.sent / entry.size) * 100)) : 0)

  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col px-4 pt-[max(1rem,env(safe-area-inset-top))] pb-[max(1.5rem,env(safe-area-inset-bottom))]">
      <header className="flex items-center justify-between">
        <span className="flex items-center gap-2">
          <LogoMark size={30} />
          <span className="font-extrabold tracking-tight">
            NEX<span className="text-accent">PAPER</span>
          </span>
        </span>
        <Link to="/" className="inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-sm font-semibold text-ink-2 hover:bg-sheet-2">
          {t('phone.quick.all')} <ArrowRight size={15} aria-hidden />
        </Link>
      </header>

      {missed && (
        <p role="status" className="mt-4 rounded-2xl border border-warn/40 bg-warn-soft px-4 py-3 text-sm text-ink" data-testid="share-missed">
          {t('phone.share.missed')}
        </p>
      )}

      {offered && (
        <section aria-label={t('phone.share.title')} className="card mt-4 p-4" data-testid="shared">
          <h2 className="flex items-center gap-2 font-semibold">
            <Share2 size={17} className="text-accent" aria-hidden /> {t('phone.share.title')}
          </h2>
          {offered.length === 0 ? (
            <p className="mt-2 text-sm text-ink-2">{t('phone.share.gone')}</p>
          ) : (
            <ul className="mt-2 space-y-1 text-sm">
              {offered.map((item, index) => (
                <li key={index} className="flex justify-between gap-3">
                  <span className="min-w-0 truncate">{item.name}</span>
                  <span className="shrink-0 text-xs text-muted">{formatBytes(item.size, i18n.language, 1000)}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-3 flex gap-2">
            {offered.length > 0 && (
              <button type="button" onClick={sendShared} className="h-10 flex-1 rounded-full bg-accent px-4 text-sm font-semibold text-accent-ink">
                {t('phone.share.upload')}
              </button>
            )}
            <button type="button" onClick={discardShared} className="h-10 rounded-full border border-line px-4 text-sm font-semibold text-ink-2">
              {t('phone.share.discard')}
            </button>
          </div>
        </section>
      )}

      <div className="mt-6 space-y-3">
        <Link to="/kamera" className="flex items-center gap-4 rounded-3xl bg-accent p-5 text-accent-ink shadow-soft active:scale-[0.99]">
          <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white/15">
            <Camera size={28} aria-hidden />
          </span>
          <span>
            <span className="block font-display text-xl font-semibold">{t('phone.quick.photo')}</span>
            <span className="text-sm opacity-85">{t('phone.quick.photoText')}</span>
          </span>
        </Link>
        <div className="grid grid-cols-2 gap-3">
          <button type="button" onClick={() => file.current?.click()} className="card flex flex-col items-start gap-2 p-4 text-left active:scale-[0.99]">
            <FileUp size={22} className="text-accent" aria-hidden />
            <span className="font-semibold">{t('phone.quick.file')}</span>
            <span className="text-xs text-muted">{t('phone.quick.fileText')}</span>
          </button>
          <button type="button" onClick={() => photos.current?.click()} className="card flex flex-col items-start gap-2 p-4 text-left active:scale-[0.99]">
            <Images size={22} className="text-accent" aria-hidden />
            <span className="font-semibold">{t('phone.quick.photos')}</span>
            <span className="text-xs text-muted">{t('phone.quick.photosText')}</span>
          </button>
        </div>
        <input ref={file} type="file" multiple accept={ACCEPT} className="hidden" data-testid="quick-file" tabIndex={-1} aria-hidden onChange={(event) => take(event.target.files, event.target)} />
        <input ref={photos} type="file" multiple accept={ACCEPT_PHOTOS} className="hidden" data-testid="quick-photos" tabIndex={-1} aria-hidden onChange={(event) => take(event.target.files, event.target)} />

        {target && quick && (
          <div className="relative">
            <button type="button" onClick={() => setPick(!pick)} aria-expanded={pick} aria-label={t('phone.quick.choose')} className="flex w-full items-center justify-center gap-1.5 py-2 text-sm text-ink-2">
              {t('phone.quick.landsIn')} <span className="font-semibold text-ink">{label(target)}</span> <ChevronDown size={15} aria-hidden />
            </button>
            {pick && (
              <div className="card rise absolute inset-x-6 top-full z-20 p-1.5" role="menu">
                {quick.vaults.map((vault) => (
                  <button
                    key={vault.id}
                    type="button"
                    role="menuitemradio"
                    aria-checked={vault.id === target.id}
                    onClick={() => choose(vault.id)}
                    className={`block w-full rounded-lg px-3 py-2 text-left text-sm font-semibold ${vault.id === target.id ? 'bg-accent-soft text-accent' : 'hover:bg-sheet-2'}`}
                  >
                    {label(vault)}
                  </button>
                ))}
                <p className="px-3 pt-1 pb-2 text-xs text-muted">{t('phone.quick.rulesHint')}</p>
              </div>
            )}
          </div>
        )}
      </div>

      <section className="mt-6">
        <h2 className="mb-2 px-1 text-xs font-bold tracking-wide text-muted uppercase">{t('phone.quick.recent')}</h2>
        <ul className="space-y-2" data-testid="quick-recent">
          {busy.map((entry) => (
            <li key={`u${entry.id}`} className="flex items-center gap-3 rounded-2xl border border-line bg-sheet p-2.5" data-phase={entry.phase}>
              <div className="shimmer aspect-[210/297] w-9 shrink-0 rounded-[3px]" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold">{entry.name}</span>
                <span className={`text-xs ${entry.phase === 'failed' ? 'text-bad' : 'text-muted'}`}>
                  {entry.phase === 'failed'
                    ? errorText(entry.error?.code ?? 'upload_failed', entry.error?.values)
                    : entry.chunked
                      ? t('phone.quick.uploadingPercent', { percent: percent(entry) })
                      : t('phone.quick.uploading')}
                </span>
              </span>
              {entry.phase === 'failed' ? (
                <span className="flex gap-1">
                  {canRetry(entry.error?.code ?? '') && (
                    <button type="button" onClick={() => uploads.retry(entry.id)} className="rounded-full border border-line px-2.5 py-1 text-xs font-semibold text-ink-2">
                      {t('phone.quick.retry')}
                    </button>
                  )}
                  <button type="button" onClick={() => uploads.cancel(entry.id)} aria-label={t('upload.cancel')} className="rounded-full p-1 text-muted">
                    <X size={15} aria-hidden />
                  </button>
                </span>
              ) : (
                <Loader2 size={16} className="animate-spin text-accent" aria-hidden />
              )}
            </li>
          ))}
          {quick?.recent.map((doc) => <Recent key={doc.id} doc={doc} justNow={t('me.justNow')} language={i18n.language} />)}
        </ul>
        {quick && quick.recent.length === 0 && busy.length === 0 && <p className="px-1 text-sm text-muted">{t('phone.quick.none')}</p>}
      </section>

      <div className="mt-auto pt-6">
        <Link to="/eingang" className="flex items-center gap-3 rounded-2xl bg-sheet-2 px-4 py-3.5 text-sm">
          <Inbox size={18} className="text-accent" aria-hidden />
          <span className="flex-1" data-testid="quick-waiting">
            <span className="font-semibold">{t('phone.quick.waiting', { count: quick?.inbox ?? 0 })}</span> <span className="text-muted">{t('phone.quick.waitingText')}</span>
          </span>
          <ArrowRight size={16} className="text-muted" aria-hidden />
        </Link>
      </div>

      {refused && <UploadNotice lead={toast ?? ''} summary={refused} onClose={() => setRefused(null)} />}
      {toast && !refused && (
        <div role="status" className="rise fixed inset-x-0 bottom-24 z-50 flex justify-center px-4">
          <p className="rounded-full bg-ink px-5 py-2.5 text-center text-sm font-semibold text-paper shadow-soft">{toast}</p>
        </div>
      )}
    </div>
  )
}

function Recent({ doc, justNow, language }: { doc: DocumentInfo; justNow: string; language: string }) {
  const { t } = useTranslation()
  const processing = doc.status === 'processing'
  const to = doc.status === 'filed' ? `/dokument/${doc.id}` : `/eingang/${doc.id}`
  return (
    <li>
      <Link to={to} className="flex items-center gap-3 rounded-2xl border border-line bg-sheet p-2.5">
        {processing || doc.pages === 0 ? (
          <div className="shimmer aspect-[210/297] w-9 shrink-0 rounded-[3px]" />
        ) : (
          <img
            src={`/api/v1/documents/${doc.id}/versions/${doc.current_version}/preview`}
            alt=""
            className="aspect-[210/297] w-9 shrink-0 rounded-[3px] border border-line bg-white object-cover object-top"
          />
        )}
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold">{processing ? t('phone.quick.reading') : doc.title}</span>
          <span className="text-xs text-muted">
            {processing ? t('phone.quick.readingMeta', { when: ago(doc.added_at, language, justNow) }) : doc.status === 'inbox' ? t('phone.quick.inInbox') : t('phone.quick.filed')}
          </span>
        </span>
        {processing && <Loader2 size={16} className="animate-spin text-accent" aria-hidden />}
      </Link>
    </li>
  )
}
