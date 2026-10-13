/**
 * The archive (`/`), as the mock draws it. Without a search or a filter it is an overview: the newest documents and
 * how the archive spreads over senders, kinds, years and tags (`GET /api/v1/search/overview`), each a way into the
 * table. A search, a filter or "show all" opens the table: numbered pages, sortable by its columns (`GET
 * /api/v1/search` with `page` and `sort`), so thousands of documents never become one endless list. Everything stands in
 * the address, so a search or a page can be bookmarked and the back button returns to the overview. The search is
 * braked by the server (120 a minute) and every answer takes 25 to 50 ms on purpose: the field waits until the typing
 * pauses, a request that is no longer wanted is stopped, and a brake is waited out.
 */
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Download, FileCode2, LayoutGrid, Link2, List, ListTree, MessageSquare, Search, SlidersHorizontal, Users, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
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
  type NameCount,
  type NameGroup,
  type Person,
  type SearchHit,
  type SearchOrder,
  type SearchOverview,
  type Vault,
} from '../api/client'
import { Button } from '../components/Button'
import { Dialog } from '../components/Dialog'
import { SenderPicker } from '../components/SenderPicker'
import { Chip, DocThumb, FileSign, KindPill, Marked } from '../components/docs'
import { Avatar } from '../components/Avatar'
import { VaultIcon } from '../components/VaultIcon'
import { DEFAULT_SIZE, filtersOf, KEYS, NARROWING, nextOrder, orderOf, pageList, pageOf, SIZES, sizeOf, type Chosen } from '../lib/archive'
import { shortDate } from '../lib/dates'
import { errorText } from '../lib/errors'
import { oneOfEachName, representative } from '../lib/kinds'
import { money } from '../lib/money'
import { asAvatarPerson, personName } from '../lib/people'
import { iso, listOf } from '../lib/say'
import { useAuth } from '../state/auth'
import { slots as appSlots, type Slots } from '../slots'

/** How long the field waits after the last key before it searches. */
export const TYPING_PAUSE_MS = 300
/** How many of the newest documents the overview shows. */
export const NEWEST = 6
/** How many senders the overview's card shows before "all". */
const TOP_SENDERS = 7
/** How many tags the overview shows. */
const TOP_TAGS = 12
/** How many examples the help under the field shows (their words come in the language of the page). */
const HELP = 6

type Problem = { code: string; values: Record<string, unknown> }
const problemOf = (error: unknown): Problem => (error instanceof ApiError ? { code: error.code, values: error.values } : { code: 'internal_error', values: {} })
const stopped = (error: unknown, signal: AbortSignal) => signal.aborted || (error instanceof ApiError && error.code === 'cancelled')

/** An overview as the page can draw it, whatever the answer left out. */
function overviewOf(found: Partial<SearchOverview> | null | undefined): SearchOverview {
  return {
    total: typeof found?.total === 'number' ? found.total : 0,
    senders: listOf(found?.senders),
    kinds: listOf(found?.kinds),
    years: listOf(found?.years),
    tags: listOf(found?.tags),
  }
}

/** The month a document belongs to in the table: its date, else the day it came in. */
function monthKey(hit: SearchHit): string {
  return (hit.document.date ?? hit.document.added_at).slice(0, 7)
}

