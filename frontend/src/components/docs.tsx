/**
 * The small pieces the pages with documents share, as the mock draws them (`attrappe/src/components/ui.tsx`): the kind
 * as a coloured pill, where a proposal came from, marks of a search in a text (ranges from the server, never HTML), a
 * filter chip, a menu that drops down, and the little picture of a document.
 */
import { AlertTriangle, FileText, type LucideIcon } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { api, fileUrls, type DocumentInfo, type DocumentKind, type Mark } from '../api/client'
import { useAuth } from '../state/auth'
import { PagePicture } from './PagePicture'

export function KindPill({ kind, small = false }: { kind: Pick<DocumentKind, 'name' | 'hue'> | null; small?: boolean }) {
  if (!kind) return null
  const hue = kind.hue
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full font-semibold ${small ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs'}`}
      style={{ background: `hsl(${hue} 45% 50% / 0.13)`, color: `light-dark(hsl(${hue} 45% 32%), hsl(${hue} 55% 75%))` }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: `hsl(${hue} 50% 50%)` }} />
      {kind.name}
    </span>
  )
}

/** Where a proposal in the inbox came from ("Regel", "KI", "aus dem Text", ...). Nothing for an origin it does not know. */
export function WhyBadge({ why }: { why?: string }) {
  const { t, i18n } = useTranslation()
  if (!why || !i18n.exists(`docs.why.${why}`)) return null
  return <span className="rounded-full bg-sheet-2 px-2 py-0.5 text-[0.7rem] font-semibold text-muted">{t(`docs.why.${why}`)}</span>
}

/** A text with the places a search found marked. The ranges count UTF-16 code units, as JavaScript does; ranges that
 * overlap or run past the end are cut, never trusted. */
export function Marked({ text, marks }: { text: string; marks: Mark[] }) {
  const parts: ReactNode[] = []
  let at = 0
  const sorted = [...marks].filter(([start, end]) => Number.isInteger(start) && Number.isInteger(end) && end > start).sort((a, b) => a[0] - b[0])
  for (const [rawStart, rawEnd] of sorted) {
    const start = Math.max(at, Math.min(rawStart, text.length))
    const end = Math.min(rawEnd, text.length)
    if (end <= start) continue
    if (start > at) parts.push(text.slice(at, start))
    parts.push(<mark key={start}>{text.slice(start, end)}</mark>)
    at = end
  }
  if (at < text.length) parts.push(text.slice(at))
  // A person's text: kept apart from what stands around it, whatever direction its characters turn to.
  return <bdi>{parts}</bdi>
}

export function Chip({ active = false, children, onClick, label }: { active?: boolean; children: ReactNode; onClick?: () => void; label?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      aria-label={label}
      className={`inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-sm font-semibold transition ${
        active ? 'border-transparent bg-accent text-accent-ink' : 'border-line bg-sheet text-ink-2 hover:border-accent'
      }`}
    >
      {children}
    </button>
  )
}

/** A menu below a button; a click outside or Escape closes it, a click on an item too. */
export function Menu({ children, onClose, right = false, label }: { children: ReactNode; onClose: () => void; right?: boolean; label: string }) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const close = (event: MouseEvent) => box.current && !box.current.contains(event.target as Node) && onClose()
    const key = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('mousedown', close)
    window.addEventListener('keydown', key)
    return () => {
      window.removeEventListener('mousedown', close)
      window.removeEventListener('keydown', key)
    }
  }, [onClose])
  return (
    <div ref={box} role="menu" aria-label={label} className={`card rise absolute top-full z-40 mt-2 w-64 p-1.5 ${right ? 'right-0' : 'left-0 sm:right-0 sm:left-auto'}`} onClick={onClose}>
      {children}
    </div>
  )
}

