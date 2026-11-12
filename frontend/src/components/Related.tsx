/**
 * "Gehört zu" (English "Goes with"): documents that go with each other, both ways, no kind, no chains. The section on the
 * document page (the list, the proposals below it with a dashed edge, the button that opens the dialog), the dialog to
 * set a pair (the proposals on top, then the normal search, only documents the person may change), and the line on a card
 * of the inbox ("Passt zu: Lieferschein, Stadtwerke Lindenau, 03.11.2026"). Everything through `/api/v1`
 * (`related`); the server decides what the person may see and change.
 *
 * Removing a pair ("Lösen") asks nothing first: nothing is deleted, the pair can be set again any moment, and the
 * proposal it came from comes back below the list, so a slip is undone with one click.
 */
import { Plus, Search, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import {
  ApiError,
  relatedApi,
  searchApi,
  type DocumentInfo,
  type RelatedDocument,
  type RelatedSuggestion,
} from '../api/client'
import { shortDate } from '../lib/dates'
import { errorText } from '../lib/errors'
import { pageOf, proposalLine, type RelatedShown } from '../lib/related'
import { iso, listOf } from '../lib/say'
import { Button } from './Button'
import { Dialog } from './Dialog'
import { KindPill } from './docs'

type Shown = RelatedShown

const SEARCH_MS = 250

function Item({ document: d, children }: { document: Shown; children?: React.ReactNode }) {
  const { i18n } = useTranslation()
  return (
    <>
      <Link to={pageOf(d)} className="flex min-w-0 flex-1 items-center gap-2.5 hover:text-accent">
        <KindPill kind={d.kind} small />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-semibold">
            <bdi>{d.title}</bdi>
          </span>
          <span className="block truncate text-xs text-muted">
            {[d.sender?.name, d.date ? shortDate(d.date, i18n.language) : null].filter(Boolean).join(' · ')}
          </span>
        </span>
      </Link>
      {children}
    </>
  )
}

/** The section "Gehört zu" under the notes on the document page. */
export function RelatedSection({ document: d, canEdit, onChange }: { document: Pick<DocumentInfo, 'id' | 'title' | 'status'>; canEdit: boolean; onChange?: () => void }) {
  const { t } = useTranslation()
  const [items, setItems] = useState<RelatedDocument[] | null>(null)
  const [proposals, setProposals] = useState<RelatedSuggestion[]>([])
  const [problem, setProblem] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const trashed = d.status === 'trash'

  const load = useCallback(async () => {
    try {
      const [list, found] = await Promise.all([relatedApi.list(d.id), canEdit && !trashed ? relatedApi.suggestions(d.id) : Promise.resolve([])])
      setItems(listOf(list))
      setProposals(listOf(found))
      setProblem(null)
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
    }
  }, [d.id, canEdit, trashed])
  useEffect(() => {
    void load()
  }, [load])

  const act = async (work: () => Promise<unknown>) => {
    setProblem(null)
    try {
      await work()
      await load()
      onChange?.()
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
    }
  }

  return (
    <section className="card p-5" aria-label={t('related.title')} data-testid="related">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="font-display text-lg font-semibold">{t('related.title')}</h2>
        {canEdit && !trashed && (items?.length ?? 0) > 0 && (
          <Button variant="soft" size="sm" onClick={() => setOpen(true)}>
            <Plus size={14} aria-hidden /> {t('related.link')}
          </Button>
        )}
      </div>
      {items && items.length > 0 && (
        <ul className="space-y-2">
          {items.map((item) => (
            <li key={item.id} className="flex items-center gap-2 rounded-xl bg-sheet-2/60 px-3 py-2 text-sm" data-testid="related-item">
              <Item document={item}>
                {item.can_unlink && (
                  <button type="button" onClick={() => void act(() => relatedApi.unlink(d.id, item.id))} className="shrink-0 text-xs font-semibold text-muted hover:text-ink" aria-label={t('related.unlinkFor', { title: item.title })}>
                    {t('related.unlink')}
                  </button>
                )}
              </Item>
            </li>
          ))}
        </ul>
      )}
      {items && items.length === 0 && (
        <div className="space-y-3">
          <p className="text-sm text-muted">{canEdit && !trashed ? t('related.empty') : t('related.emptyRead')}</p>
          {canEdit && !trashed && (
            <Button variant="soft" size="sm" onClick={() => setOpen(true)}>
              <Plus size={14} aria-hidden /> {t('related.link')}
            </Button>
          )}
        </div>
      )}
      {proposals.length > 0 && (
        <ul className="mt-3 space-y-2" aria-label={t('related.proposals')}>
          {proposals.map((found) => (
            <li key={found.id} className="rounded-xl border border-dashed border-line px-3 py-2 text-sm" data-testid="related-proposal">
              <div className="flex items-center gap-2">
                <Item document={found} />
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="flex-1 text-xs text-muted">{t(`related.via.${found.via}`)}</span>
                <button type="button" onClick={() => void act(() => relatedApi.link(d.id, found.id))} className="text-xs font-semibold text-accent" aria-label={t('related.linkFor', { title: found.title })}>
                  {t('related.link')}
                </button>
                <button type="button" onClick={() => void act(() => relatedApi.dismiss(d.id, found.id))} className="text-xs font-semibold text-muted hover:text-ink" aria-label={t('related.dismissFor', { title: found.title })}>
                  {t('related.dismiss')}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {problem && <p className="mt-3 text-sm text-bad">{errorText(problem)}</p>}
      {open && (
        <RelatedDialog
          document={d}
          linked={new Set((items ?? []).map((item) => item.id))}
          onClose={() => setOpen(false)}
          onLinked={() => {
            setOpen(false)
            void load()
            onChange?.()
          }}
        />
      )}
    </section>
  )
}

/** "Verknüpfen": the proposals first, then the search of the archive; only what the person may change. */
export function RelatedDialog({ document: d, linked, onClose, onLinked }: { document: Pick<DocumentInfo, 'id' | 'title'>; linked: Set<number>; onClose: () => void; onLinked: () => void }) {
  const { t } = useTranslation()
  const [typed, setTyped] = useState('')
  const [hits, setHits] = useState<Shown[] | null>(null)
  const [proposals, setProposals] = useState<RelatedSuggestion[]>([])
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    void relatedApi.suggestions(d.id).then((found) => setProposals(listOf(found)), () => undefined)
  }, [d.id])
  useEffect(() => {
    const words = typed.trim()
    if (!words) {
      setHits(null)
      return
    }
    const stop = new AbortController()
    const timer = window.setTimeout(() => {
      searchApi.find(words, { limit: 20 }, stop.signal).then(
        (result) => {
          const found = listOf<{ document: DocumentInfo }>(result.items).map((hit) => hit.document)
          setHits(found.filter((doc) => doc.id !== d.id && doc.status !== 'trash' && (doc.my_right === 'edit' || doc.my_right === 'manage')))
          setProblem(null)
        },
        (error: unknown) => {
          if (!stop.signal.aborted) setProblem(error instanceof ApiError ? error.code : 'internal_error')
        },
      )
    }, SEARCH_MS)
    return () => {
      stop.abort()
      window.clearTimeout(timer)
    }
  }, [typed, d.id])

  const link = async (other: number) => {
    setBusy(true)
    setProblem(null)
    try {
      await relatedApi.link(d.id, other)
      onLinked()
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
      setBusy(false)
    }
  }
  const shown = useMemo(() => proposals.filter((found) => !linked.has(found.id)), [proposals, linked])

  const row = (doc: Shown, note?: string) => (
    <li key={doc.id} className="flex items-center gap-2 rounded-xl bg-sheet-2/60 px-3 py-2 text-sm">
      <span className="flex min-w-0 flex-1 items-center gap-2.5">
        <KindPill kind={doc.kind} small />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-semibold">
            <bdi>{doc.title}</bdi>
          </span>
          <span className="block truncate text-xs text-muted">{note ?? doc.sender?.name ?? ''}</span>
        </span>
      </span>
      {linked.has(doc.id) ? (
        <span className="shrink-0 text-xs text-muted">{t('related.already')}</span>
      ) : (
        <Button size="sm" variant="soft" onClick={() => void link(doc.id)} disabled={busy} aria-label={t('related.linkFor', { title: doc.title })}>
          {t('related.link')}
        </Button>
      )}
    </li>
  )

  return (
    <Dialog title={t('related.dialogTitle')} onClose={onClose}>
      <p className="-mt-2 mb-3 text-sm text-ink-2">{t('related.dialogText', { title: iso(d.title) })}</p>
      {shown.length > 0 && (
        <div className="mb-4">
          <p className="mb-2 text-xs font-semibold text-muted">{t('related.proposals')}</p>
          <ul className="space-y-2" aria-label={t('related.proposals')}>
            {shown.map((found) => row(found, t(`related.via.${found.via}`)))}
          </ul>
        </div>
      )}
      <div className="relative">
        <Search size={15} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted" aria-hidden />
        <input
          type="search"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          placeholder={t('related.searchPlaceholder')}
          aria-label={t('related.searchPlaceholder')}
          maxLength={200}
          className="input h-10 pl-9"
          data-autofocus
        />
        {typed && (
          <button type="button" onClick={() => setTyped('')} className="absolute top-1/2 right-2 -translate-y-1/2 rounded-full p-1 text-muted hover:text-ink" aria-label={t('related.clear')}>
            <X size={14} aria-hidden />
          </button>
        )}
      </div>
      {hits === null ? (
        <p className="mt-3 text-xs text-muted">{t('related.typeToSearch')}</p>
      ) : hits.length === 0 ? (
        <p className="mt-3 text-sm text-muted">{t('related.noHits')}</p>
      ) : (
        <ul className="mt-3 space-y-2" aria-label={t('related.results')}>
          {hits.map((doc) => row(doc))}
        </ul>
      )}
      {problem && <p className="mt-3 text-sm text-bad">{errorText(problem)}</p>}
      <div className="mt-5 flex justify-end">
        <Button variant="ghost" onClick={onClose}>
          {t('common.close')}
        </Button>
      </div>
    </Dialog>
  )
}

/** The line on a card of the inbox: the first proposal, with "Verknüpfen" and "Passt nicht". */
export function RelatedHint({ documentId, proposals, onDone }: { documentId: number; proposals: RelatedSuggestion[]; onDone: () => void }) {
  const { t, i18n } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const first = proposals[0]
  if (!first) return null
  const act = async (work: () => Promise<unknown>) => {
    setBusy(true)
    setProblem(null)
    try {
      await work()
      onDone()
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="mt-1 rounded-xl border border-dashed border-line px-3 py-1.5 text-xs" data-testid="related-hint">
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Link to={pageOf(first)} className="min-w-[12rem] flex-1 break-words text-ink-2 hover:text-accent">
          {t('related.fits', { what: iso(proposalLine(first, i18n.language)) })}
        </Link>
        <button type="button" disabled={busy} onClick={() => void act(() => relatedApi.link(documentId, first.id))} className="font-semibold text-accent disabled:opacity-50" aria-label={t('related.linkFor', { title: first.title })}>
          {t('related.link')}
        </button>
        <button type="button" disabled={busy} onClick={() => void act(() => relatedApi.dismiss(documentId, first.id))} className="font-semibold text-muted hover:text-ink disabled:opacity-50" aria-label={t('related.dismissFor', { title: first.title })}>
          {t('related.dismiss')}
        </button>
      </p>
      {problem && <p className="mt-1 text-bad">{errorText(problem)}</p>}
    </div>
  )
}
