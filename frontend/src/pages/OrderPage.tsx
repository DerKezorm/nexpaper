/**
 * Order (`/ordnung`): where senders, kinds and tags are tidied up. One tab for each, a filter by vault above, and for every
 * entry how many documents have it, with the ways to rename it, merge it into another and delete it. Rename, merge and
 * delete are for those who manage the vault (the operator for the kinds that come with nexpaper); everybody else sees the
 * list and the numbers. Everything asks first, with the number of documents it reaches (`ConfirmDialog`).
 *
 * The lists come from `GET /api/v1/order/...`, which looks at the vaults the person is in and nothing else.
 */
import { Archive, GitMerge, Info, Pencil, Plus, Tags, Trash2, Users } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { ApiError, catalogApi, keepingApi, kindsApi, orderApi, vaultsApi, type KeepPreview, type OrderEntry, type OrderWhat, type Vault } from '../api/client'
import { Button } from '../components/Button'
import { Dialog } from '../components/Dialog'
import { useConfirm } from '../components/useConfirm'
import { KindPill } from '../components/docs'
import { VaultFilter } from '../components/VaultFilter'
import { dayInDays, shortDate } from '../lib/dates'
import { errorText } from '../lib/errors'
import { KEEP_CHOICES } from '../lib/keeping'
import { foldName } from '../lib/kinds'
import { iso, listOf, useSay } from '../lib/say'
import { vaultLabel } from '../lib/vaultLabel'
import { useAuth } from '../state/auth'
import { Feedback, TabRow, type Tab } from './settings/ui'

const WHATS: OrderWhat[] = ['senders', 'kinds', 'tags']
const PAGE = 100
/** How long the search field waits after the last key. */
const PAUSE_MS = 250

type Sort = 'name' | 'documents'

/** The address of a tab with a vault chosen: the vault stays across tabs, but "for all vaults" only means something for kinds. */
function paramsFor(tab: OrderWhat, vault: string): Record<string, string> {
  const keep = vault && (/^\d+$/.test(vault) || (vault === 'server' && tab === 'kinds'))
  return { ...(tab === 'senders' ? {} : { tab }), ...(keep ? { vault } : {}) }
}

