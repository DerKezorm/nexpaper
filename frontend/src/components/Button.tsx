import type { ButtonHTMLAttributes } from 'react'

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'soft' | 'ghost' | 'line'; size?: 'sm' | 'md' }

/** The buttons of the pages with documents and vaults, in the shapes of nexnotes (`.btn` in index.css): the accent one
 * for the main step, one with an edge for the usual (`soft` and `line` look alike now), a bare one for the quiet.
 * (The settings have theirs in `settings/ui`, with the same classes.) */
export function Button({ variant = 'soft', size = 'md', className = '', type = 'button', ...rest }: Props) {
  const sizes = size === 'sm' ? 'h-8 px-2.5 text-xs' : ''
  const look = variant === 'primary' ? 'btn-accent' : variant === 'ghost' ? 'text-ink-2 not-disabled:hover:bg-sheet-2 not-disabled:hover:text-ink disabled:bg-transparent' : 'btn-ghost'
  return <button type={type} className={`btn ${sizes} ${look} ${className}`} {...rest} />
}
