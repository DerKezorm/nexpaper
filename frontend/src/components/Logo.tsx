// nexpaper mark: a sheet with a dog-ear, three lines of text and a seal, in kraft brown on a white tile. The mark stays
// the same in every theme; the wordmark's second half follows the accent.
const BROWN = '#9a6a3a'

export function LogoMark({ size = 36, className = '' }: { size?: number; className?: string }) {
  const line = { fill: 'none', stroke: BROWN, strokeWidth: 2.8 }
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" className={className} aria-hidden="true">
      <rect x="2" y="2" width="60" height="60" rx="16" fill="#ffffff" />
      <rect x="2" y="2" width="60" height="60" rx="16" fill="none" stroke={BROWN} strokeWidth="2.5" />
      <path d="M20 10h18l10 10v32a4 4 0 0 1-4 4H20a4 4 0 0 1-4-4V14a4 4 0 0 1 4-4z" {...line} strokeLinejoin="round" />
      <path d="M38 10v8a2 2 0 0 0 2 2h8" {...line} strokeLinejoin="round" />
      <path d="M23 30h17M23 37h17M23 44h9" {...line} strokeLinecap="round" />
      <circle cx="44" cy="48" r="4.2" fill={BROWN} />
    </svg>
  )
}

export function Wordmark({ size = 34 }: { size?: number }) {
  return (
    <span className="flex items-center gap-2.5">
      <LogoMark size={size} />
      <span className="text-lg font-extrabold tracking-tight text-ink">
        NEX<span className="text-accent">PAPER</span>
      </span>
    </span>
  )
}
