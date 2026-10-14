/**
 * Deadlines (the mock's `FristenPage`): what has to be paid, cancelled or claimed under a warranty, from every vault where
 * the person may change things (like the inbox). Overdue first, then the next 14 days, then later. "Bezahlt",
 * "Gekündigt" or "Erledigt" ends the reminders for everybody; "Später" only pauses them for oneself. Everything comes
 * from `GET /api/v1/deadlines`, the rights are the server's.
 */
import { CalendarClock, Check, ChevronDown, Clock, Receipt, RotateCcw, ScrollText, ShieldCheck, Users, type LucideIcon } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { ApiError, deadlinesApi, vaultsApi, type Deadline, type DeadlineQuery, type Deadlines, type DeadlineSection, type DeadlineWhat, type Vault } from '../api/client'
import { Button } from '../components/Button'
import { Chip } from '../components/docs'
import { MayGo, MayGoChip } from '../components/MayGo'
import { VaultIcon } from '../components/VaultIcon'
import { shortDate } from '../lib/dates'
import { addDays, LATER_SHOWN, relative, SNOOZE_DAYS, useDayName, weekday } from '../lib/deadlines'
import { errorText } from '../lib/errors'
import { money } from '../lib/money'
import { personName } from '../lib/people'
import { useMayGo } from '../lib/mayGo'
import { inboxChanged, iso, listOf, useSay } from '../lib/say'
import { useAuth } from '../state/auth'

const ICON: Record<DeadlineWhat, LucideIcon> = { pay: Receipt, cancel: ScrollText, ends: CalendarClock, warranty: ShieldCheck }
/** `go`: "Darf weg", the documents whose keeping time is over (`components/MayGo.tsx`). */
type Filter = 'all' | 'pay' | 'cancel' | 'warranty' | 'go'
const FILTERS: Exclude<Filter, 'go'>[] = ['all', 'pay', 'cancel', 'warranty']

/** "12.10.": a day without its year. */
function dayMonth(day: string, language: string): string {
  try {
    return new Intl.DateTimeFormat(language, { day: '2-digit', month: '2-digit' }).format(new Date(`${day}T12:00:00`))
  } catch {
    return day
  }
}

