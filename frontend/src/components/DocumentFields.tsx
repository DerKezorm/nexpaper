/**
 * The fields of a document as the inbox and the document page edit them:
 * an amount typed the way people type it, the tags as chips, and the
 * dates with their kind (due, contract until, warranty until, keep until). Each part keeps nothing of its own: the page
 * holds the values and decides when they are saved.
 */
import { Check, Plus, X } from 'lucide-react'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import type { DateKind, DocumentDate, Notice } from '../api/client'
import { dayInDays, shortDate } from '../lib/dates'
import { YEAR_FROM, YEAR_TO, expandYear, yearOf } from '../lib/dateInput'
import { keepUntil } from '../lib/keeping'
import { addMonths, daysBetween, isDay, lastToCancel, useDayName, whatOfKind } from '../lib/deadlines'
import { personName } from '../lib/people'
import { amountText, parseAmount } from '../lib/money'
import { Chip, WhyBadge } from './docs'
import { TagPicker } from './TagPicker'

// A year typed with all four digits is settled as soon as it stands; a shorter one waits for the field to be left.
const SETTLED_YEAR = 1000

const DATE_KINDS: DateKind[] = ['due', 'contract_end', 'warranty_end', 'keep_until']
/** A date of a document; a contract may carry its notice period and how many months it renews by. `manual` only for
 * `keep_until`: set by hand (`false`: worked out from the kind). */
export type DateEntry = { kind: DateKind; date: string; notice?: Notice | null; renew_months?: number | null; manual?: boolean }
/**
 * What `keep_until` is worked out from: the kind's name and keeping time, the year the time counts
 * from, and whether the document is as it was saved (`fresh`: its stored date stands; otherwise a kind or a date was
 * changed in the draft and the page works the date out itself, as the server will on saving).
 */
export type KeepContext = {
  kindName: string | null
  years: number | null
  base: number
  fresh: boolean
  /**
   * The kind has the switch "expired ones into the trash by themselves" and the document is one the nightly task would
   * take: `inbox` (it goes once it is filed) or `filed`. `over` is the server's verdict that the time is over (the
   * document page); left out, the date shown decides (the inbox, where the date is being edited).
   */
  auto?: { where: 'inbox' | 'filed'; over?: boolean } | null
}
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
 * The dates of a document with their kind; each kind once. A new one starts at the document's date, a contract with a
 * notice period of 3 months and a renewal of 12. `onChange` is called when a date stands; a page
 * that keeps a draft takes every keystroke through `onDraft` too. `refused` is the field the server turned down
 * (`dates[n]`, n counted in `dates`) with the value it refused. `done` and `onDone` (the document page): each deadline
 * says whether it is paid, cancelled or claimed, with a button to mark it so or to take that back.
 */
