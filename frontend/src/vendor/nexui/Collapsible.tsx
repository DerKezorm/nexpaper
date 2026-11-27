/**
 * Since 1.1.0: a box that folds. Closed it shows its title and, on the right, its state (a symbol, a `Badge`, or a
 * summary such as "connected · tasks.example.com"); open also what it holds. The head is one button in the heading:
 * Enter and space fold it, `aria-expanded` says how it stands, `aria-controls` names what it opens.
 *
 * Two forms: `box` (the default, like a `Box`: the points of "Ready for the internet?", each closed) and `card` (like a
 * `Card`, with its symbol or an app's logo and a line under the title: one card per other nex app under Connections).
 * Open or closed is the caller's when it passes `open` and `onOpenChange` (an app that remembers it per device), else
 * the box keeps it itself, starting with `defaultOpen` (closed).
 */
import { useId, useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'

import { iconOf, type IconLike } from './icons'
import { BOX, CARD, FOCUS, MUTED, PLAIN, TILE } from './styles'

export function Collapsible({
  title,
  status,
  subtitle,
  icon,
  logo,
  mark: ownMark,
  variant = 'box',
  children,
  open,
  defaultOpen = false,
  onOpenChange,
  id,
  testId,
}: {
  /** Since 1.3.0 also an element (a `NexWordmark`). */
  title: ReactNode
  /** Right of the title, open and closed: a symbol, a `Badge`, a short summary. */
  status?: ReactNode
  /** A line under the title (the card's line; in a box a short explanation). */
  subtitle?: ReactNode
  /** The card's symbol (form `card`). */
  icon?: IconLike
  /** An app's own mark in place of the symbol (form `card`). */
  logo?: string
  /** Since 1.3.0 (form `card`): an element in place of the symbol, 36 px, hidden from readers: `<NexMark />`. */
  mark?: ReactNode
  variant?: 'box' | 'card'
  children?: ReactNode
  open?: boolean
  defaultOpen?: boolean
  onOpenChange?: (open: boolean) => void
  /** Names the part; a card also carries it as `data-card`. */
  id?: string
  testId?: string
}) {
  const own = useId()
  const base = id ?? own
  const [kept, setKept] = useState(defaultOpen)
  const shown = open ?? kept
  const card = variant === 'card'
  const Heading = card ? 'h2' : 'h3'
  function toggle() {
    if (open === undefined) setKept(!shown)
    onOpenChange?.(!shown)
  }
  const mark = card ? (
    ownMark !== undefined && ownMark !== null && ownMark !== false ? (
      <span aria-hidden className="flex h-9 w-9 shrink-0 items-center justify-center" data-part="card-mark">
        {ownMark}
      </span>
    ) : logo ? (
      <img src={logo} alt="" className="h-9 w-9 shrink-0 rounded-[12px]" />
    ) : icon ? (
      <span className={TILE}>
        <CardIcon icon={icon} />
      </span>
    ) : null
  ) : null
  return (
    <section
      id={id}
      aria-labelledby={`${base}-title`}
      className={card ? CARD : BOX}
      data-card={card ? id : undefined}
      data-collapsible={card ? 'card' : 'box'}
      data-open={shown}
      data-testid={testId}
    >
      <Heading id={`${base}-title`} className={`${PLAIN} text-[length:inherit] font-[inherit]`}>
        <button
          type="button"
          aria-expanded={shown}
          aria-controls={`${base}-body`}
          onClick={toggle}
          className={`flex w-full cursor-pointer items-center gap-3 rounded-[9px] border-0 bg-transparent p-0 text-left text-[var(--nexui-text)] [font-family:inherit] ${FOCUS}`}
          data-part="collapsible-head"
        >
          {mark}
          {/* Since 1.1.3 (V-15): title and state share a line that wraps as a whole; the title keeps at least 10rem, so a
              short name ("nextime") never breaks inside a word, and the state goes under it when the place is narrow. */}
          <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1" data-part="collapsible-main">
            <span className="min-w-[min(100%,10rem)] flex-1 basis-40" data-part="collapsible-title">
              <span
                className={`${PLAIN} block [overflow-wrap:break-word] ${card ? 'text-base leading-6 font-semibold' : 'text-sm leading-5 font-medium'}`}
              >
                {title}
              </span>
              {subtitle && <span className={`${PLAIN} block ${card ? 'text-sm leading-5' : 'text-xs leading-4'} ${MUTED}`}>{subtitle}</span>}
            </span>
            {status !== undefined && status !== null && status !== false && (
              <span className="flex min-w-0 max-w-full items-center gap-2 text-xs leading-4 text-[var(--nexui-text-muted)]" data-part="collapsible-status">
                {status}
              </span>
            )}
          </span>
          <ChevronDown aria-hidden className={`h-4 w-4 shrink-0 ${MUTED} transition-transform${shown ? '' : ' -rotate-90'}`} strokeWidth={2} />
        </button>
      </Heading>
      <div id={`${base}-body`} hidden={!shown} className={`${card ? 'mt-4' : 'mt-3'} flex flex-col gap-3`}>
        {shown && children}
      </div>
    </section>
  )
}

function CardIcon({ icon }: { icon: IconLike }) {
  const { Icon } = iconOf(icon)
  return <Icon aria-hidden className="h-4 w-4" strokeWidth={1.8} />
}
