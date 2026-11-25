/**
 * A dialog over the page (nexnotes' `Dialog`: 16 px corners, a head with the title and a close button, the inside
 * scrolls), and on it `ConfirmDialog`: "Really?" with an optional field (the own password), the problem in red, and the
 * buttons right below, "Cancel" first. Escape and the scrim close it, focus starts inside and comes back afterwards.
 */
import { useEffect, useId, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'

import { Button } from './Button'
import type { IconLike } from './icons'
import { MUTED, PLAIN, type ButtonKind } from './styles'

export function Dialog({
  title,
  onClose,
  closeLabel,
  children,
  wide = false,
  testId,
}: {
  title: string
  onClose: () => void
  /** The name of the close button ("Close"). */
  closeLabel: string
  children: ReactNode
  wide?: boolean
  testId?: string
}) {
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)
  const close = useRef(onClose)
  useEffect(() => {
    close.current = onClose
  }, [onClose])
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null
    const first = panel.current?.querySelector<HTMLElement>('input:not([type="hidden"]), textarea, select, button:not([data-close])')
    first?.focus()
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        close.current()
      }
    }
    window.addEventListener('keydown', key, true)
    return () => {
      window.removeEventListener('keydown', key, true)
      before?.focus?.()
    }
  }, [])
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-[var(--nexui-scrim)] p-4" onPointerDown={(event) => event.target === event.currentTarget && onClose()}>
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
  testId?: string
}) {
  return (
    <Dialog title={title} onClose={onCancel} closeLabel={closeLabel} testId={testId}>
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
