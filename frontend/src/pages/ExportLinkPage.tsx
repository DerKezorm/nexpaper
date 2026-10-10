/**
 * What somebody without an account sees behind a link to an export (`/x/<token>`), built like the page behind a link
 * to a document: who shared it, for whom, how many documents, until when it works, and the ZIP to download once it is
 * packed. Nothing else of nexpaper opens from here; the page asks the server for nothing but the link's own routes.
 */
import { Clock, Download, FileArchive } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { useParams } from 'react-router-dom'

import { ApiError, exportsApi, type PublicExport } from '../api/client'
import { LogoMark } from '../components/Logo'
import { formatBytes } from '../lib/bytes'
import { shortDate } from '../lib/dates'
import { errorText } from '../lib/errors'

/** While the ZIP is packed the page asks again now and then. */
const POLL_MS = 15_000

export function ExportLinkPage() {
  const { t, i18n } = useTranslation()
  const { token = '' } = useParams()
  const [found, setFound] = useState<PublicExport | null>(null)
  const [gone, setGone] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    let timer = 0
    const load = () =>
      exportsApi.open(token).then(
        (shown) => {
          if (!alive) return
          setFound(shown)
          if (shown.state === 'packing') timer = window.setTimeout(load, POLL_MS)
        },
        (error: unknown) => {
          if (!alive) return
          if (error instanceof ApiError && error.code !== 'not_found') setProblem(error.code)
          else setGone(true)
        },
      )
    void load()
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [token])

  const who = found?.shared_by
  return (
    <div className="min-h-dvh">
      <header className="border-b border-line bg-sheet">
        <div className="mx-auto flex max-w-4xl items-center gap-3 px-4 py-3">
          <LogoMark size={28} />
          <p className="flex-1 text-sm text-ink-2">
            {found && (who ? <Trans i18nKey="exports.page.sharedBy" values={{ name: who }} components={{ name: <span className="font-semibold text-ink" /> }} /> : t('exports.page.sharedByUnknown'))}
          </p>
          {found && (
            <span className="hidden items-center gap-1.5 text-xs text-muted sm:flex">
              <Clock size={13} aria-hidden /> {t('link.validUntil', { date: shortDate(found.until, i18n.language) })}
            </span>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 py-6">
        {gone && (
          <div className="card p-10 text-center" role="alert">
            <p className="font-display text-xl font-semibold">{t('link.gone')}</p>
            <p className="mt-1 text-sm text-ink-2">{t('link.goneText')}</p>
          </div>
        )}
        {problem && (
          <p role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
            {errorText(problem)}
          </p>
        )}
        {!found && !gone && !problem && <p className="text-sm text-muted">{t('link.loading')}</p>}
        {found && (
          <>
            <div className="card mx-auto flex max-w-2xl flex-col items-center gap-3 p-10 text-center">
              <span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-accent-soft text-accent">
                <FileArchive size={28} aria-hidden />
              </span>
              <h1 className="font-display text-2xl font-semibold">{t('exports.page.heading', { recipient: found.recipient })}</h1>
              {found.state === 'ready' && (
                <p className="text-sm text-muted">
                  {t('exports.page.meta', { n: found.documents.toLocaleString(i18n.language), size: formatBytes(found.size, i18n.language, 1000) })}
                </p>
              )}
              {found.date_from && found.date_to && (
                <p className="text-sm text-muted">{t('exports.page.period', { from: shortDate(found.date_from, i18n.language), to: shortDate(found.date_to, i18n.language) })}</p>
              )}
              <p className="inline-flex items-center gap-1.5 text-xs text-muted sm:hidden">
                <Clock size={13} aria-hidden /> {t('link.validUntil', { date: shortDate(found.until, i18n.language) })}
              </p>
              {found.state === 'ready' ? (
                <>
                  <p className="text-sm text-ink-2">{t('exports.page.ready')}</p>
                  <a href={exportsApi.publicFileUrl(token)} download className="inline-flex h-10 items-center gap-2 rounded-full bg-accent px-4 font-semibold text-accent-ink">
                    <Download size={16} aria-hidden /> {t('exports.page.download')}
                  </a>
                </>
              ) : (
                <p className="text-sm text-ink-2">{t('exports.page.packing')}</p>
              )}
            </div>
            <p className="mt-8 text-center text-xs text-muted">{who ? t('exports.page.footer', { name: who }) : t('exports.page.footerUnknown')}</p>
          </>
        )}
      </main>
    </div>
  )
}
