/**
 * What can be done with one version beside downloading it, in its row of the document's list of versions: "Zurückholen"
 * on a version that was read and is not the current one (it comes back as a new version; nothing is deleted), "Verwerfen"
 * on an uploaded version that could not be read. A second click while the first is on its way does nothing.
 *
 * `UploadVersionDialog` is "Neue Fassung hochladen" from the document's menu: a file, and on request a note on what is new.
 */
import { FileUp, RotateCcw, Trash2, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { DocumentInfo, DocumentVersion } from '../api/client'
import { pageToolsApi, type VersionInfo } from '../api/pagetools'
import { ACCEPT } from '../lib/formats'
import { codeOf, toolText } from '../lib/toolErrors'
import { Button } from './Button'
import { Dialog } from './Dialog'
import { useConfirm } from './useConfirm'
import { ToolProblem } from './ToolProblem'

export type VersionRowActionsProps = {
  document: Pick<DocumentInfo, 'id' | 'current_version'>
  version: Pick<DocumentVersion, 'n' | 'current' | 'state'>
  /** The caller may change the document (`edit`). */
  canEdit: boolean
  /** Done: the document as it is now (restored) or nothing (a version put away); the page loads again. */
  onDone: (document: DocumentInfo | null) => void
  /** A sentence for the page: what was done, or what went wrong. */
  say?: (text: string) => void
}

export function VersionRowActions({ document, version: v, canEdit, onDone, say }: VersionRowActionsProps) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const running = useRef(false)
  const { ask, dialog } = useConfirm()
  const state = v.state ?? 'ready'

  const run = async (work: () => Promise<void>) => {
    if (running.current) return
    running.current = true
    setBusy(true)
    try {
      await work()
    } catch (error) {
      say?.(toolText(codeOf(error)))
    } finally {
      running.current = false
      setBusy(false)
    }
  }
  const restore = () =>
    run(async () => {
      const now = await pageToolsApi.restore(document.id, v.n, document.current_version)
      say?.(t('pagetools.versions.restored', { n: v.n, m: now.current_version }))
      onDone(now)
    })
  /** Puts a version away that could not be read, after asking: its file goes with it. */
  const discard = () =>
    ask({
      title: t('confirm.version.title', { n: v.n }),
      text: t('confirm.version.text', { n: v.n }),
      confirm: t('confirm.version.confirm'),
      run: () =>
        run(async () => {
          await pageToolsApi.discard(document.id, v.n)
          say?.(t('pagetools.versions.discarded', { n: v.n }))
          onDone(null)
        }),
    })

  if (!canEdit || v.current) return null
  if (state === 'ready')
    return (
      <Button size="sm" variant="ghost" className="shrink-0 px-2.5 sm:px-3.5" disabled={busy} onClick={restore} aria-label={t('pagetools.versions.restoreLabel', { n: v.n })} title={t('pagetools.versions.restoreLabel', { n: v.n })}>
        <RotateCcw size={14} /> <span className="hidden sm:inline">{t('pagetools.versions.restore')}</span>
      </Button>
    )
  if (state === 'failed')
    return (
      <>
        <Button size="sm" variant="ghost" className="shrink-0 px-2.5 sm:px-3.5" disabled={busy} onClick={discard} aria-label={t('pagetools.versions.discardLabel', { n: v.n })} title={t('pagetools.versions.discardLabel', { n: v.n })}>
          <Trash2 size={14} /> <span className="hidden sm:inline">{t('pagetools.versions.discard')}</span>
        </Button>
        {dialog}
      </>
    )
  return null
}

export type UploadVersionDialogProps = {
  document: Pick<DocumentInfo, 'id' | 'title'>
  onClose: () => void
  /** The new version is on the server and is being read (`state: processing`). */
  onUploaded: (version: VersionInfo) => void
  say?: (text: string) => void
}

export function UploadVersionDialog({ document, onClose, onUploaded, say }: UploadVersionDialogProps) {
  const { t } = useTranslation()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const running = useRef(false)

  const send = async () => {
    if (running.current || !file) return
    running.current = true
    setBusy(true)
    setProblem(null)
    try {
      const made = await pageToolsApi.uploadVersion(document.id, file, note.trim())
      say?.(t('pagetools.versions.uploaded'))
      onUploaded(made)
      onClose()
    } catch (error) {
      setProblem(codeOf(error))
    } finally {
      running.current = false
      setBusy(false)
    }
  }

  return (
    <Dialog title={t('pagetools.versions.upload')} onClose={onClose}>
      <p className="-mt-2 mb-3 text-sm text-ink-2">{t('pagetools.versions.note')}</p>
      <input ref={input} type="file" accept={ACCEPT} className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} data-testid="version-file" />
      <Button variant="line" size="sm" onClick={() => input.current?.click()}>
        <FileUp size={15} /> {file ? file.name : t('pagetools.versions.uploadPick')}
      </Button>
      <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} placeholder={t('pagetools.versions.uploadNote')} aria-label={t('pagetools.versions.uploadNote')} className="input mt-3" />
      <ToolProblem code={problem} />
      <div className="mt-5 flex gap-2">
        <Button variant="primary" size="sm" disabled={busy || !file} onClick={send}>
          <Upload size={15} /> {t('pagetools.versions.upload')}
        </Button>
        <Button variant="ghost" size="sm" disabled={busy} onClick={onClose}>
          {t('pagetools.editor.cancel')}
        </Button>
      </div>
    </Dialog>
  )
}
