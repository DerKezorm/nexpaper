/**
 * Building blocks of the settings, account and about pages, the same as nexnotes' (`pages/settings/ui.tsx` there) in
 * nexpaper's colours: whoever knows one app finds the same card, row with its checkbox, field and button in the other.
 */
import type { LucideIcon } from 'lucide-react'
import { useCallback, useId, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../api/client'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { copyText } from '../../lib/copy'
import { errorText } from '../../lib/errors'

/** A card with its symbol in a small box, a title and a line of explanation. */
export function Card({ icon: Icon, title, text, children, id }: { icon: LucideIcon; title: string; text?: string; children: ReactNode; id?: string }) {
  return (
    <section id={id} aria-labelledby={id ? `${id}-title` : undefined} className="card p-5">
      <div className="mb-4 flex gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent">
          <Icon className="h-4 w-4" strokeWidth={1.8} aria-hidden />
        </span>
        <div>
          <h2 id={id ? `${id}-title` : undefined} className="font-semibold">
            {title}
          </h2>
          {text && <p className="text-sm text-muted">{text}</p>}
        </div>
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  )
}

/** A heading inside a card, for a second part of it (as "OpenID Connect" under "Sign-in"). */
export function SubHead({ title, text }: { title: string; text?: string }) {
  return (
    <div className="pt-3">
      <h3 className="text-sm font-semibold">{title}</h3>
      {text && <p className="text-xs text-muted">{text}</p>}
    </div>
  )
}

/** A switch with its name and a line of explanation; the whole row is the label, the switch a checkbox as in nexnotes
 * (never a sliding switch in the nex apps). */
export function Toggle({ label, hint, checked, onChange, disabled = false }: { label: string; hint?: string; checked: boolean; onChange: (value: boolean) => void; disabled?: boolean }) {
  const hintId = useId()
  return (
    <label className={'flex items-center justify-between gap-4 rounded-[12px] border border-line bg-paper px-4 py-3 text-sm ' + (disabled ? 'opacity-60' : 'cursor-pointer')}>
      <span>
        <span className="font-medium">{label}</span>
        {hint && (
          <span id={hintId} className="block text-xs text-muted">
            {hint}
          </span>
        )}
      </span>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        aria-checked={checked}
        aria-label={label}
        aria-describedby={hint ? hintId : undefined}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="h-5 w-5 shrink-0 accent-[var(--accent)]"
      />
    </label>
  )
}

const FIELD = 'input mt-1'

/** A field with its name above it and an optional line below. */
export function Input({
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
  hint,
  className = '',
  autoComplete = 'off',
  autoFocus = false,
  min,
  max,
  maxLength,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  type?: string
  placeholder?: string
  hint?: string
  className?: string
  autoComplete?: string
  autoFocus?: boolean
  min?: number
  max?: number
  maxLength?: number
}) {
  const hintId = useId()
  return (
    <div className={'text-sm ' + className}>
      <label className="block">
        <span className="text-xs font-medium text-ink-2">{label}</span>
        <input
          type={type}
          value={value}
          placeholder={placeholder}
          autoComplete={autoComplete}
          autoFocus={autoFocus}
          min={min}
          max={max}
          maxLength={maxLength}
          aria-describedby={hint ? hintId : undefined}
          onChange={(event) => onChange(event.target.value)}
          className={FIELD}
        />
      </label>
      {hint && (
        <span id={hintId} className="mt-1 block text-xs text-muted">
          {hint}
        </span>
      )}
    </div>
  )
}

export function Select<T extends string>({ label, value, options, onChange, className = '' }: { label: string; value: T; options: { value: T; label: string }[]; onChange: (value: T) => void; className?: string }) {
  return (
    <label className={'block text-sm ' + className}>
      <span className="text-xs font-medium text-ink-2">{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value as T)} className="input mt-1 px-2">
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}

/** The buttons of the settings: one primary per card, the others quiet; `danger` for what cannot be taken back. */
export function Button({
  children,
  onClick,
  busy = false,
  primary = false,
  danger = false,
  small = false,
  type = 'button',
  disabled = false,
  label,
  className = '',
}: {
  children: ReactNode
  onClick?: () => void
  busy?: boolean
  primary?: boolean
  danger?: boolean
  small?: boolean
  type?: 'button' | 'submit'
  disabled?: boolean
  label?: string
  className?: string
}) {
  const look = primary ? 'btn-accent' : danger ? 'btn-ghost not-disabled:hover:border-bad/50 not-disabled:hover:text-bad' : 'btn-ghost'
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={busy || disabled}
      aria-label={label}
      className={`btn ${small ? 'h-8 px-2.5 text-xs' : ''} ${look} ${className}`}
    >
      {busy ? '…' : children}
    </button>
  )
}

