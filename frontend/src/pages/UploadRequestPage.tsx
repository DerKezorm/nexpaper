/**
 * What somebody without an account sees behind an upload request (`/u/<token>`): who asks, whom the request is for, a
 * place to drop or choose files, what is taken and how many still go. It never shows what came already, not even names
 * of earlier files, and nothing of the server. Files go one by one (one request each, `POST /api/v1/u/<token>/files`);
 * each says "angekommen" or why it was not taken, in a sentence. An address that does not work (unknown, run out,
 * withdrawn, all files there, switched off) gets the same sentence, whatever the reason.
 */
import { AlertTriangle, Check, Clock, FileText, Loader2, Upload } from 'lucide-react'
import { useEffect, useRef, useState, type DragEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams } from 'react-router-dom'

import { ApiError, uploadRequestsApi, type PublicRequest } from '../api/client'
import { LogoMark } from '../components/Logo'
import { NamedSentence } from '../components/NamedSentence'
import { shortDate } from '../lib/dates'
import { ACCEPT } from '../lib/formats'
import { iso } from '../lib/say'

type Sent = { key: number; name: string; state: 'waiting' | 'sending' | 'arrived' | 'refused'; reason?: string; values?: Record<string, unknown> }

/** The reasons the page has a sentence for; anything else says that it did not work. */
const REASONS = ['unsupported_type', 'xml_not_invoice', 'xml_doctype', 'too_large', 'empty_file', 'request_busy', 'request_day_full', 'too_slow', 'not_found', 'too_many_attempts']

