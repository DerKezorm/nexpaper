import type { ButtonHTMLAttributes } from 'react'

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'soft' | 'ghost' | 'line'; size?: 'sm' | 'md' }

/** The buttons of the pages with documents and vaults: a filled one for the main step, a soft one
 * for the usual, a bare one for the quiet, an outlined one beside it. (The settings have their own, in `settings/ui`.) */
export function Button({ variant = 'soft', size = 'md', className = '', type = 'button', ...rest }: Props) {
  const base = 'inline-flex items-center justify-center gap-2 rounded-full font-semibold transition disabled:opacity-50 disabled:pointer-events-none'
  const sizes = size === 'sm' ? 'h-8 px-3.5 text-sm' : 'h-10 px-4.5 text-[0.95rem]'
  const look =
    variant === 'primary'
      ? 'bg-accent text-accent-ink hover:brightness-105 shadow-soft'
      : variant === 'soft'
        ? 'bg-accent-soft text-accent hover:brightness-[0.98]'
        : variant === 'line'
          ? 'border border-line bg-sheet text-ink-2 hover:bg-sheet-2 hover:text-ink'
          : 'text-ink-2 hover:bg-sheet-2'
  return <button type={type} className={`${base} ${sizes} ${look} ${className}`} {...rest} />
}
