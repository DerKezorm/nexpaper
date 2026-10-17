/**
 * "Mit anderem zusammenfügen" on a document: search a document, and its pages come after those of this
 * one. More than one may be chosen; the order can be changed, and the first one keeps its fields (title, sender, kind, date)
 * and gets the notes and tags of the others, which go to the trash. On the server it is a new version of the first document.
 *
 * The documents offered are the filed ones of the same vault, newest first, as the search finds them.
 */
import { ArrowDown, ArrowUp, FileStack, Plus, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { searchApi, type DocumentInfo } from '../api/client'
import { pageToolsApi } from '../api/pagetools'
import { shortDate } from '../lib/dates'
import { Button } from './Button'
import { Dialog } from './Dialog'
import { PageThumb } from './PageThumb'
import { codeOf } from '../lib/toolErrors'
import { ToolProblem } from './ToolProblem'

type Item = Pick<DocumentInfo, 'id' | 'title' | 'vault_id' | 'current_version' | 'pages'> & Partial<Pick<DocumentInfo, 'sender' | 'date'>>

export type MergeDialogProps = {
  /** The document the dialog was opened on: first in the order until it is moved. */
  document: Item
  onClose: () => void
  /** Joined: the first document as it is now (the page shows it); the others are in the trash. */
  onMerged: (document: DocumentInfo) => void
  say?: (text: string) => void
}

const SHOWN = 6
const WAIT_MS = 250

export function MergeDialog({ document, onClose, onMerged, say }: MergeDialogProps) {
  const { t, i18n } = useTranslation()
  const [q, setQ] = useState('')
  const [found, setFound] = useState<DocumentInfo[]>([])
  const [order, setOrder] = useState<Item[]>([document])
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  /** A request on its way: a second click does nothing. */
  const running = useRef(false)

  useEffect(() => {
    const control = new AbortController()
    const timer = window.setTimeout(() => {
      searchApi
        .find(q.trim(), { vault_id: document.vault_id, status: 'filed', limit: SHOWN + 10 }, control.signal)
        .then((result) => setFound(result.items.map((hit) => hit.document)))
        .catch((error: unknown) => {
          if (!(error instanceof DOMException && error.name === 'AbortError')) setProblem(codeOf(error))
        })
    }, q ? WAIT_MS : 0)
    return () => {
      window.clearTimeout(timer)
      control.abort()
    }
  }, [q, document.vault_id])

  const chosen = new Set(order.map((item) => item.id))
  const list = found.filter((x) => !chosen.has(x.id)).slice(0, SHOWN)
  const shift = (index: number, by: -1 | 1) => {
    const next = [...order]
    ;[next[index], next[index + by]] = [next[index + by], next[index]]
    setOrder(next)
  }
  const pages = order.reduce((sum, item) => sum + item.pages, 0)

  const join = async () => {
    if (running.current || busy || order.length < 2) return
    running.current = true
    setBusy(true)
    setProblem(null)
    const [first, ...others] = order
    try {
      const joined = await pageToolsApi.merge(
        first.id,
        first.current_version,
        others.map((item) => ({ id: item.id, base_version: item.current_version })),
      )
      say?.(t('pagetools.merge.done', { count: joined.pages }))
      onMerged(joined)
      onClose()
    } catch (error) {
      setProblem(codeOf(error))
    } finally {
      running.current = false
      setBusy(false)
    }
  }

  return (
    <Dialog title={t('pagetools.merge.title')} onClose={onClose}>
      <p className="-mt-2 mb-3 text-sm text-ink-2">{t('pagetools.merge.intro', { title: order[0].title })}</p>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('pagetools.merge.search')} aria-label={t('pagetools.merge.search')} className="input mb-3" autoFocus />
      <ul className="space-y-1.5">
        {list.map((x) => (
          <li key={x.id}>
            <button
              type="button"
              onClick={() => setOrder([...order, x])}
              aria-label={t('pagetools.merge.add', { title: x.title })}
              className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm hover:bg-sheet-2"
            >
              <span className="w-8 shrink-0">
                <PageThumb document={x.id} version={x.current_version} page={1} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-semibold">{x.title}</span>
                <span className="text-xs text-muted">
                  {[x.sender?.name, x.date ? shortDate(x.date, i18n.language) : null, t('pagetools.pages', { count: x.pages })].filter(Boolean).join(' · ')}
                </span>
              </span>
              <Plus size={14} className="text-muted" />
            </button>
          </li>
        ))}
        {list.length === 0 && <li className="px-3 py-2 text-sm text-muted">{t('pagetools.merge.none')}</li>}
      </ul>
      {order.length > 1 && (
        <div className="mt-4 border-t border-line pt-4">
          <p className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{t('pagetools.merge.order')}</p>
          <ol className="space-y-2" data-testid="merge-order">
            {order.map((item, index) => (
              <li key={item.id} className="flex items-center gap-3 rounded-xl bg-sheet-2/60 px-4 py-2.5 text-sm">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-bold text-accent-ink">{index + 1}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-semibold">{item.title}</span>
                  <span className="text-xs text-muted">
                    {t('pagetools.pages', { count: item.pages })}
                    {index === 0 ? ` · ${t('pagetools.merge.keeps')}` : ''}
                  </span>
                </span>
                <button type="button" disabled={index === 0} onClick={() => shift(index, -1)} className="rounded-full p-1 text-muted hover:text-ink disabled:opacity-30" aria-label={t('pagetools.merge.up', { title: item.title })}>
                  <ArrowUp size={14} />
                </button>
                <button type="button" disabled={index === order.length - 1} onClick={() => shift(index, 1)} className="rounded-full p-1 text-muted hover:text-ink disabled:opacity-30" aria-label={t('pagetools.merge.down', { title: item.title })}>
                  <ArrowDown size={14} />
                </button>
                <button type="button" onClick={() => setOrder(order.filter((other) => other.id !== item.id))} disabled={order.length === 1} className="rounded-full p-1 text-muted hover:text-ink disabled:opacity-30" aria-label={t('pagetools.merge.remove', { title: item.title })}>
                  <X size={14} />
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}
      <ToolProblem code={problem} />
      <div className="mt-5 flex flex-wrap items-center gap-2">
        <Button variant="primary" size="sm" disabled={busy || order.length < 2} onClick={join}>
          <FileStack size={15} /> {t('pagetools.merge.go')}
        </Button>
        {order.length > 1 && <span className="text-xs text-muted">{t('pagetools.pages', { count: pages })}</span>}
      </div>
    </Dialog>
  )
}