export function Dates({ dates, onChange, onDraft, start, why, refused, done, onDone, keep }: { dates: DateEntry[]; onChange: (dates: DateEntry[]) => void; onDraft?: (dates: DateEntry[]) => void; start: string | null; why?: string; refused?: { field: string; value: string; kind?: string } | null; done?: Partial<Record<string, DocumentDate['done']>>; onDone?: (kind: DateKind, done: boolean) => void; keep?: KeepContext }) {
  const { t } = useTranslation()
  const [adding, setAdding] = useState(false)
  const today = dayInDays(0)
  // "Aufbewahren bis" worked out from the kind: the stored one while nothing it rests on was changed, else the sum.
  const stored = dates.find((d) => d.kind === KEEP)
  const fromKind = stored ? stored.manual === false : !!keep?.years
  const worked = (() => {
    if (!fromKind || !keep) return null
    if (stored && keep.fresh) return { date: stored.date, years: Number(stored.date.slice(0, 4)) - keep.base }
    return keep.years ? { date: keepUntil(keep.base, keep.years), years: keep.years } : null
  })()
  const shown = dates.filter((d) => !(d.kind === KEEP && fromKind))
  const free = DATE_KINDS.filter((kind) => !shown.some((d) => d.kind === kind) && !(kind === KEEP && worked))
  const yearsText = (years: number) => t('keeping.years', { count: years })
  const byHand = (day: string): DateEntry => ({ kind: KEEP, date: day, manual: true })
  const withoutKeep = dates.filter((d) => d.kind !== KEEP)
  const change = (kind: DateKind, patch: Partial<DateEntry>) => onChange(dates.map((d) => (d.kind === kind ? { ...d, ...patch } : d)))
  /** The time is over and the nightly task will take the document: said under "Aufbewahren bis". */
  const goesTonight = (day: string) => !!keep?.auto && (keep.auto.over ?? day < today)
  const tonight = (
    <span className="font-semibold text-warn" data-testid="goes-tonight">
      {' '}
      {t(keep?.auto?.where === 'inbox' ? 'keeping.goesTonightInbox' : 'keeping.goesTonight')}
    </span>
  )
  return (
    <div className="text-sm">
      <div className="flex items-center justify-between">
        <span className="font-semibold">{t('docs.fields.dates')}</span>
        <WhyBadge why={why} />
      </div>
      <div className="mt-1 space-y-2">
        {[...shown].sort((a, b) => DATE_KINDS.indexOf(a.kind) - DATE_KINDS.indexOf(b.kind)).map((entry) => {
          // A "keep until" in this list was set by hand: changing it keeps it so.
          const set = (d: DateEntry, day: string) => (d.kind !== entry.kind ? d : entry.kind === KEEP ? byHand(day) : { ...d, date: day })
          return (
            <div key={entry.kind}>
              <div className="flex items-start gap-2">
                <span className="w-32 shrink-0 pt-2 text-ink-2">{t(`docs.dateKinds.${entry.kind}`)}</span>
                <DateInput
                  value={entry.date}
                  label={t(`docs.dateKinds.${entry.kind}`)}
                  // The server counts the terms as they were sent, in the order of the list given here.
                  refused={refused && (refused.kind ? refused.kind === entry.kind : refused.field === `dates[${dates.findIndex((d) => d.kind === entry.kind)}]`) ? refused.value : undefined}
                  onChange={onDraft && ((day) => day && onDraft(dates.map((d) => set(d, day))))}
                  onCommit={(day) => day && onChange(dates.map((d) => set(d, day)))}
                  className="input h-9 w-full"
                  wrapperClass="min-w-0 flex-1"
                />
                <button type="button" onClick={() => onChange(dates.filter((d) => d.kind !== entry.kind))} className="mt-1.5 rounded-full p-1.5 text-muted hover:bg-sheet-2" aria-label={t('docs.fields.removeDate', { kind: t(`docs.dateKinds.${entry.kind}`) })}>
                  <X size={14} aria-hidden />
                </button>
              </div>
              {onDone && entry.kind !== KEEP && <DoneLine kind={entry.kind} done={done?.[entry.kind] ?? null} onDone={(on) => onDone(entry.kind, on)} />}
              {entry.kind === 'contract_end' && <ContractTerms entry={entry} today={today} change={(patch) => change('contract_end', patch)} />}
              {entry.kind === KEEP && keep?.years && keep.kindName && (
                <p className="mt-1 pl-34 text-xs text-muted">
                  {t('keeping.byHandNote')}{' '}
                  <button type="button" onClick={() => onChange(withoutKeep)} className="font-semibold text-accent hover:underline">
                    {t('keeping.back', { kind: keep.kindName, years: yearsText(keep.years) })}
                  </button>
                  {goesTonight(entry.date) && tonight}
                </p>
              )}
              {entry.kind === KEEP && !(keep?.years && keep.kindName) && goesTonight(entry.date) && <p className="mt-1 pl-34 text-xs">{tonight}</p>}
            </div>
          )
        })}
        {worked && keep && (
          <div>
            <div className="flex items-start gap-2">
              <span className="w-32 shrink-0 pt-2 text-ink-2">{t('docs.dateKinds.keep_until')}</span>
              <DateInput
                value={worked.date}
                label={t('docs.dateKinds.keep_until')}
                refused={refused && stored && (refused.kind ? refused.kind === KEEP : refused.field === `dates[${dates.indexOf(stored)}]`) ? refused.value : undefined}
                onChange={onDraft && ((day) => day && onDraft([...withoutKeep, byHand(day)]))}
                onCommit={(day) => day && day !== worked.date && onChange([...withoutKeep, byHand(day)])}
                className="input h-9 w-full"
                wrapperClass="min-w-0 flex-1"
              />
              <span className="w-7 shrink-0" />
            </div>
            <p className="mt-1 pl-34 text-xs text-muted">
              {t('keeping.fromKind', { kind: keep.kindName ?? '', years: yearsText(worked.years), year: keep.base })}
              {goesTonight(worked.date) ? tonight : worked.date < today && <span className="font-semibold text-warn"> {t('keeping.over')}</span>}
            </p>
          </div>
        )}
        {adding ? (
          <div className="flex flex-wrap gap-1.5">
            {free.map((kind) => (
              <Chip
                key={kind}
                onClick={() => {
                  const day = start ?? today
                  onChange(kind === KEEP ? [...withoutKeep, byHand(day)] : [...dates, kind === 'contract_end' ? { kind, date: day, notice: { n: 3, unit: 'months' }, renew_months: 12 } : { kind, date: day }])
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
      <p className="mt-1.5 text-xs text-muted">
        <Trans i18nKey="reminders.datesNote" components={{ account: <Link to="/konto?tab=erinnerungen" className="font-semibold text-accent hover:underline" /> }} />
      </p>
    </div>
  )
}


const RENEW_CHOICES = [0, 1, 3, 6, 12, 24]

/** Notice period and renewal of a contract, and the last day to cancel worked out from them.
 * The number of the period is taken when the field is left or Enter is pressed. */
function ContractTerms({ entry, today, change }: { entry: DateEntry; today: string; change: (patch: Partial<DateEntry>) => void }) {
  const { t, i18n } = useTranslation()
  const dayName = useDayName()
  const notice = entry.notice ?? null
  const [typed, setTyped] = useState(notice ? String(notice.n) : '')
  const shown = notice ? String(notice.n) : ''
  const [was, setWas] = useState(shown)
  if (was !== shown) {
    // The period came anew from outside (saved, another document): the field shows it.
    setWas(shown)
    setTyped(shown)
  }
  const commit = () => {
    if (!notice) return
    const n = Math.min(24, Math.max(1, Math.round(Number(typed)) || 1))
    setTyped(String(n))
    if (n !== notice.n) change({ notice: { ...notice, n } })
  }
  const last = notice && isDay(entry.date) ? lastToCancel(entry.date, notice) : null
  const passed = last !== null && daysBetween(today, last) < 0
  const renew = entry.renew_months ?? 0
  const choices = RENEW_CHOICES.includes(renew) ? RENEW_CHOICES : [...RENEW_CHOICES, renew].sort((a, b) => a - b)
  return (
    <div className="mt-1.5 space-y-1.5 rounded-xl bg-sheet-2/70 px-3 py-2.5" data-testid="contract-terms">
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-32 text-ink-2">{t('deadlines.terms.notice')}</span>
        {notice ? (
          <>
            <input
              type="number"
              min={1}
              max={24}
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              onBlur={commit}
              onKeyDown={(event) => event.key === 'Enter' && commit()}
              className="input h-9 w-16 text-center"
              aria-label={t('deadlines.terms.noticeNumber')}
            />
            <select value={notice.unit} onChange={(event) => change({ notice: { ...notice, unit: event.target.value as Notice['unit'] } })} className="input h-9 w-auto" aria-label={t('deadlines.terms.noticeUnit')}>
              <option value="weeks">{t('deadlines.terms.weeks')}</option>
              <option value="months">{t('deadlines.terms.months')}</option>
            </select>
            <button type="button" onClick={() => change({ notice: null })} className="rounded-full p-1.5 text-muted hover:bg-sheet hover:text-ink" aria-label={t('deadlines.terms.noNotice')} title={t('deadlines.terms.noNotice')}>
              <X size={14} aria-hidden />
            </button>
          </>
        ) : (
          <button type="button" onClick={() => change({ notice: { n: 3, unit: 'months' } })} className="inline-flex items-center gap-1 text-xs font-semibold text-accent">
            <Plus size={13} aria-hidden /> {t('deadlines.terms.addNotice')}
          </button>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-32 text-ink-2">{t('deadlines.terms.renew')}</span>
        <select value={renew} onChange={(event) => change({ renew_months: Number(event.target.value) || null })} className="input h-9 w-auto" aria-label={t('deadlines.terms.renewLabel')}>
          {choices.map((months) => (
            <option key={months} value={months}>
              {months === 0 ? t('deadlines.terms.renewNone') : t('deadlines.terms.renewMonths', { count: months })}
            </option>
          ))}
        </select>
      </div>
      {last && (
        <p className={`pt-0.5 text-sm ${passed ? 'text-warn' : 'text-ink'}`} data-testid="last-to-cancel">
          {t('deadlines.terms.lastDay')} <span className="font-semibold">{dayName(last)}</span>
          {passed && (renew ? t('deadlines.terms.passedRenews', { date: shortDate(addMonths(entry.date, renew), i18n.language) }) : t('deadlines.terms.passed'))}
        </p>
      )}
      <p className="text-xs text-muted">{t('deadlines.terms.hint')}</p>
    </div>
  )
}

/** Paid, cancelled, claimed: ends the reminders for everybody. */
function DoneLine({ kind, done, onDone }: { kind: DateKind; done: DocumentDate['done']; onDone: (done: boolean) => void }) {
  const { t, i18n } = useTranslation()
  const what = whatOfKind(kind)
  return (
    <div className="mt-1 flex flex-wrap items-center gap-2 pl-34">
      {done ? (
        <>
          <span className="inline-flex items-center gap-1 rounded-full bg-ok-soft px-2.5 py-0.5 text-xs font-semibold text-ok">
            <Check size={12} aria-hidden /> {t(`deadlines.what.${what}.done`)}
          </span>
          <span className="text-xs text-muted">
            {done.by ? `${personName(done.by)}, ` : ''}
            {shortDate(done.at, i18n.language)}
          </span>
          <button type="button" onClick={() => onDone(false)} className="text-xs font-semibold text-accent hover:underline">
            {t('deadlines.undo')}
          </button>
        </>
      ) : (
        <button type="button" onClick={() => onDone(true)} className="inline-flex items-center gap-1 text-xs font-semibold text-accent hover:underline">
          <Check size={12} aria-hidden /> {t('deadlines.markAs', { what: t(`deadlines.what.${what}.doneShort`) })}
        </button>
      )}
    </div>
  )
}
