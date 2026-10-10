/**
 * "Stapelscan aufteilen?" in the inbox, as the mock draws it: the blank separator pages the server found mark where one
 * letter ends. A click between two pages cuts there or joins again; a page taken for a separator by mistake can be kept. Each
 * part becomes a document of its own in the inbox (the separators are dropped), the stack goes to the trash. "Als ein
 * Dokument behalten" puts the proposal away for good.
 *
 * Also usable on a document without a proposal: then there is nothing to drop and every cut is the person's own.
 */
import { Scissors } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import type { DocumentInfo } from '../api/client'
import { pageToolsApi, type Separators } from '../api/pagetools'
import { partsOf } from '../lib/splitParts'
import { Button } from './Button'
import { PageThumb } from './PageThumb'
import { codeOf } from '../lib/toolErrors'
import { ToolProblem } from './ToolProblem'

export type SplitPanelProps = {
  document: Pick<DocumentInfo, 'id' | 'title' | 'pages' | 'current_version' | 'source'>
  /** Split: the new documents, in order (the first one is where the inbox goes on). */
  onSplit: (parts: DocumentInfo[]) => void
  /** "Als ein Dokument behalten": the proposal is put away. */
  onKeep: () => void
  /** What stands above the title (the inbox's way back to its list on a phone). */
  back?: ReactNode
  say?: (text: string) => void
}

export function SplitPanel({ document, onSplit, onKeep, back, say }: SplitPanelProps) {
  const { t } = useTranslation()
  const [found, setFound] = useState<Separators | null>(null)
  const [cuts, setCuts] = useState<Set<number>>(new Set())
  const [dropped, setDropped] = useState<Set<number>>(new Set())
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  /** A request on its way: a second click does nothing. */
  const running = useRef(false)

  useEffect(() => {
    let live = true
    pageToolsApi
      .separators(document.id)
      .then((answer) => {
        if (!live) return
        setFound(answer)
        setDropped(new Set(answer.blank_pages.map((page) => page - 1)))
        setCuts(new Set(answer.parts.slice(1).map((part) => part[0] - 1)))
      })
      .catch((error: unknown) => live && setProblem(codeOf(error)))
    return () => {
      live = false
    }
  }, [document.id, document.current_version])

  const parts = partsOf(document.pages, cuts, dropped)
  const toggle = (set: Set<number>, value: number, change: (next: Set<number>) => void) => {
    const next = new Set(set)
    if (next.has(value)) next.delete(value)
    else next.add(value)
    change(next)
  }
  const partOf = (i: number) => parts.findIndex((p) => p.includes(i))
  const separators = [...dropped].length
  const source = t(`pagetools.split.from.${document.source}`, { defaultValue: '' })

  const split = async () => {
    if (running.current || busy || parts.length < 2) return
    running.current = true
    setBusy(true)
    setProblem(null)
    try {
      const made = await pageToolsApi.split(
        document.id,
        document.current_version,
        parts.map((part) => ({ pages: part.map((i) => ({ page: i + 1, turn: 0 as const })) })),
      )
      say?.(separators ? t('pagetools.split.done', { count: parts.length }) : t('pagetools.split.doneNoBlanks', { count: parts.length }))
      onSplit(made.items)
    } catch (error) {
      setProblem(codeOf(error))
    } finally {
      running.current = false
      setBusy(false)
    }
  }

  const keep = async () => {
    if (running.current || busy) return
    running.current = true
    setBusy(true)
    setProblem(null)
    try {
      await pageToolsApi.keepAsOne(document.id)
      say?.(t('pagetools.split.kept'))
      onKeep()
    } catch (error) {
      setProblem(codeOf(error))
    } finally {
      running.current = false
      setBusy(false)
    }
  }

  return (
    <div className="card min-w-0 p-5" data-testid="split-panel">
      {back}
      <p className="flex items-center gap-2 font-display text-xl font-semibold">
        <Scissors size={19} className="text-accent" /> {t('pagetools.split.title')}
      </p>
      <p className="mt-1 text-sm text-ink-2">
        {source ? t('pagetools.split.lead', { count: document.pages, from: source }) : t('pagetools.pages', { count: document.pages }) + '.'}{' '}
        {found && found.blank_pages.length > 0
          ? t('pagetools.split.found', { count: found.blank_pages.length, parts: Math.max(found.parts.length, 1) })
          : found
            ? t('pagetools.split.foundNone')
            : ''}{' '}
        {found?.duplex ? t('pagetools.split.duplex') + ' ' : ''}
        {t('pagetools.split.click')}
      </p>
      <div className="scroll-x mt-5 flex items-end gap-1 overflow-x-auto pb-2">
        {Array.from({ length: document.pages }, (_, i) => (
          <div key={i} className="flex items-end gap-1">
            {i > 0 && !dropped.has(i) && !dropped.has(i - 1) && !cuts.has(i) && (
              <button type="button" onClick={() => toggle(cuts, i, setCuts)} className="mb-10 h-16 w-3 shrink-0 rounded-full hover:bg-accent-soft" aria-label={t('pagetools.split.cut')} title={t('pagetools.split.cut')} />
            )}
            {i > 0 && !dropped.has(i) && !dropped.has(i - 1) && cuts.has(i) && (
              <button type="button" onClick={() => toggle(cuts, i, setCuts)} className="mb-10 flex h-16 w-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent" aria-label={t('pagetools.split.join')}>
                <Scissors size={13} />
              </button>
            )}
            <div className="w-24 shrink-0 text-center">
              {dropped.has(i) ? (
                <button type="button" className="block w-full opacity-50 hover:opacity-80" onClick={() => toggle(dropped, i, setDropped)} aria-label={t('pagetools.split.notSeparator', { n: i + 1 })} title={t('pagetools.split.notSeparator', { n: i + 1 })}>
                  <PageThumb document={document.id} version={document.current_version} page={i + 1} />
                </button>
              ) : (
                <PageThumb document={document.id} version={document.current_version} page={i + 1} className={partOf(i) % 2 ? 'ring-2 ring-accent/30' : ''} />
              )}
              <p className="mt-1 text-xs text-muted">{dropped.has(i) ? t('pagetools.split.separator') : t('pagetools.page', { n: i + 1 })}</p>
            </div>
          </div>
        ))}
      </div>
      <ol className="mt-4 space-y-2">
        {parts.map((p, i) => (
          <li key={p[0]} className="flex items-center gap-3 rounded-xl bg-sheet-2/60 px-4 py-2.5 text-sm">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-bold text-accent-ink">{i + 1}</span>
            <span className="min-w-0 flex-1 truncate font-semibold">{t('pagetools.split.part', { title: document.title, n: i + 1 })}</span>
            <span className="text-muted">{t('pagetools.split.partPages', { count: p.length, list: p.map((x) => x + 1).join(', ') })}</span>
          </li>
        ))}
      </ol>
      <ToolProblem code={problem} />
      <div className="mt-5 flex flex-wrap gap-2">
        <Button variant="primary" disabled={busy || parts.length < 2} onClick={split}>
          <Scissors size={16} /> {t('pagetools.split.go', { count: parts.length })}
        </Button>
        <Button variant="ghost" disabled={busy} onClick={keep}>
          {t('pagetools.split.keep')}
        </Button>
      </div>
      <p className="mt-4 text-xs text-muted">{t('pagetools.split.tip')}</p>
    </div>
  )
}