export function DeadlinesPage() {
  const { t } = useTranslation()
  const { me } = useAuth()
  const [filter, setFilter] = useState<Filter>('all')
  const [vault, setVault] = useState<string>('all')
  const [showDone, setShowDone] = useState(false)
  const [allLater, setAllLater] = useState(false)
  const [found, setFound] = useState<Deadlines | null>(null)
  const [vaults, setVaults] = useState<Vault[]>([])
  const [problem, setProblem] = useState<string | null>(null)

  useEffect(() => {
    void vaultsApi.list().then((list) => setVaults(listOf(list)), () => undefined)
  }, [])

  const load = useCallback(() => {
    const query: DeadlineQuery = { done: true, ...(filter !== 'all' && filter !== 'go' ? { what: filter } : {}) }
    if (vault === 'shared') query.shared = true
    else if (vault !== 'all') query.vault_id = Number(vault)
    return deadlinesApi.list(query).then(
      (answer) => {
        setFound(answer)
        setProblem(null)
      },
      (error) => setProblem(errorText(error instanceof ApiError ? error.code : 'internal_error')),
    )
  }, [filter, vault])
  useEffect(() => {
    void load()
  }, [load])

  // "Darf weg": the count on the chip is the whole of it; the section follows the vault chosen on this page. Documents
  // seen through a share alone are not in it (the server looks at vaults where the person may change things).
  const mayGoAll = useMayGo()
  const vaultNumber = /^\d+$/.test(vault) ? Number(vault) : undefined
  const mayGoVault = useMayGo(vaultNumber, vaultNumber !== undefined)
  const mayGo = vault === 'all' ? mayGoAll : vault === 'shared' ? { ...mayGoAll, items: [], total: 0 } : mayGoVault

  const changed = useCallback(() => {
    inboxChanged()
    return load()
  }, [load])
  const goChanged = () => {
    mayGoAll.reload()
    mayGoVault.reload()
    void load()
  }

  const section = (part: DeadlineSection | null | undefined): DeadlineSection => ({ total: part?.total ?? 0, items: listOf(part?.items) })
  const overdue = section(found?.overdue)
  const soon = section(found?.soon)
  const later = section(found?.later)
  const done = section(found?.done)
  const open = overdue.total + soon.total + later.total
  const counts = found?.counts ?? {}
  const withDeadlines = vaults.filter((v) => (counts[String(v.id)] ?? 0) > 0 || vault === String(v.id))
  const vaultOf = (id: number) => vaults.find((v) => v.id === id)

  return (
    <div className="page pt-6 pb-28 lg:pt-8 lg:pb-12">
      <div className="mb-5">
        <h1 className="font-display text-3xl font-semibold tracking-tight">{t('deadlines.title')}</h1>
        <p className="max-w-2xl text-sm text-muted">{t('deadlines.intro')}</p>
      </div>

      <div className="scroll-x -mx-1 mb-2 flex gap-2 overflow-x-auto px-1 pb-1" role="group" aria-label={t('deadlines.filters')}>
        {FILTERS.map((value) => (
          <Chip key={value} active={filter === value} onClick={() => setFilter(value)}>
            {t(`deadlines.filter.${value}`)}
          </Chip>
        ))}
        <MayGoChip count={mayGoAll.total} active={filter === 'go'} onClick={() => setFilter('go')} />
        <span className="mx-1 w-px shrink-0 bg-line" />
        <Chip active={vault === 'all'} onClick={() => setVault('all')}>
          {t('deadlines.allVaults')}
        </Chip>
        {withDeadlines.map((v) => (
          <Chip key={v.id} active={vault === String(v.id)} onClick={() => setVault(String(v.id))}>
            {v.personal_of !== null && v.personal_of === me?.id ? t('deadlines.myVault') : v.name}
          </Chip>
        ))}
        {((found?.shared ?? 0) > 0 || vault === 'shared') && (
          <Chip active={vault === 'shared'} onClick={() => setVault('shared')}>
            {t('deadlines.shared')}
          </Chip>
        )}
      </div>
      <label className={`mb-6 inline-flex cursor-pointer items-center gap-2 text-sm text-ink-2 ${filter === 'go' ? 'invisible' : ''}`}>
        <input type="checkbox" checked={showDone} onChange={(event) => setShowDone(event.target.checked)} className="h-4 w-4 accent-[var(--accent)]" />
        {done.total > 0 ? t('deadlines.showDoneCount', { count: done.total }) : t('deadlines.showDone')}
      </label>

      {problem && (
        <p role="alert" className="mb-4 text-sm text-bad">
          {problem}
        </p>
      )}

      {mayGoAll.problem && filter === 'go' && (
        <p role="alert" className="mb-4 text-sm text-bad">
          {errorText(mayGoAll.problem)}
        </p>
      )}

      {filter === 'go' ? (
        <MayGo items={mayGo.items} total={mayGo.total} vaults={vaults} mineId={me?.id ?? 0} onChanged={goChanged} />
      ) : found === null ? null : open === 0 && !showDone ? (
        <div className="space-y-7">
          <div className="card p-12 text-center">
            <Check size={30} className="mx-auto text-ok" aria-hidden />
            <p className="mt-3 font-display text-xl font-semibold">{t('deadlines.nothing')}</p>
            <p className="mt-1 text-sm text-ink-2">{t('deadlines.nothingHint')}</p>
          </div>
          {filter === 'all' && mayGo.total > 0 && <MayGo items={mayGo.items} total={mayGo.total} vaults={vaults} mineId={me?.id ?? 0} onChanged={goChanged} />}
        </div>
      ) : (
        <div className="space-y-7">
          <Section title={t('deadlines.overdue')} part={overdue} warn vaultOf={vaultOf} onChanged={changed} />
          <Section title={t('deadlines.soon', { days: found.soon_days })} part={soon} empty={t('deadlines.soonEmpty')} vaultOf={vaultOf} onChanged={changed} />
          <Section
            title={t('deadlines.later')}
            part={allLater ? later : { total: later.total, items: later.items.slice(0, LATER_SHOWN) }}
            more={!allLater && later.total > LATER_SHOWN ? () => setAllLater(true) : undefined}
            vaultOf={vaultOf}
            onChanged={changed}
          />
          {showDone && <Section title={t('deadlines.done')} part={done} empty={t('deadlines.doneEmpty')} vaultOf={vaultOf} onChanged={changed} />}
          {filter === 'all' && mayGo.total > 0 && <MayGo items={mayGo.items} total={mayGo.total} vaults={vaults} mineId={me?.id ?? 0} onChanged={goChanged} />}
        </div>
      )}
    </div>
  )
}

type SectionProps = { title: string; part: DeadlineSection; warn?: boolean; empty?: string; more?: () => void; vaultOf: (id: number) => Vault | undefined; onChanged: () => Promise<void> }

