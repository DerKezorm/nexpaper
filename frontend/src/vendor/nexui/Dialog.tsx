/**
 * A dialog over the page (nexnotes' `Dialog`: 16 px corners, a head with the title and a close button, the inside
 * scrolls), and on it `ConfirmDialog`: "Really?" with an optional field (the own password), the problem in red, and the
 * buttons right below, "Cancel" first. Escape and the scrim close it, focus starts inside and comes back afterwards.
 * `dismissable={false}` (since E38): Escape and a click beside it do nothing; the close button and the dialog's own
 * buttons ("Cancel", "Done") stay. Since E47 Escape closes only the topmost open dialog (the one opened last), never
 * every dialog of a stack at once; a topmost one that is not dismissable keeps Escape for itself. Since 1.3.1 the focus
 * stays inside: Tab and Shift+Tab go round, and a focused button that goes with a change of the inside hands the focus
 * back to the dialog's first field or button.
 */
import { useEffect, useId, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'

import { Button } from './Button'
import type { IconLike } from './icons'
import { MUTED, PLAIN, type ButtonKind } from './styles'

/** The open dialogs, the one opened last at the end: only it hears Escape (since E47). */
const OPEN: symbol[] = []
/** Where the focus starts: the first field or button, never the close button. */
const START = 'input:not([type="hidden"]), textarea, select, button:not([data-close])'
/** What Tab reaches inside the dialog (since 1.3.1). */
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function Dialog({
  title,
  onClose,
  closeLabel,
  children,
  wide = false,
  dismissable = true,
  testId,
}: {
  title: string
  onClose: () => void
  /** The name of the close button ("Close"). */
  closeLabel: string
  children: ReactNode
  wide?: boolean
  /** False: Escape and a click beside the dialog leave it open (a step that must be finished). */
  dismissable?: boolean
  testId?: string
}) {
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)
  const close = useRef(onClose)
  const leave = useRef(dismissable)
  useEffect(() => {
    close.current = onClose
    leave.current = dismissable
  }, [onClose, dismissable])
  useEffect(() => {
    const me = Symbol('dialog')
    OPEN.push(me)
    const before = document.activeElement as HTMLElement | null
    const start = () => panel.current?.querySelector<HTMLElement>(START)?.focus()
    start()
    const key = (event: KeyboardEvent) => {
      // Only the topmost dialog answers; the ones below it stay open.
      if (OPEN[OPEN.length - 1] !== me) return
      if (event.key === 'Escape') {
        event.stopPropagation()
        if (leave.current) close.current()
      }
      // Since 1.3.1: Tab and Shift+Tab stay inside (aria-modal), from the last to the first and back.
      if (event.key === 'Tab' && panel.current) {
        const all = Array.from(panel.current.querySelectorAll<HTMLElement>(FOCUSABLE))
        if (all.length === 0) return
        const at = document.activeElement
        const inside = at instanceof HTMLElement && panel.current.contains(at)
        const [first, last] = [all[0], all.at(-1)]
        if (event.shiftKey && (!inside || at === first)) {
          event.preventDefault()
          last?.focus()
        } else if (!event.shiftKey && (!inside || at === last)) {
          event.preventDefault()
          first?.focus()
        }
      }
    }
    // Since 1.3.1: when the focused button goes with a change inside (a step that follows, "Abbrechen" becoming
    // "Fertig"), the focus comes back into the dialog instead of falling onto the page.
    const lost = new MutationObserver(() => {
      const at = document.activeElement
      if (OPEN[OPEN.length - 1] === me && (at === null || at === document.body)) start()
    })
    if (panel.current) lost.observe(panel.current, { childList: true, subtree: true })
    window.addEventListener('keydown', key, true)
    return () => {
      lost.disconnect()
      window.removeEventListener('keydown', key, true)
      OPEN.splice(OPEN.indexOf(me), 1)
      before?.focus?.()
    }
  }, [])
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-[var(--nexui-scrim)] p-4" onPointerDown={(event) => dismissable && event.target === event.currentTarget && onClose()}>
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid={testId}
        className={`flex max-h-[calc(100dvh-2rem)] w-full min-w-0 flex-col rounded-[16px] border border-solid border-[var(--nexui-line)] bg-[var(--nexui-surface)] text-[var(--nexui-text)] tracking-normal shadow-2xl ${wide ? 'max-w-2xl' : 'max-w-md'}`}
      >
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-solid border-[var(--nexui-line)] px-5 py-3.5">
          <h2 id={titleId} className={`${PLAIN} min-w-0 text-base leading-6 font-semibold text-[var(--nexui-text)]`}>
            {title}
          </h2>
          <button
            type="button"
            data-close
            aria-label={closeLabel}
            title={closeLabel}
            onClick={onClose}
            className={`inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-full border-0 bg-transparent ${MUTED} hover:bg-[var(--nexui-surface-hover)] hover:text-[var(--nexui-text)] focus-visible:outline-2 focus-visible:outline-[var(--nexui-accent)]`}
          >
            <X aria-hidden className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  )
}

/** The button that confirms: its words, kind and symbol (from the app's table of buttons). */
export type Confirm = { label: string; kind: ButtonKind; icon: IconLike }

export function ConfirmDialog({
  title,
  text,
  children,
  confirm,
  cancel,
  closeLabel,
  onConfirm,
  onCancel,
  busy = false,
  error,
  confirmDisabled = false,
  dismissable = true,
  testId,
}: {
  title: string
  text?: ReactNode
  /** More between the text and the buttons: the own password, what a step changes. */
  children?: ReactNode
  confirm: Confirm
  /** The words of "Cancel" (secondary, X). */
  cancel: string
  closeLabel: string
  onConfirm: () => void
  onCancel: () => void
  busy?: boolean
  error?: ReactNode
  confirmDisabled?: boolean
  /** False: only "Cancel", the confirming button and the close button end it (since E38). */
  dismissable?: boolean
  testId?: string
}) {
  return (
    <Dialog title={title} onClose={onCancel} closeLabel={closeLabel} dismissable={dismissable} testId={testId}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault()
          if (!busy && !confirmDisabled) onConfirm()
        }}
      >
        {text && <p className={`${PLAIN} text-sm leading-5 text-[var(--nexui-text)]`}>{text}</p>}
        {children}
        {error && (
          <p role="alert" className={`${PLAIN} text-sm leading-5 text-[var(--nexui-danger)]`}>
            {error}
          </p>
        )}
        <div className="flex flex-wrap justify-end gap-2">
          <Button kind="secondary" icon="X" onClick={onCancel}>
            {cancel}
          </Button>
          <Button type="submit" kind={confirm.kind} icon={confirm.icon} busy={busy} disabled={confirmDisabled}>
            {confirm.label}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
