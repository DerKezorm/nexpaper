/**
 * The inside of a dialog about one thing (since 0.1.1, first for "Manage" in the account list): `Facts`, what is known
 * about it, label left and grey, value right, one under the other; `ButtonGroup`, a small heading over a group of
 * buttons ("Change", "Access", "End") or of boxes to tick ("Rights"), so that the dialog looks the same in every app.
 */
import { useId, type ReactNode } from 'react'

import { GROUP_TITLE, MUTED, PLAIN, SUB } from './styles'

export type Fact = {
  /** The label, left and grey ("Username"). */
  label: ReactNode
  /** The value, right ("kim"). */
  value: ReactNode
  /** A small line under the value ("Another account has this address too."). */
  note?: ReactNode
  testId?: string
}

/** What is known, label and value in two columns; the value breaks rather than being cut off. */
export function Facts({ items, label, testId }: { items: readonly Fact[]; label?: string; testId?: string }) {
  return (
    <dl aria-label={label} className="m-0 grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-2 p-0 tracking-normal" data-testid={testId}>
      {items.map((item, index) => (
        <div key={index} className="contents" data-testid={item.testId}>
          <dt className={`${PLAIN} text-sm leading-5 ${MUTED}`}>{item.label}</dt>
          <dd className={`${PLAIN} min-w-0 text-right text-sm leading-5 text-[var(--nexui-text)] [overflow-wrap:anywhere]`}>
            {item.value}
            {item.note && <span className={`${SUB} mt-0.5`}>{item.note}</span>}
          </dd>
        </div>
      ))}
    </dl>
  )
}

/** A group with its small heading: buttons side by side and wrapping (`buttons`), or rows one under the other
 * (`list`, the boxes to tick). A `section` named by its heading. */
export function ButtonGroup({
  title,
  children,
  layout = 'buttons',
  testId,
}: {
  title: string
  children: ReactNode
  layout?: 'buttons' | 'list'
  testId?: string
}) {
  const titleId = useId()
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-2 tracking-normal" data-group-layout={layout} data-testid={testId}>
      <h3 id={titleId} className={GROUP_TITLE}>
        {title}
      </h3>
      <div className={layout === 'list' ? 'flex flex-col gap-2' : 'flex flex-wrap items-center gap-2'}>{children}</div>
    </section>
  )
}
