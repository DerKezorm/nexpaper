/**
 * Since 1.1.0: a table with a head row, framed like a box (12 px corners), small words (12 px), the head grey. Where its
 * place is narrower than 640 px (its own width, not the window's) each row becomes a card instead: the columns one under
 * the other, label left and grey, value right, no sideways scrolling. For the log and the API keys of all accounts.
 *
 * The caller names the columns (`key`, `label`, a `width` such as `9rem`) and fills each cell (`cell`). `rowProps` adds
 * `data-…` marks to a row (the log's level). Both forms carry the same marks, so a test finds them in either.
 */
import type { ReactNode } from 'react'

import { HINT, MUTED, PLAIN } from './styles'

export type TableColumn<K extends string = string> = {
  key: K
  label: string
  /** A fixed width of the column on a wide place ("9rem"); without, it takes what is left. */
  width?: string
}

export function Table<T, K extends string = string>({
  label,
  columns,
  rows,
  cell,
  rowKey,
  rowProps,
  empty,
  testId,
}: {
  /** The name of the table for readers ("Log"). */
  label: string
  columns: readonly TableColumn<K>[]
  rows: readonly T[]
  cell: (row: T, key: K) => ReactNode
  rowKey?: (row: T, index: number) => string | number
  rowProps?: (row: T) => Record<`data-${string}`, string | undefined>
  /** What stands in place of an empty table ("Nothing logged yet."). */
  empty?: ReactNode
  testId?: string
}) {
  if (rows.length === 0) {
    return empty ? (
      <p className={`${PLAIN} rounded-[12px] border border-dashed border-[var(--nexui-line)] px-6 py-8 text-center text-sm leading-5 ${MUTED}`} data-testid={testId}>
        {empty}
      </p>
    ) : null
  }
  const keyOf = (row: T, index: number) => (rowKey ? rowKey(row, index) : index)
  return (
    <div className="@container min-w-0" data-testid={testId}>
      <table
        aria-label={label}
        className="hidden w-full table-fixed border-separate border-spacing-0 overflow-hidden rounded-[12px] border border-solid border-[var(--nexui-line)] text-left text-xs leading-4 tracking-normal text-[var(--nexui-text)] @min-[640px]:table"
        data-part="table"
      >
        <colgroup>
          {columns.map((column) => (
            <col key={column.key} style={column.width ? { width: column.width } : undefined} />
          ))}
        </colgroup>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col" className={`border-0 border-b border-solid border-[var(--nexui-line)] px-3 py-2 font-medium ${MUTED}`}>
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={keyOf(row, index)} {...rowProps?.(row)} data-part="table-row">
              {columns.map((column) => (
                <td
                  key={column.key}
                  className="border-0 border-b border-solid border-[color-mix(in_srgb,var(--nexui-line)_60%,transparent)] px-3 py-1.5 align-top [overflow-wrap:anywhere]"
                >
                  {cell(row, column.key)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <ul aria-label={label} className="m-0 flex list-none flex-col gap-2 p-0 @min-[640px]:hidden" data-part="table-cards">
        {rows.map((row, index) => (
          <li
            key={keyOf(row, index)}
            {...rowProps?.(row)}
            className="rounded-[12px] border border-solid border-[var(--nexui-line)] px-3 py-2 text-xs leading-4 tracking-normal text-[var(--nexui-text)]"
            data-part="table-card"
          >
            <dl className="m-0 grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-3 gap-y-1 p-0">
              {columns.map((column) => (
                <div key={column.key} className="contents">
                  <dt className={HINT}>{column.label}</dt>
                  <dd className={`${PLAIN} min-w-0 text-right text-xs leading-4 [overflow-wrap:anywhere]`}>{cell(row, column.key)}</dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
      </ul>
    </div>
  )
}
