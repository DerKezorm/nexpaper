/**
 * Since 1.3.0 (B19, B20, decided 27.11.2026): the umbrella brand nex in an app, for the places that speak of the nex
 * apps as a family (the card "Other nex apps", a heading over them).
 *
 * `NexMark` is the mark "Kachelfamilie": four app tiles in a 2x2 grid, three as frames in a graphite gradient, the
 * fourth filled at the bottom right. Taken unchanged from `nexapps/icons-vergleich/neu/nex-logo.svg` (source `neu.py`,
 * `nex()`; `NEX-ZEICHEN.md`), drawn nowhere anew. One change only: the filled tile ("the dot") is always the accent of
 * the app it stands in (`--nexui-accent`), not indigo; its ring stays in the tile's colour.
 *
 * The mark's own colours are the brand's, fixed like an app's logo, and the only colours the kit writes out itself
 * (in `nexBrand.ts`; the colour rule in `tests/test_sync.py` allows exactly these, in that file only). Light or dark follows the app:
 * the luminance of `--nexui-surface`, which every app sets for both, else the system (`usePageDark`).
 *
 * `NexWordmark` writes "nex-Apps" the way the apps write their names (NEXNOTES): NEX in the text's colour, APPS in the
 * accent, bold and tight; for titles and headings, never inside running text.
 */
import { useId } from 'react'

import { NEX_MARK_COLORS, usePageDark } from './nexBrand'
import { useNexuiTexts } from './texts'

export function NexMark({
  size = 36,
  label,
  dark,
  className,
  testId,
}: {
  /** Width and height in px; 36 is the tile of a `Card` (pass it as `mark`). */
  size?: number
  /** Only where no text stands beside it: names it for readers (`role="img"`). Without it the mark is hidden. */
  label?: string
  /** Light or dark by hand; without it the page's (`usePageDark`). */
  dark?: boolean
  className?: string
  testId?: string
}) {
  const id = `nexmark-${useId().replace(/[^\w-]/g, '')}`
  const pageDark = usePageDark()
  const look = (dark ?? pageDark) ? 'dark' : 'light'
  const colors = NEX_MARK_COLORS[look]
  const frame = { fill: 'none', stroke: `url(#${id})`, strokeWidth: 4 } as const
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
      className={`shrink-0${className ? ` ${className}` : ''}`}
      data-mark="nex"
      data-look={look}
      data-testid={testId}
    >
      <defs>
        <linearGradient id={id} gradientUnits="userSpaceOnUse" x1="10" y1="10" x2="54" y2="54">
          <stop offset="0" stopColor={colors.gradient[0]} />
          <stop offset=".5" stopColor={colors.gradient[1]} />
          <stop offset="1" stopColor={colors.gradient[2]} />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="16" fill={colors.tile} data-part="tile" />
      <rect
        x="2.75"
        y="2.75"
        width="58.5"
        height="58.5"
        rx="15.3"
        fill="none"
        stroke={colors.border}
        strokeOpacity={colors.borderOpacity}
        strokeWidth="1.5"
      />
      <rect x="13" y="13" width="16" height="16" rx="4.5" {...frame} />
      <rect x="35" y="13" width="16" height="16" rx="4.5" {...frame} />
      <rect x="13" y="35" width="16" height="16" rx="4.5" {...frame} />
      <rect
        x="33"
        y="33"
        width="20"
        height="20"
        rx="5.5"
        stroke={colors.tile}
        strokeWidth="2"
        style={{ fill: 'var(--nexui-accent)' }}
        data-part="dot"
      />
    </svg>
  )
}

export function NexWordmark({ label, className, testId }: { label?: string; className?: string; testId?: string }) {
  const texts = useNexuiTexts()
  return (
    <span
      className={`relative m-0 inline-block font-bold tracking-tight whitespace-nowrap text-[var(--nexui-text)] [font-family:'Inter_Variable','Segoe_UI',system-ui,-apple-system,sans-serif]${className ? ` ${className}` : ''}`}
      data-wordmark="nex"
      data-testid={testId}
    >
      <span aria-hidden="true">NEX</span>
      <span aria-hidden="true" className="text-[var(--nexui-accent-text)]" data-part="wordmark-accent">
        APPS
      </span>
      <span className="sr-only">{label ?? texts.nexWordmark}</span>
    </span>
  )
}
