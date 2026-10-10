/**
 * The archive (`/`), as the mock draws it: one search over every vault the person may see, filters as chips, a list or
 * tiles grouped by month, more of it loaded while scrolling. Everything comes from `GET /api/v1/search` (the language
 * of the search field, the filters as parameters, the rights in the server's query) and stands in the address, so a
 * search can be bookmarked and the back button works. The search is braked by the server (120 a minute) and every
 * answer takes 25 to 50 ms on purpose: the field waits until the typing pauses, a request that is no longer wanted is
 * stopped, and a brake is waited out.
 */
import { Download, FileCode2, LayoutGrid, Link2, List, MessageSquare, ListTree, Search, SlidersHorizontal, Users, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'

import {
  ApiError,
  authApi,
  catalogApi,
  documentsApi,
  searchApi,
  vaultsApi,
  type DocumentKind,
  type NameGroup,
  type Person,
  type SearchHit,
  type Vault,
} from '../api/client'
import { Avatar } from '../components/Avatar'
import { SenderPicker } from '../components/SenderPicker'
import { Button } from '../components/Button'
import { Chip, DocThumb, FileSign, KindPill, Marked } from '../components/docs'
import { VaultIcon } from '../components/VaultIcon'
import { shortDate } from '../lib/dates'
import { filtersOf, KEYS, SPANS, type Chosen, type Span } from '../lib/archive'
import { errorText } from '../lib/errors'
import { oneOfEachName, representative } from '../lib/kinds'
import { iso, listOf } from '../lib/say'
import { money } from '../lib/money'
import { asAvatarPerson, personName } from '../lib/people'
import { useAuth } from '../state/auth'
import { slots as appSlots, type Slots } from '../slots'

/** How long the field waits after the last key before it searches. */
export const TYPING_PAUSE_MS = 300
const PAGE = 50
/** How many examples the help under the field shows (their words come in the language of the page). */
const HELP = 6

/** The filters of the whole archive: filed, nothing else. */
const WHOLE = JSON.stringify(filtersOf({ vault: '', kind: '', sender: '', tag: '', owner: '', span: '' }))

/** The month a document belongs to in the list: its date, else the day it came in. */
function monthKey(hit: SearchHit): string {
  return (hit.document.date ?? hit.document.added_at).slice(0, 7)
}

export function ArchivePage({ slots = appSlots }: { slots?: Slots }) {
  const { t, i18n } = useTranslation()
  const { me, setMe } = useAuth()
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const chosen = useMemo(() => Object.fromEntries(KEYS.map((key) => [key, params.get(key) ?? ''])) as Chosen, [params])
  const [typed, setTyped] = useState(q)
  const [help, setHelp] = useState(false)
  const [more, setMore] = useState(false)
  const [exporting, setExporting] = useState(false)
  /** A sentence after the export was asked for (the ZIP is packed, the link was copied). */
  const [said, setSaid] = useState<string | null>(null)

  const [vaults, setVaults] = useState<Vault[]>([])
  const [kinds, setKinds] = useState<DocumentKind[]>([])
  const [senders, setSenders] = useState<NameGroup[]>([])
  const [tags, setTags] = useState<NameGroup[]>([])
  const [people, setPeople] = useState<Person[]>([])
  const [sharedToMe, setSharedToMe] = useState(false)
  const [filed, setFiled] = useState<number | null>(null)

  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const [total, setTotal] = useState(0)
  const [next, setNext] = useState<string | null>(null)
  const [took, setTook] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [problem, setProblem] = useState<{ code: string; values: Record<string, unknown> } | null>(null)
  const [again, setAgain] = useState(0)
  const running = useRef<AbortController | null>(null)
  const searchBox = useRef<HTMLDivElement>(null)
  const field = useRef<HTMLInputElement>(null)
  const examples = Array.from({ length: HELP }, (_, index) => t(`docs.archive.example.${index}`))
  const sentinel = useRef<HTMLDivElement>(null)

  // What the chips and the filters offer.
  const loadCatalog = useCallback(() => {
    void catalogApi.senders().then((list) => setSenders(listOf(list)), () => undefined)
    void catalogApi.tags().then((list) => setTags(listOf(list)), () => undefined)
  }, [])
  useEffect(() => {
    void vaultsApi.list().then((list) => setVaults(listOf(list)), () => undefined)
    void catalogApi.kinds().then((list) => setKinds(listOf(list)), () => undefined)
    void vaultsApi.people().then((list) => setPeople(listOf(list)), () => undefined)
    loadCatalog()
    // Whether anything was shared one by one: the list of documents answers that without using up a search.
    void documentsApi.list({ status: 'filed', via_share: true, limit: 1 }).then((found) => setSharedToMe(listOf(found.items).length > 0), () => undefined)
  }, [loadCatalog])

  // The field follows the address (back, a click on a tag, the help), and the address follows the field after a pause.
  const sent = useRef(q)
  useEffect(() => {
    // Only a change from elsewhere: what the field sent itself may already be behind what is typed now.
    if (q !== sent.current) setTyped(q)
    sent.current = q
  }, [q])
  useEffect(() => {
    if (typed === q) return
    const timer = window.setTimeout(() => {
      sent.current = typed
      setParams((current) => {
        const out = new URLSearchParams(current)
        if (typed) out.set('q', typed)
        else out.delete('q')
        return out
      }, { replace: true })
    }, TYPING_PAUSE_MS)
    return () => window.clearTimeout(timer)
  }, [typed, q, setParams])

  const filters = useMemo(() => filtersOf(chosen), [chosen])

  // The notice "export ready" leads to `/?export=1`: the dialog opens with the person's exports, and the address
  // forgets it again (a reload does not open it once more).
  const askedExport = params.get('export') === '1'
  useEffect(() => {
    if (!askedExport) return
    if (slots.ExportDialog) setExporting(true)
    setParams((current) => {
      const out = new URLSearchParams(current)
      out.delete('export')
      return out
    }, { replace: true })
  }, [askedExport, slots.ExportDialog, setParams])

  // The sentence after an export goes after a while.
  useEffect(() => {
    if (!said) return
    const timer = window.setTimeout(() => setSaid(null), 6000)
    return () => window.clearTimeout(timer)
  }, [said])
  const filterKey = JSON.stringify(filters)

  // The first page of every new search; the request before it is stopped.
  useEffect(() => {
    running.current?.abort()
    const stop = new AbortController()
    running.current = stop
    setLoading(true)
    const began = performance.now()
    searchApi.find(q, { ...filters, limit: PAGE }, stop.signal).then(
      (found) => {
        if (stop.signal.aborted) return
        setHits(listOf(found.items))
        setTotal(found.total ?? 0)
        // The archive as a whole (no words, no filter): the number of the heading.
        if (!q && filterKey === WHOLE) setFiled(found.total ?? 0)
        setNext(found.next ?? null)
        setTook((performance.now() - began) / 1000)
        setProblem(null)
        setLoading(false)
      },
      (error: unknown) => {
        if (stop.signal.aborted || (error instanceof ApiError && error.code === 'cancelled')) return
        setLoading(false)
        setProblem(error instanceof ApiError ? { code: error.code, values: error.values } : { code: 'internal_error', values: {} })
      },
    )
    return () => stop.abort()
    // `filters` is the same as `filterKey`; the key keeps an equal object from searching again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, filterKey, again])

  // A brake: tried again by itself once the server's minute allows it.
  useEffect(() => {
    if (problem?.code !== 'search_too_often') return
    const seconds = Number(problem.values.retry_after ?? 10)
    const timer = window.setTimeout(() => setAgain((n) => n + 1), Math.min(60, Math.max(1, seconds)) * 1000)
    return () => window.clearTimeout(timer)
  }, [problem])

  const loadMore = useCallback(() => {
    if (!next || loading) return
    const stop = new AbortController()
    running.current = stop
    setLoading(true)
    searchApi.find(q, { ...filters, limit: PAGE, cursor: next }, stop.signal).then(
      (found) => {
        if (stop.signal.aborted) return
        setHits((current) => [...(current ?? []), ...listOf<SearchHit>(found.items).filter((hit) => !(current ?? []).some((had) => had.document.id === hit.document.id))])
        setNext(found.next ?? null)
        setLoading(false)
      },
      (error: unknown) => {
        if (stop.signal.aborted || (error instanceof ApiError && error.code === 'cancelled')) return
        setLoading(false)
        setProblem(error instanceof ApiError ? { code: error.code, values: error.values } : { code: 'internal_error', values: {} })
      },
    )
  }, [next, loading, q, filters])

  // More while scrolling: when the end of the list comes near, the next page is fetched.
  useEffect(() => {
    const element = sentinel.current
    if (!element || !next || typeof IntersectionObserver === 'undefined') return
    const watcher = new IntersectionObserver((entries) => entries.some((entry) => entry.isIntersecting) && loadMore(), { rootMargin: '800px' })
    watcher.observe(element)
    return () => watcher.disconnect()
  }, [next, loadMore])

  if (!me) return null
  const view = me.profile.view === 'grid' ? 'grid' : 'list'
  const setView = (value: 'list' | 'grid') => {
    if (value === view) return
    setMe({ ...me, profile: { ...me.profile, view: value } })
    void authApi.preferences({ view: value }).then((profile) => setMe({ ...me, profile }), () => undefined)
  }
  const choose = (change: Partial<Chosen>) =>
    setParams((current) => {
      const out = new URLSearchParams(current)
      for (const [key, value] of Object.entries(change)) {
        if (value) out.set(key, value)
        else out.delete(key)
      }
      return out
    }, { replace: true })
  const active = (['kind', 'sender', 'tag', 'owner', 'span'] as const).filter((key) => chosen[key]).length
  const vaultById = new Map(vaults.map((v) => [v.id, v]))
  const vaultName = (v: Vault) => (v.personal_of === me.id ? t('vaults.mine') : v.name)

  const groups: [string, SearchHit[]][] = []
  for (const hit of hits ?? []) {
    const key = monthKey(hit)
    const group = groups.find((g) => g[0] === key)
    if (group) group[1].push(hit)
    else groups.push([key, [hit]])
  }
  const monthName = (key: string) => {
    const [year, month] = key.split('-').map(Number)
    return new Intl.DateTimeFormat(i18n.language, { month: 'long', year: 'numeric' }).format(new Date(year, month - 1, 15))
  }
  const nothingAtAll = hits !== null && hits.length === 0 && !q && !active && !chosen.vault

  return (
    <div className="page space-y-5 pt-6 pb-28 lg:pt-8 lg:pb-12">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight">{t('docs.archive.title')}</h1>
          <p className="text-sm text-muted" data-testid="archive-count">
            {filed !== null &&
              t('docs.archive.sub', {
                documents: t('docs.archive.documents', { count: filed, n: filed.toLocaleString(i18n.language) }),
                vaults: t('docs.archive.vaults', { count: vaults.length }),
              })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div role="radiogroup" aria-label={t('docs.archive.view')} className="inline-flex rounded-full border border-line bg-sheet p-0.5">
            {([['list', List, t('docs.archive.list')], ['grid', LayoutGrid, t('docs.archive.tiles')]] as const).map(([value, Icon, label]) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={view === value}
                aria-label={label}
                title={label}
                onClick={() => setView(value)}
                className={`rounded-full p-2 ${view === value ? 'bg-accent-soft text-accent' : 'text-muted hover:text-ink'}`}
              >
                <Icon size={16} aria-hidden />
              </button>
            ))}
          </div>
          {slots.ExportDialog && (
            <Button variant="line" size="sm" onClick={() => setExporting(true)}>
              <Download size={15} aria-hidden /> {t('docs.archive.export')}
            </Button>
          )}
        </div>
      </div>

      <div
        className="relative"
        ref={searchBox}
        onBlur={(event) => {
          // Only when the focus leaves the field and its help together (Tab from the field reaches the examples).
          if (!searchBox.current?.contains(event.relatedTarget as Node | null)) setHelp(false)
        }}
      >
        <Search size={19} className="absolute top-1/2 left-4 -translate-y-1/2 text-muted" aria-hidden />
        <input
          type="search"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          ref={field}
          onFocus={() => setHelp(true)}
          placeholder={t('docs.archive.placeholder')}
          aria-label={t('docs.archive.searchLabel')}
          maxLength={500}
          className="h-13 w-full rounded-2xl border border-line bg-sheet pr-12 pl-12 text-[1.02rem] shadow-soft outline-none placeholder:text-muted focus:border-accent [&::-webkit-search-cancel-button]:hidden"
        />
        {typed && (
          <button type="button" onClick={() => setTyped('')} className="absolute top-1/2 right-3 -translate-y-1/2 rounded-full p-1.5 text-muted hover:bg-sheet-2" aria-label={t('docs.archive.clear')}>
            <X size={17} aria-hidden />
          </button>
        )}
        {help && !typed && (
          <div className="card rise absolute inset-x-0 top-full z-20 mt-2 p-4 text-sm" data-testid="search-help">
            <p className="mb-2 text-xs font-bold tracking-wide text-muted uppercase">{t('docs.archive.helpTitle')}</p>
            <div className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
              {examples.map((example, index) => (
                <button
                  key={example}
                  type="button"
                  // The pointer does not take the focus away from the field; a click, Enter or the space bar chooses.
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => {
                    setTyped(example)
                    sent.current = example
                    setParams((current) => {
                      const out = new URLSearchParams(current)
                      out.set('q', example)
                      return out
                    }, { replace: true })
                    field.current?.focus()
                  }}
                  className="flex items-baseline gap-3 rounded-lg px-2 py-1 text-left hover:bg-sheet-2"
                >
                  <code className="shrink-0 rounded bg-sheet-2 px-1.5 py-0.5 text-xs text-accent">{example}</code>
                  <span className="text-ink-2">{t(`docs.archive.help.${index}`)}</span>
                </button>
              ))}
            </div>
            <p className="mt-3 text-xs text-muted">{t('docs.archive.helpParts')}</p>
          </div>
        )}
      </div>

      <div className="scroll-x -mx-1 flex items-center gap-2 overflow-x-auto px-1 pb-1">
        <Chip active={!chosen.vault} onClick={() => choose({ vault: '' })}>
          {t('docs.archive.allVaults')}
        </Chip>
        {vaults.map((v) => (
          <Chip key={v.id} active={chosen.vault === String(v.id)} onClick={() => choose({ vault: String(v.id) })}>
            <VaultIcon icon={v.icon} size={14} /> {vaultName(v)}
          </Chip>
        ))}
        {sharedToMe && (
          <Chip active={chosen.vault === 'shared'} onClick={() => choose({ vault: 'shared' })}>
            <Users size={14} aria-hidden /> {t('docs.archive.sharedToMe')}
          </Chip>
        )}
        <span className="mx-1 h-5 w-px shrink-0 bg-line" />
        <Chip active={more || active > 0} onClick={() => setMore(!more)}>
          <SlidersHorizontal size={14} aria-hidden /> {active > 0 ? t('docs.archive.filterCount', { count: active }) : t('docs.archive.filter')}
        </Chip>
      </div>

      {more && (
        <Filters
          chosen={chosen}
          choose={choose}
          kinds={kinds}
          senders={senders}
          tags={tags}
          people={people}
          active={active}
        />
      )}

      {problem && (
        <p role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
          {errorText(problem.code, problem.values)}
        </p>
      )}

      {q && hits && !problem && (
        <p className="text-sm text-ink-2" data-testid="hit-count">
          {total === 0 ? t('docs.archive.noHits') : t('docs.archive.hits', { count: total, n: total.toLocaleString(i18n.language) })} {t('docs.archive.for', { q: iso(q) })}
          {total > 0 && took !== null && <span className="text-muted"> · {t('docs.archive.took', { seconds: took.toLocaleString(i18n.language, { maximumFractionDigits: 2, minimumFractionDigits: 2 }) })}</span>}
        </p>
      )}

      {hits && hits.length === 0 && !problem && (
        <div className="card p-10 text-center">
          <Search size={28} className="mx-auto text-muted" aria-hidden />
          <p className="mt-3 font-semibold">{nothingAtAll ? t('docs.archive.emptyTitle') : t('docs.archive.nothingTitle')}</p>
          <p className="mt-1 text-sm text-ink-2">{nothingAtAll ? t('docs.archive.emptyText') : t('docs.archive.nothingText')}</p>
        </div>
      )}
      {!hits && !problem && <p className="text-sm text-muted">{t('docs.loading')}</p>}

      {groups.map(([month, list]) => (
        <section key={month} aria-label={monthName(month)}>
          <h2 className="mb-2 px-1 text-xs font-bold tracking-wide text-muted uppercase">{monthName(month)}</h2>
          {view === 'list' ? (
            <ul className="card divide-y divide-line overflow-hidden p-0">
              {list.map((hit) => (
                <Row key={hit.document.id} hit={hit} vault={vaultById.get(hit.document.vault_id)} vaultName={vaultName} searching={!!q} />
              ))}
            </ul>
          ) : (
            <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              {list.map((hit) => (
                <Tile key={hit.document.id} hit={hit} />
              ))}
            </ul>
          )}
        </section>
      ))}
      <div ref={sentinel} />
      {next && (
        <div className="flex flex-col items-center gap-2 pt-2">
          <p className="text-center text-xs text-muted">{t('docs.archive.scrollMore')}</p>
          <Button variant="ghost" size="sm" onClick={loadMore} disabled={loading}>
            {t('docs.archive.loadMore')}
          </Button>
        </div>
      )}

      {said && (
        <div role="status" className="rise fixed inset-x-0 bottom-24 z-50 flex justify-center px-4 lg:bottom-8">
          <p className="rounded-full bg-ink px-5 py-2.5 text-center text-sm font-semibold text-paper shadow-soft">{said}</p>
        </div>
      )}
      {exporting && slots.ExportDialog && (
        <slots.ExportDialog
          q={q}
          filters={filters}
          count={total}
          sum={(hits ?? []).reduce((all, hit) => all + (hit.document.amount ?? 0), 0)}
          say={setSaid}
          onClose={() => setExporting(false)}
        />
      )}
    </div>
  )
}

function Select({ label, value, onChange, options, empty }: { label: string; value: string; onChange: (value: string) => void; options: [string, string][]; empty: string }) {
  return (
    <label className="text-sm">
      <span className="text-xs font-semibold text-muted">{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} aria-label={label} className="mt-1 block h-10 w-full rounded-xl border border-line bg-sheet px-3 text-ink outline-none focus:border-accent">
        <option value="">{empty}</option>
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </label>
  )
}

type FiltersProps = {
  chosen: Chosen
  choose: (change: Partial<Chosen>) => void
  kinds: DocumentKind[]
  senders: NameGroup[]
  tags: NameGroup[]
  people: Person[]
  active: number
}

function Filters({ chosen, choose, kinds, senders, tags, people, active }: FiltersProps) {
  const { t } = useTranslation()
  const year = new Date().getFullYear()
  const spanName: Record<Span, string> = { year: String(year), lastyear: String(year - 1), '12m': t('docs.archive.last12') }
  return (
    <div className="card rise grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-6">
      <Select label={t('docs.archive.kind')} value={representative(kinds, chosen.kind)} onChange={(kind) => choose({ kind })} options={oneOfEachName(kinds).map((k) => [String(k.id), k.name])} empty={t('docs.archive.all')} />
      <div className="text-sm sm:col-span-2">
        <span className="text-xs font-semibold text-muted">{t('docs.archive.sender')}</span>
        <div className="mt-1">
          <SenderPicker known value={chosen.sender} onChange={(value) => choose({ sender: value })} names={senders.map((g) => g.name)} label={t('docs.archive.sender')} placeholder={t('docs.archive.all')} className="input h-10" />
        </div>
      </div>
      <Select label={t('docs.archive.tag')} value={chosen.tag} onChange={(tag) => choose({ tag })} options={tags.map((g) => [g.name, g.name])} empty={t('docs.archive.all')} />
      <Select label={t('docs.archive.owner')} value={chosen.owner} onChange={(owner) => choose({ owner })} options={people.map((p) => [String(p.id), personName(p)])} empty={t('docs.archive.all')} />
      <Select label={t('docs.archive.span')} value={chosen.span} onChange={(span) => choose({ span })} options={SPANS.map((s) => [s, spanName[s]])} empty={t('docs.archive.anytime')} />
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm font-semibold text-accent sm:col-span-2 lg:col-span-6">
        {active > 0 && (
          <button type="button" onClick={() => choose({ kind: '', sender: '', tag: '', owner: '', span: '' })} className="text-left">
            {t('docs.archive.reset')}
          </button>
        )}
        <Link to="/ordnung" className="inline-flex items-center gap-1.5">
          <ListTree size={14} aria-hidden /> {t('order.link')}
        </Link>
      </div>
    </div>
  )
}

function Row({ hit, vault, vaultName, searching }: { hit: SearchHit; vault: Vault | undefined; vaultName: (v: Vault) => string; searching: boolean }) {
  const { t, i18n } = useTranslation()
  const d = hit.document
  const when = d.date ?? d.added_at
  return (
    <li>
      <Link to={`/dokument/${d.id}`} className="flex items-center gap-4 px-4 py-3 hover:bg-sheet-2/60">
        <DocThumb document={d} className="w-10 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate font-semibold">
              <Marked text={d.title} marks={hit.title_marks} />
            </span>
            <span className="flex items-center gap-1.5 text-muted">
              <FileSign state={d.files_state} />
              {d.einvoice && <FileCode2 size={14} aria-label={t('sorting.einvoice.icon')} />}
              {d.notes > 0 && <MessageSquare size={14} aria-label={t('docs.archive.withNote')} />}
              {(d.share_count ?? 0) > 0 && <Users size={14} aria-label={t('docs.archive.sharedOut')} />}
              {(d.link_count ?? 0) > 0 && <Link2 size={14} aria-label={t('docs.archive.linkOut')} />}
            </span>
          </div>
          <div className="truncate text-sm text-ink-2">
            {d.sender && (
              <>
                <Marked text={d.sender.name} marks={hit.sender_marks} /> ·{' '}
              </>
            )}
            {shortDate(when, i18n.language)}
          </div>
          {searching && hit.excerpt && (
            <p className="mt-1 line-clamp-2 text-sm text-muted" data-testid="excerpt">
              {hit.excerpt.source === 'notes' && <MessageSquare size={12} className="mr-1 inline" aria-label={t('docs.archive.inNote')} />}
              <Marked text={hit.excerpt.text} marks={hit.excerpt.marks} />
            </p>
          )}
        </div>
        <div className="hidden w-28 md:block">
          <KindPill kind={d.kind} />
        </div>
        <div className="hidden w-36 items-center gap-1.5 text-sm text-ink-2 lg:flex">
          {vault && !d.via_share ? <VaultIcon icon={vault.icon} size={14} /> : <Users size={14} aria-hidden />}
          <span className="truncate">{vault && !d.via_share ? vaultName(vault) : t('docs.archive.sharedLower')}</span>
        </div>
        {d.owner && <Avatar person={asAvatarPerson(d.owner)} size={26} />}
        <span className="w-24 text-right text-sm font-semibold tabular-nums">{money(d.amount, i18n.language, d.currency)}</span>
      </Link>
    </li>
  )
}

function Tile({ hit }: { hit: SearchHit }) {
  const { i18n } = useTranslation()
  const d = hit.document
  return (
    <li>
      <Link to={`/dokument/${d.id}`} className="card block overflow-hidden p-0 transition hover:-translate-y-0.5">
        <div className="relative bg-sheet-2 px-6 pt-5">
          <DocThumb document={d} className="w-full [&_img]:rounded-b-none" />
          {d.files_state && <FileSign state={d.files_state} size={18} className="absolute top-2 left-2 rounded-full bg-sheet p-0.5" />}
          {d.owner && (
            <span className="absolute top-2 right-2">
              <Avatar person={asAvatarPerson(d.owner)} size={24} />
            </span>
          )}
        </div>
        <div className="space-y-1 p-3">
          <p className="truncate text-sm font-semibold">
            <bdi>{d.title}</bdi>
          </p>
          <p className="truncate text-xs text-muted">
            {d.sender ? <><bdi>{d.sender.name}</bdi> · </> : ''}
            {shortDate(d.date ?? d.added_at, i18n.language)}
          </p>
          <div className="flex items-center justify-between gap-2 pt-1">
            <KindPill kind={d.kind} small />
            <span className="text-xs font-semibold tabular-nums">{money(d.amount, i18n.language, d.currency)}</span>
          </div>
        </div>
      </Link>
    </li>
  )
}
