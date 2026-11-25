/**
 * The looks of the kit as Tailwind classes. Colours only through CSS variables the app sets (README, "Farben"); every
 * size, gap and corner is nexnotes' (its buttons, fields and cards): buttons and fields 40 px high with 9 px corners,
 * cards and boxes 12 px, dialogs 16 px. Each element names its own size, weight, line height, letter spacing and margin,
 * so that an app's own rules for `h2`, `p` or `button` (nexmail's base.css) cannot change it.
 */

/** Text that ignores the app's rules for headings and paragraphs: no margin, normal letter spacing, the page's font,
 * lines broken the plain way (nexmail's body sets `text-wrap: pretty`, which breaks the same hint elsewhere). */
export const PLAIN = 'm-0 tracking-normal [font-family:inherit] [text-wrap:wrap]'

export const MUTED = 'text-[var(--nexui-text-muted)]'

/** The focus ring of buttons and links: an outline in the accent colour, never the app's own box shadow. */
export const FOCUS =
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--nexui-accent)] focus-visible:shadow-none'

export const BUTTON_BASE =
  'inline-flex h-10 min-w-0 shrink-0 cursor-pointer items-center justify-center gap-2 rounded-[9px] border border-solid px-4 ' +
  'text-center text-sm leading-5 font-semibold tracking-normal no-underline [font-family:inherit] transition-colors ' +
  'disabled:cursor-not-allowed disabled:border-[var(--nexui-line)] disabled:bg-[var(--nexui-disabled-bg)] ' +
  'disabled:text-[var(--nexui-disabled-text)] aria-disabled:cursor-not-allowed aria-disabled:border-[var(--nexui-line)] ' +
  'aria-disabled:bg-[var(--nexui-disabled-bg)] aria-disabled:text-[var(--nexui-disabled-text)] ' +
  FOCUS

export const BUTTON_KIND = {
  primary:
    'border-[var(--nexui-accent)] bg-[var(--nexui-accent)] text-[var(--nexui-on-accent)] ' +
    'not-disabled:hover:border-[var(--nexui-accent-hover)] not-disabled:hover:bg-[var(--nexui-accent-hover)]',
  secondary:
    'border-[var(--nexui-edge)] bg-[var(--nexui-surface-raised)] text-[var(--nexui-text)] ' +
    'not-disabled:hover:bg-[var(--nexui-surface-hover)]',
  danger:
    'border-transparent bg-[color-mix(in_srgb,var(--nexui-danger)_14%,transparent)] text-[var(--nexui-danger)] ' +
    'not-disabled:hover:bg-[color-mix(in_srgb,var(--nexui-danger)_24%,transparent)]',
} as const

export type ButtonKind = keyof typeof BUTTON_KIND

export const BUTTON_ICON = 'h-4 w-4 shrink-0'

export const BADGE_BASE =
  'inline-flex h-6 shrink-0 items-center gap-1 rounded-full border border-solid px-2.5 text-xs leading-4 font-medium tracking-normal whitespace-nowrap'

export const BADGE_TONE = {
  on: 'border-transparent bg-[color-mix(in_srgb,var(--nexui-ok)_14%,transparent)] text-[var(--nexui-ok)]',
  off: 'border-[var(--nexui-line)] bg-transparent text-[var(--nexui-text-muted)]',
  warn: 'border-transparent bg-[color-mix(in_srgb,var(--nexui-warn)_14%,transparent)] text-[var(--nexui-warn)]',
  /** Since 0.1.1: a role ("Operator"), in the accent colour. */
  accent: 'border-transparent bg-[color-mix(in_srgb,var(--nexui-accent)_14%,transparent)] text-[var(--nexui-accent-text)]',
  /** Since 0.1.1: a state that keeps the account out ("Blocked", "Deleted"). */
  danger: 'border-transparent bg-[color-mix(in_srgb,var(--nexui-danger)_14%,transparent)] text-[var(--nexui-danger)]',
} as const

export type BadgeTone = keyof typeof BADGE_TONE

export const CARD =
  'rounded-[12px] border border-solid border-[var(--nexui-line)] bg-[var(--nexui-surface)] p-5 text-[var(--nexui-text)] tracking-normal [text-wrap:wrap]'

export const TILE =
  'flex h-9 w-9 shrink-0 items-center justify-center rounded-[12px] bg-[color-mix(in_srgb,var(--nexui-accent)_14%,transparent)] text-[var(--nexui-accent-text)]'

export const BOX = 'rounded-[12px] border border-solid border-[var(--nexui-line)] px-4 py-3 text-sm leading-5 text-[var(--nexui-text)] tracking-normal [text-wrap:wrap]'

export const FIELD =
  'block h-10 w-full min-w-0 rounded-[9px] border border-solid border-[var(--nexui-edge)] bg-[var(--nexui-field)] px-3 text-sm leading-5 ' +
  'text-[var(--nexui-text)] tracking-normal [font-family:inherit] outline-none placeholder:text-[var(--nexui-text-muted)] ' +
  'focus:border-[var(--nexui-accent)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--nexui-accent)_28%,transparent)] ' +
  'focus-visible:outline-none aria-invalid:border-[var(--nexui-danger)] disabled:cursor-not-allowed disabled:opacity-60'

export const LABEL = `${PLAIN} block text-sm leading-5 font-medium text-[var(--nexui-text)]`

export const HINT = `${PLAIN} block text-xs leading-4 ${MUTED}`

export const CHECK = 'h-5 w-5 shrink-0 cursor-pointer accent-[var(--nexui-accent)] disabled:cursor-not-allowed'

export const NOTICE_TONE = {
  warn: 'border-[color-mix(in_srgb,var(--nexui-warn)_40%,transparent)] bg-[color-mix(in_srgb,var(--nexui-warn)_10%,transparent)]',
  danger: 'border-[color-mix(in_srgb,var(--nexui-danger)_40%,transparent)] bg-[color-mix(in_srgb,var(--nexui-danger)_10%,transparent)]',
  ok: 'border-[color-mix(in_srgb,var(--nexui-ok)_40%,transparent)] bg-[color-mix(in_srgb,var(--nexui-ok)_10%,transparent)]',
} as const

export const NOTICE_TEXT = {
  warn: 'text-[var(--nexui-warn)]',
  danger: 'text-[var(--nexui-danger)]',
  ok: 'text-[var(--nexui-ok)]',
} as const

export type NoticeTone = keyof typeof NOTICE_TONE

/** Since 0.1.1: a person's picture, round, never squeezed. */
export const AVATAR = 'inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full'

/** Since 0.1.1: the letter of a picture-less person on its hue; saturation, lightness and the letter's colour are the
 * app's (README, "Farben"). */
export const AVATAR_LETTER =
  'bg-[hsl(var(--nexui-avatar-hue)_var(--nexui-avatar-saturation)_var(--nexui-avatar-lightness))] text-[var(--nexui-avatar-text)] ' +
  'font-semibold tracking-normal select-none [font-family:inherit]'

/** Since 0.1.1: the small grey second line of a row (username, address); it breaks rather than being cut off. */
export const SUB = `${PLAIN} block text-xs leading-4 ${MUTED} [overflow-wrap:anywhere]`

/** Since 0.1.1: the heading over a group of buttons in a dialog ("Change", "Access", "End"). */
export const GROUP_TITLE = `${PLAIN} text-xs leading-4 font-semibold ${MUTED}`