export function UploadRequestPage() {
  const { t, i18n } = useTranslation()
  const { token = '' } = useParams()
  const [request, setRequest] = useState<PublicRequest | null>(null)
  const [gone, setGone] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [sent, setSent] = useState<Sent[]>([])
  const [dragging, setDragging] = useState(false)
  const chooser = useRef<HTMLInputElement>(null)
  const counter = useRef(0)

  useEffect(() => {
    let alive = true
    uploadRequestsApi.open(token).then(
      (found) => alive && setRequest(found),
      (error: unknown) => {
        if (!alive) return
        if (error instanceof ApiError && error.code === 'too_many_attempts') setBusy(error.code)
        else setGone(true)
      },
    )
    return () => {
      alive = false
    }
  }, [token])

  const remaining = request?.remaining ?? 0
  const running = sent.some((s) => s.state === 'waiting' || s.state === 'sending')

  const take = async (list: File[]) => {
    if (!request || list.length === 0 || running) return
    const entries: Sent[] = list.map((file) => ({ key: ++counter.current, name: file.name, state: 'waiting' }))
    setSent((had) => [...entries, ...had])
    let left = remaining
    for (let index = 0; index < list.length; index++) {
      const entry = entries[index]
      const update = (patch: Partial<Sent>) => setSent((had) => had.map((s) => (s.key === entry.key ? { ...s, ...patch } : s)))
      if (left <= 0) {
        update({ state: 'refused', reason: 'full' })
        continue
      }
      update({ state: 'sending' })
      try {
        const answer = await uploadRequestsApi.send(token, list[index])
        left = answer.remaining
        update({ state: 'arrived' })
        setRequest((had) => (had ? { ...had, remaining: answer.remaining } : had))
      } catch (error) {
        const code = error instanceof ApiError ? error.code : 'failed'
        update({ state: 'refused', reason: REASONS.includes(code) ? code : 'failed', values: error instanceof ApiError ? error.values : {} })
        if (code === 'not_found') {
          // The address stopped working meanwhile (withdrawn, all files there): nothing more goes.
          left = 0
          setRequest((had) => (had ? { ...had, remaining: 0 } : had))
        }
      }
    }
  }

  const dropped = (event: DragEvent<HTMLElement>) => {
    event.preventDefault()
    setDragging(false)
    void take(Array.from(event.dataTransfer.files ?? []))
  }

  const who = request?.requested_by
  return (
    <div className="min-h-dvh">
      <header className="border-b border-line bg-sheet">
        <div className="mx-auto flex max-w-3xl items-center gap-3 px-4 py-3">
          <LogoMark size={28} />
          <p className="flex-1 text-sm text-ink-2">
            {request && (who ? <NamedSentence i18nKey="uploadRequest.page.asks" name={who} /> : t('uploadRequest.page.asksUnknown'))}
          </p>
          {request && (
            <span className="hidden items-center gap-1.5 text-xs text-muted sm:flex">
              <Clock size={13} aria-hidden /> {t('uploadRequest.page.until', { date: shortDate(request.until, i18n.language) })}
            </span>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-6">
        {gone && (
          <div className="card p-10 text-center" role="alert" data-testid="request-gone">
            <p className="font-display text-xl font-semibold">{t('uploadRequest.page.gone')}</p>
            <p className="mt-1 text-sm text-ink-2">{t('uploadRequest.page.goneText')}</p>
          </div>
        )}
        {busy && (
          <p role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
            {t('uploadRequest.reason.too_many_attempts')}
          </p>
        )}
        {!request && !gone && !busy && <p className="text-sm text-muted">{t('uploadRequest.page.loading')}</p>}
        {request && (
          <>
            <h1 className="font-display text-2xl font-semibold break-words">{who ? t('uploadRequest.page.title', { name: iso(who) }) : t('uploadRequest.page.titleUnknown')}</h1>
            <p className="mt-1 text-sm text-ink-2">
              <NamedSentence i18nKey="uploadRequest.page.for" name={request.name} />
            </p>
            <p className="mt-1 text-xs text-muted sm:hidden">{t('uploadRequest.page.until', { date: shortDate(request.until, i18n.language) })}</p>
            <section
              aria-label={t('uploadRequest.page.drop')}
              onDragOver={(event) => {
                event.preventDefault()
                if (remaining > 0) setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={dropped}
              data-testid="request-drop"
              className={`mt-5 flex flex-col items-center gap-3 rounded-3xl border-2 border-dashed px-5 py-10 text-center ${dragging ? 'border-accent bg-accent-soft/60' : 'border-line bg-sheet'}`}
            >
              <Upload size={34} className="text-accent" aria-hidden />
              {remaining > 0 ? (
                <>
                  <p className="font-display text-lg font-semibold">{t('uploadRequest.page.drop')}</p>
                  <button type="button" disabled={running} onClick={() => chooser.current?.click()} className="inline-flex h-11 items-center gap-2 rounded-full bg-accent px-5 font-semibold text-accent-ink hover:brightness-105 disabled:opacity-60">
                    {t('uploadRequest.page.choose')}
                  </button>
                  <input
                    ref={chooser}
                    type="file"
                    multiple
                    accept={ACCEPT}
                    className="hidden"
                    aria-label={t('uploadRequest.page.choose')}
                    onChange={(event) => {
                      const chosen = Array.from(event.target.files ?? [])
                      event.target.value = ''
                      void take(chosen)
                    }}
                  />
                  <p className="text-sm text-ink-2">{t('uploadRequest.page.remaining', { count: remaining })}</p>
                </>
              ) : (
                <p className="font-display text-lg font-semibold" data-testid="request-full">{t('uploadRequest.page.full')}</p>
              )}
              <p className="max-w-md text-xs text-muted">{t('uploadRequest.page.accepts', { mb: request.max_mb })}</p>
            </section>
            {sent.length > 0 && (
              <ul className="mt-5 space-y-2" aria-label={t('uploadRequest.page.sentTitle')} data-testid="request-sent">
                {sent.map((s) => (
                  <li key={s.key} data-state={s.state} className="card flex items-start gap-3 px-4 py-3">
                    {s.state === 'arrived' ? (
                      <Check size={18} className="mt-0.5 shrink-0 text-ok" aria-hidden />
                    ) : s.state === 'refused' ? (
                      <AlertTriangle size={18} className="mt-0.5 shrink-0 text-bad" aria-hidden />
                    ) : s.state === 'sending' ? (
                      <Loader2 size={18} className="mt-0.5 shrink-0 animate-spin text-muted" aria-hidden />
                    ) : (
                      <FileText size={18} className="mt-0.5 shrink-0 text-muted" aria-hidden />
                    )}
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold">
                        <bdi>{s.name}</bdi>
                      </span>
                      <span className={`block text-xs ${s.state === 'refused' ? 'text-bad' : 'text-ink-2'}`}>
                        {s.state === 'refused' ? t(`uploadRequest.reason.${s.reason}`, { mb: request.max_mb, ...s.values }) : t(`uploadRequest.page.${s.state}`)}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-8 text-center text-xs text-muted">{who ? t('uploadRequest.page.footer', { name: iso(who) }) : t('uploadRequest.page.footerUnknown')}</p>
          </>
        )}
      </main>
    </div>
  )
}