function Section({ title, part, warn, empty, more, vaultOf, onChanged }: SectionProps) {
  const { t } = useTranslation()
  if (!part.total && !empty) return null
  return (
    <section>
      <h2 className={`mb-2 flex items-center gap-2 text-sm font-bold tracking-wide uppercase ${warn ? 'text-warn' : 'text-muted'}`}>
        {title}
        {part.total > 0 && <span className={`rounded-full px-1.5 text-xs ${warn ? 'bg-warn-soft' : 'bg-sheet-2'}`}>{part.total}</span>}
      </h2>
      {part.total === 0 ? (
        <p className="rounded-2xl border border-dashed border-line px-5 py-4 text-sm text-muted">{empty}</p>
      ) : (
        <ul className="card divide-y divide-line">
          {part.items.map((x) => (
            <Row key={`${x.document_id}:${x.kind}`} x={x} vault={vaultOf(x.vault_id)} onChanged={onChanged} />
          ))}
          {more && (
            <li>
              <button type="button" onClick={more} className="w-full rounded-b-[1.25rem] px-5 py-3 text-sm font-semibold text-accent hover:bg-sheet-2">
                {t('deadlines.showAll', { count: part.total })}
              </button>
            </li>
          )}
        </ul>
      )}
    </section>
  )
}

function DateBlock({ date, warn, done }: { date: string; warn?: boolean; done?: boolean }) {
  const { t } = useTranslation()
  const [, m, d] = date.split('-').map(Number)
  const months = t('deadlines.months', { returnObjects: true }) as string[]
  const days = t('deadlines.weekdays', { returnObjects: true }) as string[]
  return (
    <div className={`flex w-14 shrink-0 flex-col items-center rounded-xl py-1.5 leading-none ${done ? 'bg-sheet-2 text-muted' : warn ? 'bg-warn text-paper' : 'bg-accent-soft text-accent'}`} aria-hidden>
      <span className="text-[0.65rem] font-bold uppercase">{days[weekday(date)]}</span>
      <span className="font-display text-2xl font-semibold tabular-nums">{d}</span>
      <span className="text-[0.7rem] font-bold uppercase">{months[m - 1]}</span>
    </div>
  )
}

function Row({ x, vault, onChanged }: { x: Deadline; vault: Vault | undefined; onChanged: () => Promise<void> }) {
  const { t, i18n } = useTranslation()
  const say = useSay()
  const dayName = useDayName()
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const Icon = ICON[x.what]
  const overdue = x.days < 0 && !x.done
  const date = (day: string) => shortDate(day, i18n.language)
  const rel = relative(x.days)
  const doneWord = t(`deadlines.what.${x.what}.done`)

  const act = async (work: () => Promise<unknown>, said: string) => {
    if (busy) return
    setBusy(true)
    setProblem(null)
    try {
      await work()
      await onChanged()
      say(said)
    } catch (error) {
      setProblem(errorText(error instanceof ApiError ? error.code : 'internal_error'))
    } finally {
      setBusy(false)
    }
  }
  const laterWords = (day: string) => ({ day: (t('deadlines.weekdays', { returnObjects: true }) as string[])[weekday(day)], date: dayMonth(day, i18n.language) })
  const later = (days: 1 | 3 | 7) => act(() => deadlinesApi.snooze(x.document_id, x.kind, days), t('deadlines.saidLater', laterWords(addDays(todayOf(x), days))))

  return (
    <li className={`flex gap-4 px-4 py-4 first:rounded-t-[1.25rem] last:rounded-b-[1.25rem] sm:px-5 ${overdue ? 'bg-warn-soft/40' : ''}`} data-testid="deadline">
      <DateBlock date={x.date} warn={overdue} done={!!x.done} />
      <div className="min-w-0 flex-1">
        <p className={`flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm font-semibold ${overdue ? 'text-warn' : 'text-ink-2'}`}>
          <Icon size={15} className="shrink-0" aria-hidden />
          <span>
            {t(`deadlines.what.${x.what}.name`)} {dayName(x.date)}
          </span>
          {!x.done && <span className={`rounded-full px-2 py-0.5 text-xs ${overdue ? 'bg-warn-soft' : 'bg-sheet-2 text-muted'}`}>{t(`deadlines.relative.${rel.key}`, { count: rel.count })}</span>}
        </p>
        <Link to={x.status === 'inbox' ? `/eingang/${x.document_id}` : `/dokument/${x.document_id}`} className="mt-0.5 flex min-w-0 items-center gap-2 font-display text-lg font-semibold hover:text-accent">
          <bdi className="truncate">{x.title}</bdi>
          {x.status === 'inbox' && <span className="shrink-0 rounded-full bg-accent-soft px-2 py-0.5 font-sans text-xs font-bold text-accent">{t('deadlines.inInbox')}</span>}
        </Link>
        <p className="flex flex-wrap items-center gap-x-2 text-sm text-muted">
          {x.sender && (
            <>
              <bdi>{x.sender}</bdi>
              <span aria-hidden>·</span>
            </>
          )}
          <span className="inline-flex items-center gap-1.5">
            {vault && !x.via_share ? (
              <>
                <VaultIcon icon={vault.icon} size={14} />
                {vault.personal_of !== null ? t('docs.inbox.personalVault', { name: vault.name }) : vault.name}
              </>
            ) : (
              <>
                <Users size={14} aria-hidden /> {t('deadlines.shared')}
              </>
            )}
          </span>
        </p>

        {x.what === 'cancel' && x.notice && (
          <p className="mt-1.5 text-sm text-ink-2">
            {t('deadlines.contractLine', { end: date(x.end), notice: t(`deadlines.notice.${x.notice.unit}`, { count: x.notice.n }) })}{' '}
            {x.renews_to ? t('deadlines.renewsTo', { date: date(x.renews_to) }) : t('deadlines.endsItself')}
          </p>
        )}
        {x.what === 'ends' && x.missed && !x.done && (
          <p className="mt-1.5 text-sm text-ink-2">
            {t('deadlines.missed', { date: date(x.missed) })}
            {x.renews_to ? ` ${t('deadlines.missedRenews', { to: date(x.renews_to), on: date(addDays(x.end, 1)) })}` : ''}
          </p>
        )}

        {x.done ? (
          <p className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            <span className="inline-flex items-center gap-1 rounded-full bg-ok-soft px-2.5 py-0.5 font-semibold text-ok">
              <Check size={13} aria-hidden /> {doneWord}
            </span>
            <span className="text-muted">
              {x.done.by ? `${personName(x.done.by)}, ` : ''}
              {date(x.done.at)}
            </span>
            <button type="button" disabled={busy} onClick={() => void act(() => deadlinesApi.reopen(x.document_id, x.kind), t('deadlines.saidOpen'))} className="inline-flex items-center gap-1 font-semibold text-accent hover:underline">
              <RotateCcw size={13} aria-hidden /> {t('deadlines.undo')}
            </button>
          </p>
        ) : (
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <Button size="sm" variant="soft" disabled={busy} onClick={() => void act(() => deadlinesApi.done(x.document_id, x.kind), t('deadlines.saidDone', { done: doneWord, title: iso(x.title) }))}>
              <Check size={15} aria-hidden /> {doneWord}
            </Button>
            {x.snoozed_until ? (
              <span className="inline-flex flex-wrap items-center gap-x-1.5 text-sm text-muted">
                <Clock size={14} aria-hidden /> {t('deadlines.snoozed', laterWords(x.snoozed_until))}
                <button type="button" disabled={busy} onClick={() => void act(() => deadlinesApi.unsnooze(x.document_id, x.kind), t('deadlines.saidOpen'))} className="font-semibold text-accent hover:underline">
                  {t('deadlines.again')}
                </button>
              </span>
            ) : (
              <Later today={todayOf(x)} onPick={(days) => void later(days)} disabled={busy} />
            )}
          </div>
        )}
        {problem && (
          <p role="alert" className="mt-1.5 text-sm text-bad">
            {problem}
          </p>
        )}
      </div>
      {x.what === 'pay' && x.amount !== null && (
        <div className={`hidden shrink-0 text-right font-semibold tabular-nums sm:block ${x.done ? 'text-muted line-through' : ''}`}>{money(x.amount, i18n.language, x.currency)}</div>
      )}
    </li>
  )
}

