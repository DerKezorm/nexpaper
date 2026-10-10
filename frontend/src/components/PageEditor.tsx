/**
 * "Seiten bearbeiten" on a document, as the mock draws it: tap a page, then turn it, move it or delete it; "Speichern" makes a
 * new version on the server (the original file stays as it came). "Ab hier eigenes Dokument" splits the document at the page
 * chosen (both parts go to the inbox, the document to the trash) after one more click to confirm.
 *
 * The editor works on the current version (`document.current_version`) and names it when it saves: when somebody else changed
 * the document in the meantime the server says so, nothing is saved, and "Neu laden" starts again from the version that is
 * current now. A second click while the first one is on its way does nothing.
 */
import { ArrowLeft, ArrowRight, Check, RefreshCw, RotateCcw, RotateCw, Scissors, Trash2 } from 'lucide-react'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { documentsApi, type DocumentInfo } from '../api/client'
import { pageToolsApi, turnOf } from '../api/pagetools'
import { Button } from './Button'
import { PageThumb } from './PageThumb'
import { codeOf } from '../lib/toolErrors'
import { ToolProblem } from './ToolProblem'

export type PageEditorProps = {
  document: Pick<DocumentInfo, 'id' | 'pages' | 'current_version'>
  /** Saved (the document as it is now) or cancelled (`null`). */
  onDone: (document: DocumentInfo | null) => void
  /** "Ab hier eigenes Dokument" made two new documents in the inbox; the document went to the trash. */
  onSplit?: (parts: DocumentInfo[]) => void
  /** What was done, in a sentence, for the page to show. */
  say?: (text: string) => void
  /** "Neu laden" after a change in the meantime: the document as it is now (the page may show it too). */
  onReloaded?: (document: DocumentInfo) => void
}

type Sheet = { i: number; rot: number }
type Shown = Pick<DocumentInfo, 'id' | 'pages' | 'current_version'>

const fresh = (count: number): Sheet[] => Array.from({ length: count }, (_, i) => ({ i, rot: 0 }))

export function PageEditor({ document: given, onDone, onSplit, say, onReloaded }: PageEditorProps) {
  const { t } = useTranslation()
  const [document, setDocument] = useState<Shown>(given)
  const [pages, setPages] = useState<Sheet[]>(() => fresh(given.pages))
  const [sel, setSel] = useState(0)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [asking, setAsking] = useState(false)
  /** A request on its way: a second click does nothing (the state of `busy` comes a moment later). */
  const running = useRef(false)

  const run = async (work: () => Promise<void>) => {
    if (running.current) return
    running.current = true
    setBusy(true)
    setProblem(null)
    try {
      await work()
    } catch (error) {
      setProblem(codeOf(error))
    } finally {
      running.current = false
      setBusy(false)
    }
  }

  const reload = () =>
    run(async () => {
      const now = await documentsApi.read(document.id)
      setDocument(now)
      setPages(fresh(now.pages))
      setSel(0)
      setAsking(false)
      onReloaded?.(now)
    })

  const move = (dir: -1 | 1) => {
    const j = sel + dir
    if (j < 0 || j >= pages.length) return
    const p = [...pages]
    ;[p[sel], p[j]] = [p[j], p[sel]]
    setPages(p)
    setSel(j)
  }
  const turn = (by: number) => setPages(pages.map((p, k) => (k === sel ? { ...p, rot: p.rot + by } : p)))
  const specs = (list: Sheet[]) => list.map((p) => ({ page: p.i + 1, turn: turnOf(p.rot) }))

  const save = () =>
    run(async () => {
      const unchanged = pages.every((p, k) => p.i === k && turnOf(p.rot) === 0) && pages.length === document.pages
      if (unchanged) {
        say?.(t('pagetools.editor.unchanged'))
        onDone(null)
        return
      }
      const saved = await pageToolsApi.editPages(document.id, document.current_version, specs(pages))
      say?.(t('pagetools.editor.saved'))
      onDone(saved)
    })

  const splitHere = () =>
    run(async () => {
      try {
        const made = await pageToolsApi.split(document.id, document.current_version, [{ pages: specs(pages.slice(0, sel)) }, { pages: specs(pages.slice(sel)) }])
        say?.(t('pagetools.editor.splitDone'))
        onSplit?.(made.items)
      } finally {
        setAsking(false)
      }
    })

  const tool = 'inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1.5 text-sm font-semibold text-ink-2 hover:bg-sheet-2 disabled:opacity-40'
  return (
    <div data-testid="page-editor">
      <p className="mb-3 text-sm text-ink-2">{t('pagetools.editor.hint')}</p>
      <div className="flex flex-wrap gap-3">
        {pages.map((p, k) => (
          <button
            key={p.i}
            type="button"
            onClick={() => {
              setSel(k)
              setAsking(false)
            }}
            aria-label={t('pagetools.editor.pick', { n: k + 1 })}
            aria-pressed={sel === k}
            className={`w-28 rounded-lg p-1.5 ring-2 ${sel === k ? 'ring-accent' : 'ring-transparent'}`}
          >
            <PageThumb document={document.id} version={document.current_version} page={p.i + 1} turn={p.rot} />
            <span className="mt-1 block text-xs text-muted">{k + 1}</span>
          </button>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" className={tool} onClick={() => turn(-90)}>
          <RotateCcw size={14} /> {t('pagetools.editor.left')}
        </button>
        <button type="button" className={tool} onClick={() => turn(90)}>
          <RotateCw size={14} /> {t('pagetools.editor.right')}
        </button>
        <button type="button" className={tool} disabled={sel === 0} onClick={() => move(-1)}>
          <ArrowLeft size={14} /> {t('pagetools.editor.forward')}
        </button>
        <button type="button" className={tool} disabled={sel === pages.length - 1} onClick={() => move(1)}>
          {t('pagetools.editor.back')} <ArrowRight size={14} />
        </button>
        <button
          type="button"
          className={tool}
          disabled={pages.length < 2}
          onClick={() => {
            setPages(pages.filter((_, k) => k !== sel))
            setSel(Math.max(0, sel - 1))
          }}
        >
          <Trash2 size={14} /> {t('pagetools.editor.delete')}
        </button>
        <button type="button" className={tool} disabled={sel === 0 || !onSplit} onClick={() => setAsking(true)}>
          <Scissors size={14} /> {t('pagetools.editor.fromHere')}
        </button>
      </div>
      {asking && (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-sheet-2/60 px-4 py-2.5 text-sm" role="group">
          <span className="flex-1 text-ink-2">{t('pagetools.editor.fromHereAsk', { n: sel + 1 })}</span>
          <Button size="sm" variant="soft" disabled={busy} onClick={splitHere}>
            <Scissors size={14} /> {t('pagetools.editor.fromHereGo')}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setAsking(false)}>
            {t('pagetools.editor.cancel')}
          </Button>
        </div>
      )}
      <ToolProblem code={problem} />
      {problem === 'version_changed' && (
        <Button className="mt-2" size="sm" variant="soft" disabled={busy} onClick={reload}>
          <RefreshCw size={14} /> {t('pagetools.editor.reload')}
        </Button>
      )}
      <div className="mt-5 flex gap-2 border-t border-line pt-4">
        <Button variant="primary" size="sm" disabled={busy} onClick={save}>
          <Check size={15} /> {t('pagetools.editor.save')}
        </Button>
        <Button variant="ghost" size="sm" disabled={busy} onClick={() => onDone(null)}>
          {t('pagetools.editor.cancel')}
        </Button>
      </div>
    </div>
  )
}
