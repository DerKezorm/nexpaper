/**
 * The one button of the nex apps, in three kinds: `primary` filled in the accent colour (at most one per box),
 * `secondary` light with a fine edge, `danger` light red with red symbol and words for everything that ends or removes
 * something. Always with a symbol in front, always 40 px high with 9 px corners and 14 px semibold words (nexnotes'
 * buttons). `data-kind` and `data-icon` say kind and symbol, for the apps' tests.
 *
 * Three forms with the same look: a `button` (default), a link (`href`), and a file picker (`onFile`: a label around a
 * hidden file field, so the button opens the file dialog).
 */
import { useId, type ButtonHTMLAttributes, type ReactNode } from 'react'

import { iconOf, type IconLike } from './icons'
import { BUTTON_BASE, BUTTON_ICON, BUTTON_KIND, type ButtonKind } from './styles'

export type ButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className' | 'style' | 'children'> & {
  kind: ButtonKind
  icon: IconLike
  children: ReactNode
  /** Shows a spinner in place of the symbol and locks the button. */
  busy?: boolean
  /** As wide as its place (the sign-in screens). */
  wide?: boolean
  /** A link that looks like the button. */
  href?: string
  /** A file picker that looks like the button; called with the chosen file. */
  onFile?: (file: File) => void
  /** The files the picker offers (`accept` of the file field). */
  accept?: string
  /** `data-testid` of the button (of a picker: the label; its file field gets `<testId>-file`). */
  testId?: string
}

export function Button({ kind, icon, children, busy = false, wide = false, href, onFile, accept, testId, disabled, type = 'button', ...rest }: ButtonProps) {
  const { Icon, name } = iconOf(icon)
  const fileId = useId()
  const locked = Boolean(disabled || busy)
  const className = `${BUTTON_BASE} ${BUTTON_KIND[kind]}${wide ? ' w-full' : ''}`
  const inside = (
    <>
      {busy ? (
        <span aria-hidden className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-solid border-current border-t-transparent" />
      ) : (
        <Icon aria-hidden className={BUTTON_ICON} strokeWidth={2} />
      )}
      <span className="min-w-0">{children}</span>
    </>
  )
  if (onFile) {
    return (
      <label htmlFor={fileId} className={className} data-kind={kind} data-icon={name} aria-disabled={locked || undefined} data-testid={testId}>
        {inside}
        <input
          id={fileId}
          type="file"
          accept={accept}
          disabled={locked}
          className="sr-only"
          data-testid={testId ? `${testId}-file` : undefined}
          onChange={(event) => {
            const file = event.target.files?.[0]
            event.target.value = ''
            if (file) onFile(file)
          }}
        />
      </label>
    )
  }
  if (href !== undefined) {
    return (
      <a
        href={locked ? undefined : href}
        className={className}
        data-kind={kind}
        data-icon={name}
        aria-disabled={locked || undefined}
        aria-label={rest['aria-label']}
        data-testid={testId}
      >
        {inside}
      </a>
    )
  }
  return (
    <button {...rest} {...(testId ? { 'data-testid': testId } : {})} type={type} disabled={locked} aria-busy={busy || undefined} className={className} data-kind={kind} data-icon={name}>
      {inside}
    </button>
  )
}

/** A row of buttons, wrapping on a narrow screen. */
export function Buttons({ children, end = false }: { children: ReactNode; end?: boolean }) {
  return <div className={`flex flex-wrap items-center gap-2${end ? ' justify-end' : ''}`}>{children}</div>
}

/** A link in words (not a button): "Forgot your password?". A `button` when it acts, an `a` when it leads somewhere. */
export function TextLink({ children, href, onClick, testId }: { children: ReactNode; href?: string; onClick?: () => void; testId?: string }) {
  const className =
    'm-0 cursor-pointer border-0 bg-transparent p-0 text-sm leading-5 font-normal tracking-normal text-[var(--nexui-text-muted)] underline underline-offset-2 [font-family:inherit] hover:text-[var(--nexui-text)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--nexui-accent)] focus-visible:shadow-none'
  if (href !== undefined) {
    return (
      <a href={href} onClick={onClick} className={className} data-testid={testId}>
        {children}
      </a>
    )
  }
  return (
    <button type="button" onClick={onClick} className={className} data-testid={testId}>
      {children}
    </button>
  )
}
