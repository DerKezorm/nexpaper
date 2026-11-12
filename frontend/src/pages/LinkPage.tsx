/**
 * What somebody without an account sees behind a link (`/l/<token>`): this one document, who shared it, until when
 * it works. Nothing else of nexpaper opens from here; the page asks the server for nothing but the link's own routes.
 * The pages are shown as pictures (`/l/<token>/pages/<n>`, for as long as the link works, with or without downloading),
 * each fetched only when it comes near the view, small first (drawn ahead by the server) and sharp after, in a queue
 * that waits as long as the server's `Retry-After` says when it is busy (`components/PagePicture.tsx`);
 * the file itself is handed out only when the link allows downloading. A document without pages (an e-invoice as XML)
 * shows no pictures.
 * A link may show further documents that go with the first (N2): they stand under it as "Gehört dazu", and one opens
 * in the same page under the link's own paths (`/l/<token>/also/<n>/...`), with a way back to the first.
 * A dead link or a sender who has to rest gets a header without a sentence: there is nobody to name.
 */
import { ArrowLeft, Clock, Download, ExternalLink, Eye, FileText, Paperclip } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams } from 'react-router-dom'

import { ApiError, sharingApi, type PublicAlso, type PublicLink } from '../api/client'
import { LogoMark } from '../components/Logo'
import { NamedSentence } from '../components/NamedSentence'
import { PagePicture } from '../components/PagePicture'
import { shortDate } from '../lib/dates'
import { errorText } from '../lib/errors'
import { iso } from '../lib/say'

/** What one document of the page needs: the paths of its own and what it can show. */
type Shown = { base: string; title: string; pages: number; has_file: boolean; viewable: boolean; has_pages: boolean; meta: string }

