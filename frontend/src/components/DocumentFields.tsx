/**
 * The fields of a document as the inbox and the document page edit them (the mock's `InboxPage` and `DocumentPage`):
 * an amount typed the way people type it, the tags as chips, and the
 * dates with their kind (due, contract until, warranty until, keep until). Each part keeps nothing of its own: the page
 * holds the values and decides when they are saved.
 */
import { Plus, X } from 'lucide-react'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import type { DateKind } from '../api/client'
import { dayInDays } from '../lib/dates'
import { YEAR_FROM, YEAR_TO, expandYear, yearOf } from '../lib/dateInput'
import { amountText, parseAmount } from '../lib/money'
import { Chip, WhyBadge } from './docs'
import { TagPicker } from './TagPicker'

// A year typed with all four digits is settled as soon as it stands; a shorter one waits for the field to be left.
const SETTLED_YEAR = 1000

const DATE_KINDS: DateKind[] = ['due', 'contract_end', 'warranty_end', 'keep_until']
/** `manual` only for `keep_until`: set by hand (`false`: worked out from the kind). */
export type DateEntry = { kind: DateKind; date: string; manual?: boolean }
/**
 * What `keep_until` is worked out from (the mock's `Dates`): the kind's name and keeping time, the year the time counts
 * from, and whether the document is as it was saved (`fresh`: its stored date stands; otherwise a kind or a date was
 * changed in the draft and the page works the date out itself, as the server will on saving).
 */
export type KeepContext = { kindName: string | null; years: number | null; base: number; fresh: boolean }
const KEEP: DateKind = 'keep_until'

/** A labelled field with where its proposal came from. */
export function Field({ label, why, children }: { label: string; why?: string; children: ReactNode }) {
  return (
    <div className="text-sm">
      <div className="mb-1 flex items-center justify-between">
        <span className="font-semibold">{label}</span>
        <WhyBadge why={why} />
      </div>
      {children}
    </div>
  )
}

