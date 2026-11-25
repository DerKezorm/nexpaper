/**
 * The parts of a settings page: a `Card` (symbol in a small tile, title, a line under it, then its content), in it one
 * `Box` per topic (title left, a `Badge` right, one line of explanation, the content, the row of buttons below), in a box
 * a list of `Row`s (devices, passkeys, providers: symbol, name, more to the right, a button at the end). Sizes of
 * nexnotes' settings: cards 20 px inside, boxes 16 by 12 px, both with 12 px corners, 12 px between the parts.
 */
import { Children, useId, type ReactNode } from 'react'

/** Whether a slot holds anything to show (`false`, `null`, `''` and empty lists do not count, else an empty gap stays). */
const filled = (slot: ReactNode) => Children.toArray(slot).some((child) => child !== '')

import { iconOf, type IconLike } from './icons'
import { BADGE_BASE, BADGE_TONE, BOX, CARD, HINT, MUTED, PLAIN, SUB, TILE, type BadgeTone } from './styles'

/** A state in a word: "On" (`on`), "Off" (`off`), "Linked" (`on`), few codes left (`warn`); since 0.1.1 a role
 * ("Operator", `accent`) and what keeps an account out ("Blocked", `danger`). */
export function Badge({ tone, children, testId }: { tone: BadgeTone; children: ReactNode; testId?: string }) {
  return (
    <span className={`${BADGE_BASE} ${BADGE_TONE[tone]}`} data-tone={tone} data-testid={testId}>
      {children}
    </span>
  )
}

export function Card({
  icon,
  logo,
  title,
  subtitle,
  children,
  id,
  testId,
}: {
  icon: IconLike
  /** An app's own mark in place of the symbol (e.g. nextasks' in nexnotes, the connections to other nex apps). */
  logo?: string
  title: string
  subtitle?: ReactNode
  children?: ReactNode
  /** Names the card; since 1.1.0 also as `data-card`, for the comparison of the settings across the apps. */
  id?: string
  testId?: string
}) {
  const own = useId()
  const titleId = `${id ?? own}-title`
  const { Icon } = iconOf(icon)
  return (
    <section id={id} aria-labelledby={titleId} className={CARD} data-card={id} data-testid={testId}>
      <div className={`flex gap-3${filled(children) ? ' mb-4' : ''}`}>
        {logo ? (
          <img src={logo} alt="" className="h-9 w-9 shrink-0 rounded-[12px]" />
        ) : (
          <span className={TILE}>
            <Icon aria-hidden className="h-4 w-4" strokeWidth={1.8} />
          </span>
        )}
        <div className="min-w-0 flex-1">
          <h2 id={titleId} className={`${PLAIN} text-base leading-6 font-semibold text-[var(--nexui-text)] [overflow-wrap:break-word]`}>
            {title}
          </h2>
          {subtitle && <p className={`${PLAIN} text-sm leading-5 ${MUTED}`}>{subtitle}</p>}
        </div>
      </div>
      {filled(children) && <div className="flex flex-col gap-3">{children}</div>}
    </section>
  )
}

export function Box({
  title,
  badge,
  hint,
  children,
  actions,
  testId,
}: {
  title: string
  /** Right of the title: the state (`Badge`). */
  badge?: ReactNode
  /** One line of explanation under the title. */
  hint?: ReactNode
  /** What the box holds: rows, a field, a list of codes. */
  children?: ReactNode
  /** The buttons, in one row below everything else. */
  actions?: ReactNode
  testId?: string
}) {
  const titleId = useId()
  const hintId = useId()
  return (
    <section aria-labelledby={titleId} aria-describedby={hint ? hintId : undefined} className={BOX} data-testid={testId}>
      {/* Since 1.0.0 the title never shrinks below its longest word ("Wiederherstellungscodes" next to a badge at
          360 px was cut): no min-w-0, the badge wraps under it instead; only a word wider than the whole box breaks. */}
      <div className="flex min-h-6 flex-wrap items-center gap-x-2 gap-y-1" data-part="box-head">
        <h3 id={titleId} className={`${PLAIN} flex-1 text-sm leading-5 font-medium text-[var(--nexui-text)] [overflow-wrap:break-word]`}>
          {title}
        </h3>
        {badge}
      </div>
      {hint && (
        <p id={hintId} className={`${HINT} mt-0.5`}>
          {hint}
        </p>
      )}
      {filled(children) && <div className="mt-3 flex flex-col gap-3">{children}</div>}
      {filled(actions) && <div className="mt-3 flex flex-wrap items-center gap-2">{actions}</div>}
    </section>
  )
}

/** The list of rows in a box. */
export function Rows({ children, label, testId }: { children: ReactNode; label?: string; testId?: string }) {
  return (
    <ul aria-label={label} className="m-0 flex list-none flex-col p-0 [&>li+li]:border-t [&>li+li]:border-solid [&>li+li]:border-[var(--nexui-line)]" data-testid={testId}>
      {children}
    </ul>
  )
}

export function Row({
  icon,
  lead,
  name,
  badge,
  sub,
  detail,
  action,
  note,
  testId,
}: {
  /** The symbol in front (devices, passkeys, providers). */
  icon?: IconLike
  /** Since 0.1.1: in place of the symbol, e.g. a person's picture (`Avatar`, 32 px). */
  lead?: ReactNode
  name: ReactNode
  /** A state right of the name ("Linked", "This browser"); several side by side, wrapping. */
  badge?: ReactNode
  /** Since 0.1.1: a second line under the name, small and grey, breaking where it must ("kim · kim@example.com"). */
  sub?: ReactNode
  /** Small and grey to the right: when last used, an address. */
  detail?: ReactNode
  /** The button at the end. */
  action?: ReactNode
  /** A line under the row (why a button is missing). */
  note?: ReactNode
  testId?: string
}) {
  const front = lead ?? (icon ? <RowIcon icon={icon} /> : null)
  if (lead !== undefined || filled(sub)) {
    // Since 0.1.1: picture, then name and badges with the second line under them, the button at the end.
    return (
      <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2" data-testid={testId}>
        {front}
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <span className={`${PLAIN} min-w-0 truncate text-sm leading-5 font-medium text-[var(--nexui-text)]`}>{name}</span>
            {badge}
          </div>
          {filled(sub) && <span className={`${SUB} mt-0.5`}>{sub}</span>}
        </div>
        {detail && <span className={`${PLAIN} text-xs leading-4 ${MUTED}`}>{detail}</span>}
        {action}
        {note && <span className={`${HINT} basis-full`}>{note}</span>}
      </li>
    )
  }
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2" data-testid={testId}>
      {front}
      <span className={`${PLAIN} min-w-0 flex-1 truncate text-sm leading-5 text-[var(--nexui-text)]`}>{name}</span>
      {badge}
      {detail && <span className={`${PLAIN} text-xs leading-4 ${MUTED}`}>{detail}</span>}
      {action}
      {note && <span className={`${HINT} basis-full pl-7`}>{note}</span>}
    </li>
  )
}

function RowIcon({ icon }: { icon: IconLike }) {
  const { Icon } = iconOf(icon)
  return <Icon aria-hidden className={`h-4 w-4 shrink-0 ${MUTED}`} strokeWidth={1.8} />
}
