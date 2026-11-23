import { X } from 'lucide-react'
import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'

/** The dialogs that are open, the last one on top: only that one answers to Escape (a "really?" over a dialog must not
 * close the dialog under it as well). */
const open: symbol[] = []

/** A dialog over the page: from below on a phone, in the middle on a larger screen. Escape and the scrim
 * close it, focus starts inside and comes back afterwards. `medium`: a little wider, for a form of several parts (as
 * nexnotes' medium dialog). `above`: over everything, also over the big view of a photo
 * (drawn into the body, outside the page behind, which stands still while that view is open). */
export function Dialog({ title, onClose, children, wide = false, medium = false, above = false }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean; medium?: boolean; above?: boolean }) {
  const { t } = useTranslation()
  const panel = useRef<HTMLDivElement>(null)
  // The latest way to close, kept apart from the effect: the dialog starts once, however often its page draws it anew.
  const closer = useRef(onClose)
  closer.current = onClose
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null
    const me = Symbol('dialog')
    open.push(me)
    const first = panel.current?.querySelector<HTMLElement>('[data-autofocus]') ?? panel.current?.querySelector<HTMLElement>('input, textarea, select, button:not([data-close])')
    first?.focus()
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open[open.length - 1] === me) {
        e.stopPropagation()
        closer.current()
      }
    }
    window.addEventListener('keydown', key, true)
    return () => {
      window.removeEventListener('keydown', key, true)
      open.splice(open.indexOf(me), 1)
      before?.focus?.()
    }
  }, [])
  const dialog = (
    <div className={`fixed inset-0 ${above ? 'z-[70]' : 'z-50'} flex items-end justify-center bg-scrim p-0 sm:items-center sm:p-6`} onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      {/* As nexnotes' dialog: 16 px corners, a head with a line below it, the content scrolling under it. */}
      <div ref={panel} role="dialog" aria-modal="true" aria-label={title} className={`rise flex max-h-[92dvh] w-full min-w-0 flex-col rounded-t-[16px] border border-line bg-sheet shadow-2xl shadow-black/25 sm:rounded-b-[16px] ${wide ? 'max-w-3xl' : medium ? 'max-w-xl' : 'max-w-lg'}`}>
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-line px-5 py-3.5">
          <h2 className="min-w-0 text-base font-semibold">{title}</h2>
          <button type="button" data-close onClick={onClose} className="rounded-full p-1.5 text-muted hover:bg-sheet-2 hover:text-ink" aria-label={t('common.close')}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="soft-scroll min-h-0 overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  )
  return above ? createPortal(dialog, document.body) : dialog
}