/** Today as the server counted it for this deadline: its day to act minus the days to it. */
function todayOf(x: Deadline): string {
  return addDays(x.date, -x.days)
}

function Later({ today, onPick, disabled }: { today: string; onPick: (days: 1 | 3 | 7) => void; disabled?: boolean }) {
  const { t, i18n } = useTranslation()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => box.current && !box.current.contains(event.target as Node) && setOpen(false)
    const escape = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false)
    window.addEventListener('mousedown', close)
    window.addEventListener('keydown', escape)
    return () => {
      window.removeEventListener('mousedown', close)
      window.removeEventListener('keydown', escape)
    }
  }, [open])
  return (
    <div ref={box} className="relative">
      <Button size="sm" variant="ghost" disabled={disabled} onClick={() => setOpen(!open)} aria-expanded={open}>
        <Clock size={15} aria-hidden /> {t('deadlines.laterButton')} <ChevronDown size={14} aria-hidden />
      </Button>
      {open && (
        <div className="card rise absolute top-full left-0 z-40 mt-1 w-52 p-1.5" role="menu">
          {SNOOZE_DAYS.map((days) => (
            <button
              key={days}
              type="button"
              role="menuitem"
              onClick={() => {
                onPick(days)
                setOpen(false)
              }}
              className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm font-semibold text-ink-2 hover:bg-sheet-2 hover:text-ink"
            >
              {t(`deadlines.laterMenu.${days}`)}
              <span className="text-xs font-normal text-muted">{dayMonth(addDays(today, days), i18n.language)}</span>
            </button>
          ))}
          <p className="px-3 pt-1 pb-1.5 text-xs text-muted">{t('deadlines.laterHint')}</p>
        </div>
      )}
    </div>
  )
}