export function OrderPage() {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const say = useSay()
  const [params, setParams] = useSearchParams()
  const asked = params.get('tab') as OrderWhat | null
  const what: OrderWhat = asked && WHATS.includes(asked) ? asked : 'senders'
  const vault = params.get('vault') ?? ''
  const [typed, setTyped] = useState('')
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<Sort>('name')
  const [vaults, setVaults] = useState<Vault[]>([])
  const [items, setItems] = useState<OrderEntry[] | null>(null)
  const [total, setTotal] = useState(0)
  const [problem, setProblem] = useState<string | null>(null)
  const [renaming, setRenaming] = useState<OrderEntry | null>(null)
  const [merging, setMerging] = useState<OrderEntry | null>(null)
  const [keeping, setKeeping] = useState<{ entry: OrderEntry; years: number } | null>(null)
  const { ask, dialog } = useConfirm()

  useEffect(() => {
    void vaultsApi.list().then((list) => setVaults(listOf<Vault>(list)), () => undefined)
  }, [])
  useEffect(() => {
    const timer = window.setTimeout(() => setQ(typed.trim()), PAUSE_MS)
    return () => window.clearTimeout(timer)
  }, [typed])

  // The kinds are few and come with the server's own: the filter by vault is made here, so that "for all vaults" is one
  // of the choices. Senders and tags are asked for by the vault.
  const byVault = what !== 'kinds' && /^\d+$/.test(vault) ? Number(vault) : undefined
  const [again, setAgain] = useState(0)
  useEffect(() => {
    let alive = true
    orderApi.list(what, { vault_id: byVault, q: q || undefined, order: sort, limit: what === 'kinds' ? 500 : PAGE }).then(
      (answer) => {
        if (!alive) return
        setItems(answer.items)
        setTotal(answer.total)
        setProblem(null)
      },
      (error: unknown) => alive && setProblem(error instanceof ApiError ? error.code : 'internal_error'),
    )
    return () => {
      alive = false
    }
  }, [what, byVault, q, sort, again])
  /** The next page of a long list, put below the ones shown. */
  const more = async () => {
    try {
      const answer = await orderApi.list(what, { vault_id: byVault, q: q || undefined, order: sort, limit: PAGE, offset: items?.length ?? 0 })
      setItems((current) => [...(current ?? []), ...answer.items])
      setTotal(answer.total)
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
    }
  }

  if (!me) return null
  const shown = (items ?? []).filter((entry) => {
    if (what !== 'kinds' || !vault) return true
    return vault === 'server' ? entry.vault_id === null : String(entry.vault_id) === vault
  })
  const vaultName = (id: number | null) => {
    if (id === null) return t('order.everywhere')
    const found = vaults.find((v) => v.id === id)
    return found ? vaultLabel(found, me.id, t('vaults.mine')) : ''
  }
  const refresh = (notice: string) => {
    setAgain((n) => n + 1)
    say(notice)
  }
  const tabs: Tab<OrderWhat>[] = WHATS.map((value) => ({ value, label: t(`order.tabs.${value}`) }))
  const anyReadOnly = shown.some((entry) => !entry.can_change && entry.vault_id !== null)

  /** The keeping time chosen in a row: none at once, a number of years after the question about the documents there. */
  const keepFor = async (entry: OrderEntry, years: number) => {
    setProblem(null)
    try {
      if (!years) {
        await keepingApi.set(entry.id, null, true)
        refresh(t('keeping.removed', { name: iso(entry.name) }))
      } else setKeeping({ entry, years })
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
    }
  }

  /** Asks, then deletes. The number of documents it reaches is in the question. */
  const remove = (entry: OrderEntry) => {
    const count = entry.documents + entry.in_trash
    const name = iso(entry.name)
    const base = what === 'senders' ? 'sender' : what === 'tags' ? 'tag' : 'kind'
    const key = what === 'kinds' && entry.vault_id === null ? 'kindServer' : count > 0 ? `${base}Used` : base
    ask({
      title: t(`confirm.${key}.title`),
      text: t(`confirm.${key}.text`, { count, name }),
      confirm: t(`confirm.${key}.confirm`),
      run: async () => {
        if (what === 'senders') await catalogApi.deleteSender(entry.id)
        else if (what === 'tags') await catalogApi.deleteTag(entry.id)
        else await catalogApi.removeKind(entry.id)
        refresh(t('order.done.deleted'))
      },
    })
  }
  /** After the person chose where an entry goes: asks once more, with the numbers, then merges. */
  const merge = (entry: OrderEntry, into: OrderEntry) => {
    const count = entry.documents + entry.in_trash
    ask({
      title: t('confirm.merge.title'),
      text: count > 0 ? t(`confirm.merge.${what}`, { count, from: iso(entry.name), into: iso(into.name) }) : t('confirm.merge.unused', { from: iso(entry.name) }),
      confirm: t('confirm.merge.confirm'),
      run: async () => {
        await orderApi.merge(what, entry.id, into.id)
        refresh(t('order.done.merged'))
      },
    })
  }

  return (
    <div className="page space-y-5 pt-6 pb-28 lg:pt-8 lg:pb-12">
      <div>
        <h1 className="font-display text-3xl font-semibold tracking-tight">{t('order.title')}</h1>
        <p className="max-w-2xl text-sm text-muted">{t('order.intro')}</p>
      </div>

      <TabRow
        tabs={tabs}
        active={what}
        label={t('order.title')}
        onChange={(value) => {
          setTyped('')
          setItems(null)
          setParams(paramsFor(value, vault), { replace: true })
        }}
      />

      <VaultFilter
        vaults={vaults}
        value={vault}
        onChange={(value) => setParams(paramsFor(what, value), { replace: true })}
        mineId={me.id}
        label={t('order.vault')}
        extra={what === 'kinds' ? { value: 'server', label: t('order.everywhere') } : undefined}
      />

      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          placeholder={t(`order.search.${what}`)}
          aria-label={t(`order.search.${what}`)}
          maxLength={100}
          className="input h-10 min-w-48 flex-1"
        />
        <select value={sort} onChange={(event) => setSort(event.target.value as Sort)} aria-label={t('order.sort')} className="input h-10 w-auto">
          <option value="name">{t('order.sortName')}</option>
          <option value="documents">{t('order.sortDocuments')}</option>
        </select>
      </div>

      <Feedback problem={problem} />

      {items === null ? null : shown.length === 0 ? (
        <p className="card p-6 text-sm text-muted">{q ? t('order.noMatch') : t(`order.empty.${what}`)}</p>
      ) : (
        <ul className="card divide-y divide-line p-0" aria-label={t(`order.tabs.${what}`)}>
          {shown.map((entry) => (
            <li key={entry.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
              {/* A kind keeps room for its name and numbers: on a phone the keeping time goes to a line of its own. */}
              <div className={`flex-1 ${what === 'kinds' ? 'min-w-44' : 'min-w-0'}`}>
                <p className="font-semibold break-words">{what === 'kinds' ? <KindPill kind={{ name: entry.name, hue: entry.hue ?? 30 }} /> : <bdi>{entry.name}</bdi>}</p>
                <p className="mt-0.5 text-sm text-muted">
                  {(!vault || (what === 'kinds' && entry.vault_id === null)) && vaults.length > 1 && (
                    <>
                      <span className="inline-flex items-center gap-1">
                        {entry.vault_id === null ? <Tags size={12} aria-hidden /> : <Users size={12} aria-hidden />} {vaultName(entry.vault_id)}
                      </span>
                      {' · '}
                    </>
                  )}
                  {t('order.documents', { count: entry.documents })}
                  {entry.in_trash > 0 && <> · {t('order.inTrash', { count: entry.in_trash })}</>}
                  {what === 'kinds' && entry.keep_years && entry.keep_new_only ? <> · {t('keeping.newOnly')}</> : null}
                </p>
              </div>
              {what === 'kinds' && <KeepSelect entry={entry} onPick={(years) => void keepFor(entry, years)} />}
              {entry.can_change && (
                <div className="flex shrink-0 items-center gap-1">
                  <IconButton icon={Pencil} text={t('order.rename')} name={entry.name} onClick={() => setRenaming(entry)} />
                  <IconButton icon={GitMerge} text={t('order.merge')} name={entry.name} onClick={() => setMerging(entry)} />
                  <IconButton icon={Trash2} text={t('order.delete')} name={entry.name} onClick={() => remove(entry)} />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {items !== null && what !== 'kinds' && total > items.length && (
        <div className="flex items-center justify-between gap-3 text-sm text-muted">
          <span>{t('order.shown', { shown: items.length.toLocaleString(i18n.language), total: total.toLocaleString(i18n.language) })}</span>
          <Button size="sm" variant="line" onClick={() => void more()}>
            {t('order.more')}
          </Button>
        </div>
      )}
      {what === 'kinds' && items !== null && (
        <div className="flex gap-3 rounded-2xl bg-sheet-2/70 p-4 text-sm text-ink-2">
          <Info size={18} className="mt-0.5 shrink-0 text-accent" aria-hidden />
          <div className="space-y-1.5">
            <p>
              <span className="font-semibold text-ink">{t('keeping.infoLead')}</span> {t('keeping.info')}
            </p>
            <p>{t('keeping.examples')}</p>
          </div>
        </div>
      )}
      {anyReadOnly && <p className="text-xs text-muted">{t('order.readOnly')}</p>}
      {what === 'kinds' && shown.some((entry) => entry.vault_id === null && !entry.can_change) && <p className="text-xs text-muted">{t('order.serverKind')}</p>}

      {what === 'kinds' && <NewKind vaults={vaults} operator={me.role === 'operator'} count={items?.length ?? 0} onAdded={() => refresh(t('order.done.added'))} />}

      {renaming && (
        <RenameDialog
          what={what}
          entry={renaming}
          onClose={() => setRenaming(null)}
          onDone={() => {
            setRenaming(null)
            refresh(t('order.done.renamed'))
          }}
        />
      )}
      {keeping && (
        <KeepDialog
          entry={keeping.entry}
          years={keeping.years}
          onClose={() => setKeeping(null)}
          onDone={(notice) => {
            setKeeping(null)
            refresh(notice)
          }}
        />
      )}
      {merging && (
        <MergeDialog
          what={what}
          entry={merging}
          vaultName={vaultName}
          onClose={() => setMerging(null)}
          onPick={(into) => {
            setMerging(null)
            merge(merging, into)
          }}
        />
      )}
      {dialog}
    </div>
  )
}

/** The keeping time of a kind: a choice for whoever may set it (the operator for the server's kinds, a manager of the
 * vault for its own), else the time as text. */
function KeepSelect({ entry, onPick }: { entry: OrderEntry; onPick: (years: number) => void }) {
  const { t } = useTranslation()
  const years = entry.keep_years ?? 0
  const choices = years && !KEEP_CHOICES.includes(years) ? [...KEEP_CHOICES, years].sort((a, b) => a - b) : KEEP_CHOICES
  return (
    <label className="flex shrink-0 items-center gap-2 text-sm">
      <Archive size={15} className="text-muted" aria-hidden />
      <span className="text-ink-2">{t('keeping.column')}</span>
      {entry.can_change ? (
        <select value={years} onChange={(event) => onPick(Number(event.target.value))} className="input h-9 w-auto" aria-label={t('keeping.selectLabel', { name: entry.name })}>
          <option value={0}>{t('keeping.notSet')}</option>
          {choices.map((n) => (
            <option key={n} value={n}>
              {t('keeping.years', { count: n })}
            </option>
          ))}
        </select>
      ) : (
        <span className="font-semibold">{years ? t('keeping.years', { count: years }) : t('keeping.notSet')}</span>
      )}
    </label>
  )
}

/**
 * Setting a keeping time: also for the documents already there? Says how many there are (only the ones the person may
 * see), how many were set by hand (they stay) and how many may go at once. None there: set without asking.
 */
function KeepDialog({ entry, years, onClose, onDone }: { entry: OrderEntry; years: number; onClose: () => void; onDone: (notice: string) => void }) {
  const { t, i18n } = useTranslation()
  const [found, setFound] = useState<KeepPreview | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const today = dayInDays(0)
  const yearsText = t('keeping.years', { count: years })
  const name = iso(entry.name)
  const set = async (existing: boolean) => {
    if (busy) return
    setBusy(true)
    setProblem(null)
    try {
      const done = await keepingApi.set(entry.id, years, existing)
      onDone(done.queued ? t('keeping.setQueued', { name, years: yearsText }) : t(existing ? 'keeping.setAll' : 'keeping.setNew', { name, years: yearsText }))
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
      setBusy(false)
    }
  }
  const setRef = useRef(set)
  setRef.current = set
  useEffect(() => {
    let alive = true
    keepingApi.preview(entry.id, years).then(
      (answer) => {
        if (!alive) return
        // Nothing there to ask about: it holds for what is filed from now on.
        if (answer.documents === 0) void setRef.current(true)
        else setFound(answer)
      },
      (error: unknown) => alive && setProblem(error instanceof ApiError ? error.code : 'internal_error'),
    )
    return () => {
      alive = false
    }
  }, [entry.id, years])
  if (!found && !problem) return null
  const count = (n: number) => n.toLocaleString(i18n.language)
  return (
    <Dialog title={t('keeping.dialogTitle', { name: entry.name, years: yearsText })} onClose={onClose}>
      <div className="space-y-3 text-sm">
        <p className="text-ink-2">{t('keeping.dialogText', { years: yearsText, today: shortDate(today, i18n.language), year: Number(today.slice(0, 4)) + years })}</p>
        {found && (
          <div className="rounded-xl border border-line bg-sheet-2/50 p-4">
            <p className="font-semibold">{t('keeping.existing', { count: found.documents, n: count(found.documents) })}</p>
            <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-ink-2">
              {found.by_hand > 0 && <li>{t('keeping.byHand', { count: found.by_hand, n: count(found.by_hand) })}</li>}
              {found.expired > 0 ? <li>{t('keeping.expired', { count: found.expired, n: count(found.expired) })}</li> : <li>{t('keeping.noneExpired')}</li>}
            </ul>
          </div>
        )}
        {problem && <Feedback problem={problem} />}
        <div className="flex flex-wrap justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="line" disabled={!found || busy} onClick={() => void set(false)}>
            {t('keeping.onlyNew')}
          </Button>
          <Button variant="primary" disabled={!found || busy} onClick={() => void set(true)}>
            {t('keeping.forAll', { n: count(found?.documents ?? 0) })}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}

function IconButton({ icon: Icon, text, name, onClick }: { icon: typeof Pencil; text: string; name: string; onClick: () => void }) {
  const { t } = useTranslation()
  return (
    <button type="button" onClick={onClick} title={text} aria-label={t('order.action', { action: text, name })} className="inline-flex h-9 w-9 items-center justify-center rounded-full text-muted transition hover:bg-sheet-2 hover:text-ink">
      <Icon size={17} aria-hidden />
    </button>
  )
}

/** A name for an entry: typed, checked against the ones there (the same name is a merge, which has its own question). */
function RenameDialog({ what, entry, onClose, onDone }: { what: OrderWhat; entry: OrderEntry; onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation()
  const [name, setName] = useState(entry.name)
  const [exists, setExists] = useState(false)
  const [problem, setProblem] = useState<{ code: string; values?: Record<string, unknown> } | null>(null)
  const [busy, setBusy] = useState(false)
  const clean = name.trim()
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!clean || busy) return
    setBusy(true)
    setProblem(null)
    try {
      const same = await orderApi.list(what, { vault_id: entry.vault_id ?? undefined, q: clean, limit: 50 })
      if (same.items.some((other) => other.id !== entry.id && other.vault_id === entry.vault_id && foldName(other.name) === foldName(clean))) {
        setExists(true)
        setBusy(false)
        return
      }
      if (what === 'senders') await catalogApi.renameSender(entry.id, clean)
      else if (what === 'tags') await catalogApi.renameTag(entry.id, clean)
      else await catalogApi.renameKind(entry.id, clean)
      onDone()
    } catch (error) {
      setProblem(error instanceof ApiError ? { code: error.code, values: error.values } : { code: 'internal_error' })
      setBusy(false)
    }
  }
  return (
    <Dialog title={t(`order.renameTitle.${what}`)} onClose={onClose}>
      <form onSubmit={(event) => void submit(event)}>
        <label className="text-sm font-semibold" htmlFor="order-new-name">
          {t('order.newName')}
        </label>
        <input
          id="order-new-name"
          data-autofocus
          value={name}
          onChange={(event) => {
            setName(event.target.value)
            setExists(false)
          }}
          maxLength={what === 'senders' ? 160 : what === 'kinds' ? 60 : 40}
          className="input mt-1"
        />
        {exists && (
          <p role="alert" className="mt-2 text-sm text-bad">
            {t('order.exists')}
          </p>
        )}
        {problem && <p role="alert" className="mt-2 text-sm text-bad">{errorText(problem.code, problem.values)}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" type="submit" disabled={!clean || clean === entry.name || busy}>
            {t('common.save')}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

/** Where an entry goes: the other entries of the same vault (for a kind also the ones for all vaults), found by typing. */
function MergeDialog({ what, entry, vaultName, onClose, onPick }: { what: OrderWhat; entry: OrderEntry; vaultName: (id: number | null) => string; onClose: () => void; onPick: (into: OrderEntry) => void }) {
  const { t } = useTranslation()
  const [typed, setTyped] = useState('')
  const [found, setFound] = useState<OrderEntry[] | null>(null)
  const serial = useRef(0)
  useEffect(() => {
    const mine = (serial.current += 1)
    const timer = window.setTimeout(() => {
      void orderApi
        .list(what, { vault_id: what === 'kinds' ? undefined : (entry.vault_id ?? undefined), q: typed.trim() || undefined, limit: what === 'kinds' ? 500 : 50 })
        .then((answer) => {
          if (mine !== serial.current) return
          setFound(
            answer.items.filter((other) => {
              if (other.id === entry.id) return false
              if (what !== 'kinds') return true
              return entry.vault_id === null ? other.vault_id === null : other.vault_id === null || other.vault_id === entry.vault_id
            }),
          )
        }, () => mine === serial.current && setFound([]))
    }, typed ? PAUSE_MS : 0)
    return () => window.clearTimeout(timer)
  }, [what, entry, typed])
  return (
    <Dialog title={t('order.mergeTitle', { name: iso(entry.name) })} onClose={onClose}>
      <p className="text-sm text-ink-2">{t(`order.mergeText.${what}`, { name: iso(entry.name) })}</p>
      <input data-autofocus value={typed} onChange={(event) => setTyped(event.target.value)} placeholder={t('order.mergeSearch')} aria-label={t('order.mergeSearch')} maxLength={100} className="input mt-3" />
      {found !== null && found.length === 0 ? (
        <p className="mt-4 text-sm text-muted">{t('order.mergeNone')}</p>
      ) : (
        <ul className="soft-scroll mt-3 max-h-[45dvh] overflow-auto rounded-xl border border-line" aria-label={t('order.mergeSearch')}>
          {(found ?? []).map((other) => (
            <li key={other.id} className="border-b border-line last:border-b-0">
              <button type="button" onClick={() => onPick(other)} className="flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm hover:bg-sheet-2">
                <span className="min-w-0 flex-1 font-semibold break-words">{what === 'kinds' ? <KindPill kind={{ name: other.name, hue: other.hue ?? 30 }} /> : <bdi>{other.name}</bdi>}</span>
                <span className="shrink-0 text-xs text-muted">
                  {what === 'kinds' && entry.vault_id !== null ? `${vaultName(other.vault_id)} · ` : ''}
                  {t('order.documents', { count: other.documents })}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  )
}

/** A kind of one's own: for a vault the person may change, or (the operator) for all vaults. */
function NewKind({ vaults, operator, count, onAdded }: { vaults: Vault[]; operator: boolean; count: number; onAdded: () => void }) {
  const { t } = useTranslation()
  const choices = useMemo(
    () => [...(operator ? [{ value: 'all', label: t('order.everywhere') }] : []), ...vaults.filter((v) => v.my_right !== 'read').map((v) => ({ value: String(v.id), label: v.personal_of !== null ? t('docs.inbox.personalVault', { name: v.name }) : v.name }))],
    [vaults, operator, t],
  )
  const [name, setName] = useState('')
  const [where, setWhere] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  if (choices.length === 0) return null
  const target = where && choices.some((c) => c.value === where) ? where : choices[0].value
  const add = async (event: FormEvent) => {
    event.preventDefault()
    const typed = name.trim()
    if (!typed || busy) return
    setBusy(true)
    setProblem(null)
    try {
      const hue = (count * 47) % 360
      if (target === 'all') await kindsApi.create(typed, hue)
      else await catalogApi.createKind(typed, Number(target), hue)
      setName('')
      onAdded()
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
    } finally {
      setBusy(false)
    }
  }
  return (
    <form className="card flex flex-wrap items-end gap-3 p-4" onSubmit={(event) => void add(event)} aria-label={t('order.newKind')}>
      <label className="min-w-48 flex-1 text-sm">
        <span className="font-semibold">{t('order.newKind')}</span>
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder={t('order.newKindPlaceholder')} maxLength={60} className="input mt-1" />
      </label>
      {choices.length > 1 && (
        <label className="text-sm">
          <span className="font-semibold">{t('order.newKindWhere')}</span>
          <select value={target} onChange={(event) => setWhere(event.target.value)} className="input mt-1 w-auto">
            {choices.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <Button variant="soft" type="submit" disabled={!name.trim() || busy}>
        <Plus size={15} aria-hidden /> {t('order.add')}
      </Button>
      {problem && <Feedback problem={problem} />}
    </form>
  )
}
