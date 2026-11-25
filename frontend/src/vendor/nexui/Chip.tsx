/**
 * Since 1.1.0: a small mark for a thing in a list that can be taken out (an own language: "Plattdeutsch (nds) · 412
 * texts"), 28 px high with 9 px corners and a fine frame; with `onRemove` a small remove button at its end (Trash2, as
 * nexnotes' languages), named "Remove <name>" for readers. Without `onRemove` it only shows (the built-in languages).
 * A state in a word is a `Badge`, never a chip.
 */
import type { ReactNode } from 'react'
import { Trash2 } from 'lucide-react'

import { FOCUS, MUTED, PLAIN } from './styles'
import { fill, useNexuiTexts } from './texts'

export function Chip({
  children,
  name,
  onRemove,
  disabled = false,
  testId,
}: {
  children: ReactNode
  /** The thing's name for "Remove <name>" (default: the words of the chip, where they are plain text). */
  name?: string
  onRemove?: () => void
  disabled?: boolean
  testId?: string
}) {
  const texts = useNexuiTexts()
  const called = name ?? (typeof children === 'string' ? children : '')
  return (
    <span
      className={`${PLAIN} inline-flex h-7 max-w-full min-w-0 items-center gap-1 rounded-[9px] border border-solid border-[var(--nexui-line)] pl-2.5 text-xs leading-4 text-[var(--nexui-text)] ${onRemove ? 'pr-1' : 'pr-2.5'}`}
      data-chip
      data-testid={testId}
    >
      <span className="min-w-0 truncate">{children}</span>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          disabled={disabled}
          aria-label={called ? fill(texts.removeName, { name: called }) : texts.remove}
          title={texts.remove}
          className={`inline-flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center rounded-[6px] border-0 bg-transparent p-0 ${MUTED} not-disabled:hover:bg-[color-mix(in_srgb,var(--nexui-danger)_14%,transparent)] not-disabled:hover:text-[var(--nexui-danger)] disabled:cursor-not-allowed disabled:opacity-40 ${FOCUS}`}
          data-icon="Trash2"
        >
          <Trash2 aria-hidden className="h-3 w-3" strokeWidth={2} />
        </button>
      )}
    </span>
  )
}