export function MenuItem({ icon: Icon, text, hint, onClick, href, download }: { icon: LucideIcon; text: string; hint?: string; onClick?: () => void; href?: string; download?: boolean }) {
  const inner = (
    <>
      <Icon size={16} className="mt-0.5 shrink-0 text-ink-2" aria-hidden />
      <span>
        <span className="font-semibold">{text}</span>
        {hint && <span className="block text-xs text-muted">{hint}</span>}
      </span>
    </>
  )
  const look = 'flex w-full items-start gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-sheet-2'
  if (href)
    return (
      <a role="menuitem" href={href} download={download ? '' : undefined} className={look}>
        {inner}
      </a>
    )
  return (
    <button type="button" role="menuitem" onClick={onClick} className={look}>
      {inner}
    </button>
  )
}

/** The little picture of a document: its first page; a shimmer while it is being read; a sheet with a sign for one
 * without pages (an e-invoice as XML, a file that could not be read). */
export function DocThumb({ document, className = '', eager = false }: { document: Pick<DocumentInfo, 'id' | 'status' | 'pages' | 'current_version' | 'title'>; className?: string; eager?: boolean }) {
  if (document.status === 'processing') return <div className={`shimmer aspect-[210/297] rounded-[3px] ${className}`} aria-hidden />
  if (document.pages < 1)
    return (
      <span className={`flex aspect-[210/297] items-center justify-center rounded-[3px] bg-white text-muted shadow-[0_1px_3px_rgb(0_0_0/0.18)] ${className}`} aria-hidden>
        <FileText size={16} />
      </span>
    )
  return <PagePicture src={fileUrls.preview(document.id, document.current_version)} alt="" className={className} eager={eager} />
}

/** The warning sign of a document whose file is missing or no longer matches its checksum (the check of the files,
 * `services/filecheck.py`). Nothing for a document that is in order. */
export function FileSign({ state, size = 14, className = '' }: { state?: string; size?: number; className?: string }) {
  const { t } = useTranslation()
  if (state !== 'missing' && state !== 'changed') return null
  return (
    <span className={`inline-flex shrink-0 text-bad ${className}`} role="img" aria-label={t(`docs.files.${state}`)} title={t(`docs.files.${state}`)} data-testid="file-sign">
      <AlertTriangle size={size} aria-hidden />
    </span>
  )
}

/** On the page of the document and in the inbox: what the sign means and what to do. The operator gets the way out (the
 * backup of the server, and the check of the files to see that it worked); everybody else is told whom to ask, because
 * they have no access to the server and the settings are not theirs. */
export function FileNotice({ state, documentId, onChecked }: { state?: string; documentId?: number; onChecked?: () => void }) {
  const { t } = useTranslation()
  const { me } = useAuth()
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  if (state !== 'missing' && state !== 'changed') return null
  const operator = me?.role === 'operator'
  const again = async () => {
    setBusy(true)
    setFailed(false)
    try {
      await api(`/api/v1/storage/files/documents/${documentId}/check`, { method: 'POST' })
      onChecked?.()
    } catch {
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div role="alert" className="rounded-2xl border border-bad/40 bg-bad/10 p-4 text-sm" data-testid="file-notice">
      <p className="flex items-center gap-2 font-semibold text-bad">
        <AlertTriangle size={15} aria-hidden /> {t(`docs.files.${state}Title`)}
      </p>
      <p className="mt-1 text-ink-2">{t(operator ? `docs.files.${state}Text` : `docs.files.${state}TextMember`)}</p>
      {operator && (
        <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
          {documentId !== undefined && (
            <button type="button" onClick={() => void again()} disabled={busy} className="font-semibold text-accent underline decoration-accent/40 underline-offset-4 disabled:opacity-60">
              {t('docs.files.recheck')}
            </button>
          )}
          <Link to="/einstellungen?tab=backups" className="font-semibold text-accent underline decoration-accent/40 underline-offset-4">
            {t('docs.files.checkLink')}
          </Link>
          {failed && (
            <span role="status" className="text-xs text-bad">
              {t('docs.files.recheckFailed')}
            </span>
          )}
        </p>
      )}
    </div>
  )
}