/** An amount in cents, typed with a comma or a point; what is no amount is said under the field and not taken. */
export function AmountInput({ cents, onChange, label, className = 'input', language }: { cents: number | null; onChange: (cents: number | null) => void; label: string; className?: string; language: string }) {
  const { t } = useTranslation()
  const [typed, setTyped] = useState(amountText(cents, language))
  const [wrong, setWrong] = useState(false)
  useEffect(() => {
    setTyped(amountText(cents, language))
    setWrong(false)
  }, [cents, language])
  const commit = () => {
    const parsed = parseAmount(typed)
    if (parsed === 'invalid') {
      setWrong(true)
      return
    }
    setWrong(false)
    if (parsed !== cents) onChange(parsed)
    else setTyped(amountText(cents, language))
  }
  return (
    <>
      <input
        value={typed}
        inputMode="decimal"
        aria-label={label}
        aria-invalid={wrong}
        placeholder={t('docs.fields.noAmount')}
        onChange={(event) => setTyped(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => event.key === 'Enter' && commit()}
        className={`${className} text-right tabular-nums ${wrong ? 'border-bad' : ''}`}
      />
      {wrong && <p className="mt-1 text-xs text-bad">{t('docs.fields.amountWrong')}</p>}
    </>
  )
}

/**
 * A date field. A year under 100 (0027, from the browser's date field) is read as 20xx when the field is left. Saved
 * pages take `onCommit` (called once a date stands, not while the year is typed), a draft takes `onChange` too (every
 * keystroke). `refused` is the value the server turned down: while the field still holds it, the field is marked and
 * says why under it, with the year it probably meant and a button to take that.
 */
export function DateInput({ value, onChange, onCommit, label, className = 'input', wrapperClass = 'min-w-0', refused }: { value: string; onChange?: (value: string) => void; onCommit: (value: string) => void; label: string; className?: string; wrapperClass?: string; refused?: string }) {
  const { t } = useTranslation()
  const id = useId()
  const [typed, setTyped] = useState(value)
  const sent = useRef(value)
  useEffect(() => {
    setTyped(value)
    sent.current = value
  }, [value])
  const settle = (day: string) => {
    if (day === sent.current) return
    sent.current = day
    onCommit(day)
  }
  const year = yearOf(typed)
  const wrong = refused !== undefined && refused === typed
  const maybe = wrong && year && year.number < 100 ? expandYear(typed) : null
  return (
    <div className={wrapperClass}>
      <input
        type="date"
        value={typed}
        aria-label={label}
        aria-invalid={wrong}
        aria-describedby={wrong ? `${id}-why` : undefined}
        onChange={(event) => {
          const day = event.target.value
          setTyped(day)
          onChange?.(day)
          if (day === '' || (yearOf(day)?.number ?? 0) >= SETTLED_YEAR) settle(day)
        }}
        onBlur={() => {
          const day = expandYear(typed)
          if (day !== typed) {
            setTyped(day)
            onChange?.(day)
          }
          settle(day)
        }}
        className={`${className} ${wrong ? 'border-bad' : ''}`}
      />
      {wrong && (
        <p id={`${id}-why`} role="alert" className="mt-1 text-xs text-bad">
          {maybe && year ? t('docs.fields.dateTypo', { typed: year.text, year: yearOf(maybe)?.text }) : t('docs.fields.dateRange', { from: YEAR_FROM, to: YEAR_TO })}
          {maybe && (
            <button
              type="button"
              onClick={() => {
                setTyped(maybe)
                onChange?.(maybe)
                settle(maybe)
              }}
              className="ml-2 font-semibold underline"
            >
              {t('docs.fields.dateTake')}
            </button>
          )}
        </p>
      )}
    </div>
  )
}

/** The tags as chips, each with a cross, and the field for another one (with the tags of the vault to choose from). */
export function TagEditor({ tags, onChange, label, known = [] }: { tags: string[]; onChange: (tags: string[]) => void; label: string; known?: string[] }) {
  const { t } = useTranslation()
  const add = (name: string) => {
    const word = name.trim().replace(/^#/, '')
    if (word && !tags.some((had) => had.toLocaleLowerCase() === word.toLocaleLowerCase())) onChange([...tags, word])
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {tags.map((name) => (
        <span key={name} className="inline-flex items-center gap-1 rounded-full bg-sheet-2 py-1 pr-1.5 pl-2.5 text-xs font-semibold">
          {name}
          <button type="button" onClick={() => onChange(tags.filter((had) => had !== name))} aria-label={t('docs.fields.removeTag', { tag: name })} className="rounded-full p-0.5 text-muted hover:text-ink">
            <X size={12} aria-hidden />
          </button>
        </span>
      ))}
      <TagPicker known={known} taken={tags} onAdd={add} placeholder={t('docs.fields.addTag')} label={label} />
    </div>
  )
}

/**
 * The dates of a document with their kind; each kind once. A new one starts at the document's date. `onChange` is called
 * when a date stands; a page that keeps a draft takes every keystroke through `onDraft` too. `refused` is the field the
 * server turned down (`dates[n]`, n counted in `dates`) with the value it refused.
 */
export function Dates({ dates, onChange, onDraft, start, why, refused, keep }: { dates: DateEntry[]; onChange: (dates: DateEntry[]) => void; onDraft?: (dates: DateEntry[]) => void; start: string | null; why?: string; refused?: { field: string; value: string } | null; keep?: KeepContext }) {
  const { t } = useTranslation()
  const [adding, setAdding] = useState(false)
  const today = dayInDays(0)
  // "Aufbewahren bis" worked out from the kind: the stored one while nothing it rests on was changed, else the sum.
  const stored = dates.find((d) => d.kind === KEEP)
  const fromKind = stored ? stored.manual === false : !!keep?.years
  const worked = (() => {
    if (!fromKind || !keep) return null
    if (stored && keep.fresh) return { date: stored.date, years: Number(stored.date.slice(0, 4)) - keep.base }
    return keep.years ? { date: `${keep.base + keep.years}-12-31`, years: keep.years } : null
  })()
  const shown = dates.filter((d) => !(d.kind === KEEP && fromKind))
  const free = DATE_KINDS.filter((kind) => !shown.some((d) => d.kind === kind) && !(kind === KEEP && worked))
  const yearsText = (years: number) => t('keeping.years', { count: years })
  const byHand = (day: string): DateEntry => ({ kind: KEEP, date: day, manual: true })
  const withoutKeep = dates.filter((d) => d.kind !== KEEP)
  return (
    <div className="text-sm">
      <div className="flex items-center justify-between">
        <span className="font-semibold">{t('docs.fields.dates')}</span>
        <WhyBadge why={why} />
      </div>
      <div className="mt-1 space-y-1.5">
        {[...shown].sort((a, b) => DATE_KINDS.indexOf(a.kind) - DATE_KINDS.indexOf(b.kind)).map((entry) => {
          // A "keep until" in this list was set by hand: changing it keeps it so.
          const set = (d: DateEntry, day: string) => (d.kind !== entry.kind ? d : entry.kind === KEEP ? byHand(day) : { ...d, date: day })
          return (
            <div key={entry.kind}>
              <div className="flex items-start gap-2">
                <span className="w-32 pt-2 text-ink-2">{t(`docs.dateKinds.${entry.kind}`)}</span>
                <DateInput
                  value={entry.date}
                  label={t(`docs.dateKinds.${entry.kind}`)}
                  // The server counts the terms as they were sent, in the order of the list given here.
                  refused={refused && refused.field === `dates[${dates.findIndex((d) => d.kind === entry.kind)}]` ? refused.value : undefined}
                  onChange={onDraft && ((day) => day && onDraft(dates.map((d) => set(d, day))))}
                  onCommit={(day) => day && onChange(dates.map((d) => set(d, day)))}
                  className="input h-9 w-full"
                  wrapperClass="min-w-0 flex-1"
                />
                <button type="button" onClick={() => onChange(dates.filter((d) => d.kind !== entry.kind))} className="mt-1.5 rounded-full p-1.5 text-muted hover:bg-sheet-2" aria-label={t('docs.fields.removeDate', { kind: t(`docs.dateKinds.${entry.kind}`) })}>
                  <X size={14} aria-hidden />
                </button>
              </div>
              {entry.kind === KEEP && keep?.years && keep.kindName && (
                <p className="mt-1 pl-34 text-xs text-muted">
                  {t('keeping.byHandNote')}{' '}
                  <button type="button" onClick={() => onChange(withoutKeep)} className="font-semibold text-accent hover:underline">
                    {t('keeping.back', { kind: keep.kindName, years: yearsText(keep.years) })}
                  </button>
                </p>
              )}
            </div>
          )
        })}
        {worked && keep && (
          <div>
            <div className="flex items-start gap-2">
              <span className="w-32 pt-2 text-ink-2">{t('docs.dateKinds.keep_until')}</span>
              <DateInput
                value={worked.date}
                label={t('docs.dateKinds.keep_until')}
                refused={refused && stored && refused.field === `dates[${dates.indexOf(stored)}]` ? refused.value : undefined}
                onChange={onDraft && ((day) => day && onDraft([...withoutKeep, byHand(day)]))}
                onCommit={(day) => day && day !== worked.date && onChange([...withoutKeep, byHand(day)])}
                className="input h-9 w-full"
                wrapperClass="min-w-0 flex-1"
              />
              <span className="w-7 shrink-0" />
            </div>
            <p className="mt-1 pl-34 text-xs text-muted">
              {t('keeping.fromKind', { kind: keep.kindName ?? '', years: yearsText(worked.years), year: keep.base })}
              {worked.date < today && <span className="font-semibold text-warn"> {t('keeping.over')}</span>}
            </p>
          </div>
        )}
        {adding ? (
          <div className="flex flex-wrap gap-1.5">
            {free.map((kind) => (
              <Chip
                key={kind}
                onClick={() => {
                  onChange(kind === KEEP ? [...withoutKeep, byHand(start ?? today)] : [...dates, { kind, date: start ?? today }])
                  setAdding(false)
                }}
              >
                {t(`docs.dateKinds.${kind}`)}
              </Chip>
            ))}
          </div>
        ) : (
          free.length > 0 && (
            <button type="button" onClick={() => setAdding(true)} className="inline-flex items-center gap-1 text-xs font-semibold text-accent">
              <Plus size={13} aria-hidden /> {t('docs.fields.addDate')}
            </button>
          )
        )}
      </div>
      <p className="mt-1 text-xs text-muted">{t('docs.fields.datesHint')}</p>
    </div>
  )
}