/** One line under a card: what went wrong, or that it worked. */
export function Feedback({ problem, done = null, values }: { problem: string | null; done?: string | null; values?: Record<string, unknown> }) {
  // Nothing at all while there is nothing to say: an empty line would add its gap to the card.
  if (!problem && !done) return null
  return (
    <div aria-live="polite">
      {problem && (
        <p role="alert" className="text-sm text-bad">
          {errorText(problem, values)}
        </p>
      )}
      {done && (
        <p role="status" className="text-sm font-semibold text-accent">
          ✓ {done}
        </p>
      )}
    </div>
  )
}

/** A link or value to copy: the field and the button that copies it. */
export function CopyLink({ value, label }: { value: string; label: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  return (
    <div className="flex items-center gap-2 rounded-[12px] border border-accent/40 bg-accent-soft/50 p-2">
      <input readOnly value={value} aria-label={label} onFocus={(event) => event.target.select()} className="min-w-0 flex-1 bg-transparent px-2 font-mono text-xs text-ink outline-none" />
      <button type="button" onClick={() => void copyText(value).then(setCopied)} className="btn btn-accent h-8 shrink-0 px-3 text-xs">
        {copied ? '✓' : t('common.copy')}
      </button>
    </div>
  )
}

/** Runs a change, remembers whether it worked; the card shows it with `Feedback`. */
// eslint-disable-next-line react-refresh/only-export-components
export function useAction() {
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  /** What the server said along with the problem (a limit, a number), for the sentence. */
  const [values, setValues] = useState<Record<string, unknown>>({})
  const run = useCallback(async (work: () => Promise<unknown>, success?: string): Promise<boolean> => {
    setBusy(true)
    setProblem(null)
    setValues({})
    setDone(null)
    try {
      await work()
      if (success) setDone(success)
      return true
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
      setValues(error instanceof ApiError ? error.values : {})
      return false
    } finally {
      setBusy(false)
    }
  }, [])
  const clear = useCallback(() => {
    setProblem(null)
    setDone(null)
  }, [])
  return { busy, problem, values, done, run, clear }
}

/** "Really?" with the operator's password where the server asks for it again: the dialog of the whole interface
 * (``components/ConfirmDialog``), here with the words of the settings (its button is the quiet one unless ``danger``). */
export function Confirm({ title, text, confirm, danger = false, password = false, onCancel, onConfirm }: {
  title: string
  text: ReactNode
  confirm: string
  danger?: boolean
  password?: boolean
  onCancel: () => void
  onConfirm: (password: string) => Promise<void>
}) {
  return <ConfirmDialog title={title} text={text} confirm={confirm} danger={danger} password={password} onCancel={onCancel} onConfirm={onConfirm} />
}

export type Tab<T extends string> = { value: T; label: string; icon?: LucideIcon }

/** A row of round tabs. `under`: a second row below the first, tied to it by a line on the left. Wraps when narrow. */
export function TabRow<T extends string>({ tabs, active, onChange, under = false, label }: { tabs: Tab<T>[]; active: T; onChange: (value: T) => void; under?: boolean; label?: string }) {
  return (
    <div
      role="tablist"
      aria-label={label}
      className={`flex flex-wrap items-center gap-2 ${under ? 'border-l-2 border-accent/40 pl-4' : ''}`}
    >
      {tabs.map(({ value, label: name, icon: Icon }) => {
        const on = value === active
        return (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => onChange(value)}
            className={`inline-flex max-w-full items-center gap-2 rounded-[9px] border text-sm font-medium transition-colors ${under ? 'px-3.5 py-1.5' : 'px-4 py-2'} ${
              on ? 'chosen border-accent/50' : 'border-line bg-sheet text-muted hover:text-ink'
            }`}
          >
            {Icon && <Icon size={16} aria-hidden />}
            {name}
          </button>
        )
      })}
    </div>
  )
}

/** A choice of a few, as a pill with segments. */
export function Segment<T extends string>({ options, value, onChange, label }: { options: { value: T; label: string; disabled?: boolean }[]; value: T; onChange: (value: T) => void; label?: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex flex-wrap rounded-[9px] border border-line bg-sheet-2/60 p-1 text-sm font-medium">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={value === option.value}
          disabled={option.disabled}
          onClick={() => onChange(option.value)}
          className={`rounded-[7px] px-3.5 py-1.5 disabled:opacity-50 ${value === option.value ? 'bg-sheet text-ink shadow-sm' : 'text-muted hover:text-ink disabled:hover:text-muted'}`}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function saveAsFile(name: string, data: Blob) {
  const url = URL.createObjectURL(data)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