export function LinkPage() {
  const { t, i18n } = useTranslation()
  const { token = '' } = useParams()
  const [link, setLink] = useState<PublicLink | null>(null)
  const [gone, setGone] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  /** The further document open in the page, by its number within the link; null: the first one. */
  const [open, setOpen] = useState<number | null>(null)

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

  const root = `/api/v1/l/${encodeURIComponent(token)}`
  const also = link?.also ?? []
  const other = open === null ? undefined : also.find((a) => a.id === open)
  const pagesText = (count: number) => t('linkRelated.pages', { count })
  const alsoMeta = (a: PublicAlso) => [a.kind, a.date ? shortDate(a.date, i18n.language) : null, pagesText(a.pages)].filter(Boolean).join(' · ')
  const shown: Shown | null = !link
    ? null
    : other
      ? { base: `${root}/also/${other.id}`, title: other.title, pages: other.pages, has_file: other.has_file, viewable: other.viewable, has_pages: other.has_pages, meta: alsoMeta(other) }
      : { base: root, title: link.title, pages: link.pages, has_file: link.has_file, viewable: link.viewable, has_pages: link.has_pages, meta: t('link.meta', { sender: link.sender ? iso(link.sender) : t('link.noSender'), count: link.pages }) }
  const choose = (id: number | null) => {
    setOpen(id)
    window.scrollTo?.({ top: 0 })
  }
  const fileUrl = shown ? `${shown.base}/file` : ''
  const who = link?.shared_by
  return (
    <div className="min-h-dvh">
      <header className="border-b border-line bg-sheet">
        <div className="mx-auto flex max-w-4xl items-center gap-3 px-4 py-3">
          <LogoMark size={28} />
          <p className="flex-1 text-sm text-ink-2">
            {link &&
              (also.length > 0 ? (
                who ? (
                  <NamedSentence i18nKey="linkRelated.sharedBy" name={who} values={{ count: also.length + 1 }} />
                ) : (
                  t('linkRelated.sharedByUnknown', { count: also.length + 1 })
                )
              ) : who ? (
                <NamedSentence i18nKey="link.sharedBy" name={who} />
              ) : (
                t('link.sharedByUnknown')
              ))}
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
        {link && shown && (
          <>
            {other && (
              <button type="button" onClick={() => choose(null)} className="mb-3 inline-flex items-center gap-1.5 text-sm font-semibold text-accent" data-testid="link-back">
                <ArrowLeft size={15} aria-hidden /> {t('linkRelated.back', { title: iso(link.title) })}
              </button>
            )}
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div className="min-w-0">
                <h1 className="font-display text-2xl font-semibold break-words">
                  <bdi>{shown.title}</bdi>
                </h1>
                <p className="text-sm text-muted">{shown.meta}</p>
              </div>
              {shown.has_file && link.allow_download && (
                <a href={fileUrl} download className="inline-flex h-10 items-center gap-2 rounded-full bg-accent px-4 font-semibold text-accent-ink">
                  <Download size={16} aria-hidden /> {t('link.download')}
                </a>
              )}
            </div>
            {shown.has_pages && (
              <ol key={shown.base} className="mx-auto mt-5 max-w-2xl space-y-4" aria-label={t('link.pagesLabel')}>
                {Array.from({ length: Math.max(shown.pages, 1) }, (_, index) => (
                  <li key={index}>
                    <PagePicture
                      src={`${shown.base}/pages/${index + 1}?size=small`}
                      better={`${shown.base}/pages/${index + 1}?size=large`}
                      alt={t('link.page', { n: index + 1 })}
                      eager={index === 0}
                    />
                  </li>
                ))}
              </ol>
            )}
            <div className={`card mx-auto flex max-w-2xl flex-col items-center gap-3 text-center ${shown.has_pages ? 'mt-4 p-4' : 'mt-5 p-10'}`}>
              {!shown.has_pages && (
                <span className="flex h-20 w-14 items-center justify-center rounded-[4px] bg-white text-muted shadow-[0_1px_3px_rgb(0_0_0/0.18)]">
                  <FileText size={26} aria-hidden />
                </span>
              )}
              {!shown.has_file ? (
                <p className="text-sm text-ink-2">{t('link.processing')}</p>
              ) : link.allow_download ? (
                <p className="text-sm text-ink-2">{t('link.ready')}</p>
              ) : (
                <>
                  <p className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink-2">
                    <Eye size={15} aria-hidden /> {t('link.viewOnly')}
                  </p>
                  {!shown.has_pages && <p className="text-sm text-muted">{t('link.noPages')}</p>}
                </>
              )}
              {shown.has_file && shown.viewable && (
                <a href={fileUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-sm font-semibold text-accent">
                  <ExternalLink size={14} aria-hidden /> {t('link.view')}
                </a>
              )}
            </div>
            {also.length > 0 && (
              <section className="mx-auto mt-6 max-w-2xl" aria-labelledby="link-also-title">
                <h2 id="link-also-title" className="flex items-center gap-2 font-semibold">
                  <Paperclip size={16} aria-hidden /> {t('linkRelated.title')}
                </h2>
                <ul className="mt-2 space-y-2">
                  {other && (
                    <li>
                      <button type="button" onClick={() => choose(null)} className="card flex w-full items-center gap-3 px-4 py-3 text-left hover:border-accent/50">
                        <FileText size={18} className="shrink-0 text-muted" aria-hidden />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-semibold">
                            <bdi>{link.title}</bdi>
                          </span>
                          <span className="block text-xs text-muted">{t('linkRelated.first')}</span>
                        </span>
                      </button>
                    </li>
                  )}
                  {also.map((a) => (
                    <li key={a.id}>
                      <button
                        type="button"
                        onClick={() => choose(a.id)}
                        aria-current={a.id === open ? 'page' : undefined}
                        className={`card flex w-full items-center gap-3 px-4 py-3 text-left hover:border-accent/50 ${a.id === open ? 'border-accent/60' : ''}`}
                      >
                        <FileText size={18} className="shrink-0 text-muted" aria-hidden />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-semibold">
                            <bdi>{a.title}</bdi>
                          </span>
                          <span className="block text-xs text-muted">{alsoMeta(a)}</span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            <p className="mt-8 text-center text-xs text-muted">
              {also.length > 0
                ? who
                  ? t('linkRelated.footer', { name: iso(who), count: also.length + 1 })
                  : t('linkRelated.footerUnknown', { count: also.length + 1 })
                : who
                  ? t('link.footer', { name: iso(who) })
                  : t('link.footerUnknown')}
            </p>
          </>
        )}
      </main>
    </div>
  )
}
