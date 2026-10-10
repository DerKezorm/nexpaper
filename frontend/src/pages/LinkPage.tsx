/**
 * What somebody without an account sees behind a link (`/l/<token>`): only this one document, who shared it, until when
 * it works. Nothing else of nexpaper opens from here; the page asks the server for nothing but the link's own routes.
 * The pages are shown as pictures (`/l/<token>/pages/<n>`, for as long as the link works, with or without downloading),
 * each fetched only when it comes near the view, small first (drawn ahead by the server) and sharp after, in a queue
 * that waits as long as the server's `Retry-After` says when it is busy (`components/PagePicture.tsx`);
 * the file itself is handed out only when the link allows downloading. A document without pages (an e-invoice as XML)
 * shows no pictures.
 * A dead link or a sender who has to rest gets a header without a sentence: there is nobody to name.
 */
import { Clock, Download, ExternalLink, Eye, FileText } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { useParams } from 'react-router-dom'

import { ApiError, sharingApi, type PublicLink } from '../api/client'
import { LogoMark } from '../components/Logo'
import { PagePicture } from '../components/PagePicture'
import { shortDate } from '../lib/dates'
import { errorText } from '../lib/errors'
import { iso } from '../lib/say'

export function LinkPage() {
  const { t, i18n } = useTranslation()
  const { token = '' } = useParams()
  const [link, setLink] = useState<PublicLink | null>(null)
  const [gone, setGone] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    sharingApi.open(token).then(
      (found) => alive && setLink(found),
      (error: unknown) => {
        if (!alive) return
        if (error instanceof ApiError && error.code !== 'not_found') setProblem(error.code)
        else setGone(true)
      },
    )
    return () => {
      alive = false
    }
  }, [token])

  const fileUrl = `/api/v1/l/${encodeURIComponent(token)}/file`
  const who = link?.shared_by
  return (
    <div className="min-h-dvh">
      <header className="border-b border-line bg-sheet">
        <div className="mx-auto flex max-w-4xl items-center gap-3 px-4 py-3">
          <LogoMark size={28} />
          <p className="flex-1 text-sm text-ink-2">
            {link && (who ? <Trans i18nKey="link.sharedBy" values={{ name: iso(who) }} components={{ name: <span className="font-semibold text-ink" /> }} /> : t('link.sharedByUnknown'))}
          </p>
          {link && (
            <span className="hidden items-center gap-1.5 text-xs text-muted sm:flex">
              <Clock size={13} aria-hidden /> {t('link.validUntil', { date: shortDate(link.until, i18n.language) })}
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
        {!link && !gone && !problem && <p className="text-sm text-muted">{t('link.loading')}</p>}
        {link && (
          <>
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h1 className="font-display text-2xl font-semibold">
                  <bdi>{link.title}</bdi>
                </h1>
                <p className="text-sm text-muted">{t('link.meta', { sender: link.sender ? iso(link.sender) : t('link.noSender'), count: link.pages })}</p>
              </div>
              {link.has_file && link.allow_download && (
                <a href={fileUrl} download className="inline-flex h-10 items-center gap-2 rounded-full bg-accent px-4 font-semibold text-accent-ink">
                  <Download size={16} aria-hidden /> {t('link.download')}
                </a>
              )}
            </div>
            {link.has_pages && (
              <ol className="mx-auto mt-5 max-w-2xl space-y-4" aria-label={t('link.pagesLabel')}>
                {Array.from({ length: Math.max(link.pages, 1) }, (_, index) => (
                  <li key={index}>
                    <PagePicture
                      src={`/api/v1/l/${encodeURIComponent(token)}/pages/${index + 1}?size=small`}
                      better={`/api/v1/l/${encodeURIComponent(token)}/pages/${index + 1}?size=large`}
                      alt={t('link.page', { n: index + 1 })}
                      eager={index === 0}
                    />
                  </li>
                ))}
              </ol>
            )}
            <div className={`card mx-auto flex max-w-2xl flex-col items-center gap-3 text-center ${link.has_pages ? 'mt-4 p-4' : 'mt-5 p-10'}`}>
              {!link.has_pages && (
                <span className="flex h-20 w-14 items-center justify-center rounded-[4px] bg-white text-muted shadow-[0_1px_3px_rgb(0_0_0/0.18)]">
                  <FileText size={26} aria-hidden />
                </span>
              )}
              {!link.has_file ? (
                <p className="text-sm text-ink-2">{t('link.processing')}</p>
              ) : link.allow_download ? (
                <p className="text-sm text-ink-2">{t('link.ready')}</p>
              ) : (
                <>
                  <p className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink-2">
                    <Eye size={15} aria-hidden /> {t('link.viewOnly')}
                  </p>
                  {!link.has_pages && <p className="text-sm text-muted">{t('link.noPages')}</p>}
                </>
              )}
              {link.has_file && link.viewable && (
                <a href={fileUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-sm font-semibold text-accent">
                  <ExternalLink size={14} aria-hidden /> {t('link.view')}
                </a>
              )}
            </div>
            <p className="mt-8 text-center text-xs text-muted">{who ? t('link.footer', { name: iso(who) }) : t('link.footerUnknown')}</p>
          </>
        )}
      </main>
    </div>
  )
}
