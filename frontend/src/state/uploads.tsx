/**
 * The uploads of this page: one queue (`lib/uploader.ts`) for the whole app, a hidden file input that the button in the
 * menu and the one in the phone's header both open, and the whole page as a place to drop files on (the mock's way). The
 * list of what is being uploaded and what came of it is `components/UploadPanel.tsx`.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ChangeEvent, type ReactNode } from 'react'

import { useLocation, useNavigate } from 'react-router-dom'

import { type UploadTarget } from '../api/client'
import { ACCEPT } from '../lib/formats'
import { inboxChanged } from '../lib/say'
import { Uploader, type Entry, type Summary } from '../lib/uploader'

type Uploads = {
  entries: readonly Entry[]
  /** Opens the dialog that chooses files. */
  pick: () => void
  /** Files to upload; `target` names the vault and where they came from (else the person's choice). */
  add: (files: File[], target?: UploadTarget) => void
  cancel: (id: number) => void
  resume: (id: number) => void
  retry: (id: number) => void
  clear: () => void
  /** What came of the last run of the queue, until it is shown. */
  summary: Summary | null
  dismissSummary: () => void
  /** Files are being dragged over the page. */
  dragging: boolean
}

const Context = createContext<Uploads | null>(null)

/** The phone's pages with their own way of showing uploads: no jump to the inbox from there. */
const PHONE_PAGES = ['/schnell', '/teilen', '/kamera']

export function UploadProvider({ children, uploader: given }: { children: ReactNode; uploader?: Uploader }) {
  const uploader = useMemo(() => given ?? new Uploader(), [given])
  const entries = useSyncExternalStore(uploader.subscribe, uploader.getSnapshot)
  const input = useRef<HTMLInputElement>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [dragging, setDragging] = useState(false)
  const navigate = useNavigate()
  const { pathname } = useLocation()
  // After files were chosen or dropped in the full app, the inbox opens (as the mock does): that is where they land. The
  // phone's pages keep their own list.
  const toInbox = useRef(() => {})
  toInbox.current = () => {
    if (!PHONE_PAGES.includes(pathname) && !pathname.startsWith('/eingang')) navigate('/eingang')
  }

  useEffect(
    () =>
      uploader.whenIdle((summary) => {
        setSummary(summary)
        // New documents: the inbox, its count in the menu and the counts of the vaults are told.
        inboxChanged()
      }),
    [uploader],
  )

  // The whole page takes dropped files, not only a field: the overlay says so while something is dragged over it.
  useEffect(() => {
    const files = (event: DragEvent) => !!event.dataTransfer?.types.includes('Files')
    const over = (event: DragEvent) => {
      if (!files(event)) return
      event.preventDefault()
      setDragging(true)
    }
    const leave = (event: DragEvent) => {
      if (!event.relatedTarget) setDragging(false)
    }
    const drop = (event: DragEvent) => {
      if (!files(event)) return
      event.preventDefault()
      setDragging(false)
      const dropped = Array.from(event.dataTransfer?.files ?? [])
      if (dropped.length) {
        uploader.add(dropped)
        toInbox.current()
      }
    }
    window.addEventListener('dragover', over)
    window.addEventListener('dragleave', leave)
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragover', over)
      window.removeEventListener('dragleave', leave)
      window.removeEventListener('drop', drop)
    }
  }, [uploader])

  const value = useMemo<Uploads>(
    () => ({
      entries,
      pick: () => input.current?.click(),
      add: (files, target) => uploader.add(files, target),
      cancel: (id) => uploader.cancel(id),
      resume: (id) => uploader.resume(id),
      retry: (id) => uploader.retry(id),
      clear: () => uploader.clear(),
      summary,
      dismissSummary: () => setSummary(null),
      dragging,
    }),
    [entries, uploader, summary, dragging],
  )
  const choose = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const chosen = Array.from(event.target.files ?? [])
      // The same file may be chosen again later: the field forgets it.
      event.target.value = ''
      if (chosen.length) {
        uploader.add(chosen)
        toInbox.current()
      }
    },
    [uploader],
  )
  return (
    <Context.Provider value={value}>
      <input ref={input} type="file" multiple accept={ACCEPT} className="hidden" data-testid="upload-input" tabIndex={-1} aria-hidden onChange={choose} />
      {children}
    </Context.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useUploads(): Uploads {
  const value = useContext(Context)
  if (!value) throw new Error('useUploads needs an UploadProvider')
  return value
}
