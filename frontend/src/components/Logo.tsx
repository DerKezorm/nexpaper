// nexpaper mark: an in-tray holding two sheets, the back one tilted, in kraft brown. The source of every version is
// nexapps/icons-vergleich/neu.py; the same shape is in public/logo.svg (favicon) and scripts/app-icons.mjs (home
// screen). The colours come from index.css (--np-logo-…) and follow the theme: a white tile in light mode, a dark one
// in dark mode.
export function LogoMark({ size = 36, className = '' }: { size?: number; className?: string }) {
  const grund = { fill: 'var(--np-logo-grund)' }
  const akzent = { stroke: 'var(--np-logo-akzent)' }
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="nexpaper-mark" gradientUnits="userSpaceOnUse" x1="10" y1="10" x2="54" y2="54">
          <stop offset="0" style={{ stopColor: 'var(--np-logo-verlauf-1)' }} />
          <stop offset=".5" style={{ stopColor: 'var(--np-logo-verlauf-2)' }} />
          <stop offset="1" style={{ stopColor: 'var(--np-logo-verlauf-3)' }} />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="16" style={grund} />
      <rect
        x="2.75"
        y="2.75"
        width="58.5"
        height="58.5"
        rx="15.3"
        fill="none"
        strokeWidth="1.5"
        style={{ stroke: 'var(--np-logo-rand)', strokeOpacity: 'var(--np-logo-rand-deckung)' }}
      />
      <rect
        x="16.5"
        y="12"
        width="29"
        height="24"
        rx="2.5"
        stroke="url(#nexpaper-mark)"
        strokeWidth="3"
        strokeOpacity=".6"
        transform="rotate(-7 31 24)"
        style={grund}
      />
      <rect x="19" y="16" width="26" height="22" rx="2.5" strokeWidth="3.4" style={{ ...grund, ...akzent }} />
      <path d="M23.5 22.5h17M23.5 28h11" strokeWidth="2.8" strokeLinecap="round" style={akzent} />
      <path
        d="M10 35h11.5l3 5.5h15l3-5.5H54v11a4 4 0 0 1-4 4H14a4 4 0 0 1-4-4Z"
        stroke="url(#nexpaper-mark)"
        strokeWidth="4.2"
        strokeLinejoin="round"
        style={grund}
      />
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