export function ArchivePage({ slots = appSlots }: { slots?: Slots }) {
  const { t, i18n } = useTranslation()
  const { me, setMe } = useAuth()
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const chosen = useMemo(() => Object.fromEntries(KEYS.map((key) => [key, params.get(key) ?? ''])) as Chosen, [params])
  const showAll = params.get('all') === '1'
  const order = orderOf(params.get('sort'))
  const size = sizeOf(params.get('n'))
  const page = pageOf(params.get('page'))
  const listing = Boolean(q || showAll || NARROWING.some((key) => chosen[key]))

  const [typed, setTyped] = useState(q)
  const [help, setHelp] = useState(false)
  const [more, setMore] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [allSenders, setAllSenders] = useState(false)
  /** A sentence after the export was asked for (the ZIP is packed, the link was copied). */
  const [said, setSaid] = useState<string | null>(null)

  const [vaults, setVaults] = useState<Vault[]>([])
  const [kinds, setKinds] = useState<DocumentKind[]>([])
  const [senders, setSenders] = useState<NameGroup[]>([])
  const [tags, setTags] = useState<NameGroup[]>([])
  const [people, setPeople] = useState<Person[]>([])
  const [sharedToMe, setSharedToMe] = useState(false)

  /** The whole archive (for the heading), and the one of the chosen vault (for the overview). */
  const [whole, setWhole] = useState<SearchOverview | null>(null)
  const [ofVault, setOfVault] = useState<SearchOverview | null>(null)
  const [newest, setNewest] = useState<SearchHit[] | null>(null)

  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const [total, setTotal] = useState(0)
  const [took, setTook] = useState<number | null>(null)
  const [problem, setProblem] = useState<Problem | null>(null)
  const [again, setAgain] = useState(0)
  const searchBox = useRef<HTMLDivElement>(null)
  const field = useRef<HTMLInputElement>(null)
  const top = useRef<HTMLDivElement>(null)
  const examples = Array.from({ length: HELP }, (_, index) => t(`docs.archive.example.${index}`))

  // What the filters offer.
  useEffect(() => {
    void vaultsApi.list().then((list) => setVaults(listOf(list)), () => undefined)
    void catalogApi.kinds().then((list) => setKinds(listOf(list)), () => undefined)
    void vaultsApi.people().then((list) => setPeople(listOf(list)), () => undefined)
    void catalogApi.senders().then((list) => setSenders(listOf(list)), () => undefined)
    void catalogApi.tags().then((list) => setTags(listOf(list)), () => undefined)
    // Whether anything was shared one by one: the list of documents answers that without using up a search.
    void documentsApi.list({ status: 'filed', via_share: true, limit: 1 }).then((found) => setSharedToMe(listOf(found.items).length > 0), () => undefined)
  }, [])

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
        out.delete('page')
        return out
      }, { replace: true })
    }, TYPING_PAUSE_MS)
    return () => window.clearTimeout(timer)
  }, [typed, q, setParams])

  const filters = useMemo(() => filtersOf(chosen), [chosen])
  const filterKey = JSON.stringify(filters)
  const vaultFilters = useMemo(() => {
    const { status, vault_id, via_share } = filters
    return { status, vault_id, via_share }
  }, [filters])
  const vaultKey = JSON.stringify(vaultFilters)

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

  // The whole archive, for the number in the heading and the overview without a vault.
  useEffect(() => {
    const stop = new AbortController()
    searchApi.overview({ status: 'filed' }, stop.signal).then(
      (found) => !stop.signal.aborted && setWhole(overviewOf(found)),
      (error: unknown) => !stopped(error, stop.signal) && setProblem(problemOf(error)),
    )
    return () => stop.abort()
  }, [again])

  // The overview of one vault (or of what was shared one by one), and the newest documents in it.
  useEffect(() => {
    if (listing) return
    const stop = new AbortController()
    if (vaultFilters.vault_id || vaultFilters.via_share) {
      searchApi.overview(vaultFilters, stop.signal).then(
        (found) => !stop.signal.aborted && setOfVault(overviewOf(found)),
        (error: unknown) => !stopped(error, stop.signal) && setProblem(problemOf(error)),
      )
    }
    searchApi.find('', { ...vaultFilters, limit: NEWEST }, stop.signal).then(
      (found) => {
        if (stop.signal.aborted) return
        setNewest(listOf(found.items))
        setProblem(null)
      },
      (error: unknown) => !stopped(error, stop.signal) && setProblem(problemOf(error)),
    )
    return () => stop.abort()
    // `vaultFilters` is the same as `vaultKey`; the key keeps an equal object from asking again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listing, vaultKey, again])

  // One page of the table; the request before it is stopped.
  useEffect(() => {
    if (!listing) return
    const stop = new AbortController()
    const began = performance.now()
    searchApi.find(q, { ...filters, limit: size, sort: order, page }, stop.signal).then(
      (found) => {
        if (stop.signal.aborted) return
        const items = listOf<SearchHit>(found.items)
        const all = found.total ?? 0
        // A page past the end (fewer documents since): the last one there is.
        if (items.length === 0 && all > 0 && page > 1) {
          setParams((current) => {
            const out = new URLSearchParams(current)
            const last = Math.ceil(all / size)
            if (last > 1) out.set('page', String(last))
            else out.delete('page')
            return out
          }, { replace: true })
          return
        }
        setHits(items)
        setTotal(all)
        setTook((performance.now() - began) / 1000)
        setProblem(null)
      },
      (error: unknown) => !stopped(error, stop.signal) && setProblem(problemOf(error)),
    )
    return () => stop.abort()
    // `filters` is the same as `filterKey`; the key keeps an equal object from searching again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listing, q, filterKey, order, size, page, again])

  // A brake: tried again by itself once the server's minute allows it.
  useEffect(() => {
    if (problem?.code !== 'search_too_often') return
    const seconds = Number(problem.values.retry_after ?? 10)
    const timer = window.setTimeout(() => setAgain((n) => n + 1), Math.min(60, Math.max(1, seconds)) * 1000)
    return () => window.clearTimeout(timer)
  }, [problem])

  /** Changes the address: a new choice starts again on the first page; the overview and the table are steps back. */
  const go = useCallback(
    (change: Record<string, string>, { keepPage = false, replace = false } = {}) =>
      setParams((current) => {
        const out = new URLSearchParams(current)
        for (const [key, value] of Object.entries(change)) {
          if (value) out.set(key, value)
          else out.delete(key)
        }
        if (!keepPage) out.delete('page')
        return out
      }, { replace }),
    [setParams],
  )

  if (!me) return null
  const view = me.profile.view === 'grid' ? 'grid' : 'list'
  const setView = (value: 'list' | 'grid') => {
    if (value === view) return
    setMe({ ...me, profile: { ...me.profile, view: value } })
    void authApi.preferences({ view: value }).then((profile) => setMe({ ...me, profile }), () => undefined)
  }
  const choose = (change: Partial<Chosen>) => go(change as Record<string, string>)
  const toOverview = () => {
    setTyped('')
    sent.current = ''
    go({ q: '', all: '', kind: '', sender: '', tag: '', owner: '', year: '' })
  }
  const toPage = (n: number) => {
    go({ page: n > 1 ? String(n) : '' }, { keepPage: true })
    top.current?.scrollIntoView?.({ block: 'start' })
  }
  const narrowing = NARROWING.filter((key) => chosen[key]).length
  const vaultById = new Map(vaults.map((v) => [v.id, v]))
  const vaultName = (v: Vault) => (v.personal_of === me.id ? t('vaults.mine') : v.name)
  const n = (value: number) => value.toLocaleString(i18n.language)
  const overview = vaultFilters.vault_id || vaultFilters.via_share ? ofVault : whole
  const nothingAtAll = whole !== null && whole.total === 0 && !listing && !chosen.vault
  const pages = Math.max(1, Math.ceil(total / size))
  const kindName = (id: string) => kinds.find((k) => String(k.id) === id)?.name ?? overview?.kinds.find((k) => String(k.kind.id) === id)?.kind.name ?? id

  // What narrows the table, each removable on its own.
  const pills: [keyof Chosen, string, string][] = [
    ['sender', t('docs.archive.sender'), chosen.sender],
    ['kind', t('docs.archive.kind'), chosen.kind && kindName(chosen.kind)],
    ['year', t('docs.archive.year'), chosen.year],
    ['tag', t('docs.archive.tag'), chosen.tag],
    ['owner', t('docs.archive.owner'), chosen.owner && personName(people.find((p) => String(p.id) === chosen.owner) ?? { id: 0, name: chosen.owner, display_name: '' })],
  ].filter(([, , value]) => value) as [keyof Chosen, string, string][]

  return (
    <div ref={top} className="page space-y-5 pt-6 pb-28 lg:pt-8 lg:pb-12">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight">{t('docs.archive.title')}</h1>
          <p className="text-sm text-muted" data-testid="archive-count">
            {whole !== null &&
              t('docs.archive.sub', {
                documents: t('docs.archive.documents', { count: whole.total, n: n(whole.total) }),
                vaults: t('docs.archive.vaults', { count: vaults.length }),
              })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {listing && (
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
          )}
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
                    go({ q: example }, { replace: true })
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
        <Chip active={more || narrowing > 0} onClick={() => setMore(!more)}>
          <SlidersHorizontal size={14} aria-hidden /> {narrowing > 0 ? t('docs.archive.filterCount', { count: narrowing }) : t('docs.archive.filter')}
        </Chip>
      </div>

      {more && <Filters chosen={chosen} choose={choose} kinds={kinds} senders={senders} tags={tags} people={people} years={(overview ?? whole)?.years ?? []} active={narrowing} />}

      {problem && (
        <p role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
          {errorText(problem.code, problem.values)}
        </p>
      )}

      {!listing ? (
        nothingAtAll ? (
          <Empty title={t('docs.archive.emptyTitle')} text={t('docs.archive.emptyText')} />
        ) : !overview || !newest ? (
          !problem && <p className="text-sm text-muted">{t('docs.loading')}</p>
        ) : overview.total === 0 ? (
          <Empty title={t('docs.archive.nothingTitle')} text={t('docs.archive.nothingText')} />
        ) : (
          <Overview
            data={overview}
            newest={newest}
            onAll={() => go({ all: '1' })}
            onPick={(key, value) => go({ [key]: value })}
            onAllSenders={() => setAllSenders(true)}
            table={<Table hits={newest} vaultById={vaultById} vaultName={vaultName} searching={false} order="-date" bare />}
          />
        )
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={toOverview} className="inline-flex h-8 items-center gap-1 rounded-full pr-2 text-sm font-semibold text-accent hover:underline">
              <ChevronLeft size={16} aria-hidden /> {t('docs.archive.overview')}
            </button>
            {pills.map(([key, label, value]) => (
              <span key={key} data-testid="pill" className="inline-flex h-8 max-w-full items-center gap-1.5 rounded-full bg-accent-soft pr-1 pl-3 text-sm">
                <span className="text-muted">{label}</span>
                <bdi className="truncate font-semibold text-accent">{value}</bdi>
                <button type="button" onClick={() => go({ [key]: '' })} aria-label={t('docs.archive.remove', { what: label })} className="rounded-full p-1 text-muted hover:bg-sheet hover:text-ink">
                  <X size={14} aria-hidden />
                </button>
              </span>
            ))}
            {hits && !problem && (
              <p className="ml-auto text-sm text-ink-2" data-testid="hit-count">
                {q ? (
                  <>
                    {total === 0 ? t('docs.archive.noHits') : t('docs.archive.hits', { count: total, n: n(total) })} {t('docs.archive.for', { q: iso(q) })}
                    {total > 0 && took !== null && <span className="text-muted"> · {t('docs.archive.took', { seconds: took.toLocaleString(i18n.language, { maximumFractionDigits: 2, minimumFractionDigits: 2 }) })}</span>}
                  </>
                ) : (
                  t('docs.archive.documents', { count: total, n: n(total) })
                )}
              </p>
            )}
          </div>

          {hits && hits.length === 0 && !problem && <Empty title={t('docs.archive.nothingTitle')} text={t('docs.archive.nothingText')} />}
          {!hits && !problem && <p className="text-sm text-muted">{t('docs.loading')}</p>}

          {hits && hits.length > 0 &&
            (view === 'list' ? (
              <Table hits={hits} vaultById={vaultById} vaultName={vaultName} searching={!!q} order={order} onOrder={(next) => go({ sort: next === '-date' ? '' : next })} />
            ) : (
              <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
                {hits.map((hit) => (
                  <Tile key={hit.document.id} hit={hit} />
                ))}
              </ul>
            ))}

          {hits && hits.length > 0 && (
            <Pager page={Math.min(page, pages)} pages={pages} from={(page - 1) * size + 1} to={Math.min(total, (page - 1) * size + hits.length)} total={total} size={size} onPage={toPage} onSize={(value) => go({ n: value === DEFAULT_SIZE ? '' : String(value) })} />
          )}
        </>
      )}

      {allSenders && overview && (
        <SenderDialog
          senders={overview.senders}
          onClose={() => setAllSenders(false)}
          onPick={(name) => {
            setAllSenders(false)
            go({ sender: name })
          }}
        />
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
          count={listing ? total : (overview?.total ?? 0)}
          sum={(listing ? (hits ?? []) : []).reduce((all, hit) => all + (hit.document.amount ?? 0), 0)}
          say={setSaid}
          onClose={() => setExporting(false)}
        />
      )}
    </div>
  )
}

function Empty({ title, text }: { title: string; text: string }) {
  return (
    <div className="card p-10 text-center">
      <Search size={28} className="mx-auto text-muted" aria-hidden />
      <p className="mt-3 font-semibold">{title}</p>
      <p className="mt-1 text-sm text-ink-2">{text}</p>
    </div>
  )
}

type OverviewProps = {
  data: SearchOverview
  newest: SearchHit[]
  table: ReactNode
  onAll: () => void
  onPick: (key: keyof Chosen, value: string) => void
  onAllSenders: () => void
}

function Overview({ data, newest, table, onAll, onPick, onAllSenders }: OverviewProps) {
  const { t, i18n } = useTranslation()
  const n = (value: number) => value.toLocaleString(i18n.language)
  const most = data.years.reduce((all, y) => Math.max(all, y.count), 1)
  return (
    <div className="space-y-6" data-testid="overview">
      {newest.length > 0 && (
        <section aria-label={t('docs.archive.newest')}>
          <div className="mb-2 flex items-baseline justify-between gap-3 px-1">
            <h2 className="text-xs font-bold tracking-wide text-muted uppercase">{t('docs.archive.newest')}</h2>
            <button type="button" onClick={onAll} className="text-sm font-semibold text-accent hover:underline">
              {t('docs.archive.showAll', { n: n(data.total) })}
            </button>
          </div>
          {table}
        </section>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        {data.senders.length > 0 && (
          <Group title={t('docs.archive.bySender')} footer={t('docs.archive.allSenders', { n: n(data.senders.length) })} onFooter={onAllSenders}>
            {data.senders.slice(0, TOP_SENDERS).map((s) => (
              <Pick key={s.name} count={s.count} onClick={() => onPick('sender', s.name)}>
                <bdi className="truncate">{s.name}</bdi>
              </Pick>
            ))}
          </Group>
        )}
        {data.kinds.length > 0 && (
          <Group title={t('docs.archive.byKind')}>
            {data.kinds.map(({ kind, count }) => (
              <Pick key={kind.id} count={count} onClick={() => onPick('kind', String(kind.id))}>
                <KindPill kind={kind} small />
              </Pick>
            ))}
          </Group>
        )}
        {data.years.length > 0 && (
          <Group title={t('docs.archive.byYear')}>
            {data.years.map(({ year, count }) => (
              <Pick key={year} count={count} onClick={() => onPick('year', String(year))}>
                <span className="w-12 shrink-0 font-semibold tabular-nums">{year}</span>
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-sheet-2" aria-hidden>
                  <span className="block h-full rounded-full bg-accent/60" style={{ width: `${(count / most) * 100}%` }} />
                </span>
              </Pick>
            ))}
          </Group>
        )}
      </div>

      {data.tags.length > 0 && (
        <section aria-label={t('docs.archive.oftenTags')}>
          <h2 className="mb-2 px-1 text-xs font-bold tracking-wide text-muted uppercase">{t('docs.archive.oftenTags')}</h2>
          <div className="flex flex-wrap gap-2">
            {data.tags.slice(0, TOP_TAGS).map((tag) => (
              <Chip key={tag.name} onClick={() => onPick('tag', tag.name)}>
                <bdi>{tag.name}</bdi> <span className="font-normal text-muted tabular-nums">{n(tag.count)}</span>
              </Chip>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

function Group({ title, children, footer, onFooter }: { title: string; children: ReactNode; footer?: string; onFooter?: () => void }) {
  return (
    <section className="card flex flex-col overflow-hidden p-0" aria-label={title}>
      <h2 className="px-4 pt-4 pb-1 text-xs font-bold tracking-wide text-muted uppercase">{title}</h2>
      <ul className="flex-1 px-2 pb-2">{children}</ul>
      {footer && (
        <button type="button" onClick={onFooter} className="border-t border-line px-4 py-3 text-left text-sm font-semibold text-accent hover:bg-sheet-2/60">
          {footer}
        </button>
      )}
    </section>
  )
}

function Pick({ children, count, onClick }: { children: ReactNode; count: number; onClick: () => void }) {
  const { i18n } = useTranslation()
  return (
    <li>
      <button type="button" onClick={onClick} className="flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-sheet-2">
        <span className="flex min-w-0 flex-1 items-center gap-3">{children}</span>
        <span className="shrink-0 text-muted tabular-nums">{count.toLocaleString(i18n.language)}</span>
      </button>
    </li>
  )
}

/** The columns of the table: from `md` a grid, the vault from `lg`; below, title, sender and date in two lines. Title
 * and sender share what is left, the title twice as much: fixed widths cut the titles short on a laptop. */
const COLUMNS = 'md:grid md:grid-cols-[1.5rem_minmax(0,2fr)_minmax(0,1fr)_7rem_5.5rem_6rem] lg:grid-cols-[1.5rem_minmax(0,2fr)_minmax(0,1fr)_7rem_minmax(0,8rem)_5.5rem_6rem] md:items-center md:gap-3'

type TableProps = {
  hits: SearchHit[]
  vaultById: Map<number, Vault>
  vaultName: (v: Vault) => string
  searching: boolean
  order: SearchOrder
  onOrder?: (order: SearchOrder) => void
  /** Without the heading and the months (the newest of the overview). */
  bare?: boolean
}

function Table({ hits, vaultById, vaultName, searching, order, onOrder, bare = false }: TableProps) {
  const { t, i18n } = useTranslation()
  const byDate = !bare && order.endsWith('date')
  const monthName = (key: string) => {
    const [year, month] = key.split('-').map(Number)
    return new Intl.DateTimeFormat(i18n.language, { month: 'long', year: 'numeric' }).format(new Date(year, month - 1, 15))
  }
  const rows: ReactNode[] = []
  let month = ''
  for (const hit of hits) {
    const key = monthKey(hit)
    if (byDate && key !== month) {
      rows.push(
        <li key={`m-${key}`} className="bg-sheet-2/60 px-4 py-1.5 text-[0.7rem] font-bold tracking-wide text-muted uppercase" data-testid="month">
          {monthName(key)}
        </li>,
      )
      month = key
    }
    rows.push(<Row key={hit.document.id} hit={hit} vault={vaultById.get(hit.document.vault_id)} vaultName={vaultName} searching={searching} />)
  }
  const head = (column: 'title' | 'sender' | 'date' | 'amount', label: string, right = false) => {
    const on = order === column || order === `-${column}`
    const down = order === `-${column}`
    return (
      <button
        type="button"
        onClick={() => onOrder?.(nextOrder(order, column))}
        aria-label={t('docs.archive.sortBy', { what: label })}
        aria-pressed={on}
        className={`inline-flex items-center gap-1 uppercase hover:text-ink ${right ? 'justify-self-end' : ''} ${on ? 'text-ink' : ''}`}
      >
        {label}
        {on && (down ? <ArrowDown size={12} aria-hidden /> : <ArrowUp size={12} aria-hidden />)}
      </button>
    )
  }
  return (
    <div className="card overflow-hidden p-0" data-testid="table">
      {!bare && (
        <div className={`hidden border-b border-line px-4 py-2.5 text-xs font-bold tracking-wide text-muted ${COLUMNS}`}>
          <span />
          {head('title', t('docs.archive.colTitle'))}
          {head('sender', t('docs.archive.sender'))}
          <span className="uppercase">{t('docs.archive.kind')}</span>
          <span className="hidden uppercase lg:block">{t('docs.archive.colVault')}</span>
          {head('date', t('docs.archive.colDate'))}
          {head('amount', t('docs.archive.colAmount'), true)}
        </div>
      )}
      <ul className="divide-y divide-line">{rows}</ul>
    </div>
  )
}

function Row({ hit, vault, vaultName, searching }: { hit: SearchHit; vault: Vault | undefined; vaultName: (v: Vault) => string; searching: boolean }) {
  const { t, i18n } = useTranslation()
  const d = hit.document
  const when = shortDate(d.date ?? d.added_at, i18n.language)
  return (
    <li data-testid="row">
      <Link to={`/dokument/${d.id}`} className={`flex items-center gap-3 px-4 py-2 hover:bg-sheet-2/60 ${COLUMNS}`}>
        <DocThumb document={d} className="w-6 shrink-0" />
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
          <div className="truncate text-sm text-ink-2 md:hidden">
            {d.sender && (
              <>
                <Marked text={d.sender.name} marks={hit.sender_marks} /> ·{' '}
              </>
            )}
            {when}
          </div>
          {searching && hit.excerpt && (
            <p className="mt-0.5 line-clamp-2 text-sm text-muted" data-testid="excerpt">
              {hit.excerpt.source === 'notes' && <MessageSquare size={12} className="mr-1 inline" aria-label={t('docs.archive.inNote')} />}
              <Marked text={hit.excerpt.text} marks={hit.excerpt.marks} />
            </p>
          )}
        </div>
        <span className="hidden truncate text-sm text-ink-2 md:block">{d.sender && <Marked text={d.sender.name} marks={hit.sender_marks} />}</span>
        <span className="hidden md:block">
          <KindPill kind={d.kind} small />
        </span>
        <span className="hidden min-w-0 items-center gap-1.5 text-sm text-ink-2 lg:flex">
          {vault && !d.via_share ? <VaultIcon icon={vault.icon} size={14} /> : <Users size={14} aria-hidden />}
          <span className="truncate">{vault && !d.via_share ? vaultName(vault) : t('docs.archive.sharedLower')}</span>
        </span>
        <span className="hidden text-sm text-ink-2 tabular-nums md:block">{when}</span>
        <span className="w-20 shrink-0 text-right text-sm font-semibold tabular-nums md:w-auto">{money(d.amount, i18n.language, d.currency)}</span>
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

type PagerProps = { page: number; pages: number; from: number; to: number; total: number; size: number; onPage: (n: number) => void; onSize: (n: number) => void }

function Pager({ page, pages, from, to, total, size, onPage, onSize }: PagerProps) {
  const { t, i18n } = useTranslation()
  const n = (value: number) => value.toLocaleString(i18n.language)
  const button = 'inline-flex h-9 min-w-9 items-center justify-center rounded-full px-2 text-sm font-semibold tabular-nums'
  return (
    <div className="flex flex-wrap items-center justify-between gap-3" data-testid="pager">
      <span className="text-sm text-ink-2 tabular-nums">{t('docs.archive.range', { from: n(from), to: n(to), total: n(total) })}</span>
      {pages > 1 && (
        <nav aria-label={t('docs.archive.pages')} className="flex items-center gap-1">
          <button type="button" onClick={() => onPage(page - 1)} disabled={page === 1} aria-label={t('docs.archive.prev')} className={`${button} text-ink-2 hover:bg-sheet-2 disabled:opacity-30`}>
            <ChevronLeft size={18} aria-hidden />
          </button>
          {pageList(page, pages).map((number, index) =>
            number === null ? (
              <span key={`gap-${index}`} className="px-1 text-muted" aria-hidden>
                …
              </span>
            ) : (
              <button
                key={number}
                type="button"
                onClick={() => onPage(number)}
                aria-label={t('docs.archive.pageN', { n: number })}
                aria-current={number === page ? 'page' : undefined}
                className={`${button} ${number === page ? 'bg-accent text-accent-ink' : 'text-ink-2 hover:bg-sheet-2'}`}
              >
                {n(number)}
              </button>
            ),
          )}
          <button type="button" onClick={() => onPage(page + 1)} disabled={page === pages} aria-label={t('docs.archive.next')} className={`${button} text-ink-2 hover:bg-sheet-2 disabled:opacity-30`}>
            <ChevronRight size={18} aria-hidden />
          </button>
        </nav>
      )}
      <label className="flex items-center gap-2 text-sm text-ink-2">
        <select value={size} onChange={(event) => onSize(Number(event.target.value))} aria-label={t('docs.archive.perPage')} className="h-9 rounded-xl border border-line bg-sheet px-2 text-ink outline-none focus:border-accent">
          {SIZES.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        {t('docs.archive.perPage')}
      </label>
    </div>
  )
}

function SenderDialog({ senders, onClose, onPick }: { senders: NameCount[]; onClose: () => void; onPick: (name: string) => void }) {
  const { t, i18n } = useTranslation()
  const [find, setFind] = useState('')
  const [byName, setByName] = useState(false)
  const folded = find.trim().toLocaleLowerCase(i18n.language)
  const list = senders
    .filter((s) => s.name.toLocaleLowerCase(i18n.language).includes(folded))
    .sort((a, b) => (byName ? a.name.localeCompare(b.name, i18n.language) : b.count - a.count))
  return (
    <Dialog title={t('docs.archive.allSenders', { n: senders.length.toLocaleString(i18n.language) })} onClose={onClose}>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search size={16} className="absolute top-1/2 left-3 -translate-y-1/2 text-muted" aria-hidden />
          <input data-autofocus value={find} onChange={(event) => setFind(event.target.value)} placeholder={t('docs.archive.findSender')} aria-label={t('docs.archive.findSender')} className="input h-10 w-full pl-9" />
        </div>
        <select value={byName ? 'name' : 'count'} onChange={(event) => setByName(event.target.value === 'name')} aria-label={t('docs.archive.senderOrder')} className="h-10 rounded-xl border border-line bg-sheet px-2 text-sm outline-none focus:border-accent">
          <option value="count">{t('docs.archive.mostFirst')}</option>
          <option value="name">{t('docs.archive.aToZ')}</option>
        </select>
      </div>
      <ul className="-mx-2 mt-3 max-h-[55vh] overflow-y-auto" data-testid="all-senders">
        {list.map((s) => (
          <Pick key={s.name} count={s.count} onClick={() => onPick(s.name)}>
            <bdi className="truncate">{s.name}</bdi>
          </Pick>
        ))}
        {list.length === 0 && <li className="px-2 py-6 text-center text-sm text-muted">{t('docs.archive.noSender')}</li>}
      </ul>
    </Dialog>
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
  years: { year: number }[]
  active: number
}

function Filters({ chosen, choose, kinds, senders, tags, people, years, active }: FiltersProps) {
  const { t } = useTranslation()
  // The years the archive has, and the chosen one even when it has none (an address from elsewhere).
  const yearOptions = [...new Set([...years.map((y) => String(y.year)), ...(chosen.year ? [chosen.year] : [])])].sort().reverse()
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
      <Select label={t('docs.archive.year')} value={chosen.year} onChange={(year) => choose({ year })} options={yearOptions.map((y) => [y, y])} empty={t('docs.archive.anytime')} />
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm font-semibold text-accent sm:col-span-2 lg:col-span-6">
        {active > 0 && (
          <button type="button" onClick={() => choose({ kind: '', sender: '', tag: '', owner: '', year: '' })} className="text-left">
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
