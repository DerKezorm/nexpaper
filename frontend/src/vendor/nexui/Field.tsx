/**
 * Fields: the label written normally above (joined by `htmlFor`, so the field's name is exactly the label), the field
 * 40 px high with 9 px corners, every hint below in its own line and joined by `aria-describedby`; a problem in red under
 * them, the field marked `aria-invalid`. Boxes to tick: inline (`Checkbox`, "Stay signed in") or as a framed row with a
 * line of explanation and the box on the right (`CheckboxRow`, as nexnotes' switches).
 */
import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react'

import { CHECK, FIELD, HINT, LABEL, PLAIN } from './styles'

type Described = {
  label: string
  /** The lines under the field, top to bottom. */
  hints?: readonly ReactNode[]
  /** What is wrong with the value, in red under the hints. */
  error?: ReactNode
}

function described(base: string, hints: readonly ReactNode[], error: ReactNode, own?: string): string | undefined {
  const ids = hints.map((_, index) => `${base}-hint-${index}`)
  if (error) ids.push(`${base}-error`)
  if (own) ids.unshift(own)
  return ids.length ? ids.join(' ') : undefined
}

function Below({ base, hints, error }: { base: string; hints: readonly ReactNode[]; error: ReactNode }) {
  return (
    <>
      {hints.map((hint, index) => (
        <span key={index} id={`${base}-hint-${index}`} className={HINT}>
          {hint}
        </span>
      ))}
      {error && (
        <span id={`${base}-error`} role="alert" className={`${PLAIN} block text-xs leading-4 text-[var(--nexui-danger)]`}>
          {error}
        </span>
      )}
    </>
  )
}

export type FieldProps = Described &
  Omit<InputHTMLAttributes<HTMLInputElement>, 'className' | 'style' | 'size'> & {
    /** Fixed-width letters (codes, keys). */
    mono?: boolean
  }

export function Field({ label, hints = [], error, mono = false, id, ...rest }: FieldProps) {
  const own = useId()
  const base = id ?? own
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={base} className={LABEL}>
        {label}
      </label>
      <input
        {...rest}
        id={base}
        aria-invalid={error ? true : rest['aria-invalid']}
        aria-describedby={described(base, hints, error, rest['aria-describedby'])}
        className={`${FIELD}${mono ? ' font-mono' : ''}`}
      />
      <Below base={base} hints={hints} error={error} />
    </div>
  )
}

export type SelectFieldProps = Described &
  Omit<SelectHTMLAttributes<HTMLSelectElement>, 'className' | 'style' | 'size'> & {
    options: readonly { value: string; label: string }[]
  }

export function SelectField({ label, hints = [], error, options, id, ...rest }: SelectFieldProps) {
  const own = useId()
  const base = id ?? own
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={base} className={LABEL}>
        {label}
      </label>
      <select {...rest} id={base} aria-describedby={described(base, hints, error, rest['aria-describedby'])} className={`${FIELD} cursor-pointer px-2`}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <Below base={base} hints={hints} error={error} />
    </div>
  )
}

type CheckProps = {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  testId?: string
}

/** A box to tick with its words right of it, in one line. */
export function Checkbox({ label, checked, onChange, disabled, testId }: CheckProps) {
  const id = useId()
  return (
    <div className="flex items-center gap-2.5">
      <input id={id} type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} className={CHECK} data-testid={testId} />
      <label htmlFor={id} className={`${PLAIN} cursor-pointer text-sm leading-5 text-[var(--nexui-text)]`}>
        {label}
      </label>
    </div>
  )
}

/** On or off with its name and a line of explanation, framed; the whole row is the label, the box stands right. */
export function CheckboxRow({ label, hint, checked, onChange, disabled, testId }: CheckProps & { hint?: ReactNode }) {
  const id = useId()
  return (
    <div className="flex items-center justify-between gap-4 rounded-[12px] border border-solid border-[var(--nexui-line)] px-4 py-3 tracking-normal">
      {/* The label alone names the box; the explanation only describes it. */}
      <div className="min-w-0 flex-1">
        <label htmlFor={id} className={`${LABEL} cursor-pointer`}>
          {label}
        </label>
        {hint && (
          <span id={`${id}-hint`} className={HINT}>
            {hint}
          </span>
        )}
      </div>
      <input
        id={id}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        aria-describedby={hint ? `${id}-hint` : undefined}
        onChange={(event) => onChange(event.target.checked)}
        className={CHECK}
        data-testid={testId}
      />
    </div>
  )
}
